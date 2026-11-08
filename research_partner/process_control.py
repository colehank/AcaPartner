"""macOS process observations through psutil; Linux keeps its existing /proc IDs.

These are local ownership checks, not a sandbox or a remote execution proof.
The dependency is lazy so the editing-only workbench remains stdlib-only.
"""
import os

from .store import Problem, digest, require


def _psutil():
    try:
        import psutil
    except ImportError as error:
        raise Problem('macOS 任务执行需要可选运行依赖；请安装 .[runtime]',
                      'runtime_unavailable', 503) from error
    return psutil


def identity(pid):
    psutil = _psutil()
    try:
        process = psutil.Process(pid)
        created = process.create_time()
        uid = process.uids().real
        status = process.status()
        argv = [] if status == psutil.STATUS_ZOMBIE else process.cmdline()
        # A fresh object avoids psutil's cached creation time hiding PID reuse
        # between the separate native observations above.
        require(psutil.Process(pid).create_time() == created,
                '读取期间进程身份变化', 'process_identity', 409)
        raw = b'\0'.join(os.fsencode(arg) for arg in argv) + (b'\0' if argv else b'')
        return {'pid': pid, 'start_ticks': str(int(created * 1_000_000)),
                'uid': uid, 'state': 'Z' if status == psutil.STATUS_ZOMBIE else 'R',
                'command_sha256': digest(raw), 'identity_source': 'psutil-macos-v1'}
    except psutil.NoSuchProcess:
        return None
    except psutil.AccessDenied as error:
        raise Problem('无法读取进程身份；未推断进程已退出', 'process_identity', 409) from error


def group_members(record):
    """Observe the original session/group, retaining UID/start-time guards."""
    require(record.get('identity_source') == 'psutil-macos-v1',
            '执行记录不属于当前平台；未按旧 PID 终止进程', 'process_identity', 409)
    result = []
    for pid in _psutil().pids():
        try:
            if os.getpgid(pid) != record['pid'] or os.getsid(pid) != record['pid']:
                continue
            current = identity(pid)
        except ProcessLookupError:
            continue
        except PermissionError as error:
            raise Problem('无法核验执行进程组；未发送信号', 'process_identity', 409) from error
        if current is None or current['state'] == 'Z':
            continue
        require(current['uid'] == record['uid']
                and int(current['start_ticks']) >= int(record['start_ticks']),
                '进程组身份已变化', 'process_identity', 409)
        result.append(pid)
    return result
