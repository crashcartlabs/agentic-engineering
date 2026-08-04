/**
 * Agentic Engineering subagent adapter for pi.
 *
 * Pi intentionally has no built-in subagent tool. This extension exposes the
 * provider-neutral Markdown agents installed under ~/.pi/agent/agents and runs one in
 * an isolated pi process. It deliberately supports one delegated task at a time; fleet
 * orchestration remains the cmux workflow's responsibility.
 */

import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { Type } from "@earendil-works/pi-ai";
import { defineTool, getAgentDir, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

type AgentDefinition = {
	name: string;
	description: string;
	prompt: string;
};

const MAX_STREAM_BYTES = 4 * 1024 * 1024;
const MAX_RUNTIME_MS = 30 * 60 * 1000;
const TERMINATION_GRACE_MS = 5_000;

function redactDiagnostics(text: string): string {
	return text
		.replace(/\b(api[_-]?key|token|secret|password)\s*[=:]\s*\S+/gi, "$1=[redacted]")
		.replace(/\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]+\b/g, "[redacted-token]");
}

function readAgent(name: string): AgentDefinition {
	if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) {
		throw new Error(`Invalid agent name: ${name}`);
	}
	const file = path.join(getAgentDir(), "agents", `${name}.md`);
	const text = fs.readFileSync(file, "utf-8");
	if (!text.startsWith("---\n")) throw new Error(`${file}: missing frontmatter`);
	const end = text.indexOf("\n---\n", 4);
	if (end < 0) throw new Error(`${file}: unterminated frontmatter`);
	const fields = new Map<string, string>();
	for (const line of text.slice(4, end).split("\n")) {
		const match = /^([A-Za-z0-9_-]+):\s*(.*)$/.exec(line);
		if (match) fields.set(match[1], match[2].trim());
	}
	if (!fields.get("name") || !fields.get("description")) {
		throw new Error(`${file}: agent requires name and description`);
	}
	let description = fields.get("description")!;
	if (description.startsWith('"')) {
		try { description = JSON.parse(description); } catch { /* retain the literal */ }
	}
	return {
		name: fields.get("name")!,
		description,
		prompt: text.slice(end + 5),
	};
}

function piInvocation(args: string[]): { command: string; args: string[] } {
	const currentScript = process.argv[1];
	if (currentScript && fs.existsSync(currentScript)) {
		return { command: process.execPath, args: [currentScript, ...args] };
	}
	return { command: "pi", args };
}

function assistantText(event: unknown): string | null {
	if (!event || typeof event !== "object") return null;
	const record = event as Record<string, unknown>;
	if (record.type !== "message_end" || !record.message || typeof record.message !== "object") return null;
	const message = record.message as Record<string, unknown>;
	if (message.role !== "assistant" || !Array.isArray(message.content)) return null;
	const chunks = message.content
		.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
		.filter((item) => item.type === "text" && typeof item.text === "string")
		.map((item) => item.text as string);
	return chunks.length ? chunks.join("\n") : null;
}

