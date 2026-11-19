#!/usr/bin/env python3
"""Launch a prepared DSH instance; the installed runtime owns all agent work."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4


def main():
    instance = Path(__file__).resolve().parent
    preparation = json.loads((instance / "preparation.json").read_text())
    runtime = Path(preparation["runtime"])
    capsule = Path(preparation["capsule"])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump-config", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--resume-session")
    parser.add_argument("--port", type=int, default=3081)
    args = parser.parse_args()
    headless = args.headless or args.prompt_file is not None
    if args.resume_session and not args.prompt_file:
        parser.error("--resume-session requires --prompt-file")
    if headless and not args.dump_config and not args.prompt_file:
        parser.error("a headless run requires --prompt-file")
    prompt = args.prompt_file.read_text() if args.prompt_file else ""
    if args.prompt_file and not prompt.strip():
        parser.error("the prompt must not be empty")
    receipt = json.loads((runtime / "install-receipt.json").read_text())
    if receipt.get("status") != "installed_version_probe_passed":
        raise SystemExit("Runtime installation has no successful version receipt.")
    node_bin = Path(receipt["plan"]["node_runtime"]) / "bin"
    dsh = runtime / "app/node_modules/.bin/dsh"
    if not (node_bin / "node").is_file() or not dsh.is_file():
        raise SystemExit("The installed Node/DSH paths from the receipt are unavailable.")
    env = os.environ.copy()
    env.update(PATH=str(node_bin) + os.pathsep + env.get("PATH", ""),
               DSH_HOME=str(instance / "home"), DSH_TELEMETRY_DISABLED="1")
    env.pop("DEEPSEEK_BASE_URL", None)
    keyfile = instance / "control/api-key.txt"
    if keyfile.exists():
        if keyfile.is_symlink() or not keyfile.is_file() or keyfile.stat().st_mode & 0o077:
            raise SystemExit("Credential file must be a private regular file (0600).")
        env["DEEPSEEK_API_KEY"] = keyfile.read_text().strip()
    lock = instance / "launch.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        raise SystemExit("Existing instance lock: inspect the running or interrupted process before relaunching.")
    try:
        (lock / "owner.json").write_text(json.dumps({"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()}))
        profile = "acaworker-headless" if headless else "acaworker"
        run_dir = None
        if headless:
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
            run_dir = instance / "control/runs" / run_id
            run_dir.mkdir(parents=True, mode=0o700)
            (run_dir / "prompt.txt").write_text(prompt)
            config = {"promptPath": str(run_dir / "prompt.txt"), "receiptPath": str(run_dir / "native-receipt.json")}
            if args.resume_session:
                config["resumeSessionId"] = args.resume_session
            patch = (instance / "control/profile-base.yml").read_text()
            # JSON scalars are valid YAML; task text is read from a private file.
            patch += "\n- insert:\n    - id: acaworker-native-session-driver\n      name: " + json.dumps(str(instance / "plugin/native-session-driver.mjs")) + "\n      config:\n"
            patch += "".join("        " + key + ": " + json.dumps(value) + "\n" for key, value in config.items())
            (instance / "home/profiles" / profile / "cordis.patch.yml").write_text(patch)
            (run_dir / "profile.yml").write_text(patch)
        cmd = [str(dsh), "--profile", profile]
        if args.dump_config:
            cmd.append("--dump-config")
        elif not headless:
            cmd += ["--no-open", "--host", "127.0.0.1", "--port", str(args.port)]
        record = {"command": cmd, "started_at": datetime.now(timezone.utc).isoformat(),
                  "resume_session": args.resume_session, "dump_config": args.dump_config,
                  "instance": str(instance), "effective_backend_version": None}
        if run_dir:
            (run_dir / "launch.json").write_text(json.dumps(record, indent=2) + "\n")
            print("Native run evidence: " + str(run_dir), flush=True)
        completed = subprocess.call(cmd, cwd=capsule, env=env)
        if run_dir:
            record.update(returncode=completed, finished_at=datetime.now(timezone.utc).isoformat())
            (run_dir / "launch.json").write_text(json.dumps(record, indent=2) + "\n")
        return completed
    finally:
        (lock / "owner.json").unlink(missing_ok=True)
        lock.rmdir()


if __name__ == "__main__":
    raise SystemExit(main())
