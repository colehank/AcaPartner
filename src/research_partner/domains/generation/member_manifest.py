"""Bounded files for the existing dataset member_manifest contract.

Members are explicit caller-provided scientific identities, never inferred from
CSV, filenames or ordinals. This module has no Store, Task or access authority.
The caller owns a fresh staging directory and supplies its current check gate.
SQLite is a disposable index; pages always come from SHA-verified typed chunks.
"""
from __future__ import annotations

import contextlib
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import uuid

from research_partner.storage.store import Problem, encoded, now, require

MAX_CHUNK_BYTES = 1024 * 1024
MAX_CHUNK_MEMBERS = 4096
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_PAGE_MEMBERS = 200
MAX_CHUNKS = 65536
READ_BYTES = 65536
MANIFEST = "member-manifest.json"
INDEX = "member-index.sqlite3"
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_LEVELS = {"file", "record", "trial", "unit", "image", "sample"}
_MEMBER_KEYS = {"member_id", "source_member_id", "batch_ref", "annotation_ref", "included", "exclusion_reason"}


def _check(condition, message, code="member_manifest_invalid", status=422):
    require(condition, message, code, status)


def _integer(value, minimum=0, maximum=2**63-1):
    return type(value) is int and minimum <= value <= maximum


def _text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 180:
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True


def _ref(value):
    _check(type(value) is dict and set(value) == {"id", "revision"}
           and _text(value["id"]) and _integer(value["revision"]), "成员引用必须含明确ID与非负整数修订")
    return dict(value)


def _metadata(value):
    keys = {"id", "parent", "batch_refs", "selection_rule", "created_at", "member_level", "membership_format", "ordering_contract"}
    _check(type(value) is dict and set(value) == keys and _text(value["id"]), "成员快照元数据字段无效")
    if value["parent"] is not None:
        _ref(value["parent"])
    refs = value["batch_refs"]
    _check(type(refs) is list and refs, "成员快照需要明确批次引用")
    for ref in refs:
        _ref(ref)
    levels = value["member_level"]
    _check(type(levels) is list and levels and all(type(level) is str and level in _LEVELS for level in levels)
           and len(levels) == len(set(levels)), "成员层级必须明确且不重复")
    _check(value["membership_format"] == "typed_id_array", "此模块只写明确typed_id_array成员")
    for key in ("selection_rule", "created_at", "ordering_contract"):
        _check(isinstance(value[key], str) and (key == "selection_rule" or value[key]), "成员选择、时间或顺序合同无效")
        _check(len(value[key]) <= MAX_MANIFEST_BYTES, "成员元数据超过完整文件界限", "context_limit", 413)
        try:
            value[key].encode("utf-8", errors="strict")
        except UnicodeError as error:
            raise Problem("成员元数据不是有效UTF-8", "member_manifest_invalid", 422) from error
    try:
        _check("T" in value["created_at"] and datetime.fromisoformat(value["created_at"]).tzinfo is not None, "成员创建时间需要准确时区")
    except ValueError as error:
        raise Problem("成员创建时间无效", "member_manifest_invalid", 422) from error
    return {encoded(ref) for ref in refs}


def _member(value, batches, byte_limit=MAX_CHUNK_BYTES):
    _check(type(value) is dict and set(value) == _MEMBER_KEYS, "成员必须保留全部原合同字段，不能混入额外字段")
    _check(_text(value["member_id"]) and _text(value["source_member_id"]), "成员与源成员ID无效")
    batch = _ref(value["batch_ref"])
    _check(encoded(batch) in batches, "成员批次不在明确批次引用中")
    if value["annotation_ref"] is not None:
        _ref(value["annotation_ref"])
    _check(type(value["included"]) is bool, "included必须是布尔值")
    reason = value["exclusion_reason"]
    _check(reason is None or isinstance(reason, str), "排除原因必须为原文或null")
    _check(value["included"] or isinstance(reason, str) and len(reason) > 0, "排除成员必须保留明确原因")
    _check(reason is None or len(reason) <= byte_limit, "单成员超过分块界限；未截断", "context_limit", 413)
    try:
        raw = encoded(value).encode("utf-8", errors="strict")
    except UnicodeError as error:
        raise Problem("成员不是有效UTF-8", "member_manifest_invalid", 422) from error
    _check(len(raw) + 2 <= byte_limit, "单成员超过分块界限；未截断", "context_limit", 413)
    return raw


