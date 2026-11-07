#!/usr/bin/env python3
"""在临时目录验收离线源码发行；--wheel 另验标准 sdist/wheel 和隔离安装。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from research_partner.packaging.compatibility import verify_release  # noqa: E402
from tools.build import build  # noqa: E402
from tools.install import install  # noqa: E402


SOURCE_TESTS = """
import pathlib, sys, unittest
root = pathlib.Path(sys.argv[1]).resolve()
sys.path[:0] = [str(root / 'src'), str(root)]
suite = unittest.defaultTestLoader.discover(str(root / 'tests'), top_level_dir=str(root))
def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test
ids = [test.id() for test in flatten(suite)]
assert len(ids) == len(set(ids)), 'duplicate test discovery'
assert ids, 'no packaged tests discovered'
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
"""

WHEEL_SMOKE = """
import http.client, json, pathlib, secrets, sys, tempfile, threading
from research_partner.app import App
from research_partner.http.server import serve
from research_partner.resources import package_root, resource_path, web_directory
assert pathlib.Path(sys.prefix) in package_root().parents, package_root()
for interface in ('workdesk', 'legacy'):
    assert (web_directory(interface) / 'index.html').is_file(), interface
for name in ('fonts/DejaVuSans.ttf', 'fonts/DejaVuSans.LICENSE',
             'fonts/NotoSansMath-Regular.ttf', 'fonts/NotoSansMath.LICENSE',
             'fonts/NotoEmoji-Variable.ttf', 'fonts/NotoEmoji.LICENSE',
             'agent_runtime/native-launch.py', 'agent_runtime/research-strategy.md',
             'runtime-features.json'):
    assert resource_path(*name.split('/')).is_file(), name
with tempfile.TemporaryDirectory() as temporary:
    root = pathlib.Path(temporary)
    token = root / 'token'
    token.write_text(secrets.token_urlsafe(32))
    token.chmod(0o600)
    app = App(root / 'workspace', {'access_token_file': str(token), 'workdesk_w1a': True})
    assert app.runner is None
    project = app.dispatch({'action': 'project.create', 'title': 'Wheel fixture'})
    assert project['title'] == 'Wheel fixture'
    server = serve(app, '127.0.0.1', 0)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})
    thread.start()
    try:
        for path, expected in (('/', 200), ('/workdesk/', 200), ('/app.js', 200), ('/api/state', 401)):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                connection.request('GET', path)
                response = connection.getresponse()
                assert response.status == expected, (path, response.status)
                assert response.read(), path
            finally:
                connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()
print(json.dumps({'wheel_import': True, 'resources': True, 'temporary_project': True, 'http_pages': True, 'http_auth': True}))
"""


def run(command, *, cwd):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(command, cwd=cwd, env=environment, check=True, timeout=300)


def check_release(root: Path, *, wheel: bool = False):
    with tempfile.TemporaryDirectory(prefix="research-partner-release-") as temporary:
        work = Path(temporary).resolve()
        first = build(root, work / "first")
        second = build(root, work / "second")
        if first["sha256"] != second["sha256"]:
            raise ValueError("相同输入的源码归档不可重现")
        release = work / "installed"
        install(first["path"], release)
        verified = verify_release(release)
        run(
            [
                sys.executable,
                "-I",
                "-W",
                "error::ResourceWarning",
                "-c",
                SOURCE_TESTS,
                str(release),
            ],
            cwd=work,
        )
        run(
            [sys.executable, "-I", str(release / "research-partner"), "--help"],
            cwd=work,
        )
        run(
            [
                sys.executable,
                "-I",
                str(release / "tools/start_local.py"),
                "--plan",
                "--data-dir",
                str(work / "private-data"),
            ],
            cwd=work,
        )
        if (work / "private-data").exists():
            raise ValueError("只读启动计划不应创建用户数据目录")
        report = {
            "source_files": verified["verified_files"],
            "source_sha256": first["sha256"],
            "reproducible": True,
            "packaged_tests": True,
            "wheel": False,
        }
        if wheel:
            # build/setuptools/wheel 是显式开发工具，不是应用运行依赖。
            artifacts = work / "artifacts"
            run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--no-isolation",
                    "--wheel",
                    "--sdist",
                    "--outdir",
                    str(artifacts),
                    str(release),
                ],
                cwd=work,
            )
            sdist = next(artifacts.glob("*.tar.gz"))
            unpacked = work / "sdist"
            unpacked.mkdir()
            with tarfile.open(sdist) as archive:
                archive.extractall(unpacked, filter="data")
            source = next(path for path in unpacked.iterdir() if path.is_dir())
            run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--no-isolation",
                    "--wheel",
                    "--outdir",
                    str(work / "rebuilt"),
                    str(source),
                ],
                cwd=work,
            )
            environment = work / "venv"
            venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
            python = environment / "bin/python"
            artifact = next((work / "rebuilt").glob("*.whl"))
            run(
                [
                    sys.executable,
                    "-I",
                    "-m",
                    "pip",
                    "--python",
                    str(python),
                    "install",
                    "--no-index",
                    "--no-deps",
                    str(artifact),
                ],
                cwd=work,
            )
            run([str(python), "-I", "-c", WHEEL_SMOKE], cwd=work)
            run([str(environment / "bin/research-partner"), "--help"], cwd=work)
            editable_source = work / "editable-source"
            install(first["path"], editable_source)
            # 仅删除本工具刚从已校验归档装配的临时页面，模拟纯后端克隆。
            shutil.rmtree(editable_source / "src/research_partner/resources/web")
            editable_environment = work / "editable-venv"
            venv.EnvBuilder(with_pip=False, symlinks=True).create(editable_environment)
            editable_python = editable_environment / "bin/python"
            # 由调用方开发工具执行标准 PEP 660 hook，目标环境不安装构建工具。
            editable_artifacts = work / "editable-artifacts"
            editable_artifacts.mkdir()
            run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "import sys; sys.path.insert(0, sys.argv[1]); "
                    "from tools.package_resources import build_editable; build_editable(sys.argv[2])",
                    str(editable_source),
                    str(editable_artifacts),
                ],
                cwd=editable_source,
            )
            run(
                [
                    sys.executable,
                    "-I",
                    "-m",
                    "pip",
                    "--python",
                    str(editable_python),
                    "install",
                    "--no-index",
                    "--no-deps",
                    str(next(editable_artifacts.glob("*.whl"))),
                ],
                cwd=work,
            )
            run(
                [
                    str(editable_python),
                    "-I",
                    "-c",
                    "from research_partner.app import App; from research_partner.resources import package_root; "
                    "import pathlib, sys; assert package_root() == pathlib.Path(sys.argv[1]) / 'src/research_partner'",
                    str(editable_source),
                ],
                cwd=work,
            )
            missing = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--no-isolation",
                    "--wheel",
                    "--outdir",
                    str(work / "missing-frontend-wheel"),
                    str(editable_source),
                ],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if (
                missing.returncode == 0
                or "built workdesk is missing" not in missing.stdout + missing.stderr
            ):
                raise ValueError(
                    "缺少前端的普通 wheel 没有按资源契约明确失败："
                    + missing.stdout
                    + missing.stderr
                )
            report.update(
                {
                    "wheel": True,
                    "sdist_rebuild": True,
                    "isolated_install": True,
                    "backend_only_editable": True,
                    "missing_frontend_wheel_rejected": True,
                }
            )
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--wheel",
        action="store_true",
        help="需预装 build、setuptools 和 wheel；不下载科学依赖",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            check_release(args.root.resolve(), wheel=args.wheel),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
