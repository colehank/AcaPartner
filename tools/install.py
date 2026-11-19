#!/usr/bin/env python3
"""从已校验的 Research Partner 源码发行包离线安装。"""

import argparse
import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath


MAX_DISTRIBUTION_SIZE = 64 * 1024 * 1024


def install(archive, target):
    archive, target = Path(archive), Path(target).expanduser().resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError(
            "Install into an empty version directory; do not overwrite an existing running version"
        )
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        names = [member.name for member in members]
        if sum(member.size for member in members) > MAX_DISTRIBUTION_SIZE:
            raise ValueError("Distribution too large")
        if len(names) != len(set(names)):
            raise ValueError("Unexpected distribution contents")
        for member in members:
            name = PurePosixPath(member.name)
            if (
                not member.isfile()
                or name.is_absolute()
                or ".." in name.parts
                or "\\" in member.name
                or name.as_posix() != member.name
                or not (target / member.name).resolve().is_relative_to(target)
            ):
                raise ValueError("Unsafe distribution member")
            if member.name == "research-partner" or any(
                parent.as_posix() in names
                for parent in name.parents
                if parent != PurePosixPath(".")
            ):
                raise ValueError("Unexpected distribution contents")
        if "distribution-manifest.json" not in names:
            raise ValueError("Missing distribution manifest")
        manifest = json.load(tar.extractfile("distribution-manifest.json"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("format") != "research-partner-source"
        ):
            raise ValueError("Unknown distribution")
        records = manifest.get("files")
        if (
            not isinstance(records, dict)
            or not records
            or any(
                not isinstance(name, str) or not isinstance(sha, str)
                for name, sha in records.items()
            )
            or set(names) != set(records) | {"distribution-manifest.json"}
        ):
            raise ValueError("Unexpected distribution contents")
        contents = {}
        for member in members:
            data = tar.extractfile(member).read()
            if (
                member.name in records
                and hashlib.sha256(data).hexdigest() != records[member.name]
            ):
                raise ValueError("Distribution hash mismatch")
            contents[member.name] = data
    # 先完成全部校验，再写入；启动器不依赖当前工作目录或全局 Python 安装。
    target.mkdir(parents=True, exist_ok=True)
    for name, data in contents.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o644)
    launcher = target / "research-partner"
    launcher.write_text(
        "#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n"
        'sys.path.insert(0,str(Path(__file__).resolve().parent / "src"))\n'
        "from research_partner.__main__ import main\nraise SystemExit(main())\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return {
        "installed": True,
        "target": str(target),
        "entry": str(launcher),
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "global_environment_modified": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.archive, args.target), indent=2))
