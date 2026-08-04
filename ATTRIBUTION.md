# Attribution

Portions of this project are derived from **Matt Pocock's skills collection**
(<https://github.com/mattpocock/skills>), used under the MIT License.

The skills below are adaptations of, or incorporate behavior from, that
collection — ranging from full adaptations to specific borrowed pieces:

- `tdd` — adapted from his `tdd` skill
- `spec` — adapted from his `to-spec` skill
- `build-skill` — adapts his `writing-great-skills` vocabulary and checklist
- `plan` — testing-strategy doctrine ported from his `tdd` skill
- `commit` — pre-commit-hook flow adapted from his `setup-pre-commit` skill
- `wayfinder` — adapted from his `wayfinder` skill
- `research` — adapted from his research skill
- `diagnosing-bugs` — incorporates behaviors backported from his skills
- `domain-modeling` — adapted from his `domain-modeling` skill (including the
  ADR-FORMAT and CONTEXT-FORMAT references)
- `codebase-design` — adapted from his `codebase-design` skill (including the
  DEEPENING and DESIGN-IT-TWICE references)
- `improve-codebase-architecture` — adapted from his skill of the same name
- `grilling` — rewritten locally, but descends from his `grilling` skill

The machine-readable pin for each derived skill (upstream repo, file path, and the
exact upstream **file blob SHA** the adaptation was last reviewed against — the SHA
the GitHub Contents API returns for that file, not a commit SHA) lives in
`upstream.json` at the repo root. `agentic check-upstream` compares those pins
against live upstream and reports drift; the weekly `upstream-check` GitHub Action
opens an issue when upstream moves. Updating a pin is a manual, reviewed decision —
adaptations diverge from upstream deliberately. To re-pin a skill, copy the `sha`
from the Contents API response for that path (or run `agentic check-upstream` and
read the reported upstream SHA).

The original MIT license covering that work is reproduced below in full.

---

MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
