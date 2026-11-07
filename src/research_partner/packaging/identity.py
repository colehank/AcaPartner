"""供运行快照与开发冻结使用的显式源码输入，不读取科研数据或凭据。"""

from __future__ import annotations

import hashlib
from pathlib import Path

IDENTITY_SCOPE = "runtime-inputs-v1"
SOURCE_SUFFIXES = frozenset(
    {".py", ".mjs", ".js", ".html", ".css", ".svg", ".ts", ".tsx"}
)
EXCLUDED_PARTS = frozenset(
    {"__pycache__", ".private", ".runtime", ".git", "node_modules"}
)
BUILD_FILES = ("pyproject.toml", "setup.cfg", "setup.py", "MANIFEST.in")
RESOURCE_FILES = (
    "runtime-features.json",
    "agent_runtime/research-strategy.md",
    "fonts/DejaVuSans.ttf",
    "fonts/DejaVuSans.LICENSE",
    "fonts/NotoSansMath-Regular.ttf",
    "fonts/NotoSansMath.LICENSE",
    "fonts/NotoEmoji-Variable.ttf",
    "fonts/NotoEmoji.LICENSE",
)


def source_files(root, *, development=False):
    """返回目标目录的相对路径摘要，不导入目标发行代码，兼容旧发行布局。"""
    root = Path(root).resolve()
    modern = (root / "src/research_partner/__init__.py").is_file()
    package = "src/research_partner" if modern else "research_partner"
    folders = [package]
    if modern:
        folders.extend(("build/frontend/workdesk", "frontend/legacy"))
    if development:
        folders.extend(("tools", "frontend", "integrations", "tests"))
    paths = set()
    for folder in folders:
        for path in (root / folder).rglob("*"):
            relative = path.relative_to(root)
            if (
                path.is_file()
                and not EXCLUDED_PARTS.intersection(relative.parts)
                and path.suffix in SOURCE_SUFFIXES
            ):
                paths.add(relative.as_posix())
    resources = [f"{package}/resources/{name}" for name in RESOURCE_FILES]
    if not modern:
        resources.extend(
            f"research_partner/{name.replace('agent_runtime/', 'native/')}"
            for name in RESOURCE_FILES
        )
        resources.append("research_partner/web/package.json")
    if development:
        resources.extend(BUILD_FILES)
        resources.extend(
            (
                "frontend/workdesk/package.json",
                "frontend/workdesk/package-lock.json",
                "frontend/workdesk/tsconfig.json",
                "frontend/package.json",
                "frontend/package-lock.json",
                "frontend/tsconfig.json",
                "environments/core-generation-runtime.in",
                "environments/core-generation-runtime.lock",
                "environments/core-generation-build.lock",
            )
        )
    for name in resources:
        if (root / name).is_file():
            paths.add(name)
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in sorted(paths)
    }
