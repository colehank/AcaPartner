"""Explicit source inputs shared by runtime snapshots and development evidence.

The two identities retain their existing digest encodings and different scopes:
the running app covers package inputs; development also covers build/entry tools.
Research assets, credentials, evidence and arbitrary Markdown/JSON are not inputs.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


IDENTITY_SCOPE = "runtime-inputs-v1"
SOURCE_SUFFIXES = frozenset({".py", ".mjs", ".js", ".html", ".css", ".svg", ".ts", ".tsx"})
RUNTIME_DATA_FILES = frozenset({
    "research_partner/runtime-features.json",
    "research_partner/native/research-strategy.md",
    "research_partner/web/package.json",
    "research_partner/fonts/DejaVuSans.ttf",
    "research_partner/fonts/DejaVuSans.LICENSE",
    "research_partner/fonts/NotoSansMath-Regular.ttf",
    "research_partner/fonts/NotoSansMath.LICENSE",
    "research_partner/fonts/NotoEmoji-Variable.ttf",
    "research_partner/fonts/NotoEmoji.LICENSE",
})
EXCLUDED_PARTS = frozenset({"__pycache__", ".private", ".runtime", ".git", "node_modules"})
BUILD_FILES = ("pyproject.toml", "setup.cfg", "setup.py", "MANIFEST.in")


def source_files(root, *, development=False):
    """Return relative file hashes, without importing code from the target root."""
    root = Path(root).resolve()
    paths = set()
    folders = ("research_partner", "tools", "frontend") if development else ("research_partner",)
    for folder in folders:
        for path in (root / folder).rglob("*"):
            relative = path.relative_to(root)
            if (path.is_file() and not EXCLUDED_PARTS.intersection(relative.parts)
                    and path.suffix in SOURCE_SUFFIXES):
                paths.add(relative.as_posix())
    for name in (*RUNTIME_DATA_FILES, *(BUILD_FILES if development else ()), *( ("frontend/package.json", "frontend/package-lock.json", "frontend/tsconfig.json") if development else ())):
        if (root / name).is_file():
            paths.add(name)
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in sorted(paths)}
