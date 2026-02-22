#!/usr/bin/env python3
from __future__ import annotations

# SPDX-FileCopyrightText: 2026 Evan McKeown
# SPDX-License-Identifier: Apache-2.0

import argparse
from pathlib import Path

COPYRIGHT_TOKEN = "SPDX-FileCopyrightText: 2026 Evan McKeown"
LICENSE_TOKEN = "SPDX-License-Identifier: Apache-2.0"

HEADER_LINES_BY_SUFFIX = {
    ".py": [f"# {COPYRIGHT_TOKEN}", f"# {LICENSE_TOKEN}"],
    ".js": [f"// {COPYRIGHT_TOKEN}", f"// {LICENSE_TOKEN}"],
    ".css": [f"/* {COPYRIGHT_TOKEN} */", f"/* {LICENSE_TOKEN} */"],
    ".html": [f"<!-- {COPYRIGHT_TOKEN} -->", f"<!-- {LICENSE_TOKEN} -->"],
}

TARGET_SUFFIXES = set(HEADER_LINES_BY_SUFFIX)
SKIP_DIR_NAMES = {".git", "node_modules", ".venv", "venv", "__pycache__"}


def discover_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in TARGET_SUFFIXES:
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _insertion_index_for_python(lines: list[str]) -> int:
    index = 0
    if lines and lines[0].startswith("#!"):
        index = 1
    if len(lines) > index and ("coding:" in lines[index] or "coding=" in lines[index]):
        index += 1
    return index


def add_header(path: Path) -> bool:
    header_lines = HEADER_LINES_BY_SUFFIX.get(path.suffix)
    if not header_lines:
        return False

    original = path.read_text(encoding="utf-8")
    first_lines = "\n".join(original.splitlines()[:12])
    has_copyright = COPYRIGHT_TOKEN in first_lines
    has_license = LICENSE_TOKEN in first_lines
    if has_copyright and has_license:
        return False

    missing_lines: list[str] = []
    if not has_copyright:
        missing_lines.append(header_lines[0])
    if not has_license:
        missing_lines.append(header_lines[1])

    lines = original.splitlines()
    insert_at = 0

    if path.suffix == ".py":
        insert_at = _insertion_index_for_python(lines)
    elif path.suffix == ".html":
        if lines and lines[0].strip().lower().startswith("<!doctype html"):
            insert_at = 1

    new_lines = lines[:insert_at] + missing_lines + [""] + lines[insert_at:]
    updated = "\n".join(new_lines).rstrip("\n") + "\n"
    path.write_text(updated, encoding="utf-8")
    return True


def is_missing_header(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    first_lines = "\n".join(original.splitlines()[:12])
    return COPYRIGHT_TOKEN not in first_lines or LICENSE_TOKEN not in first_lines


def normalize_paths(root: Path, raw_paths: list[str]) -> list[Path]:
    resolved: list[Path] = []
    for raw in raw_paths:
        p = Path(raw)
        if not p.is_absolute():
            p = (root / p).resolve()
        if p.is_file() and p.suffix in TARGET_SUFFIXES and not any(
            part in SKIP_DIR_NAMES for part in p.parts
        ):
            resolved.append(p)
    return sorted(set(resolved))


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply/check SPDX Apache-2.0 headers.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Fail if headers are missing")
    mode.add_argument("--apply", action="store_true", help="Add missing headers")
    parser.add_argument("paths", nargs="*", help="Optional file paths to process")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    files = normalize_paths(root, args.paths) if args.paths else discover_files(root)

    changed: list[Path] = []

    if args.check:
        changed = [path for path in files if is_missing_header(path)]
    else:
        for path in files:
            if add_header(path):
                changed.append(path)

    if args.check:
        if changed:
            print("Missing SPDX headers:")
            for p in changed:
                print(f"- {p.relative_to(root)}")
            return 1
        print("All checked files already contain SPDX headers.")
        return 0

    if changed:
        print("Added SPDX headers:")
        for p in changed:
            print(f"- {p.relative_to(root)}")
    else:
        print("No files needed header updates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
