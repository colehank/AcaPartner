"""Internal storage bridge for explicit member snapshots; no import authority.

Callers authorize project/source access and supply a live check. The directory
is their generated staging bundle, never an arbitrary HTTP path. Only canonical
manifest/chunk bytes enter CAS; SQLite remains a disposable derived index.
"""
import contextlib
import hashlib
import os
from pathlib import Path
import stat
import tempfile

from research_partner.domains.generation import member_manifest as members
from research_partner.storage.store import Problem, require, digest


def register_member_assets(store, directory, manifest_sha, *, project_id, check, connection=None):
    members._gate(check)
    # Complete global validation is required before a foreign bundle is adopted.
    # A page by itself verifies only its requested leaf blocks.
    members.rebuild_member_index(directory, manifest_sha, check=check)
    with members._bundle(directory) as root:
        header = members._header(root, manifest_sha, check)
        with (store.transaction() if connection is None else contextlib.nullcontext(connection)) as c:
            project = store.get(project_id, connection=c)
            require(project['kind'] == 'project' and not project['archived'],
                    '成员资产需要现存项目', 'not_found', 404)
            chunks = os.open('chunks', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            try:
                for chunk in header['chunks']:
                    check()
                    fd = os.open(chunk['sha256'] + '.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=chunks)
                    try:
                        store.add_asset_file(fd, 'members-' + chunk['sha256'] + '.json',
                                             'application/json', {'project_id': project_id, 'member_chunk': True},
                                             connection=c, expected_sha256=chunk['sha256'],
                                             expected_size=chunk['bytes'], check=check)
                    finally:
                        os.close(fd)
                check()
                require(members._header(root, manifest_sha, check) == header,
                        '成员manifest在登记期间改变', 'member_integrity', 409)
                fd = os.open(members.MANIFEST, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
                try:
                    store.add_asset_file(fd, members.MANIFEST, 'application/json',
                                         {'project_id': project_id, 'member_manifest': True},
                                         connection=c, expected_sha256=manifest_sha,
                                         expected_size=os.fstat(fd).st_size, check=check)
                finally:
                    os.close(fd)
                check()
                return {'snapshot': members._snapshot(header, manifest_sha), 'asset_sha256': manifest_sha}
            finally:
                os.close(chunks)


def _copy_authorized_asset(store, sha, target, limit, check, authorize):
    check()
    asset = authorize(sha)
    require(isinstance(asset, dict) and asset.get('sha') == sha
            and type(asset.get('size')) is int and 0 <= asset['size'] <= limit,
            '成员资产授权或大小身份不一致', 'member_integrity', 409)
    check()
    directory = os.open(store.blobs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fd = None
    try:
        fd = os.open(sha, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size == asset['size'],
                '成员资产文件身份不同', 'member_integrity', 409)
        hasher, count = hashlib.sha256(), 0
        with target.open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            while True:
                check()
                raw = os.read(fd, min(65536, limit + 1 - count))
                if not raw: break
                count += len(raw)
                require(count <= asset['size'], '成员资产在读取期间增长', 'member_integrity', 409)
                hasher.update(raw); output.write(raw)
            output.flush()
            after = os.fstat(fd)
            current = os.stat(sha, dir_fd=directory, follow_symlinks=False)
            require(count == asset['size'] and hasher.hexdigest() == sha
                    and store._file_identity(before) == store._file_identity(after) == store._file_identity(current),
                    '成员资产实际字节与固定身份不同', 'member_integrity', 409)
        check()
    finally:
        if fd is not None: os.close(fd)
        os.close(directory)


def read_member_asset_page(store, manifest_sha, *, offset, limit, check, authorize):
    members._gate(check)
    require(callable(authorize), '成员读取需要逐资产授权', 'forbidden', 403)
    require(isinstance(manifest_sha, str) and members._SHA.fullmatch(manifest_sha), '需要固定成员manifest SHA')
    require(type(offset) is int and offset >= 0 and type(limit) is int and 1 <= limit <= members.MAX_PAGE_MEMBERS,
            '成员页范围无效')
    try:
        with tempfile.TemporaryDirectory(prefix='rp-member-page-') as directory:
            root = Path(directory)
            (root / 'chunks').mkdir(mode=0o700)
            _copy_authorized_asset(store, manifest_sha, root / members.MANIFEST,
                                   members.MAX_MANIFEST_BYTES, check, authorize)
            with members._bundle(root) as fd:
                header = members._header(fd, manifest_sha, check)
            require(offset <= header['count'], '成员页起点超出固定范围')
            end = min(header['count'], offset + limit)
            for chunk in header['chunks']:
                if chunk['start'] < end and chunk['start'] + chunk['count'] > offset:
                    _copy_authorized_asset(store, chunk['sha256'], root / chunk['path'],
                                           members.MAX_CHUNK_BYTES, check, authorize)
            page = members.read_member_page(root, manifest_sha, offset=offset, limit=limit, check=check)
            check()
            return page
    except OSError as error:
        raise Problem('成员资产缺失或不能安全读取；原快照保持', 'member_integrity', 409) from error


def verify_member_asset_manifest(store, manifest_sha, *, check, authorize, expected_members=None, visit_member=None):
    """Validate every authorized chunk before adopting a saved manifest.

    A page is deliberately insufficient evidence for adoption: this also checks
    global ID uniqueness, ordinal coverage and the full ordered membership hash.
    The disposable on-disk index never becomes the object's authority.
    """
    members._gate(check)
    require(callable(authorize), '成员读取需要逐资产授权', 'forbidden', 403)
    require(isinstance(manifest_sha, str) and members._SHA.fullmatch(manifest_sha),
            '需要固定成员manifest SHA')
    require(expected_members is None or type(expected_members) is list, '明确成员声明必须为完整数组')
    try:
        with tempfile.TemporaryDirectory(prefix='rp-member-verify-') as directory:
            root = Path(directory)
            (root / 'chunks').mkdir(mode=0o700)
            _copy_authorized_asset(store, manifest_sha, root / members.MANIFEST,
                                   members.MAX_MANIFEST_BYTES, check, authorize)
            with members._bundle(root) as fd:
                header = members._header(fd, manifest_sha, check)
            for chunk in header['chunks']:
                _copy_authorized_asset(store, chunk['sha256'], root / chunk['path'],
                                       members.MAX_CHUNK_BYTES, check, authorize)
            members.rebuild_member_index(root, manifest_sha, check=check, visit_member=visit_member)
            snapshot = members._snapshot(header, manifest_sha)
            if expected_members is not None:
                require(len(expected_members) == header['count'], '明确成员数与完整清单不同', 'member_integrity', 409)
                batches = members._metadata(header['snapshot'])
                for member in expected_members:
                    check()
                    members._member(member, batches)
                require(digest(expected_members) == snapshot['membership_hash'],
                        '明确成员内容或顺序与完整清单不同', 'member_integrity', 409)
            check()
            return snapshot
    except OSError as error:
        raise Problem('成员资产缺失或不能安全读取；未采用新快照', 'member_integrity', 409) from error
