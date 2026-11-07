#!/usr/bin/env python3
"""Start the local password-protected workdesk without a task runner."""

import argparse
import contextlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


class StartupError(ValueError):
    pass


def default_data_dir():
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Research Partner"
    base = Path(os.environ.get("XDG_DATA_HOME", "")).expanduser()
    if not base.is_absolute():
        base = Path.home() / ".local/share"
    return base / "research-partner"


def private_directory(path, *, create=False):
    if path.is_symlink():
        raise StartupError(f"Private directory must not be a symlink: {path}")
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        info = path.stat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
            raise StartupError(
                f"Private directory must have mode 0700; existing permissions were not changed: {path}"
            )


def private_file(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise StartupError(
            f"Private file must be a regular file with mode 0600; existing file was not changed: {path}"
        )


def read_config(path):
    private_file(path)
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise StartupError(f"Configuration must be a JSON object: {path}")
    return value


class FrontendAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.styles = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.scripts.append(attrs["src"])
        if (
            tag == "link"
            and "stylesheet" in attrs.get("rel", "").split()
            and attrs.get("href")
        ):
            self.styles.append(attrs["href"])


def check_frontend(root, *, included=None):
    root = Path(root)
    built = root / "build/frontend/workdesk"
    folder = (
        built
        if built.exists()
        else root / "src/research_partner/resources/web/workdesk"
    )
    index = folder / "index.html"
    message = (
        "The built workdesk is missing or incomplete. Use a release package containing "
        "src/research_partner/resources/web/workdesk, or build the frontend first: "
        "npm --prefix frontend/workdesk ci && npm --prefix frontend/workdesk run build -- --configLoader runner. "
        "See docs/user/quickstart.md. Nothing was installed or downloaded by this launcher."
    )
    if not index.is_file():
        raise StartupError(message)
    assets = FrontendAssets()
    assets.feed(index.read_text(encoding="utf-8"))
    if not assets.scripts:
        raise StartupError(message)
    for reference in assets.scripts + assets.styles:
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc:
            raise StartupError(message)
        name = unquote(parsed.path)
        if name.startswith("/workdesk/"):
            name = name[len("/workdesk/") :]
        elif name.startswith("/"):
            raise StartupError(message)
        asset = (folder / name).resolve()
        if (
            not asset.is_relative_to(folder.resolve())
            or not asset.is_file()
            or not asset.stat().st_size
        ):
            raise StartupError(message)
        if (
            included is not None
            and asset.relative_to(root.resolve()).as_posix() not in included
        ):
            raise StartupError(
                message
                + " A referenced asset is excluded from the public distribution."
            )
    return index


def absolute_path(value, key):
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise StartupError(
            f"Existing configuration needs an absolute {key}; configuration was not changed."
        )
    return Path(value)


def inspect_start(data_dir, port):
    """Read-only validation, also used by --plan before creating anything."""
    check_frontend(ROOT)
    data_dir = data_dir.expanduser().absolute()
    workspace = data_dir / "workspace"
    configuration = data_dir / "config.json"
    private_directory(data_dir)
    private_directory(workspace)
    existing = configuration.exists() or configuration.is_symlink()
    config = (
        read_config(configuration)
        if existing
        else {
            "workdesk_w1a": True,
            "access_token_file": str(data_dir / "auth/owner.token"),
            "local_accounts_file": str(data_dir / "auth/accounts.json"),
            "providers": {},
            "default_provider": None,
            "clients": [],
            "import_roots": [],
            "allowed_hosts": [],
            "rendering": {},
        }
    )
    if config.get("workdesk_w1a") is not True:
        raise StartupError(
            "Existing configuration needs workdesk_w1a: true; configuration was not changed."
        )
    token = absolute_path(config.get("access_token_file"), "access_token_file")
    accounts = absolute_path(config.get("local_accounts_file"), "local_accounts_file")
    for path in (token, accounts):
        if path.resolve().is_relative_to(workspace.resolve()):
            raise StartupError(
                "Owner credentials and local accounts must be outside the workspace."
            )
        if path == configuration or path.resolve() == configuration.resolve():
            raise StartupError(
                "Configuration and credential files must have different paths."
            )
        private_directory(path.parent)
        if path.exists() or path.is_symlink():
            private_file(path)
    if token.resolve() == accounts.resolve():
        raise StartupError("Owner token and local accounts must have different paths.")
    if token.exists():
        if len(token.read_text(encoding="utf-8").strip()) < 24:
            raise StartupError(
                f"Existing owner token is invalid; it was not replaced: {token}"
            )
    elif existing:
        raise StartupError(
            f"Existing configuration refers to a missing owner token; restore it from your private backup: {token}"
        )
    return {
        "data_dir": data_dir,
        "workspace": workspace,
        "configuration": configuration,
        "config": config,
        "existing_config": existing,
        "token": token,
        "accounts": accounts,
        "url": f"http://127.0.0.1:{port}/",
        "port": port,
    }


def write_new_private(path, text):
    """Publish a complete 0600 file atomically; never replace an existing path."""
    fd, temporary = tempfile.mkstemp(prefix=".setup-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            return False
        return True
    finally:
        os.unlink(temporary)


def prepare_start(plan):
    private_directory(plan["data_dir"], create=True)
    private_directory(plan["workspace"], create=True)
    for path in (plan["token"], plan["accounts"]):
        private_directory(path.parent, create=True)
    if not plan["existing_config"]:
        write_new_private(plan["token"], secrets.token_urlsafe(48) + "\n")
        write_new_private(
            plan["configuration"],
            json.dumps(plan["config"], ensure_ascii=False, indent=2) + "\n",
        )
    # Re-read after exclusive creation, including when another launcher won a race.
    return inspect_start(plan["data_dir"], plan["port"])


def cli_arguments(plan, *, prepare=False):
    args = [
        "--workspace",
        str(plan["workspace"]),
        "--config",
        str(plan["configuration"]),
    ]
    return args + (
        ["init"]
        if prepare
        else [
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(plan["port"]),
            "--workbench-only",
        ]
    )


def invoke_cli(args):
    sys.path.insert(0, str(ROOT / "src"))
    from research_partner.__main__ import main as product_main

    return product_main(args)


def port_number(value):
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir(),
        help="private local data root (default: %(default)s); existing files are preserved",
    )
    parser.add_argument(
        "--port",
        type=port_number,
        default=8877,
        help="loopback HTTP port (default: %(default)s)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--plan",
        action="store_true",
        help="validate and show paths without writing or starting a service",
    )
    mode.add_argument(
        "--prepare",
        action="store_true",
        help="initialize private files and workspace, then exit without starting a service",
    )
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 12):
            raise StartupError("Python 3.12 or newer is required.")
        if os.name != "posix":
            raise StartupError(
                "This release requires POSIX file permissions and file locks; on Windows use WSL2."
            )
        plan = inspect_start(args.data_dir, args.port)
        summary = {
            "url": plan["url"],
            "data_dir": str(plan["data_dir"]),
            "workspace": str(plan["workspace"]),
            "configuration": str(plan["configuration"]),
            "workbench_only": True,
            "runtime_started": False,
        }
        if args.plan:
            print(
                json.dumps(
                    {**summary, "operation": "plan", "files_written": False},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        plan = prepare_start(plan)
        if args.prepare:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = invoke_cli(cli_arguments(plan, prepare=True))
            if result:
                return result
            print(
                json.dumps(
                    {**summary, "operation": "prepared", "ready": True},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        print(
            json.dumps(
                {
                    **summary,
                    "operation": "starting",
                    "next": "Open the URL and register your local account on first use. Stop with Ctrl+C.",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return invoke_cli(cli_arguments(plan))
    except (StartupError, OSError, ValueError) as error:
        print(f"Cannot start Research Partner: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
