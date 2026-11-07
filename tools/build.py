#!/usr/bin/env python3
"""构建确定性的离线源码发行包，不下载依赖或修改源码树。"""

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path, PurePosixPath


TEST_FOLDERS = (
    "tests/unit",
    "tests/integration",
    "tests/packaging",
    "tests/support",
)
DISTRIBUTION_FOLDERS = (
    "src/research_partner",
    "frontend/workdesk/src",
    "frontend/workdesk/public",
    "frontend/legacy",
    "integrations/extensions",
    "integrations/codex",
    *TEST_FOLDERS,
)
DISTRIBUTION_FILES = (
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "config.example.json",
    "docs/user/user-guide.md",
    "docs/user/quickstart.md",
    "docs/release/RELEASE.md",
    "docs/user/screenshots/workspace-guide.png",
    "docs/product/current-20261010/Research_Partner_产品书.md",
    "docs/product/04_全量功能清单.json",
    "docs/product/09_验收场景.md",
    "frontend/workdesk/package.json",
    "frontend/workdesk/package-lock.json",
    "frontend/workdesk/index.html",
    "frontend/workdesk/vite.config.ts",
    "frontend/workdesk/tsconfig.json",
    "frontend/workdesk/playwright.config.ts",
    "frontend/workdesk/tests/local-account-login.spec.ts",
    "frontend/workdesk/tests/workspace-guide.spec.ts",
    "tools/start_local.py",
    "tools/build.py",
    "tools/install.py",
    "tools/package_resources.py",
    "tools/check_backend.py",
    "tools/check_release.py",
    "tests/__init__.py",
    "docs/development/backend-development.md",
    "docs/architecture/repository-layout.md",
    ".github/workflows/backend.yml",
    ".github/workflows/frontend.yml",
    ".github/workflows/release.yml",
    "environments/core-generation-runtime.in",
    "environments/core-generation-runtime.lock",
    "environments/core-generation-build.lock",
)
WEB_RESOURCES = "src/research_partner/resources/web"
WORKDESK_BUILD = "build/frontend/workdesk"


def _safe_name(name):
    path = PurePosixPath(name)
    return (
        bool(name)
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in name
        and path.as_posix() == name
    )


def _public_file(name):
    path = PurePosixPath(name)
    return (
        _safe_name(name)
        and not set(path.parts)
        & {".git", ".private", ".runtime", ".venv", "node_modules", "__pycache__"}
        and not any(part.startswith(".env") for part in path.parts)
        and path.suffix.lower()
        not in {
            ".sqlite",
            ".sqlite3",
            ".db",
            ".pem",
            ".key",
            ".token",
            ".log",
            ".pyc",
            ".pyo",
        }
        and path.name
        not in {
            "credentials.json",
            "account.json",
            "accounts.json",
            "config.local.json",
        }
        and not name.startswith(
            ("frontend/legacy/tests/", WEB_RESOURCES + "/legacy/tests/")
        )
    )


def distributed_source(name):
    """判定原始源码路径是否属于正向产品白名单；不包括编译缓存。"""
    return _public_file(name) and (
        name in DISTRIBUTION_FILES
        or (
            any(name.startswith(folder + "/") for folder in DISTRIBUTION_FOLDERS)
            and (not name.startswith("tests/") or PurePosixPath(name).suffix == ".py")
        )
    )


def _check_source_path(root, path):
    # src/、docs/ 等中间目录也不能用链接指向白名单之外的材料。
    if any(
        parent.is_symlink()
        for parent in (path, *path.parents)
        if parent != root and parent.is_relative_to(root)
    ):
        raise ValueError(
            "Source distribution cannot contain symlinks: "
            + path.relative_to(root).as_posix()
        )


def _tree_files(root, folder):
    base = root / folder
    _check_source_path(root, base)
    for path in sorted(base.rglob("*")):
        name = path.relative_to(root).as_posix()
        if not _public_file(name):
            continue
        if path.is_symlink():
            raise ValueError("Source distribution cannot contain symlinks: " + name)
        if path.is_file():
            if path.name.endswith(("~", ".orig", ".rej", ".bak", ".swp", ".swo")):
                raise ValueError("Patch/editor backup in source distribution: " + name)
            yield name


