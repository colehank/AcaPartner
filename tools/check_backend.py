#!/usr/bin/env python3
"""统一的后端质量入口；纳管清单由此维护，CI 与本地使用相同命令。"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from collections.abc import Sequence

ROOT = Path(__file__).resolve().parents[1]
MAINTAINED_MODULES = (
    "research_partner/__main__.py",
    "research_partner/app.py",
    "research_partner/store.py",
    "research_partner/server.py",
    "research_partner/artifacts.py",
    "research_partner/render_worker.py",
    "research_partner/providers.py",
    "research_partner/codex_dynamic_configuration.py",
    "research_partner/codex_dynamic_provider.py",
    "research_partner/codex_dynamic_transport.py",
    "research_partner/action_contract.py",
    "research_partner/contracts.py",
    "research_partner/diagnostics.py",
    "research_partner/process_output.py",
    "research_partner/provider_availability.py",
    "research_partner/command_routing.py",
    "research_partner/command_objects.py",
    "research_partner/command_reviews.py",
    "research_partner/command_assets.py",
    "research_partner/command_tasks.py",
    "research_partner/command_workspace.py",
    "research_partner/object_policies.py",
    "research_partner/http_boundary.py",
    "research_partner/render_contract.py",
    "tools/check_backend.py",
    "tests",
)
TYPED_BOUNDARIES = (
    "research_partner/contracts.py",
    "research_partner/action_contract.py",
    "research_partner/provider_availability.py",
    "research_partner/process_output.py",
    "research_partner/render_contract.py",
    "research_partner/http_boundary.py",
    "research_partner/object_policies.py",
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
                "research_partner",
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
    for command in commands(args.check):
        result = subprocess.run((sys.executable, *command), cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
