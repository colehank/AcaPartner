"""仓库结构、惰性路由和包内资源的可执行约束。"""

import ast
import importlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from research_partner.app import App
from research_partner.commands.routing import COMMAND_ROUTES, DOMAIN_ROUTES
from research_partner.resources import (
    module_file,
    package_root,
    resource_path,
    source_root,
    web_directory,
)


class RepositoryLayout(unittest.TestCase):
    def test_only_application_entries_remain_at_package_root(self):
        self.assertEqual(
            {path.name for path in package_root().glob("*.py")},
            {"__init__.py", "__main__.py", "app.py"},
        )
        for name in (
            "commands",
            "contracts",
            "storage",
            "http",
            "rendering",
            "providers",
            "execution",
            "domains",
            "packaging",
            "security",
            "resources",
        ):
            self.assertTrue((package_root() / name / "__init__.py").is_file(), name)

    def test_registered_modules_and_real_handler_signatures_resolve(self):
        for route in (*DOMAIN_ROUTES, *COMMAND_ROUTES):
            with self.subTest(module=route.module, handler=route.handler):
                if route.invocation in {"method", "scope"}:
                    handler = getattr(App, route.handler)
                    args = (
                        (object(), None)
                        if route.invocation == "scope"
                        else (object(), {}, None)
                    )
                else:
                    handler = getattr(
                        importlib.import_module(route.module), route.handler
                    )
                    args = (
                        (object(), {}, None, None)
                        if route.invocation == "principal"
                        else (object(), {}, None)
                    )
                inspect.signature(handler).bind(*args)

    def test_non_http_domains_do_not_depend_on_http_transport(self):
        for base in (
            "domains",
            "storage",
            "rendering",
            "providers",
            "execution",
            "contracts",
            "security",
        ):
            for path in (package_root() / base).rglob("*.py"):
                for node in ast.walk(ast.parse(path.read_text())):
                    if isinstance(node, ast.ImportFrom):
                        self.assertFalse(
                            (node.module or "").startswith("research_partner.http"),
                            f"{path}:{node.lineno}",
                        )

    def test_resources_have_one_authoritative_location(self):
        for name in (
            "fonts/DejaVuSans.ttf",
            "fonts/DejaVuSans.LICENSE",
            "fonts/NotoSansMath-Regular.ttf",
            "fonts/NotoSansMath.LICENSE",
            "fonts/NotoEmoji-Variable.ttf",
            "fonts/NotoEmoji.LICENSE",
            "agent_runtime/native-launch.py",
            "agent_runtime/research-strategy.md",
            "runtime-features.json",
        ):
            self.assertTrue(resource_path(*name.split("/")).is_file(), name)
        self.assertTrue((web_directory("legacy") / "index.html").is_file())
        self.assertFalse((package_root() / "fonts").exists())
        self.assertFalse((package_root() / "native").exists())
        self.assertFalse((package_root() / "web").exists())
        for invalid in ("../fonts", "other"):
            with self.assertRaises(ValueError):
                web_directory(invalid)
        with self.assertRaises(ValueError):
            module_file("outside.module")
        self.assertTrue((source_root() / "src/research_partner/__init__.py").is_file())

    def test_mcp_distribution_copy_is_identical_and_self_contained(self):
        original = module_file("research_partner.integrations.mcp_workbench")
        copied = (
            source_root()
            / "integrations/codex/research-workbench/scripts/mcp_workbench.py"
        )
        self.assertEqual(original.read_bytes(), copied.read_bytes())
        with tempfile.TemporaryDirectory() as temporary:
            standalone = Path(temporary) / "adapter.py"
            standalone.write_bytes(copied.read_bytes())
            result = subprocess.run(
                [sys.executable, "-I", str(standalone), "--help"],
                cwd=temporary,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--token-file", result.stdout)

    def test_direct_source_worker_works_without_installed_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, response = root / "request.json", root / "response.json"
            request.write_text(
                json.dumps(
                    {
                        "operation": "unknown",
                        "output_dir": str(root),
                        "response": str(response),
                    }
                )
            )
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(module_file("research_partner.rendering.worker")),
                    str(request),
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(response.read_text())["code"], "invalid")
            self.assertEqual(
                json.loads(result.stdout), {"ok": False, "response": str(response)}
            )
            self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
