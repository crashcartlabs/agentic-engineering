#!/usr/bin/env python3
"""Check pinned upstream skill sources for drift.

Reads the upstream registry (upstream.json at the repo root), fetches each pinned
upstream file's current SHA from GitHub's contents API, and reports whether the
locally pinned SHA is current. The pinned values are the file **blob SHAs** the
Contents API returns for each path — not commit SHAs; recording a commit SHA in
the registry would always appear changed. Adaptations are never auto-merged; this
tool makes drift visible so a human (or the weekly GitHub Action) can review
whether to port anything from upstream.

Exit codes mirror the repo gate's tiers:
  0  all pinned skills CURRENT
  1  at least one CHANGED (upstream moved past the pinned SHA)
  2  could not verify (registry missing/broken, or an entry UNREACHABLE)

Usage:
    python3 scripts/maintenance/check_upstream.py
    python3 scripts/maintenance/check_upstream.py --selftest
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = REPO / "upstream.json"


def load_registry(path: pathlib.Path) -> dict:
    """Load and validate the upstream registry. Raises ValueError on bad shape."""
    if not path.is_file():
        raise ValueError(f"registry not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"registry is not valid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"registry root must be an object, got {type(data).__name__}: {path}")
    skills = data.get("skills")
    if not isinstance(skills, list) or not skills:
        raise ValueError(f"registry has no skills list: {path}")
    for entry in skills:
        if not isinstance(entry, dict):
            raise ValueError(f"registry entry must be an object, got {type(entry).__name__}: {path}")
        for key in ("local", "repo", "path", "ref", "sha"):
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise ValueError(f"registry entry missing '{key}': {entry}")
        extra = entry.get("files")
        if extra is not None:
            if not isinstance(extra, list) or not extra:
                raise ValueError(f"registry entry 'files' must be a non-empty list: {entry}")
            for item in extra:
                if not isinstance(item, dict):
                    raise ValueError(f"registry 'files' item must be an object: {entry}")
                for key in ("path", "sha"):
                    if not isinstance(item.get(key), str) or not item[key]:
                        raise ValueError(f"registry 'files' item missing '{key}': {item}")
    return data


def fetch_upstream_sha(entry: dict, token: str | None) -> str:
    """Return the current SHA of the upstream file named by entry."""
    import urllib.request

    url = (
        f"https://api.github.com/repos/{entry['repo']}/contents/{entry['path']}"
        f"?ref={entry['ref']}"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    sha = data.get("sha")
    if not isinstance(sha, str) or not sha:
        raise ValueError(f"no sha in API response for {entry['repo']}/{entry['path']}")
    return sha


def entry_files(entry: dict) -> list[tuple[str, str]]:
    """(path, pinned_sha) pairs for an entry: the primary file plus derived files.

    Adaptations often include upstream reference files beyond SKILL.md
    (e.g. codebase-design's DEEPENING.md); each derived file gets its own pin
    because GitHub blob SHAs are per file.
    """
    files = [(entry["path"], entry["sha"])]
    files.extend((item["path"], item["sha"]) for item in entry.get("files", []))
    return files


def check_entry(entry: dict, token: str | None) -> tuple[str, str | None]:
    """Return (status, detail) for one registry entry.

    status is CURRENT (every derived file matches its pin), CHANGED (at least
    one moved, detail names the files with full upstream SHAs for re-pinning),
    or UNREACHABLE (a fetch failed; detail carries the reason).
    """
    changed: list[str] = []
    for path, pinned in entry_files(entry):
        try:
            current = fetch_upstream_sha({**entry, "path": path}, token)
        except Exception as exc:  # network, HTTP, or JSON trouble — cannot verify
            return "UNREACHABLE", f"{type(exc).__name__}: {exc} ({path})"
        if current != pinned:
            changed.append(f"{path}: pinned {pinned[:12]}, upstream {current}")
    if not changed:
        return "CURRENT", None
    return "CHANGED", "; ".join(changed)


def run(registry_path: pathlib.Path, token: str | None) -> int:
    """Check every entry, print a per-skill report, return the exit code."""
    import os

    if token is None:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    try:
        data = load_registry(registry_path)
    except ValueError as exc:
        print(f"check_upstream: {exc}")
        return 2

    statuses: list[str] = []
    for entry in data["skills"]:
        status, detail = check_entry(entry, token)
        statuses.append(status)
        line = f"{status:10s} {entry['local']:<28s} {entry['repo']}/{entry['path']}"
        if detail:
            line += f"  ({detail})"
        print(line)

    changed = statuses.count("CHANGED")
    unreachable = statuses.count("UNREACHABLE")
    print(
        f"check_upstream: {len(statuses)} skills, "
        f"{statuses.count('CURRENT')} current, {changed} changed, {unreachable} unreachable"
    )
    if unreachable:
        return 2
    if changed:
        return 1
    return 0


def selftest() -> int:
    """Hermetic selftest: canned upstream states, no network."""
    import tempfile

    failures: list[str] = []

    def expect(name: str, got, want) -> None:
        if got != want:
            failures.append(f"{name}: got {got!r}, want {want!r}")

    # --- registry validation ---
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        missing = root / "nope.json"
        try:
            load_registry(missing)
            failures.append("load_registry: missing file must raise ValueError")
        except ValueError:
            pass
        bad = root / "bad.json"
        bad.write_text(json.dumps({"skills": [{"local": "x"}]}), encoding="utf-8")
        try:
            load_registry(bad)
            failures.append("load_registry: entry missing 'sha' must raise ValueError")
        except ValueError:
            pass
        list_root = root / "list-root.json"
        list_root.write_text(json.dumps([{"local": "x"}]), encoding="utf-8")
        try:
            load_registry(list_root)
            failures.append("load_registry: non-object root must raise ValueError")
        except ValueError:
            pass
        scalar_entry = root / "scalar-entry.json"
        scalar_entry.write_text(json.dumps({"skills": ["not-an-object"]}), encoding="utf-8")
        try:
            load_registry(scalar_entry)
            failures.append("load_registry: non-object entry must raise ValueError")
        except ValueError:
            pass
        bad_files = root / "bad-files.json"
        bad_files.write_text(json.dumps({"skills": [{
            "local": "x", "repo": "r", "path": "p", "ref": "main", "sha": "a",
            "files": [{"path": "r.md"}],
        }]}), encoding="utf-8")
        try:
            load_registry(bad_files)
            failures.append("load_registry: 'files' item missing 'sha' must raise ValueError")
        except ValueError:
            pass
        good = root / "good.json"
        good.write_text(json.dumps({"skills": [{
            "local": "tdd", "repo": "mattpocock/skills",
            "path": "skills/engineering/tdd/SKILL.md", "ref": "main",
            "sha": "abc123", "synced": "2026-08-03", "note": "n",
        }]}), encoding="utf-8")
        loaded = load_registry(good)
        expect("load_registry: entries parsed", len(loaded["skills"]), 1)

    # --- entry status classification ---
    import sys
    from typing import Any

    cu: Any = sys.modules[__name__]  # patch the running module, not a re-imported copy

    states: list[tuple[dict, str | None]] = [
        ({"sha": "same", "path": "p", "repo": "r", "ref": "main"}, "same"),      # CURRENT
        ({"sha": "old", "path": "p", "repo": "r", "ref": "main"}, "new"),        # CHANGED
    ]

    def fake_fetch(entry: dict, token: str | None) -> str:
        if entry["sha"] == "old":
            return "new"
        if entry["sha"] == "same":
            return "same"
        raise RuntimeError("boom")

    cu.fetch_upstream_sha = fake_fetch
    statuses = [check_entry(e, None)[0] for e, _ in states]
    expect("classification: CURRENT", statuses[0], "CURRENT")
    expect("classification: CHANGED", statuses[1], "CHANGED")
    status, detail = check_entry({"sha": "old", "path": "p", "repo": "r", "ref": "main"}, None)
    if detail is None or "upstream new" not in detail:
        failures.append("classification: CHANGED must carry the full upstream sha for re-pinning")

    # Multi-file entries: every derived file must match for CURRENT; one changed
    # file flips the entry to CHANGED and names the file (P2: derived references).
    def multi_fetch(entry: dict, token: str | None) -> str:
        if entry["path"].endswith("moved.md"):
            return "newsha"
        return "same"

    cu.fetch_upstream_sha = multi_fetch
    entry_ok = {"sha": "same", "path": "SKILL.md", "repo": "r", "ref": "main",
                "files": [{"path": "refs/stable.md", "sha": "same"}]}
    expect("multi-file: all current -> CURRENT", check_entry(entry_ok, None)[0], "CURRENT")
    entry_changed = {"sha": "same", "path": "SKILL.md", "repo": "r", "ref": "main",
                     "files": [{"path": "refs/moved.md", "sha": "old"}]}
    status, detail = check_entry(entry_changed, None)
    expect("multi-file: one changed -> CHANGED", status, "CHANGED")
    if detail is None or "moved.md" not in detail or "upstream newsha" not in detail:
        failures.append("multi-file: CHANGED detail must name the moved file with its full sha")

    def fake_fetch_err(entry: dict, token: str | None) -> str:
        raise RuntimeError("network down")

    cu.fetch_upstream_sha = fake_fetch_err
    status, detail = check_entry({"sha": "x", "path": "p", "repo": "r", "ref": "main"}, None)
    expect("classification: UNREACHABLE status", status, "UNREACHABLE")
    if "network down" not in detail:
        failures.append("classification: UNREACHABLE must carry the reason")

    # --- exit codes through run() with a temp registry and stubbed fetches ---
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        reg = root / "reg.json"
        reg.write_text(json.dumps({"skills": [
            {"local": "a", "repo": "r", "path": "p", "ref": "main", "sha": "same",
             "synced": "2026-08-03", "note": "n"},
            {"local": "b", "repo": "r", "path": "p", "ref": "main", "sha": "old",
             "synced": "2026-08-03", "note": "n"},
        ]}), encoding="utf-8")

        def fake_fetch2(entry: dict, token: str | None) -> str:
            return "same" if entry["sha"] == "same" else "new"

        cu.fetch_upstream_sha = fake_fetch2
        rc = run(reg, None)
        expect("run: CHANGED exits 1", rc, 1)

        reg2 = root / "reg2.json"
        reg2.write_text(json.dumps({"skills": [
            {"local": "a", "repo": "r", "path": "p", "ref": "main", "sha": "same",
             "synced": "2026-08-03", "note": "n"},
        ]}), encoding="utf-8")
        rc = run(reg2, None)
        expect("run: all CURRENT exits 0", rc, 0)

        def fake_fetch_err2(entry: dict, token: str | None) -> str:
            raise RuntimeError("down")

        cu.fetch_upstream_sha = fake_fetch_err2
        rc = run(reg2, None)
        expect("run: UNREACHABLE exits 2", rc, 2)

        # A registry whose root is a list (not an object) must exit 2, not crash
        # with AttributeError (which the GitHub Action would misread as drift).
        reg3 = root / "reg3.json"
        reg3.write_text(json.dumps([{"local": "a"}]), encoding="utf-8")
        rc = run(reg3, None)
        expect("run: non-object registry root exits 2", rc, 2)

    if failures:
        print("check_upstream selftest: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("check_upstream selftest: OK (registry, classification, exit tiers)")
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv == ["--selftest"]:
        return selftest()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=pathlib.Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args(argv)
    return run(args.registry, None)


if __name__ == "__main__":
    raise SystemExit(main())
