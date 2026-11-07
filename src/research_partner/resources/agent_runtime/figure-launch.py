#!/usr/bin/env python3
"""One fresh, task-bound Harness process; config inspection cannot run an Agent.

The product Runtime reserves and owns this launcher. This wrapper retains a
single attempt and checks the same parent stop/deadline while holding its child.
It never resumes an old instance, installs dependencies, or grants permission.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import time
from urllib.parse import urlsplit

FEATURE = 'deepseek_task_figure_tools_v1'
LOCK = 'a85eca55df1d7f4659acfec7c563c00c01c649f3ca1c2b76785de131acc1cdb2'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def private_bytes(path, limit):
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o600 or before.st_size > limit:
        raise ValueError('Private regular0600 input required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_size, opened.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns):
            raise ValueError('Private input changed while opening')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        after = path.lstat()
        if len(raw) > limit or (after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns):
            raise ValueError('Private input changed while reading')
        return raw
    finally:
        os.close(fd)


def parent_state(filename):
    filename = Path(filename)
    if not filename.is_absolute() or filename.with_suffix('.stop').exists():
        raise ValueError('Original parent stop applies')
    value = json.loads(private_bytes(filename, 4 * 1024 * 1024))
    deadline = value.get('deadline')
    authority=value.get('active_authorization',{})
    continuous=(isinstance(authority,dict) and authority.get('mode')=='continuous_development'
                and authority.get('source')=='explicit_user' and authority.get('local_caps_removed') is True
                and isinstance(authority.get('record'),str) and bool(authority['record']))
    if not (continuous and deadline is None) and (type(deadline) not in (float, int) or not math.isfinite(deadline) or time.time() >= deadline):
        raise ValueError('Original parent deadline reached')
    return value


def inspect(instance):
    instance = Path(instance).absolute()
    record = json.loads(private_bytes(instance / 'preparation.json', 131072))
    definition = record['definition']
    if record.get('instance') != str(instance) or record.get('feature') != FEATURE or definition.get('feature') != FEATURE or record.get('fresh_only') is not True:
        raise ValueError('Explicit fresh figure feature required')
    if sha(canonical({k: v for k, v in definition.items() if k != 'sha256'}).encode()) != definition.get('sha256'):
        raise ValueError('Provider definition changed')
    if definition.get('runtime_lock_sha256') != LOCK:
        raise ValueError('Locked existing runtime required')
    runtime = Path(record['runtime'])
    if not runtime.is_absolute() or str(runtime) != definition.get('runtime') or runtime.resolve() != Path(definition['runtime']).resolve() or sha((runtime / 'app/package-lock.json').read_bytes()) != LOCK:
        raise ValueError('Installed runtime lock changed')
    installed = json.loads((runtime / 'install-receipt.json').read_text())
    if installed.get('status') != 'installed_version_probe_passed' or installed.get('package_lock_sha256') != LOCK:
        raise ValueError('Installed version receipt required')
    for name, expected in definition['modules'].items():
        if Path(name).name != name or sha((instance / 'plugin' / name).read_bytes()) != expected:
            raise ValueError('Frozen native module changed')
    if definition['modules'].get('figure-launch.py') != sha(Path(__file__).read_bytes()):
        raise ValueError('Launcher was not frozen in this Task')
    base_raw = private_bytes(instance / 'control/profile-base.yml', 131072)
    if sha(base_raw) != record['profile_sha256']:
        raise ValueError('Prepared profile changed')
    base = json.loads(base_raw)
    if not isinstance(base, list):
        raise ValueError('Prepared patch must remain one JSON/YAML list')
    scope_raw = private_bytes(instance / 'control/scope.json', 131072)
    if sha(scope_raw) != record['contract_sha256']:
        raise ValueError('Frozen Task scope changed')
    scope = json.loads(scope_raw)
    auth = json.loads(private_bytes(instance / 'control/authorization.json', 131072))
    prompt = private_bytes(instance / 'control/prompt.txt', 131072).decode('utf-8', errors='strict')
    if not prompt.strip() or scope.get('definition') != definition:
        raise ValueError('Fixed prompt/scope missing')
    node = runtime / 'node-v24.21.0-linux-x64/bin/node'
    dsh = runtime / 'app/node_modules/@deepseek-ai/dsh/lib/bin.js'
    if not node.is_file() or not dsh.is_file():
        raise ValueError('Original installed executable unavailable')
    return record, scope, auth, base, node, dsh


def compose(instance, base, scope, origin, bearer_path, receipt_path):
    instance = Path(instance)
    host = {k: scope[k] for k in ('task_id', 'project_id', 'plan_sha256', 'egress_sha256')}
    host = dict(zip(('taskId', 'projectId', 'planSha256', 'egressSha256'), host.values()))
    host.update(authorityContract=scope['definition']['authority_contract'], origin=origin, taskBearerFile=str(bearer_path))
    # Both overlays remain JSON lists. No concatenated JSON plus YAML fragment.
    return base + [{'insert': [
        {'id': 'acaworker-figure-task-host', 'name': str(instance / 'plugin/figure-host-plugin.mjs'), 'config': host},
        {'id': 'acaworker-native-session-driver', 'name': str(instance / 'plugin/native-session-driver.mjs'),
         'config': {'feature': FEATURE, 'promptPath': str(instance / 'control/prompt.txt'), 'receiptPath': str(receipt_path)}}]}]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dump-config', action='store_true')
    parser.add_argument('--budget-file', required=True, type=Path)
    parser.add_argument('--reservation-id')
    parser.add_argument('--origin', required=True)
    parser.add_argument('--task-bearer-file', required=True, type=Path)
    args = parser.parse_args(argv)
    origin = urlsplit(args.origin)
    if origin.scheme != 'http' or origin.hostname not in ('127.0.0.1', '::1') or origin.username is not None or origin.password is not None or origin.path not in ('', '/') or origin.query or origin.fragment or not origin.port:
        raise ValueError('Literal loopback HTTP Task origin required')
    instance = Path(__file__).resolve().parent
    record, scope, auth, base, node, dsh = inspect(instance)
    parent = parent_state(args.budget_file)
    if not args.task_bearer_file.is_absolute():
        raise ValueError('Explicit private Task bearer path required')
    deadline = min(float('inf') if parent['deadline'] is None else parent['deadline'], scope['definition']['deadline'])
    if not args.dump_config:
        definition = scope['definition']
        expected = {k: definition[k] for k in ('authorization_reference', 'model', 'budget_mode', 'budget_usd', 'max_requests', 'max_output_tokens', 'max_request_bytes', 'rates_usd_per_million', 'pricing_reference')}
        expected.update(contract_sha256=record['contract_sha256'], task_id=scope['task_id'], project_id=scope['project_id'], plan_sha256=scope['plan_sha256'], egress_sha256=scope['egress_sha256'], disclosure_classes=['fixed_figure_context'])
        expiry = datetime.fromisoformat(auth.get('expires_at', '').replace('Z', '+00:00'))
        if auth.get('approved') is not True or auth.get('uncapped_spending_authorized') is not False or auth.get('no_expiry_authorized') is not False or expiry.tzinfo is None or not time.time() < expiry.timestamp() <= deadline or any(k not in auth or canonical(auth[k]) != canonical(v) for k, v in expected.items()):
            raise ValueError('Current explicit Task/account/finite spending authorization required')
        item = next((i for i in parent['reservations'] if i['id'] == args.reservation_id), None)
        if not item or item['kind'] != 'model' or item['state'] != 'reserved_or_uncertain' or not args.reservation_id.startswith(scope['task_id'] + ':') or item.get('request_cap') != scope['definition']['max_requests']:
            raise ValueError('Matching original parent request reservation required')
        deadline = min(deadline, item['at'] + item['seconds'])
    if deadline <= time.time():
        raise ValueError('No remaining original execution time')
    run = instance / 'control' / ('inspect-launch.json' if args.dump_config else 'launch-attempt.json')
    fd = os.open(run, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    child = None
    observation = {'feature': FEATURE, 'mode': 'inspect_no_agent' if args.dump_config else 'fresh_native', 'task_id': scope['task_id'], 'started_at': datetime.now(timezone.utc).isoformat(), 'deadline': deadline, 'returncode': None, 'actual_bill_usd': None, 'automatic_retries': 0}
    def save():
        os.lseek(fd, 0, os.SEEK_SET); os.ftruncate(fd, 0); os.write(fd, (canonical(observation) + '\n').encode()); os.fsync(fd)
    save()
    try:
        patch = compose(instance, base, scope, args.origin, args.task_bearer_file, instance / 'control/native-receipt.json')
        profile = instance / 'home/profiles/acaworker-headless/cordis.patch.yml'
        profile.write_text(canonical(patch) + '\n'); profile.chmod(0o600)
        allowed = {'PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TZ', 'TMPDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY'}
        env = {k: v for k, v in os.environ.items() if k in allowed}
        env.update(PATH=str(node.parent) + os.pathsep + env.get('PATH', ''), DSH_HOME=str(instance / 'home'), DSH_TELEMETRY_DISABLED='1')
        if not args.dump_config:
            key = private_bytes(instance / 'control/api-key.txt', 4096).decode('ascii', errors='strict').strip()
            if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
                raise ValueError('Explicit private API credential unavailable')
            env['DEEPSEEK_API_KEY'] = key
        command = [str(node), str(dsh), '--profile', 'acaworker-headless'] + (['--dump-config'] if args.dump_config else [])
        observation['command'] = command; save()
        child = subprocess.Popen(command, cwd=instance / 'capsule', env=env)
        observation['owned_child_pid'] = child.pid; save()
        while child.poll() is None:
            parent_state(args.budget_file)
            if time.time() >= deadline:
                raise TimeoutError('Original Task/parent execution bound reached')
            time.sleep(.1)
        observation['returncode'] = child.returncode
        return child.returncode
    except BaseException as error:
        observation['failure'] = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try: child.wait(timeout=3)
            except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=3)
        observation['child_closed'] = child is None or child.poll() is not None
        observation['finished_at'] = datetime.now(timezone.utc).isoformat(); save(); os.close(fd)


if __name__ == '__main__':
    raise SystemExit(main())
