import argparse
import json
import signal
import sys
from pathlib import Path
from .store import Problem, uid


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Research Partner — self-hosted scholarly workspace"
    )
    p.add_argument("--workspace", default="~/.local/share/research-partner/default")
    p.add_argument("--config", type=Path)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("status")
    server = sub.add_parser("serve")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8877)
    server.add_argument(
        "--workbench-only",
        action="store_true",
        help="Serve the workspace and explicit exports without constructing a task Runtime or consuming the queue",
    )
    action = sub.add_parser("action")
    action.add_argument("--file", type=Path)
    sub.add_parser("backup")
    restore = sub.add_parser("restore")
    restore.add_argument("archive", type=Path)
    args = p.parse_args(argv)
    try:
        from .compatibility import check_workspace

        check_workspace(args.workspace)
        from .app import App, restore_workspace

        if args.command == "restore":
            result = restore_workspace(args.archive, Path(args.workspace).expanduser())
        else:
            config = json.loads(args.config.read_text()) if args.config else {}
            app = App(args.workspace, config)
            if not app.store.setting("workspace_id"):
                app.store.set_setting("workspace_id", uid("SPACE"))
            if args.command == "init":
                result = {
                    "workspace": str(app.store.workspace),
                    "workspace_id": app.store.setting("workspace_id"),
                    "ready": True,
                }
            elif args.command == "status":
                result = app.state()
            elif args.command == "action":
                result = app.dispatch(
                    json.loads(args.file.read_text() if args.file else sys.stdin.read())
                )
            elif args.command == "backup":
                result = app.backup()
            elif args.command == "serve":
                from .server import serve

                if not args.workbench_only:
                    from .runtime import Runtime

                    app.runner = Runtime(app)
                http = serve(app, args.host, args.port)
                print(
                    json.dumps(
                        {
                            "url": f"http://{args.host}:{http.server_port}",
                            "workspace_id": app.store.setting("workspace_id"),
                            "implementation": app.loaded_implementation["digest"],
                            "workbench_only": args.workbench_only,
                        }
                    ),
                    flush=True,
                )

                def stop(signum, frame):
                    if app.runner:
                        app.runner.stop()
                    raise KeyboardInterrupt

                signal.signal(signal.SIGTERM, stop)
                try:
                    http.serve_forever(poll_interval=0.25)
                except KeyboardInterrupt:
                    pass
                finally:
                    if app.runner:
                        app.runner.stop()
                    http.server_close()
                return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Problem as e:
        print(
            json.dumps(
                {"ok": False, "error": str(e), "code": e.code, "details": e.details},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
