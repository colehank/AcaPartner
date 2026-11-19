#!/usr/bin/env python3
"""统一的后端质量入口；纳管清单由此维护，CI 与本地使用相同命令。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from collections.abc import Sequence

ROOT = Path(__file__).resolve().parents[1]
MAINTAINED_MODULES = (
    "src/research_partner/__main__.py",
    "src/research_partner/app.py",
    "src/research_partner/storage/store.py",
    "src/research_partner/http/server.py",
    "src/research_partner/rendering/engine.py",
    "src/research_partner/rendering/worker.py",
    "src/research_partner/providers/registry.py",
    "src/research_partner/providers/codex_configuration.py",
    "src/research_partner/providers/codex_dynamic.py",
    "src/research_partner/providers/codex_transport.py",
    "src/research_partner/commands/contract.py",
    "src/research_partner/contracts",
    "src/research_partner/execution/diagnostics.py",
    "src/research_partner/execution/process_output.py",
    "src/research_partner/providers/availability.py",
    "src/research_partner/commands/routing.py",
    "src/research_partner/commands/objects.py",
    "src/research_partner/commands/reviews.py",
    "src/research_partner/commands/assets.py",
    "src/research_partner/commands/tasks.py",
    "src/research_partner/commands/workspace.py",
    "src/research_partner/storage/policies.py",
    "src/research_partner/http/boundary.py",
    "src/research_partner/rendering/contract.py",
    "src/research_partner/resources/__init__.py",
    "src/research_partner/packaging/identity.py",
    "tools",
    "tests",
)
TYPED_BOUNDARIES = (
    "src/research_partner/contracts",
    "src/research_partner/commands/contract.py",
    "src/research_partner/providers/availability.py",
    "src/research_partner/execution/process_output.py",
    "src/research_partner/rendering/contract.py",
    "src/research_partner/http/boundary.py",
    "src/research_partner/storage/policies.py",
)


def commands(check: str) -> tuple[tuple[str, ...], ...]:
    checks = {
        "lint": (
            (
                "-m",
                "ruff",
                "check",
                "--select",
                "E9,F63,F7,F82",
                "src/research_partner",
                "tools",
                "tests",
            ),
            ("-m", "ruff", "check", *MAINTAINED_MODULES),
        ),
        "format": (("-m", "ruff", "format", "--check", *MAINTAINED_MODULES),),
        # 历史业务模块仍为动态类型，不把其全部隐式纳入本次静态检查。
        "types": (
            (
                "-m",
                "mypy",
                "--python-version",
                "3.12",
                "--follow-imports=skip",
                *TYPED_BOUNDARIES,
            ),
        ),
        "test": (
            (
                "-W",
                "error::ResourceWarning",
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-t",
                ".",
                "-v",
            ),
        ),
    }
    if check == "all":
        return tuple(command for group in checks.values() for command in group)
    return checks[check]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "check",
        choices=("lint", "format", "types", "test", "all"),
        nargs="?",
        default="all",
    )
    args = parser.parse_args(argv)
    environment = os.environ.copy()
    # 所有子检查统一优先使用本次源码树，避免误导入机器上旧的安装包。
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    for command in commands(args.check):
        result = subprocess.run(
            (sys.executable, *command), cwd=ROOT, env=environment, check=False
        )
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