def distribution_inputs(root):
    """返回归档路径到真实输入源路径的映射；生成 web 资源不写回源码。"""
    root = Path(root).resolve()
    inputs = {}
    for folder in DISTRIBUTION_FOLDERS:
        for name in _tree_files(root, folder):
            if distributed_source(name) and not name.startswith(WEB_RESOURCES + "/"):
                inputs[name] = name
    for name in DISTRIBUTION_FILES:
        path = root / name
        _check_source_path(root, path)
        if path.is_file():
            inputs[name] = name
    for frontend, source in (
        (
            "workdesk",
            WORKDESK_BUILD
            if (root / WORKDESK_BUILD).exists()
            else WEB_RESOURCES + "/workdesk",
        ),
        (
            "legacy",
            "frontend/legacy"
            if (root / "frontend/legacy").exists()
            else WEB_RESOURCES + "/legacy",
        ),
    ):
        for name in _tree_files(root, source):
            relative = PurePosixPath(name).relative_to(source).as_posix()
            inputs[f"{WEB_RESOURCES}/{frontend}/{relative}"] = name
    return dict(sorted(inputs.items()))


def _verify_frozen(root, inputs, source_hashes, frozen_manifest):
    frozen = json.loads(Path(frozen_manifest).read_text(encoding="utf-8"))
    declared = frozen.get("files")
    if not isinstance(declared, dict) or not declared:
        raise ValueError("Invalid frozen source manifest")
    if any(not isinstance(name, str) or not _safe_name(name) for name in declared):
        raise ValueError("Invalid frozen source path")

    # 已装配资源仅在无编译目录时作为输入；清单必须绑定实际参与构建的编译产物。
    def included(name):
        if name.startswith(WEB_RESOURCES + "/workdesk/"):
            return not (root / WORKDESK_BUILD).exists() and _public_file(name)
        if name.startswith(WEB_RESOURCES + "/legacy/"):
            return not (root / "frontend/legacy").exists() and _public_file(name)
        return distributed_source(name) or (
            name.startswith(WORKDESK_BUILD + "/") and _public_file(name)
        )

    expected = {name for name in declared if included(name)}
    actual = set(inputs.values())
    if actual != expected:
        raise ValueError(
            "Distribution member set differs from frozen source: missing="
            + repr(sorted(expected - actual))
            + ", extra="
            + repr(sorted(actual - expected))
        )
    for name, sha in source_hashes.items():
        if declared.get(name) != sha:
            raise ValueError("Distribution input not bound to frozen source: " + name)


def build(root, output, frozen_manifest=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    inputs = distribution_inputs(root)
    source_hashes = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in sorted(set(inputs.values()))
    }
    if frozen_manifest is not None:
        _verify_frozen(root, inputs, source_hashes, frozen_manifest)
    # 与启动入口使用相同的完整性检查，不悄悄运行 npm 或发起网络请求。
    try:
        from tools.start_local import check_frontend
    except ModuleNotFoundError:
        from start_local import check_frontend
    check_frontend(root, included=set(inputs.values()))
    if f"{WEB_RESOURCES}/legacy/index.html" not in inputs:
        raise ValueError(
            "Missing legacy frontend: frontend/legacy/index.html or assembled resources/web/legacy/index.html"
        )
    declaration = json.loads(
        (root / "src/research_partner/resources/runtime-features.json").read_text(
            encoding="utf-8"
        )
    )
    features = declaration.get("runtime_features")
    if (
        declaration.get("schema_version") != 1
        or not isinstance(features, list)
        or not all(isinstance(value, str) for value in features)
        or len(features) != len(set(features))
    ):
        raise ValueError("Invalid runtime feature declaration")
    records = {name: source_hashes[source] for name, source in inputs.items()}
    manifest = {
        "format": "research-partner-source",
        "files": records,
        "source_files": inputs,
        "runtime_features": sorted(features),
        "core_requires": "Python >=3.12 standard library",
        "optional_runtime_dependencies": "Configured separately; no credentials/runtime/research data included",
        "private_materials_included": False,
    }
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, sha in records.items():
            data = (root / inputs[name]).read_bytes()
            if hashlib.sha256(data).hexdigest() != sha:
                raise ValueError("Source changed during freeze: " + inputs[name])
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tar.addfile(info, io.BytesIO(data))
        data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
        info = tarfile.TarInfo("distribution-manifest.json")
        info.size, info.mode, info.mtime = len(data), 0o644, 0
        tar.addfile(info, io.BytesIO(data))
    output.mkdir(parents=True, exist_ok=True)
    dest = output / "research-partner.tar.gz"
    with dest.open("wb") as file:
        with gzip.GzipFile(fileobj=file, mode="wb", mtime=0, filename="") as gz:
            gz.write(stream.getvalue())
    result = {
        "path": str(dest),
        "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
        "files": len(records),
        "publicly_published": False,
    }
    (output / "build.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", default="dist")
    parser.add_argument(
        "--frozen-manifest",
        type=Path,
        help="Bind source files and compiled frontend inputs to an explicit frozen manifest",
    )
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.output, args.frozen_manifest), indent=2))