def _gate(check):
    _check(callable(check), "调用者必须提供当前停止/授权检查")
    check()


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextlib.contextmanager
def _bundle(directory, *, create=False, failure_cleanup=None):
    path = Path(directory)
    _check(path.is_absolute() and ".." not in path.parts and len(path.parts) > 1, "成员目录必须为明确绝对目录")
    descriptors = [os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
    links = []
    created = None
    try:
        for index, part in enumerate(path.parts[1:]):
            parent = descriptors[-1]
            if create and index == len(path.parts)-2:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=parent)
                except FileExistsError as error:
                    raise Problem("成员staging目录必须全新且独占", "member_staging_exists", 409) from error
                info = os.stat(part, dir_fd=parent, follow_symlinks=False)
                created = (parent, part, info.st_dev, info.st_ino)
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(child)
            info = os.fstat(child)
            links.append((parent, part, info.st_dev, info.st_ino))
        owned = os.fstat(descriptors[-1])
        _check(owned.st_uid == os.getuid() and not owned.st_mode & 0o077, "成员staging目录必须为调用者私有目录")
        yield descriptors[-1]
        for parent, part, device, inode in links:
            info = os.stat(part, dir_fd=parent, follow_symlinks=False)
            _check(stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (device, inode), "成员目录在核对期间被替换", "member_integrity", 409)
    except BaseException:
        if failure_cleanup:
            failure_cleanup()
        if created:
            try:
                current = os.stat(created[1], dir_fd=created[0], follow_symlinks=False)
                if (current.st_dev, current.st_ino) == created[2:]:
                    os.rmdir(created[1], dir_fd=created[0])
            except OSError:
                pass
        raise
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _write(fd, name, raw, files):
    opened = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    info = os.fstat(opened)
    files.append((fd, name, info.st_dev, info.st_ino))
    with os.fdopen(opened, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _cleanup(files):
    for fd, name, device, inode in reversed(files):
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if (info.st_dev, info.st_ino) == (device, inode):
                os.unlink(name, dir_fd=fd)
        except OSError:
            pass


def _read(fd, name, limit, expected_sha, check):
    _gate(check)
    opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = os.fstat(opened)
        _check(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= limit,
               "成员文件缺失、非普通独立文件或超限", "member_integrity", 409)
        raw = bytearray()
        while True:
            check()
            part = os.read(opened, min(READ_BYTES, limit+1-len(raw)))
            if not part:
                break
            raw.extend(part)
            _check(len(raw) <= limit, "成员文件读取超限", "context_limit", 413)
        current = os.stat(name, dir_fd=fd, follow_symlinks=False)
        _check(len(raw) == before.st_size and _stamp(before) == _stamp(os.fstat(opened)) == _stamp(current)
               and stat.S_ISREG(current.st_mode), "成员文件读取期间改变", "member_integrity", 409)
        _check(hashlib.sha256(raw).hexdigest() == expected_sha, "成员文件完整SHA不符", "member_integrity", 409)
        return bytes(raw)
    finally:
        os.close(opened)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _check(key not in result, "成员JSON含重复字段", "member_integrity", 409)
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        _check(encoded(value).encode() == raw, "成员文件不是准确canonical JSON", "member_integrity", 409)
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Problem("成员文件不是完整canonical UTF-8 JSON", "member_integrity", 409) from error


def _header(fd, expected_sha, check):
    _check(isinstance(expected_sha, str) and _SHA.fullmatch(expected_sha), "必须绑定完整manifest SHA")
    value = _json(_read(fd, MANIFEST, MAX_MANIFEST_BYTES, expected_sha, check))
    _check(type(value) is dict and set(value) == {"version", "snapshot", "count", "membership_hash", "chunks"}
           and type(value["version"]) is int and value["version"] == 1, "成员manifest结构无效")
    _metadata(value["snapshot"])
    _check(_integer(value["count"]) and isinstance(value["membership_hash"], str) and _SHA.fullmatch(value["membership_hash"]), "成员数量或有序hash无效")
    chunks = value["chunks"]
    _check(type(chunks) is list and len(chunks) <= MAX_CHUNKS, "成员manifest分块数量无效")
    cursor = 0
    seen = set()
    for chunk in chunks:
        check()
        _check(type(chunk) is dict and set(chunk) == {"path", "sha256", "start", "count", "bytes"}
               and isinstance(chunk["sha256"], str) and _SHA.fullmatch(chunk["sha256"])
               and chunk["path"] == "chunks/"+chunk["sha256"]+".json"
               and _integer(chunk["start"]) and chunk["start"] == cursor
               and _integer(chunk["count"], 1, MAX_CHUNK_MEMBERS) and _integer(chunk["bytes"], 2, MAX_CHUNK_BYTES), "成员chunk身份、顺序或界限无效")
        _check(chunk["sha256"] not in seen, "成员manifest重复引用相同chunk")
        seen.add(chunk["sha256"])
        cursor += chunk["count"]
    _check(cursor == value["count"], "成员manifest数量不一致")
    if not cursor:
        _check(value["membership_hash"] == hashlib.sha256(b"[]").hexdigest(), "空成员有序hash不符", "member_integrity", 409)
    return value


def _chunk(fd, chunk, batches, check):
    raw = _read(fd, chunk["sha256"]+".json", MAX_CHUNK_BYTES, chunk["sha256"], check)
    _check(len(raw) == chunk["bytes"], "成员chunk实际长度不符", "member_integrity", 409)
    values = _json(raw)
    _check(type(values) is list and len(values) == chunk["count"], "成员chunk实际数量不符", "member_integrity", 409)
    for value in values:
        check()
        _member(value, batches)
    return values


@contextlib.contextmanager
def _index(fd, name, files):
    # The opened FD avoids following an index symlink. SQLite's MEMORY journal
    # is confined to this disposable builder; canonical data is in chunk files.
    _check(Path("/proc/self/fd").is_dir(), "当前索引FD入口未支持此平台", "unsupported_platform", 503)
    opened = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    info = os.fstat(opened)
    files.append((fd, name, info.st_dev, info.st_ino))
    connection = None
    try:
        connection = sqlite3.connect("file:/proc/self/fd/"+str(opened)+"?mode=rw", uri=True)
        connection.execute("PRAGMA journal_mode=MEMORY")
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute("PRAGMA cache_size=-4096")
        connection.execute("CREATE TABLE members(ordinal INTEGER PRIMARY KEY,member_id TEXT UNIQUE NOT NULL,chunk_index INTEGER NOT NULL,position INTEGER NOT NULL)")
        connection.execute("CREATE TABLE binding(manifest_sha256 TEXT NOT NULL,membership_hash TEXT NOT NULL,count INTEGER NOT NULL)")
        yield connection
        connection.commit()
        os.fsync(opened)
    finally:
        if connection is not None:
            connection.close()
        os.close(opened)


def _insert(connection, ordinal, member, chunk_index, position):
    try:
        connection.execute("INSERT INTO members VALUES(?,?,?,?)", (ordinal, member["member_id"], chunk_index, position))
    except sqlite3.IntegrityError as error:
        raise Problem("成员ID重复；未发布部分快照", "duplicate_member", 422) from error


def _scan(chunks_fd, header, check, visitor=None):
    batches = _metadata(header["snapshot"])
    ordered = hashlib.sha256(b"[")
    count = 0
    for index, chunk in enumerate(header["chunks"]):
        for position, member in enumerate(_chunk(chunks_fd, chunk, batches, check)):
            if count:
                ordered.update(b",")
            ordered.update(_member(member, batches))
            if visitor:
                visitor(count, member, index, position)
            count += 1
    ordered.update(b"]")
    _check(count == header["count"] and ordered.hexdigest() == header["membership_hash"], "完整实际成员顺序/hash不符", "member_integrity", 409)


def _snapshot(header, manifest_sha):
    return {**header["snapshot"], "membership_hash": header["membership_hash"],
            "member_manifest": {"path": MANIFEST, "sha256": manifest_sha, "count": header["count"]}}


def create_member_manifest(directory, members, *, snapshot_id, parent, batch_refs,
                           member_level, ordering_contract, selection_rule, check,
                           chunk_bytes=MAX_CHUNK_BYTES, chunk_members=MAX_CHUNK_MEMBERS):
    """Consume once; publish only a complete manifest in a new private directory."""
    _gate(check)
    _check(_integer(chunk_bytes, 2, MAX_CHUNK_BYTES) and _integer(chunk_members, 1, MAX_CHUNK_MEMBERS), "成员分块配置超出硬界限")
    metadata = {"id": snapshot_id, "parent": parent, "batch_refs": batch_refs, "member_level": member_level,
                "ordering_contract": ordering_contract, "selection_rule": selection_rule,
                "created_at": now(), "membership_format": "typed_id_array"}
    batches = _metadata(metadata)
    _check(len(encoded(metadata).encode()) <= MAX_MANIFEST_BYTES, "成员元数据超限", "context_limit", 413)
    metadata = json.loads(encoded(metadata))
    files = []
    with _bundle(directory, create=True, failure_cleanup=lambda: _cleanup(files)) as root_fd:
        os.mkdir("chunks", mode=0o700, dir_fd=root_fd)
        chunks_fd = os.open("chunks", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            with _index(root_fd, INDEX, files) as index:
                chunks, buffer = [], []
                size, count, start = 2, 0, 0
                ordered = hashlib.sha256(b"[")
                def flush():
                    nonlocal buffer, size, start
                    if not buffer:
                        return
                    check()
                    _check(len(chunks) < MAX_CHUNKS, "成员分块总数超限；未截断", "context_limit", 413)
                    raw = b"["+b",".join(buffer)+b"]"
                    sha = hashlib.sha256(raw).hexdigest()
                    _write(chunks_fd, sha+".json", raw, files)
                    chunks.append({"path": "chunks/"+sha+".json", "sha256": sha, "start": start, "count": len(buffer), "bytes": len(raw)})
                    start += len(buffer)
                    buffer, size = [], 2
                iterator = iter(members)
                while True:
                    check()
                    try:
                        member = next(iterator)
                    except StopIteration:
                        break
                    raw = _member(member, batches, chunk_bytes)
                    if buffer and (size+1+len(raw) > chunk_bytes or len(buffer) == chunk_members):
                        flush()
                    _insert(index, count, member, len(chunks), len(buffer))
                    if count:
                        ordered.update(b",")
                    ordered.update(raw)
                    size += len(raw)+(1 if buffer else 0)
                    buffer.append(raw)
                    count += 1
                flush()
                ordered.update(b"]")
                header = {"version": 1, "snapshot": metadata, "count": count, "membership_hash": ordered.hexdigest(), "chunks": chunks}
                raw = encoded(header).encode()
                _check(len(raw) <= MAX_MANIFEST_BYTES, "完整成员manifest超限；未截断", "context_limit", 413)
                _scan(chunks_fd, header, check)
                manifest_sha = hashlib.sha256(raw).hexdigest()
                index.execute("INSERT INTO binding VALUES(?,?,?)", (manifest_sha, header["membership_hash"], count))
            os.fsync(chunks_fd)
            _write(root_fd, ".manifest.pending", raw, files)
            check()
            os.link(".manifest.pending", MANIFEST, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
            info = os.stat(MANIFEST, dir_fd=root_fd, follow_symlinks=False)
            files.append((root_fd, MANIFEST, info.st_dev, info.st_ino))
            os.unlink(".manifest.pending", dir_fd=root_fd)
            os.fsync(root_fd)
            return _snapshot(header, manifest_sha)
        except BaseException:
            _cleanup(files)
            try:
                os.rmdir("chunks", dir_fd=root_fd)
            except OSError:
                pass
            raise
        finally:
            os.close(chunks_fd)


def read_member_page(directory, expected_manifest_sha256, *, offset, limit, check):
    """Verify the fixed manifest and just the leaf chunks covering this page."""
    _gate(check)
    _check(_integer(offset) and _integer(limit, 1, MAX_PAGE_MEMBERS), "成员页必须是准确有界整数范围")
    with _bundle(directory) as root_fd:
        header = _header(root_fd, expected_manifest_sha256, check)
        _check(offset <= header["count"], "成员页起点超出固定快照")
        end = min(offset+limit, header["count"])
        selected, verified = [], []
        chunks_fd = os.open("chunks", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            batches = _metadata(header["snapshot"])
            for chunk in header["chunks"]:
                if chunk["start"] < end and chunk["start"]+chunk["count"] > offset:
                    values = _chunk(chunks_fd, chunk, batches, check)
                    begin, stop = max(offset-chunk["start"], 0), min(end-chunk["start"], chunk["count"])
                    selected.extend(values[begin:stop])
                    verified.append(chunk["sha256"])
        finally:
            os.close(chunks_fd)
        _check(len(selected) == end-offset, "成员页实际范围不符", "member_integrity", 409)
        return {"snapshot": _snapshot(header, expected_manifest_sha256), "offset": offset,
                "ordinals": list(range(offset, end)), "members": selected,
                "next_offset": end if end < header["count"] else None, "verified_chunk_sha256": verified}


def rebuild_member_index(directory, expected_manifest_sha256, *, check, visit_member=None):
    """Rebuild a disposable index; optionally authorize each actual member.

    The visitor is supplied by the domain owner. This byte-level module never
    guesses what an opaque scientific reference means or grants its access.
    """
    _gate(check)
    _check(visit_member is None or callable(visit_member), "成员检查入口必须可调用")
    with _bundle(directory) as root_fd:
        header = _header(root_fd, expected_manifest_sha256, check)
        chunks_fd = os.open("chunks", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        temporary = ".member-index-"+uuid.uuid4().hex+".sqlite3"
        files = []
        try:
            with _index(root_fd, temporary, files) as index:
                def consume(ordinal, member, chunk_index, position):
                    _insert(index, ordinal, member, chunk_index, position)
                    if visit_member is not None:
                        visit_member(member)
                _scan(chunks_fd, header, check, consume)
                index.execute("INSERT INTO binding VALUES(?,?,?)", (expected_manifest_sha256, header["membership_hash"], header["count"]))
            check()
            _check(_header(root_fd, expected_manifest_sha256, check) == header, "重建期间manifest改变", "member_integrity", 409)
            try:
                current = os.stat(INDEX, dir_fd=root_fd, follow_symlinks=False)
                _check(stat.S_ISREG(current.st_mode) and current.st_nlink == 1, "索引目标不是普通缓存文件", "member_integrity", 409)
            except FileNotFoundError:
                pass
            os.replace(temporary, INDEX, src_dir_fd=root_fd, dst_dir_fd=root_fd)
            os.fsync(root_fd)
            return {"manifest_sha256": expected_manifest_sha256, "membership_hash": header["membership_hash"],
                    "count": header["count"], "index_path": INDEX, "canonical_source": "sha_verified_member_chunks"}
        except BaseException:
            _cleanup(files)
            raise
        finally:
            os.close(chunks_fd)
