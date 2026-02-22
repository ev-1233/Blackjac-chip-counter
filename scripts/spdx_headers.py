#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Evan McKeown
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations


import argparse
import os
from datetime import date
from pathlib import Path

COPYRIGHT_YEAR = os.getenv("SPDX_YEAR", str(date.today().year))
COPYRIGHT_OWNER = os.getenv("SPDX_COPYRIGHT_OWNER", "Evan McKeown")
COPYRIGHT_TOKEN = f"SPDX-FileCopyrightText: {COPYRIGHT_YEAR} {COPYRIGHT_OWNER}"
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


def _insertion_index(path: Path, lines: list[str]) -> int:
    if path.suffix == ".py":
        return _insertion_index_for_python(lines)
    if path.suffix == ".html" and lines and lines[0].strip().lower().startswith("<!doctype html"):
        return 1
    return 0


def add_header(path: Path) -> bool:
    header_lines = HEADER_LINES_BY_SUFFIX.get(path.suffix)
    if not header_lines:
        return False

    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    header_line_set = {line.strip() for line in header_lines}

    # Remove existing SPDX token lines so we can reinsert a canonical adjacent pair.
    lines_without_tokens = [
        line
        for line in lines
        if line.strip() not in header_line_set
    ]

    insert_at = _insertion_index(path, lines_without_tokens)

    # Drop blank lines at insertion point to avoid accumulating spacing.
    while insert_at < len(lines_without_tokens) and not lines_without_tokens[insert_at].strip():
        lines_without_tokens.pop(insert_at)

    header_block = [header_lines[0], header_lines[1]]
    if insert_at < len(lines_without_tokens) and lines_without_tokens[insert_at].strip():
        header_block.append("")

    new_lines = (
        lines_without_tokens[:insert_at]
        + header_block
        + lines_without_tokens[insert_at:]
    )
    updated = "\n".join(new_lines).rstrip("\n") + "\n"

    normalized_original = original.rstrip("\n") + "\n"
    if updated == normalized_original:
        return False

    path.write_text(updated, encoding="utf-8")
    return True


def is_missing_header(path: Path) -> bool:
    header_lines = HEADER_LINES_BY_SUFFIX.get(path.suffix)
    if not header_lines:
        return False

    lines = path.read_text(encoding="utf-8").splitlines()
    insert_at = _insertion_index(path, lines)

    if len(lines) <= insert_at + 1:
        return True

    return not (
        lines[insert_at] == header_lines[0]
        and lines[insert_at + 1] == header_lines[1]
    )


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
