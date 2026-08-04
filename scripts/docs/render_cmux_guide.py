#!/usr/bin/env python3
"""Render docs/cmux-guide.html from the canonical Markdown guide."""

from __future__ import annotations

import html
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SOURCE = REPO / "docs" / "cmux-guide.md"
OUTPUT = REPO / "docs" / "cmux-guide.html"


def inline(text: str) -> str:
    escaped = html.escape(text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)


def markdown_body(text: str) -> str:
    lines = text.splitlines()
    rendered: list[str] = []
    paragraph: list[str] = []
    list_items: list[list[str]] = []
    code: list[str] | None = None

    def flush_paragraph() -> None:
        if paragraph:
            rendered.append(f"<p>{inline(' '.join(part.strip() for part in paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            rendered.append("<ul>")
            for item in list_items:
                rendered.append(f"  <li>{inline(' '.join(part.strip() for part in item))}</li>")
            rendered.append("</ul>")
            list_items.clear()

    for line in lines:
        if line.startswith("```"):
            flush_paragraph()
            flush_list()
            if code is None:
                code = []
            else:
                rendered.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
                code = None
            continue
        if code is not None:
            code.append(line)
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            title = heading.group(2)
            anchor = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            rendered.append(f'<h{level} id="{anchor}">{inline(title)}</h{level}>')
        elif line.startswith("- "):
            flush_paragraph()
            list_items.append([line[2:]])
        elif line.startswith("  ") and list_items:
            list_items[-1].append(line)
        elif not line.strip():
            flush_paragraph()
            flush_list()
        else:
            flush_list()
            paragraph.append(line)
    flush_paragraph()
    flush_list()
    if code is not None:
        rendered.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
    return "\n".join(rendered)


def render(source: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="scripts/docs/render_cmux_guide.py">
<title>cmux orchestrator guide</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ margin: 0; font: 16px/1.6 system-ui, sans-serif; background: #f6f7f9; color: #18202a; }}
main {{ max-width: 900px; margin: 2rem auto; padding: 2rem 3rem; background: #fff; border-radius: 14px; box-shadow: 0 8px 30px #0001; }}
h1 {{ font-size: 2rem; }} h2 {{ margin-top: 2rem; border-bottom: 1px solid #d9dee5; padding-bottom: .35rem; }}
code {{ background: #eef1f5; border-radius: 4px; padding: .12rem .35rem; }}
pre {{ overflow-x: auto; padding: 1rem; background: #111827; color: #e5e7eb; border-radius: 8px; }}
pre code {{ background: transparent; padding: 0; }} li {{ margin: .45rem 0; }}
.generated {{ color: #64748b; font-size: .85rem; }}
@media (prefers-color-scheme: dark) {{ body {{ background:#0b1017;color:#e5e7eb }} main {{ background:#131a24 }} code {{ background:#263244 }} h2 {{ border-color:#334155 }} }}
</style>
</head>
<body><main>
<p class="generated">Generated from <code>docs/cmux-guide.md</code>; do not edit this HTML directly.</p>
{markdown_body(source)}
</main></body>
</html>
"""


def main() -> int:
    expected = render(SOURCE.read_text(encoding="utf-8"))
    if "--generate" in sys.argv[1:]:
        OUTPUT.write_text(expected, encoding="utf-8")
    elif not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
        print("generated docs check: FAIL")
        print("  - docs/cmux-guide.html is stale; run render_cmux_guide.py --generate")
        return 1
    print("generated docs check: OK (cmux-guide.html matches Markdown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
