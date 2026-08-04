#!/usr/bin/env python3
"""Lint the skill set under skills/.

Hard checks (fail the build) — the invariants every skill here already holds:

- each skill dir has a SKILL.md,
- its frontmatter has a `name` and a `description`,
- `name` matches the directory name,
- every `assets/…` or `references/…` file the SKILL.md points at actually exists,
- each skill dir has a tests.md.

Pure stdlib, cross-platform. Exit 0 clean, 1 on any hard violation. Uses the source
selected by the aggregate gate: working tree for interactive checks and Git index for
pre-commit.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import sys
import json
import os
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gittracked  # noqa: E402
from lint_common import print_lint_epilogue  # noqa: E402

REPO = gittracked.REPO
SKILLS = REPO / "skills"

# Display-name casing fix-ups over the plain hyphen-title derivation. The default
# (" ".join(word.capitalize() for word in name.split("-"))) already produces the
# right shape for nearly every skill; these are the exceptions — brand/acronym
# casing that capitalize() would mangle (npm, TODO). Skill names carrying api/pr/
# rdp/ci tokens would need entries here too if such skills are ever added.
DISPLAY_NAME_FIXUPS = {
    "tdd": "TDD",
    "cmux": "cmux",
    "babysitting-pr": "Babysitting PR",
    "updating-npm-package": "Updating npm Package",
    "todo-cleanup": "TODO Cleanup",
}
# Cap for short_description: first sentence of the canonical description, truncated
# at a word boundary with an ellipsis when it exceeds this many characters.
SHORT_DESC_CAP = 140
INTERFACE_KEYS = ("display_name", "short_description", "default_prompt")

# Tokens like `assets/report-template.md` or a full `.../references/setup-hooks.md`,
# restricted to real file extensions so bare `references/` prose isn't flagged.
REF_RE = re.compile(
    r"((?:assets|references)/[A-Za-z0-9._/-]+\.(?:md|sh|py|ts|js|txt|json|ya?ml))"
)
SCENARIO_RE = re.compile(
    r"^#{2,4}\s+(?:Scenario\b|Golden\b|Edge\b|Error\b)",
    re.MULTILINE | re.IGNORECASE,
)
VERIFICATION_RE = re.compile(r"Last verified:|\b(?:live|design|static)-verified\b|\*\*Status:", re.IGNORECASE)

# Finding H regression gate: canonical skill text must never carry Claude-style
# `/name` invocation syntax — H1 (or deeper) headings like `# /spec — …` or body
# forms like "invoke /spec" / "run as /code-audit". The sweep is blanket (any
# `/name`, not just the four issue-named skills) so a future skill cannot
# reintroduce the #5 defect class. The invocation regex anchors on the verb and
# excludes path continuations (/dev/null, /tmp/setup.sh, /usr/local/bin/x) via
# the trailing lookahead, so real paths are not flagged.
# A `/name` token continues a real path when followed by path characters
# ([A-Za-z0-9/_-]) or a file extension (a dot followed by letters); that
# continuation is what keeps /dev/null, /tmp/setup.sh, /usr/local/bin/x out
# of the sweep. A sentence-final period (invoke /spec.) is NOT a path
# continuation and must not mask an invocation.
# Known absolute-directory roots are also excluded (Codex PR #17 note 7):
# prose like "use /tmp for temporary files" or "use /bin to hold executables"
# names a filesystem directory, not a skill, and the token has no path
# continuation after it, so without this exclusion it is misread as an
# invocation and fails the gate. The negative lookahead is placed immediately
# after the leading slash (so it reads the root name that follows the slash,
# e.g. "/tmp" -> checks "tmp\b") so a bare "/tmp" never matches as a token; a
# genuine path like "/tmp/setup.sh" is still excluded by the path-continuation
# branch below.
_PATH_CONT_LOOKAHEAD = r"(?![A-Za-z0-9/_-]|\.[A-Za-z])"
_ABS_DIR_ROOTS = r"tmp|bin|usr|var|etc|home|opt|dev|proc|sys|run|srv|root|mnt|media|lib|lib64|sbin"
_ABS_DIR_LOOKAHEAD = r"(?!(?:" + _ABS_DIR_ROOTS + r")\b)"
SLASH_HEADING_RE = re.compile(
    r"(?m)^#+\s+/" + _ABS_DIR_LOOKAHEAD + r"[a-z][a-z0-9-]*" + _PATH_CONT_LOOKAHEAD
)
# Invocation verbs are case-insensitive ("Invoke /spec" is the natural prose
# form), 'as'/'the' between verb and token is optional, and the token may be
# wrapped in backticks/quotes/parens ("Invoke as `/spec`"). The path
# continuation lookahead keeps real paths out.
SLASH_INVOCATION_RE = re.compile(
    r"\b(invoke|run|use|call)\s+(?:as\s+|the\s+)?[`\"'(]*/"
    + _ABS_DIR_LOOKAHEAD
    + r"[a-z][a-z0-9-]*[`\"')]*" + _PATH_CONT_LOOKAHEAD,
    re.IGNORECASE,
)


def _code_span_positions(line: str) -> set[int]:
    """Character offsets inside balanced backtick code spans.

    CommonMark-style: a run of N backticks opens a span that the next run of
    exactly N backticks closes. An unmatched delimiter is literal text, so a
    stray backtick never suppresses real prose after it, and even-length
    delimiters (`` ``x`` ``) are recognized, not XORed away.
    """
    spans: set[int] = set()
    i = 0
    n = len(line)
    while i < n:
        if line[i] != "`":
            i += 1
            continue
        j = i
        while j < n and line[j] == "`":
            j += 1
        run = j - i
        k = line.find("`" * run, j)
        if k == -1:
            i = j  # unmatched opener: literal backtick, keep scanning
            continue
        spans.update(range(j, k))
        i = k + run
    return spans


def _inside_code_span(line: str, pos: int) -> bool:
    """True when character offset `pos` in `line` falls inside a balanced code span."""
    return pos in _code_span_positions(line)


def slash_sweep_hits(text: str) -> list[tuple[int, str]]:
    """Return (line_number, stripped_line) pairs carrying `/name` invocation syntax.

    Lines inside fenced code blocks are code, not instruction, and are
    skipped. A match whose verb sits inside a balanced inline backtick span
    (`` `run /spec` ``) is likewise code and is suppressed — but a verb
    OUTSIDE the backticks with a code-formatted token after it ("Invoke as
    `/spec`") is prose and is flagged. Every match on a line is examined, so
    a suppressed code example never hides a real invocation later on the same
    line.
    """
    hits: list[tuple[int, str]] = []
    in_fence = False
    fence_marker = ""
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence = False
            continue
        if in_fence:
            continue
        span_positions = _code_span_positions(line)
        flagged = False
        for regex in (SLASH_HEADING_RE, SLASH_INVOCATION_RE):
            for m in regex.finditer(line):
                if m.start() not in span_positions:
                    flagged = True
                    break
            if flagged:
                break
        if flagged:
            hits.append((lineno, line.strip()))
    return hits


def frontmatter(text: str) -> dict[str, str] | None:
    """Minimal `key: value` frontmatter parse — no YAML dep needed for name/description."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def unquote(raw: str) -> str:
    """Strip the surrounding quotes from a frontmatter/openai.yaml scalar value."""
    try:
        return str(json.loads(raw))
    except json.JSONDecodeError:
        return raw.strip('"\'')


def display_name_for(name: str) -> str:
    """Derived Codex display_name: hyphen-title, with casing fix-ups."""
    if name in DISPLAY_NAME_FIXUPS:
        return DISPLAY_NAME_FIXUPS[name]
    return " ".join(word.capitalize() for word in name.split("-"))


def first_sentence(description: str) -> str:
    """The canonical description's first sentence (up to the first `. `)."""
    m = re.search(r"^(.+?\.)\s", description)
    return m.group(1) if m else description


def short_description_for(description: str) -> str:
    """Derived short_description: first sentence, capped at a word boundary."""
    sentence = first_sentence(description).strip()
    if len(sentence) <= SHORT_DESC_CAP:
        return sentence
    cut = sentence[: SHORT_DESC_CAP - 1].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "…"


def derived_interface_strings(name: str, description: str) -> dict[str, str]:
    """The canonical Codex interface block for a skill, derived from the dir name
    and the canonical SKILL.md description — never hand-written per skill."""
    return {
        "display_name": display_name_for(name),
        "short_description": short_description_for(description),
        "default_prompt": f"Use ${name} to help with this task.",
    }


_INTERFACE_HEAD_RE = re.compile(r"^interface:[ \t]*(?:\n|$)", re.MULTILINE)
# A line that belongs inside an interface block: any indentation, a comment,
# or blank. Anything else at column 0 (the next top-level key) ends the block.
_INTERFACE_BODY_LINE_RE = re.compile(r"^(?:[ \t].*|#.*|\s*)$")
_INTERFACE_KEY_RE = re.compile(r"^[ \t]*([A-Za-z0-9_-]+):(.*)$")


def _interface_block_span(metadata: str) -> tuple[int, int] | None:
    """Return (start, end) of the whole `interface:` block: from the head line
    through every following comment/blank/any-indent line, stopping at the
    next top-level key (or end of text). Returns None when there is no
    `interface:` head. The whole block is consumed so a rewrite can replace
    it wholesale — comments, blank lines, and hyphenated/odd-indent keys can
    never truncate the match or survive as stale duplicates.
    """
    m = _INTERFACE_HEAD_RE.search(metadata)
    if not m:
        return None
    start = m.start()
    pos = m.end()
    while pos < len(metadata):
        nl = metadata.find("\n", pos)
        line_end = len(metadata) if nl == -1 else nl
        if not _INTERFACE_BODY_LINE_RE.match(metadata[pos:line_end]):
            break
        pos = line_end + 1 if nl != -1 else line_end
    return start, pos


def parse_interface_block(metadata: str) -> dict[str, str] | None:
    """Parse the `interface:` block of an openai.yaml into {key: value}.

    Consumes the whole block (comments, blank lines, any-indent key lines,
    hyphenated keys) up to the next top-level key; only `key: value` lines
    contribute entries. An extra or hyphenated key is kept in the result so
    the divergence check can flag it.
    """
    span = _interface_block_span(metadata)
    if span is None:
        return None
    out: dict[str, str] = {}
    for line in metadata[span[0] : span[1]].splitlines()[1:]:  # skip the head
        if line.lstrip().startswith("#"):
            continue
        fm = _INTERFACE_KEY_RE.match(line)
        if fm:
            out[fm.group(1)] = unquote(fm.group(2).strip())
    return out or None


def interface_divergence(name: str, description: str, metadata: str) -> str | None:
    """Return a human-readable divergence description, or None when the interface
    block matches the derivation exactly."""
    expected = derived_interface_strings(name, description)
    actual = parse_interface_block(metadata)
    if actual is None:
        return "missing or malformed interface block"
    extra = sorted(set(actual) - set(INTERFACE_KEYS))
    if extra:
        return f"unexpected keys in interface block: {', '.join(extra)}"
    diffs = [
        f"{key}: {actual.get(key)!r} != {expected[key]!r}"
        for key in INTERFACE_KEYS
        if actual.get(key) != expected[key]
    ]
    return "; ".join(diffs) if diffs else None


def render_interface_block(name: str, description: str) -> str:
    """Render the derived `interface:` block as openai.yaml text."""
    derived = derived_interface_strings(name, description)
    return "interface:\n" + "".join(
        f"  {key}: {json.dumps(derived[key], ensure_ascii=False)}\n"
        for key in INTERFACE_KEYS
    )


def rewrite_interface_block(text: str, name: str, description: str) -> str:
    """Replace the whole `interface:` block in an openai.yaml with the derived
    one, preserving everything after it (e.g. the `policy:` block). The block
    is consumed up to the next top-level key, so comments, blank lines, and
    hyphenated/odd-indent keys can never survive as stale duplicates next to
    the derived block.
    """
    span = _interface_block_span(text)
    if span is None:
        # No interface block: insert the derived one after any leading blank
        # lines and comments (cycle-2 finding 9 + cycle-3 comment-headed
        # fixed-point) so --fix repairs a headless openai.yaml in one run and
        # the next rewrite (which consumes comment body lines) is a fixed
        # point that preserves the header comment.
        insert_at = 0
        while insert_at < len(text):
            nl = text.find("\n", insert_at)
            line_end = len(text) if nl == -1 else nl
            content = text[insert_at:line_end].lstrip()
            if content and not content.startswith("#"):
                break
            if nl == -1:
                insert_at = line_end
                break
            insert_at = nl + 1
        # Codex PR #17 note 10: when insertion lands at EOF after a
        # non-newline-terminated comment, concatenating the interface block
        # would glue onto the comment ("# generatedinterface:") and break the
        # fixed point. Ensure a separating newline before the inserted block.
        prefix = text[:insert_at]
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        return (
            prefix
            + render_interface_block(name, description)
            + text[insert_at:]
        )
    start, end = span
    # Trim trailing blank lines off the replaced span so a block-separating
    # blank line (e.g. before `policy:`) is preserved instead of being
    # reformatted away by every --fix run. Internal comments/blanks stay part
    # of the block and are replaced wholesale. A line's content ends before
    # its terminating newline, so a line whose content is empty is blank.
    while end > start:
        content_end = end - 1 if text[end - 1] == "\n" else end
        line_start = text.rfind("\n", start, content_end) + 1
        if text[line_start:content_end].strip():
            break
        end = line_start
    return text[:start] + render_interface_block(name, description) + text[end:]


def selftest() -> int:
    failures: list[str] = []
    valid = frontmatter('---\nname: demo\ndescription: "Useful skill"\n---\n')
    if valid != {"name": "demo", "description": '"Useful skill"'}:
        failures.append(f"valid frontmatter parsed incorrectly: {valid!r}")
    if frontmatter("# no frontmatter\n") is not None:
        failures.append("missing frontmatter was accepted")
    provider_specific = frontmatter(
        "---\nname: demo\ndescription: ok\ndisable-model-invocation: true\n---\n"
    ) or {}
    if not (set(provider_specific) - {"name", "description"}):
        failures.append("provider-specific frontmatter fixture was not detectable")
    tests = "## Scenario 1\n## Edge: two\n## Error: three\nLast verified: design-verified\n"
    if len(SCENARIO_RE.findall(tests)) != 3 or not VERIFICATION_RE.search(tests):
        failures.append("scenario/maturity fixture did not satisfy the contract")
    negative_tests = "## Scenario 1\n## Scenario 2\n"
    if len(SCENARIO_RE.findall(negative_tests)) >= 3 or VERIFICATION_RE.search(negative_tests):
        failures.append("short unverified tests fixture was accepted")
    # Finding H: the slash-sweep regression matcher must flag `/name` headings
    # and verb+`/name` body forms (blanket, any skill) while ignoring real
    # paths (/dev/null, /tmp/..., /usr/local/bin/...) and neutral wording.
    slash_clean = (
        "# spec — Product specification\n"
        "invoke the spec skill to draft the document.\n"
        "redirect output to /dev/null inside the script.\n"
        "run /tmp/setup.sh before starting.\n"
        "the helper lives at /usr/local/bin/helper.\n"
        "use $cmux to help with this task.\n"
        # Codex PR #17 note 7: bare absolute directories named after common
        # roots (no path continuation) must not be read as /name invocations.
        "use /tmp for temporary files.\n"
        "use /bin to hold executables.\n"
        "# /dev/null — discard output\n"
        "## /usr/local/bin/helper — tools\n"
        "```sh\n"
        "invoke /spec as a CLI example\n"
        "```\n"
        "`run /spec` from the docs.\n"
        "``run /spec`` from the docs.\n"
    )
    if slash_sweep_hits(slash_clean):
        failures.append(f"slash sweep flagged clean canonical text: {slash_sweep_hits(slash_clean)!r}")
    slash_dirty = (
        "# /spec — Product specification\n"
        "## /plan — deeper heading\n"
        "invoke /spec to draft the document.\n"
        "run as /code-audit before shipping.\n"
        "use /cmux from the terminal.\n"
        "call /execute when ready.\n"
        "Invoke as /spec to draft the document.\n"
        "Invoke as `/spec` to draft the document.\n"
        "invoke the /spec skill\n"
        "invoke /spec.\n"
        'call "/execute" now.\n'
        "`run /spec` then invoke /plan after.\n"
        "a stray ` tick then invoke /plan here — literal, not a span.\n"
    )
    if [line for _, line in slash_sweep_hits(slash_dirty)] != [
        "# /spec — Product specification",
        "## /plan — deeper heading",
        "invoke /spec to draft the document.",
        "run as /code-audit before shipping.",
        "use /cmux from the terminal.",
        "call /execute when ready.",
        "Invoke as /spec to draft the document.",
        "Invoke as `/spec` to draft the document.",
        "invoke the /spec skill",
        "invoke /spec.",
        'call "/execute" now.',
        "`run /spec` then invoke /plan after.",
        "a stray ` tick then invoke /plan here — literal, not a span.",
    ]:
        failures.append(f"slash sweep missed a slash invocation: {slash_sweep_hits(slash_dirty)!r}")
    # openai.yaml interface derivation: a diverged block must be flagged.
    desc = "Drive cmux (the terminal-multiplexer / agent-fleet CLI) from natural language. Second sentence."
    diverged = (
        "interface:\n"
        '  display_name: "Cmux"\n'
        '  short_description: "Use the Cmux workflow in this task."\n'
        '  default_prompt: "Use $cmux to help with this task."\n'
    )
    if interface_divergence("cmux", desc, diverged) is None:
        failures.append("diverged openai.yaml interface block was accepted")
    derived_block = render_interface_block("cmux", desc)
    if interface_divergence("cmux", desc, derived_block) is not None:
        failures.append("derived openai.yaml interface block was flagged")
    expected = derived_interface_strings("cmux", desc)
    if expected["display_name"] != "cmux":
        failures.append(f"cmux display_name fixup failed: {expected['display_name']!r}")
    if derived_interface_strings("tdd", desc)["display_name"] != "TDD":
        failures.append("tdd display_name fixup failed")
    if derived_interface_strings("babysitting-pr", desc)["display_name"] != "Babysitting PR":
        failures.append("babysitting-pr display_name fixup failed")
    if derived_interface_strings("updating-npm-package", desc)["display_name"] != "Updating npm Package":
        failures.append("updating-npm-package display_name fixup failed (npm must stay lowercase)")
    if derived_interface_strings("todo-cleanup", desc)["display_name"] != "TODO Cleanup":
        failures.append("todo-cleanup display_name fixup failed (TODO must stay uppercase)")
    if derived_interface_strings("code-audit", desc)["display_name"] != "Code Audit":
        failures.append("hyphenated display_name derivation failed")
    if expected["short_description"] != (
        "Drive cmux (the terminal-multiplexer / agent-fleet CLI) from natural language."
    ):
        failures.append(f"first-sentence short_description failed: {expected['short_description']!r}")
    if expected["default_prompt"] != "Use $cmux to help with this task.":
        failures.append(f"default_prompt derivation failed: {expected['default_prompt']!r}")
    long_desc = "Word " * 200 + ". Trailing."
    capped = derived_interface_strings("x", long_desc)["short_description"]
    if len(capped) > SHORT_DESC_CAP:
        failures.append(f"short_description cap not enforced: {len(capped)} > {SHORT_DESC_CAP}")
    # Finding A (code-audit): parse/rewrite must consume the WHOLE interface
    # block — comments, blank lines, hyphenated keys, any-indent key lines —
    # up to the next top-level key, and rewrite must replace the whole block
    # so --fix can never duplicate keys or emit invalid YAML.
    # NOTE: the equality assertions above use parse_interface_block() — a pure
    # stdlib parser — so this selftest never depends on PyYAML and stays green
    # on clean CI runners (Codex review note 1).

    comment_block = (
        "interface:\n"
        '  display_name: "cmux"\n'
        "  # a comment inside the block\n"
        '  short_description: "Drive cmux (the terminal-multiplexer / agent-fleet CLI) from natural language."\n'
        "  # another comment\n"
        "\n"
        '  default_prompt: "Use $cmux to help with this task."\n'
        "\n"
        "policy:\n"
        "  allow_implicit_invocation: false\n"
    )
    if interface_divergence("cmux", desc, comment_block) is not None:
        failures.append("comment-inside-block fixture was flagged as divergent")
    fixed_comment = rewrite_interface_block(comment_block, "cmux", desc)
    if fixed_comment.count("display_name:") != 1 or fixed_comment.count("default_prompt:") != 1:
        failures.append("--fix duplicated interface keys on a comment-inside-block file")
    # Parse via the stdlib parser (no PyYAML dependency) so the selftest
    # stays green on clean CI runners that install no third-party packages.
    if parse_interface_block(fixed_comment) != expected:
        failures.append("post-fix stdlib parse of comment-inside-block file does not match the derivation")

    indented_block = (
        "interface:\n"
        '    display_name: "Cmux"\n'
        '    short_description: "Use the Cmux workflow in this task."\n'
        '    default_prompt: "Use $cmux to help with this task."\n'
        "\n"
        "policy:\n"
        "  allow_implicit_invocation: false\n"
    )
    if interface_divergence("cmux", desc, indented_block) is None:
        failures.append("4-space-indented interface block was not flagged")
    fixed_indented = rewrite_interface_block(indented_block, "cmux", desc)
    if parse_interface_block(fixed_indented) != expected:
        failures.append("post-fix stdlib parse of 4-space-indented file does not match the derivation")

    # Documented expectation: the lint contract is equality with the
    # derivation, so a block carrying a key beyond the three derived ones
    # diverges; --fix replaces the whole block, dropping the extra key —
    # loudly, because lint flags it before any rewrite happens.
    extra_key_block = (
        "interface:\n"
        '  display_name: "cmux"\n'
        '  short_description: "Drive cmux (the terminal-multiplexer / agent-fleet CLI) from natural language."\n'
        '  default_prompt: "Use $cmux to help with this task."\n'
        '  extra_key: "surplus"\n'
        "\n"
        "policy:\n"
        "  allow_implicit_invocation: false\n"
    )
    if interface_divergence("cmux", desc, extra_key_block) is None:
        failures.append("interface block with an extra key was not flagged (expected divergence)")
    fixed_extra = rewrite_interface_block(extra_key_block, "cmux", desc)
    if parse_interface_block(fixed_extra) != expected or "extra_key" in fixed_extra:
        failures.append("--fix did not replace the whole block, dropping the extra key")

    hyphen_block = (
        "interface:\n"
        '  display_name: "cmux"\n'
        '  default-prompt: "Use $cmux to help with this task."\n'
        '  short_description: "Drive cmux (the terminal-multiplexer / agent-fleet CLI) from natural language."\n'
        "\n"
        "policy:\n"
        "  allow_implicit_invocation: false\n"
    )
    if interface_divergence("cmux", desc, hyphen_block) is None:
        failures.append("hyphenated interface key was not flagged as divergent")
    fixed_hyphen = rewrite_interface_block(hyphen_block, "cmux", desc)
    if parse_interface_block(fixed_hyphen) != expected:
        failures.append("--fix did not replace a hyphenated-key block wholesale")
    # Finding G (code-audit): --fix must never abort mid-regen — an unreadable
    # or undecodable openai.yaml is reported and skipped, and the rest of the
    # tree is still processed. Cycle-2 findings 1 + 7: the guard must cover
    # UnicodeDecodeError as well as OSError, and the chmod(0o000) simulation
    # must not run as root (DAC is bypassed at euid 0) — there a decode-error
    # fixture exercises the same reporting path instead.
    fix_tmp = pathlib.Path(tempfile.mkdtemp(prefix="lint-skills-fix-selftest-"))
    try:
        for sub in ("alpha", "beta", "gamma", "delta"):
            (fix_tmp / sub).mkdir()
            (fix_tmp / sub / "SKILL.md").write_text(
                f'---\nname: {sub}\ndescription: "{sub} skill."\n---\n', encoding="utf-8"
            )
            (fix_tmp / sub / "agents").mkdir()
        alpha_yaml = fix_tmp / "alpha" / "agents" / "openai.yaml"
        alpha_yaml.write_text(
            'interface:\n  display_name: "Old Alpha"\n  short_description: "stale."\n  default_prompt: "Use $alpha to help with this task."\n',
            encoding="utf-8",
        )
        # Windows lacks os.geteuid; the chmod(0o000) simulation is valid
        # anywhere DAC applies (euid != 0), so only the euid-0 branch swaps
        # in the decode-error fixture.
        if getattr(os, "geteuid", lambda: -1)() == 0:
            # Root bypasses DAC; make the file undecodable so the error path
            # still fires deterministically.
            alpha_yaml.write_bytes(b"interface:\n  display_name: \xff\xfe\n")
        else:
            alpha_yaml.chmod(0o000)
        beta_yaml = fix_tmp / "beta" / "agents" / "openai.yaml"
        beta_yaml.write_bytes(b"interface:\n  display_name: \xff\xfe\n")
        gamma_yaml = fix_tmp / "gamma" / "agents" / "openai.yaml"
        gamma_yaml.write_text(
            'interface:\n  display_name: "Old Gamma"\n  short_description: "stale."\n  default_prompt: "Use $gamma to help with this task."\n',
            encoding="utf-8",
        )
        delta_yaml = fix_tmp / "delta" / "agents" / "openai.yaml"
        delta_yaml.write_text(
            "# generated\npolicy:\n  allow_implicit_invocation: false\n",
            encoding="utf-8",
        )
        try:
            status = fix_openai_interfaces(fix_tmp)
        except (OSError, UnicodeDecodeError):
            status = -1
            failures.append("--fix aborted mid-regen on an unreadable/undecodable openai.yaml")
        finally:
            alpha_yaml.chmod(0o644)
        if status == 0:
            failures.append("--fix did not report the failing openai.yaml files")
        if "Old Gamma" in gamma_yaml.read_text(encoding="utf-8"):
            failures.append("--fix did not process files after the failing ones")
        delta_text = delta_yaml.read_text(encoding="utf-8")
        if "# generated" not in delta_text or "interface:" not in delta_text:
            failures.append("--fix did not preserve the leading comment while inserting the interface block")
        elif rewrite_interface_block(delta_text, "delta", "delta skill.") != delta_text:
            failures.append("comment-headed insert is not a --fix fixed point")
        # Codex PR #17 note 10: a headless openai.yaml that is a single
        # comment with NO trailing newline must still get a separating
        # newline before the inserted interface block — otherwise the block
        # glues onto the comment ("# generatedinterface:") and the insert is
        # neither valid nor a --fix fixed point.
        note10_yaml = fix_tmp / "note10" / "agents" / "openai.yaml"
        (fix_tmp / "note10" / "agents").mkdir(parents=True)
        (fix_tmp / "note10" / "SKILL.md").write_text(
            '---\nname: note10\ndescription: "n10."\n---\n', encoding="utf-8"
        )
        note10_yaml.write_text("# generated", encoding="utf-8")  # no trailing newline
        note10_fixed = rewrite_interface_block("# generated", "note10", "n10.")
        if "generatedinterface:" in note10_fixed:
            failures.append("comment-headed insert without trailing newline glued onto the comment")
        if rewrite_interface_block(note10_fixed, "note10", "n10.") != note10_fixed:
            failures.append("comment-headed insert without trailing newline is not a fixed point")
    finally:
        shutil.rmtree(fix_tmp, ignore_errors=True)
    # Codex PR #17 note 8 (P1): a symlinked openai.yaml must NOT be followed
    # and overwritten — that would let a contributed symlink corrupt any
    # writable file (even outside the worktree). The fixer must skip it and
    # report, never write through the link.
    if getattr(os, "symlink", None) is not None:
        sym_tmp = pathlib.Path(tempfile.mkdtemp(prefix="lint-skills-sym-selftest-"))
        try:
            victim = sym_tmp / "VICTIM.txt"
            victim.write_text("ORIGINAL - must not be touched", encoding="utf-8")
            evil = sym_tmp / "evil"
            evil.mkdir()
            (evil / "SKILL.md").write_text(
                '---\nname: evil\ndescription: "evil."\n---\n', encoding="utf-8"
            )
            (evil / "agents").mkdir()
            os.symlink(str(victim), str(evil / "agents" / "openai.yaml"))
            before = victim.read_text(encoding="utf-8")
            sym_status = fix_openai_interfaces(sym_tmp)
            after = victim.read_text(encoding="utf-8")
            if before != after:
                failures.append("symlinked openai.yaml was followed and overwrote the target")
            if sym_status == 0:
                failures.append("symlinked openai.yaml was not reported as an error")
        finally:
            shutil.rmtree(sym_tmp, ignore_errors=True)
    # Codex PR #17 round-3 note 8b (P1): a symlinked agents/ DIRECTORY (not just
    # the final openai.yaml) must also be rejected — otherwise --fix writes
    # through the link to an external target (e.g. agents -> /tmp/victimdir).
    if getattr(os, "symlink", None) is not None:
        sym2_tmp = pathlib.Path(tempfile.mkdtemp(prefix="lint-skills-symdir-selftest-"))
        try:
            victimdir = sym2_tmp / "victimdir"
            victimdir.mkdir()
            (victimdir / "openai.yaml").write_text(
                "EXTERNAL TARGET - must not be touched", encoding="utf-8"
            )
            evil2 = sym2_tmp / "evil2"
            evil2.mkdir()
            (evil2 / "SKILL.md").write_text(
                '---\nname: evil2\ndescription: "evil2."\n---\n', encoding="utf-8"
            )
            os.symlink(str(victimdir), str(evil2 / "agents"))
            before = (victimdir / "openai.yaml").read_text(encoding="utf-8")
            sym2_status = fix_openai_interfaces(sym2_tmp)
            after = (victimdir / "openai.yaml").read_text(encoding="utf-8")
            if before != after:
                failures.append("symlinked agents/ dir was followed and overwrote the target")
            if sym2_status == 0:
                failures.append("symlinked agents/ dir was not reported as an error")
        finally:
            shutil.rmtree(sym2_tmp, ignore_errors=True)
    # Codex PR #17 note 4: a SKILL.md with a name but NO description must not
    # be silently rewritten to a short_description: "" — the fixer should skip
    # and report it instead of damaging generated metadata.
    fm_tmp = pathlib.Path(tempfile.mkdtemp(prefix="lint-skills-fm-selftest-"))
    try:
        nod = fm_tmp / "nod"
        nod.mkdir()
        (nod / "SKILL.md").write_text("---\nname: nod\n---\n", encoding="utf-8")
        (nod / "agents").mkdir()
        (nod / "agents" / "openai.yaml").write_text(
            'interface:\n  display_name: "Nod"\n  short_description: "real."\n'
            '  default_prompt: "Use $nod."\n',
            encoding="utf-8",
        )
        fm_status = fix_openai_interfaces(fm_tmp)
        if 'short_description: ""' in (nod / "agents" / "openai.yaml").read_text(encoding="utf-8"):
            failures.append("--fix rewrote a valid openai.yaml to short_description: \"\" on missing description")
        if fm_status == 0:
            failures.append("missing-description SKILL.md was not reported as an error")
    finally:
        shutil.rmtree(fm_tmp, ignore_errors=True)
    if failures:
        print("skill lint selftest: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("skill lint selftest: OK (frontmatter, verification negatives, and interface derivation pinned)")
    return 0


def fix_openai_interfaces(skills_root: pathlib.Path = SKILLS) -> int:
    """Rewrite every skills/*/agents/openai.yaml interface block from the derivation.

    Reads the working tree (not the index): this is a regen command, so it fixes what
    the developer has on disk. Includes new-app and bugfix — their hand-tailored
    interface text is overwritten by design (see the plan's Decisions). A file that
    cannot be read or written (OSError or UnicodeDecodeError) is reported and
    skipped — the loop never aborts mid-regen — and a divergent file the rewrite
    could not change is also reported. Returns 1 when any file errored, else 0.
    """
    changed = 0
    errors: list[str] = []
    for skill in sorted(skills_root.glob("*/SKILL.md")):
        name = skill.parent.name
        try:
            # Reject symlinked skill dirs and metadata before reading/writing:
            # is_file() follows symlinks, so a contributed/accidental symlink
            # (incl. a sibling file outside the worktree) would be overwritten
            # by the write_text() below — arbitrary-file-write (Codex PR #17
            # note 8, P1). lstat() does NOT follow, so we skip the skill.
            if skill.is_symlink() or skill.parent.is_symlink():
                errors.append(f"{name}: skill directory or SKILL.md is a symlink; refusing to regen")
                continue
            fm = frontmatter(skill.read_text(encoding="utf-8"))
            if not fm or not fm.get("name") or not fm.get("description"):
                # Codex PR #17 note 4: a missing/malformed frontmatter (e.g. a
                # valid name but no description) parses to {} and --fix would
                # derive an empty short_description and silently overwrite a
                # previously valid openai.yaml. Skip and report instead of
                # damaging generated metadata.
                errors.append(
                    f"{name}: SKILL.md frontmatter missing or has no "
                    f"nonempty description; skipping --fix"
                )
                continue
            description = unquote(fm.get("description", ""))
            openai_path = skill.parent / "agents" / "openai.yaml"
            agents_dir = skill.parent / "agents"
            # Codex PR #17 note 8b (P1): the `agents/` directory itself may be
            # a symlink to an external writable dir (e.g. agents -> /tmp/x).
            # openai_path.is_symlink() is then False (only the final component
            # is checked), so --fix would write through the link to the outside
            # target. Reject a symlinked agents dir, and also require the
            # resolved openai.yaml to remain inside the skill directory as
            # defense in depth against any other ancestor link.
            if agents_dir.is_symlink():
                errors.append(f"{name}: agents/ directory is a symlink; refusing to regen")
                continue
            if not openai_path.exists():
                continue
            if openai_path.is_symlink():
                errors.append(f"{name}: agents/openai.yaml is a symlink; refusing to regen")
                continue
            try:
                resolved = openai_path.resolve()
                skill_root = skill.parent.resolve()
            except OSError:
                errors.append(f"{name}: could not resolve openai.yaml path; refusing to regen")
                continue
            if skill_root not in resolved.parents and resolved != skill_root:
                errors.append(
                    f"{name}: agents/openai.yaml resolves outside the skill directory; "
                    f"refusing to regen"
                )
                continue
            text = openai_path.read_text(encoding="utf-8")
            rewritten = rewrite_interface_block(text, name, description)
            if rewritten != text:
                openai_path.write_text(rewritten, encoding="utf-8")
                changed += 1
            elif interface_divergence(name, description, text) is not None:
                errors.append(f"{name}: interface block diverges but rewrite made no change")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{name}: {exc}")
    print(f"openai.yaml interface regen: rewrote {changed} file(s)")
    for error in errors:
        print(f"  error: {error}")
    return 1 if errors else 0


def main() -> int:
    if "--fix" in sys.argv[1:]:
        # Regen command: exit with the regen status and stop — running the
        # lint phase afterwards would re-read files the regen just reported
        # (e.g. an unreadable one) and crash instead of reporting.
        return fix_openai_interfaces()
    if not SKILLS.is_dir():
        print(f"skill lint: no skills dir at {SKILLS}")
        return 0

    tracked = set(gittracked.tracked_files("skills/"))
    # A tracked file directly under SKILLS (e.g. a root-level README.md) has only one
    # path component relative to SKILLS — that's the file itself, not a skill dir name.
    skill_names = sorted({
        p.relative_to(SKILLS).parts[0]
        for p in tracked
        if len(p.relative_to(SKILLS).parts) > 1
    })

    errors: list[str] = []
    missing_tests: list[str] = []
    manifest = json.loads((REPO / "toolbelt.json").read_text(encoding="utf-8"))
    explicit = set(manifest.get("skillPolicy", {}).get("explicit", []))

    for name in skill_names:
        d = SKILLS / name
        skill = d / "SKILL.md"
        if skill not in tracked:
            errors.append(f"{name}: no SKILL.md")
            continue

        text = gittracked.tracked_text_or_none(skill)
        if text is None:
            errors.append(f"{name}: SKILL.md missing from selected source")
            continue
        fm = frontmatter(text)
        if fm is None:
            errors.append(f"{name}: SKILL.md has no frontmatter block")
        else:
            if not fm.get("name"):
                errors.append(f"{name}: frontmatter missing `name`")
            elif fm["name"] != name:
                errors.append(f"{name}: frontmatter name {fm['name']!r} != dir {name!r}")
            if not fm.get("description"):
                errors.append(f"{name}: frontmatter missing `description`")
            extras = sorted(set(fm) - {"name", "description"})
            if extras:
                errors.append(
                    f"{name}: canonical frontmatter has provider-specific keys: "
                    + ", ".join(extras)
                )

        for ref in sorted(set(REF_RE.findall(text))):
            # Resolve from the ref's assets/ or references/ segment against the skill dir,
            # so both inline (`assets/x.md`) and full-path references resolve.
            seg = ref[ref.index("assets/") if "assets/" in ref else ref.index("references/"):]
            if (d / seg) not in tracked:
                errors.append(f"{name}: SKILL.md references missing file {seg}")

        tests_path = d / "tests.md"
        if tests_path not in tracked:
            missing_tests.append(name)
        else:
            tests_text = gittracked.tracked_text_or_none(tests_path) or ""
            scenarios = len(SCENARIO_RE.findall(tests_text))
            if scenarios < 3:
                errors.append(f"{name}: tests.md has {scenarios} scenario heading(s); need at least 3")
            if not VERIFICATION_RE.search(tests_text):
                errors.append(f"{name}: tests.md has no verification status/maturity marker")

        openai_path = d / "agents" / "openai.yaml"
        if openai_path not in tracked:
            errors.append(f"{name}: missing agents/openai.yaml")
        else:
            metadata = gittracked.tracked_text_or_none(openai_path) or ""
            implicit_disabled = bool(
                re.search(r"(?m)^\s*allow_implicit_invocation:\s*false\s*$", metadata)
            )
            if (name in explicit) != implicit_disabled:
                expected = "false" if name in explicit else "true/default"
                errors.append(
                    f"{name}: Codex implicit invocation policy does not match "
                    f"toolbelt.json (expected {expected})"
                )
            description = unquote(fm.get("description", "")) if fm else ""
            # Codex review note 7: a second top-level `interface:` block
            # (after policy:) is ambiguous — common YAML consumers may read
            # the later value, but the lint only inspects the first, so a
            # duplicate would pass silently. Flag it explicitly.
            interface_heads = len(_INTERFACE_HEAD_RE.findall(metadata))
            if interface_heads > 1:
                errors.append(
                    f"{name}: openai.yaml has {interface_heads} top-level "
                    f"`interface:` blocks; keep exactly one"
                )
            divergence = interface_divergence(name, description, metadata)
            # Cycle-2 finding 8: lint-clean must mean --fix fixed-point. The
            # divergence check is semantic; a file the canonical rewrite would
            # change (key order, quoting, duplicates) is divergent too.
            rewritten = rewrite_interface_block(metadata, name, description)
            if divergence is not None or rewritten != metadata:
                detail = divergence or "interface block is not in canonical serialization"
                errors.append(
                    f"{name}: openai.yaml interface block diverges from derivation "
                    f"({detail}); run scripts/ci/lint_skills.py --fix"
                )

    if missing_tests:
        errors.append(
            f"{len(missing_tests)} skill(s) without tests.md: "
            + ", ".join(missing_tests)
        )

    # Finding H: the neutral invocation sweep must not regress. Scan tracked
    # canonical text — SKILL.md plus references/ assets/ templates/ (tests.md
    # evidence prose is excluded by rule) — for any Claude-style `/name` syntax.
    slash_hits: list[str] = []
    for p in sorted(tracked):
        rel = p.relative_to(SKILLS)
        if len(rel.parts) < 2:
            continue
        if p.name != "SKILL.md" and not any(
            seg in ("references", "assets", "templates") for seg in rel.parts[1:]
        ):
            continue
        text = gittracked.tracked_text_or_none(p)
        if not text:
            continue
        for lineno, line in slash_sweep_hits(text):
            slash_hits.append(f"{p.relative_to(REPO)}:{lineno}: {line[:100]}")
    if slash_hits:
        errors.append(
            "canonical text carries Claude-style `/name` invocation syntax "
            "(sweep regression, finding H):\n  " + "\n  ".join(slash_hits)
        )

    return print_lint_epilogue(
        "skill lint",
        errors,
        "portable frontmatter, metadata policy, references, and verification scenarios",
    )


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv[1:] else main())