const subagent = defineTool({
	name: "subagent",
	label: "Subagent",
	description: "Delegate one task to an installed Agentic Engineering agent in an isolated pi process.",
	parameters: Type.Object({
		agent: Type.String({ description: "Installed agent name, such as executor" }),
		task: Type.String({ description: "Complete task brief for the delegated agent" }),
		cwd: Type.Optional(Type.String({ description: "Target repository working directory" })),
	}),

	async execute(_toolCallId, params, signal, _onUpdate, ctx) {
		let definition: AgentDefinition;
		try {
			definition = readAgent(params.agent);
		} catch (error) {
			return {
				content: [{ type: "text", text: `Cannot load subagent: ${String(error)}` }],
				details: { agent: params.agent, exitCode: 2 },
			};
		}

		const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "agentic-pi-subagent-"));
		const promptFile = path.join(tempDir, "prompt.md");
		fs.writeFileSync(promptFile, definition.prompt, { encoding: "utf-8", mode: 0o600 });
		const args = [
			"--mode",
			"json",
			"--print",
			"--no-session",
			"--append-system-prompt",
			promptFile,
			`Task: ${params.task}`,
		];
		const invocation = piInvocation(args);
		let stdout = "";
		let stderr = "";
		let aborted = false;
		let timedOut = false;

		try {
			const exitCode = await new Promise<number>((resolve) => {
				const child = spawn(invocation.command, invocation.args, {
					cwd: params.cwd ?? ctx.cwd,
					shell: false,
					detached: process.platform !== "win32",
					stdio: ["ignore", "pipe", "pipe"],
				});
				let settled = false;
				let stdoutBytes = 0;
				let stderrBytes = 0;
				let killTimer: ReturnType<typeof setTimeout> | undefined;
				let runtimeTimer: ReturnType<typeof setTimeout> | undefined;

				const killTree = (signalName: NodeJS.Signals) => {
					try {
						if (process.platform !== "win32" && child.pid) process.kill(-child.pid, signalName);
						else child.kill(signalName);
					} catch {
						child.kill(signalName);
					}
				};
				const stop = () => {
					if (settled) return;
					aborted = true;
					killTree("SIGTERM");
					if (!killTimer) {
						killTimer = setTimeout(() => killTree("SIGKILL"), TERMINATION_GRACE_MS);
						killTimer.unref();
					}
				};
				const finish = (code: number) => {
					if (settled) return;
					settled = true;
					if (killTimer) clearTimeout(killTimer);
					if (runtimeTimer) clearTimeout(runtimeTimer);
					signal.removeEventListener("abort", stop);
					resolve(code);
				};
				const append = (kind: "stdout" | "stderr", data: Buffer) => {
					const current = kind === "stdout" ? stdoutBytes : stderrBytes;
					const remaining = Math.max(0, MAX_STREAM_BYTES - current);
					const chunk = data.subarray(0, remaining).toString();
					if (kind === "stdout") {
						stdout += chunk;
						stdoutBytes += Math.min(data.length, remaining);
					} else {
						stderr += chunk;
						stderrBytes += Math.min(data.length, remaining);
					}
					if (data.length > remaining) {
						stderr += "\nSubagent output exceeded the 4 MiB stream limit.\n";
						stop();
					}
				};

				child.stdout.on("data", (data: Buffer) => append("stdout", data));
				child.stderr.on("data", (data: Buffer) => append("stderr", data));
				child.on("error", (error) => {
					stderr += String(error);
					finish(1);
				});
				child.on("close", (code) => finish(code ?? 1));
				runtimeTimer = setTimeout(() => {
					timedOut = true;
					stderr += "\nSubagent exceeded the 30 minute runtime limit.\n";
					stop();
				}, MAX_RUNTIME_MS);
				runtimeTimer.unref();
				if (signal.aborted) stop();
				else signal.addEventListener("abort", stop, { once: true });
			});

			const responses: string[] = [];
			for (const line of stdout.split("\n")) {
				if (!line.trim()) continue;
				try {
					const text = assistantText(JSON.parse(line));
					if (text) responses.push(text);
				} catch {
					// Ignore non-JSON diagnostic output; stderr remains available below.
				}
			}
			const safeStderr = redactDiagnostics(stderr.trim());
			const result = responses.at(-1) ?? safeStderr ?? "Subagent returned no text.";
			return {
				content: [{ type: "text", text: timedOut ? "Subagent timed out." : aborted ? "Subagent aborted." : result }],
				details: { agent: definition.name, exitCode, stderr: exitCode === 0 ? "" : safeStderr },
			};
		} finally {
			try {
				fs.rmSync(tempDir, { recursive: true, force: true });
			} catch {
				// Temporary cleanup failure must not hide the delegated result.
			}
		}
	},
});

export default function (pi: ExtensionAPI) {
	pi.registerTool(subagent);
}
