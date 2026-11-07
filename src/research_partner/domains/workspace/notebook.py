"""Native UTF-8 notebooks: the Markdown file, never the index, is authoritative.

The application performs user/agent permission checks before calling this
service. This layer additionally binds every operation to an existing project
and to descriptor-opened, non-symlink project directories. Application writers
share a file lock; unrelated editors do not, so CAS is checked again immediately
before replacement and a detected external race retains both byte snapshots.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
import threading
import uuid
from pathlib import Path

from research_partner.storage.store import Problem, encoded, now, require, uid


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _components(value, *, folder=False):
    require(isinstance(value, str) and 1 <= len(value) <= 1024
            and "\\" not in value and "\x00" not in value,
            "笔记路径无效", "invalid_path")
    parts = value.split("/")
    require(parts[0] == "notes" and all(p not in {"", ".", ".."} for p in parts)
            and not any(p in {".trash", ".notebook"} for p in parts[1:]),
            "笔记路径必须位于本项目 notes 中", "invalid_path")
    require(folder or (len(parts) > 1 and parts[-1].endswith(".md")),
            "笔记必须为 .md 文件", "invalid_path")
    return parts


def _open_dir(parent_fd, name, *, create=False):
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileExistsError:
            pass
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except FileNotFoundError as error:
        raise Problem("笔记目录不存在", "not_found", 404) from error
    except OSError as error:
        raise Problem("笔记目录不能含符号链接或非目录节点", "invalid_path", 409) from error


@contextlib.contextmanager
def _parent(root_fd, parts, *, create=False):
    current = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            following = _open_dir(current, component, create=create)
            os.close(current)
            current = following
        yield current, parts[-1]
    finally:
        os.close(current)


def _read_at(directory_fd, name, *, absent=False, allow_hardlink=False):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    except FileNotFoundError as error:
        if absent:
            return None
        raise Problem("笔记文件不存在", "not_found", 404) from error
    except OSError as error:
        raise Problem("笔记文件不能含符号链接", "invalid_path", 409) from error
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and (allow_hardlink or info.st_nlink == 1),
                "笔记必须为普通文件且不能是硬链接", "invalid_path", 409)
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read()
        return raw
    finally:
        os.close(fd)


def _replace_at(directory_fd, name, raw):
    temporary = ".rp-note-" + uuid.uuid4().hex
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(fd)
        os.close(fd)
        fd = None
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _create_at(directory_fd, name, raw, *, temporary=None):
    """Publish completed bytes atomically while refusing an existing target."""
    temporary = temporary or ".rp-note-" + uuid.uuid4().hex
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(fd)
        # link, unlike replace, atomically fails if the destination exists.
        os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
        os.unlink(temporary, dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        os.close(fd)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _decode(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeError as error:
        raise Problem("文件不是 UTF-8；保留原字节且未执行转换", "notes_encoding", 409) from error


def _outline(markdown):
    """Return source positions without modifying/parsing unknown Markdown."""
    result, offset, fence = [], 0, None
    previous = None
    for line in markdown.splitlines(keepends=True):
        text = line.rstrip("\r\n")
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", text)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = (token[0], len(token))
            elif token[0] == fence[0] and len(token) >= fence[1]:
                fence = None
            previous = None
        elif fence is None:
            match = re.match(r"^ {0,3}(#{1,6})(?:\s+|$)(.*?)\s*#*\s*$", text)
            if match:
                result.append({"level": len(match.group(1)), "title": match.group(2),
                               "start_offset": offset, "end_offset": offset + len(text)})
            elif previous and re.fullmatch(r" {0,3}(?:=+|-+)\s*", text):
                result.append({"level": 1 if "=" in text else 2, "title": previous[1].strip(),
                               "start_offset": previous[0], "end_offset": offset + len(text)})
            previous = (offset, text) if text.strip() and not match else None
        offset += len(line)
    return result


class NotebookService:
    """Use ``dispatch(command)``; this service never starts tasks or executes text."""

    ACTIONS = frozenset({"notes.create", "notes.read", "notes.list", "notes.search",
                         "notes.write", "notes.navigation", "notes.index.rebuild"})

    def __init__(self, store):
        self.store = store
        self._publication = threading.local()

    @contextlib.contextmanager
    def _guard_publication(self, command, check, published):
        """Internal, one-command fence; callbacks cannot arrive in a wire DTO.

        Keep App's ordinary dispatch/authorization path. The final source check
        runs only after the native file lock and SQLite writer have been taken.
        A source withdrawal therefore either precedes the check or follows the
        committed publication, never interleaves between them.
        """
        require(getattr(self._publication, "guard", None) is None,
                "笔记发布检查不能嵌套", "conflict", 409)
        self._publication.guard = (encoded(command), check, published,
                                   (command['project_id'], command['request_id']))
        try:
            yield
        finally:
            self._publication.guard = None

    def _setting(self, key, default=None, connection=None):
        if connection is None:
            return self.store.setting(key, default)
        row = connection.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def project_root(self, project_id):
        """Return the existing stable ProjectFiles root; never trust caller paths."""
        project = self.store.get(project_id)
        require(project["kind"] == "project", "笔记操作需要真实项目", "invalid_project")
        from research_partner.domains.workspace.files import ProjectFiles
        files = ProjectFiles(self.store)
        with files._locked():
            return files._root(project)

    @contextlib.contextmanager
    def _locked(self, project_id):
        root = self.project_root(project_id)
        workspace_fd = os.open(self.store.workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened = [workspace_fd]
        lock_fd = None
        try:
            current = workspace_fd
            for part in root.relative_to(self.store.workspace).parts:
                current = _open_dir(current, part)
                opened.append(current)
            state = _open_dir(current, ".notebook", create=True)
            opened.append(state)
            lock_fd = os.open("lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=state)
            require(stat.S_ISREG(os.fstat(lock_fd).st_mode) and os.fstat(lock_fd).st_nlink == 1,
                    "笔记锁文件无效", "invalid_path", 409)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            notes = _open_dir(current, "notes", create=True)
            opened.append(notes)
            snapshots = _open_dir(state, "snapshots", create=True)
            opened.append(snapshots)
            pending = _open_dir(state, "pending", create=True)
            opened.append(pending)
            recovery = _open_dir(state, "recovery", create=True)
            opened.append(recovery)
            file_ops=_open_dir(state,'file-operations',create=True);opened.append(file_ops)
            trash=_open_dir(notes,'.trash',create=True);opened.append(trash)
            session = {"root": root, "project_root_fd":current,"project_id": project_id, "notes": notes,
                       "snapshots": snapshots, "pending": pending, "recovery": recovery,'file_ops':file_ops,'trash':trash}
            self._recover(session)
            from research_partner.domains.workspace.notebook_files import recover
            recover(self,session)
            yield session
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            for fd in reversed(opened):
                os.close(fd)

    def _snapshot(self, session, raw):
        sha = _sha(raw)
        fd = session["snapshots"]
        previous = _read_at(fd, sha, absent=True)
        if previous is None:
            # Publish only completed bytes. A crash during the temporary write
            # cannot leave a partial file claiming a content-addressed name.
            _replace_at(fd, sha, raw)
            previous = _read_at(fd, sha)
        require(previous == raw, "笔记历史快照摘要不符", "notes_integrity", 409)
        return sha

    def _key(self, name, project_id):
        return "notebook:" + name + ":" + project_id

    def _register(self, session, path, raw, reason, request_id=None, *, connection=None):
        sha = self._snapshot(session, raw)
        key = self._key("revision", session["project_id"]) + ":" + _sha(path.encode("utf-8"))
        with (self.store.transaction() if connection is None else contextlib.nullcontext(connection)) as connection:
            row = connection.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            entry = json.loads(row[0]) if row else {"revision": 0, "history": []}
            note_id=entry.get("note_id") or uid("NOTE")
            if entry.get("content_sha256") != sha:
                revision = entry["revision"] + 1
                record = {"revision": revision, "parent_revision": revision - 1 if revision > 1 else None,
                          "content_sha256": sha, "reason": reason, "recorded_at": now()}
                if request_id:
                    record["request_id"] = request_id
                entry = {**entry,"note_id":note_id,"revision": revision, "content_sha256": sha,
                         "relative_path": path, "history": entry["history"] + [record]}
                connection.execute("INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                   (key, encoded(entry)))
                self.store.event(connection, "notes.revision", session["project_id"],
                                 {"relative_path": path, **record}, "file_service")
            if not entry.get("note_id"):
                entry["note_id"]=note_id
                connection.execute("UPDATE kv SET value=? WHERE key=?",(encoded(entry),key))
        return entry["revision"]

    def _read_file(self, session, path, *, absent=False):
        parts = _components(path)[1:]
        try:
            with _parent(session["notes"], parts) as (directory_fd, name):
                return _read_at(directory_fd, name, absent=absent)
        except Problem as error:
            if absent and error.code == "not_found":
                return None
            raise

    def _document(self, session, path, raw, reason="external_observed", request_id=None, *, connection=None):
        markdown = _decode(raw)
        revision = self._register(session, path, raw, reason, request_id,
                                  **({"connection": connection} if connection is not None else {}))
        key=self._key("revision",session["project_id"])+":"+_sha(path.encode("utf-8"))
        entry=self._setting(key, connection=connection)
        return {"id":entry["note_id"],"project_id": session["project_id"], "relative_path": path,
                "markdown": markdown, "content_sha256": _sha(raw), "revision": revision,
                "encoding": "utf-8", "authority_kind": "file", "outline": _outline(markdown),
                "offset_unit": "unicode_code_point", "bytes": len(raw)}

    def _recover(self, session):
        """Reconcile durable prepare records against actual bytes after a crash."""
        for filename in sorted(os.listdir(session["pending"])):
            require(re.fullmatch(r"[a-f0-9]{32}\.json", filename),
                    "笔记恢复记录文件名无效", "notes_integrity", 409)
            try:
                record = json.loads(_read_at(session["pending"], filename))
                require(record["project_id"] == session["project_id"],
                        "笔记恢复记录项目不符", "notes_integrity", 409)
                path = record["relative_path"]
                _components(path)
                temporary = record.get("temporary_name")
                if temporary:
                    require(re.fullmatch(r"\.rp-note-[a-f0-9]{32}", temporary),
                            "笔记恢复临时文件名无效", "notes_integrity", 409)
                    with _parent(session["notes"], _components(path)[1:]) as (parent_fd, name):
                        candidate = _read_at(parent_fd, temporary, absent=True, allow_hardlink=True)
                        if candidate is not None:
                            if _sha(candidate) != record["proposed_sha256"]:
                                # A terminated writer may leave an incomplete
                                # temporary. The full draft was already durably
                                # snapshotted; retain these actual bytes too.
                                record["temporary_sha256"] = self._snapshot(session, candidate)
                            # A crash after the atomic no-overwrite link but
                            # before unlink leaves an extra link to the owned
                            # temporary. The prepare record binds its name and
                            # bytes; remove that extra link before normal read.
                            os.unlink(temporary, dir_fd=parent_fd)
                            os.fsync(parent_fd)
                actual = self._read_file(session, path, absent=True)
                if actual is not None:
                    _decode(actual)
                    reason = "recovered_commit" if _sha(actual) == record["proposed_sha256"] else "external_after_prepare"
                    self._register(session, path, actual, reason, record["request_id"])
                if actual is not None and _sha(actual) == record["proposed_sha256"]:
                    os.unlink(filename, dir_fd=session["pending"])
                    os.fsync(session["pending"])
                else:
                    record["status"] = "retained_draft"
                    record["actual_sha256"] = _sha(actual) if actual is not None else None
                    _replace_at(session["pending"], filename, (encoded(record) + "\n").encode("utf-8"))
                    os.rename(filename, filename, src_dir_fd=session["pending"], dst_dir_fd=session["recovery"])
                    os.fsync(session["pending"])
                    os.fsync(session["recovery"])
            except (KeyError, ValueError, TypeError) as error:
                raise Problem("笔记恢复记录损坏，未覆盖笔记", "notes_integrity", 409) from error

    def _prepare(self, session, path, raw, before, command, *, status="prepared"):
        proposed = self._snapshot(session, raw)
        previous = self._snapshot(session, before) if before is not None else None
        filename = uuid.uuid4().hex + ".json"
        record = {"version": 1, "status": status, "project_id": session["project_id"],
                  "relative_path": path, "before_sha256": previous, "proposed_sha256": proposed,
                  "request_id": command["request_id"], "action": command["action"], "prepared_at": now()}
        if command["action"] == "notes.create" and status == "prepared":
            record["temporary_name"] = ".rp-note-" + filename[:-5]
        target = session["recovery"] if status == "conflict" else session["pending"]
        _replace_at(target, filename, (encoded(record) + "\n").encode("utf-8"))
        return filename, record

    def _conflict(self, session, path, raw, actual, command, expected, *, connection=None):
        filename, record = self._prepare(session, path, raw, actual, command, status="conflict")
        current = self._document(session, path, actual, connection=connection) if actual is not None else None
        baseline = None
        if expected:
            original = _read_at(session["snapshots"], expected, absent=True)
            if original is not None:
                require(_sha(original) == expected, "笔记基础快照摘要不符", "notes_integrity", 409)
                baseline = {"content_sha256": expected, "markdown": _decode(original)}
        raise Problem("文件已变化；项目内容与编辑草稿均已保留", "notes_conflict", 409,
                      {"project_id": session["project_id"], "relative_path": path,
                       "expected_content_sha256": expected, "baseline": baseline, "current": current,
                       "draft": {"recovery_id": filename[:-5], "content_sha256": record["proposed_sha256"],
                                 "markdown": _decode(raw)}, "saved": False})

    def _write(self, session, command, *, connection=None, committed_journals=None):
        payload = command["payload"]
        path = payload["relative_path"]
        raw = payload["markdown"].encode("utf-8")
        expected = payload.get("expected_content_sha256")
        creating = command["action"] == "notes.create"
        with _parent(session["notes"], _components(path)[1:], create=True) as (parent_fd, name):
            before = _read_at(parent_fd, name, absent=True)
            if (creating and before is not None) or (not creating and (before is None or _sha(before) != expected)):
                self._conflict(session, path, raw, before, command, expected, connection=connection)
            if before is not None:
                self._register(session, path, before, "external_observed",
                               **({"connection": connection} if connection is not None else {}))
            journal, record = self._prepare(session, path, raw, before, command)
            try:
                current = _read_at(parent_fd, name, absent=True)
                if current != before:
                    self._conflict(session, path, raw, current, command, expected, connection=connection)
                if creating:
                    # O_EXCL protects creation from another editor creating the
                    # final path between the last check and commit.
                    try:
                        _create_at(parent_fd, name, raw, temporary=record["temporary_name"])
                    except FileExistsError:
                        self._conflict(session, path, raw, _read_at(parent_fd, name), command, expected, connection=connection)
                else:
                    _replace_at(parent_fd, name, raw)
                actual = _read_at(parent_fd, name)
                if actual != raw:
                    self._conflict(session, path, raw, actual, command, expected, connection=connection)
                result = self._document(session, path, actual, "application_save", command["request_id"], connection=connection)
                result.update(saved=True, request_id=command["request_id"],
                              external_editor_cas_guarantee=False)
                self._cache(session, [result], replace=False, connection=connection)
                if committed_journals is not None:
                    committed_journals.append(journal)
                else:
                    os.unlink(journal, dir_fd=session["pending"])
                    os.fsync(session["pending"])
                return result
            except Problem:
                raise
            except OSError as error:
                raise Problem("保存未确认；编辑草稿与恢复准备记录已保留", "notes_write_failed", 503,
                              {"saved": False, "relative_path": path,
                               "draft": {"recovery_id": journal[:-5], "content_sha256": record["proposed_sha256"],
                                         "markdown": payload["markdown"]}}) from error

    def _scan(self, session, folder="notes"):
        parts = _components(folder, folder=True)[1:]
        fd = os.dup(session["notes"])
        try:
            for component in parts:
                following = _open_dir(fd, component)
                os.close(fd)
                fd = following
            documents, directories = [], []

            def walk(directory_fd, relative):
                for name in sorted(os.listdir(directory_fd)):
                    if name == ".trash" or name.startswith(".rp-note-"):
                        continue
                    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    require(not stat.S_ISLNK(info.st_mode), "笔记树含符号链接，检索未完成", "invalid_path", 409)
                    path = relative + "/" + name
                    if stat.S_ISDIR(info.st_mode):
                        _components(path, folder=True)
                        child = _open_dir(directory_fd, name)
                        try:
                            directories.append({"relative_path": path, "type": "folder", "name": name})
                            walk(child, path)
                        finally:
                            os.close(child)
                    elif name.endswith(".md"):
                        raw = _read_at(directory_fd, name)
                        documents.append(self._document(session, path, raw))
            walk(fd, folder)
            self._cache(session, documents, replace=folder == "notes")
            return documents, directories
        finally:
            os.close(fd)

    def _cache(self, session, documents, *, replace, connection=None):
        """Metadata-only derived index; deletion cannot remove native bytes/history."""
        key = self._key("index", session["project_id"])
        old = {} if replace else self._setting(key, {}, connection=connection).get("entries", {})
        entries = {**old, **{d["relative_path"]: {k: d[k] for k in
                   ("relative_path", "content_sha256", "revision", "outline", "bytes")} for d in documents}}
        value = {"version": 1, "entries": entries, "checked_at": now(),
                 "authority_kind": "derived", "freshness": "files_rechecked"}
        if connection is None:
            self.store.set_setting(key, value)
        else:
            connection.execute("INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                               (key, encoded(value)))

    def _navigation(self, session, payload):
        key = self._key("navigation", session["project_id"])
        state = self.store.setting(key, {"favorites": [], "recent": [], "history": [], "history_index": -1})
        op = payload.get("op", "get")
        require(op in {"get", "open", "favorite", "back", "forward"}, "未知笔记导航操作")
        previous = payload.get("previous_cursor_offset")
        if op in {"open", "back", "forward"} and previous is not None and state["history_index"] >= 0:
            previous_location = state["history"][state["history_index"]]
            previous_document = self._document(session, previous_location["relative_path"],
                                               self._read_file(session, previous_location["relative_path"]))
            require(type(previous) is int and 0 <= previous <= len(previous_document["markdown"]),
                    "上一笔记位置无效")
            previous_location.update(cursor_offset=previous, content_sha256=previous_document["content_sha256"])
            for item in state["recent"]:
                if item["relative_path"] == previous_location["relative_path"]:
                    item.update(previous_location)
        if op in {"open", "favorite"}:
            path = payload.get("relative_path")
            document = self._document(session, path, self._read_file(session, path))
            position = payload.get("cursor_offset", 0)
            require(type(position) is int and 0 <= position <= len(document["markdown"]), "笔记位置无效")
            location = {"relative_path": path, "cursor_offset": position,
                        "content_sha256": document["content_sha256"]}
            if op == "open":
                state["history"] = state["history"][:state["history_index"] + 1] + [location]
                state["history"] = state["history"][-200:]
                state["history_index"] = len(state["history"]) - 1
                state["recent"] = [location] + [item for item in state["recent"] if item["relative_path"] != path]
                state["recent"] = state["recent"][:50]
            else:
                require(type(payload.get("favorite")) is bool, "收藏状态必须明确")
                state["favorites"] = [p for p in state["favorites"] if p != path]
                if payload["favorite"]:
                    state["favorites"].append(path)
        elif op in {"back", "forward"}:
            target = state["history_index"] + (-1 if op == "back" else 1)
            require(0 <= target < len(state["history"]), "没有可用的笔记导航位置", "not_found", 404)
            location = state["history"][target]
            document = self._document(session, location["relative_path"], self._read_file(session, location["relative_path"]))
            if location["content_sha256"] != document["content_sha256"]:
                raise Problem("历史位置对应的文件已外部修改，请重新定位", "notes_location_stale", 409,
                              {"location": location, "current": document})
            state["history_index"] = target
        if op != "get":
            self.store.set_setting(key, state)
        return {"project_id": session["project_id"], **state,
                "location": state["history"][state["history_index"]] if state["history_index"] >= 0 else None}

    @staticmethod
    def _validate(command):
        require(isinstance(command, dict) and set(command) == {"action", "project_id", "request_id", "payload"},
                "笔记命令必须包含 action/project_id/request_id/payload")
        require(command["action"] in NotebookService.ACTIONS, "当前切片未实现此笔记命令", "unsupported_action")
        for key in ("project_id", "request_id"):
            require(isinstance(command[key], str) and 1 <= len(command[key]) <= 200, "笔记命令身份无效")
        payload, action = command["payload"], command["action"]
        require(isinstance(payload, dict), "笔记 payload 必须为对象")
        contracts = {
            "notes.create": ({"relative_path", "markdown", "if_absent"}, set()),
            "notes.read": ({"relative_path"}, set()),
            "notes.write": ({"relative_path", "expected_content_sha256", "markdown", "encoding"}, set()),
            "notes.list": ({"folder", "include_trash"}, set()),
            "notes.search": ({"query", "scope"}, {"folder", "limit"}),
            "notes.navigation": (set(), {"op", "relative_path", "cursor_offset", "previous_cursor_offset", "favorite"}),
            "notes.index.rebuild": (set(), set()),
        }
        required, optional = contracts[action]
        require(required <= payload.keys() and payload.keys() <= required | optional,
                "笔记 payload 缺少必需字段或含未知字段")
        if "relative_path" in payload:
            _components(payload["relative_path"])
        if "folder" in payload:
            _components(payload["folder"], folder=True)
        if "markdown" in payload:
            require(isinstance(payload["markdown"], str), "笔记正文必须为文本")
            try:
                payload["markdown"].encode("utf-8")
            except UnicodeError as error:
                raise Problem("笔记正文不能编码为 UTF-8", "notes_encoding", 400) from error
        if action == "notes.create":
            require(payload["if_absent"] is True, "新建笔记必须保证目标不存在")
        if action == "notes.write":
            require(payload["encoding"] == "utf-8" and isinstance(payload["expected_content_sha256"], str)
                    and re.fullmatch(r"[a-f0-9]{64}", payload["expected_content_sha256"]),
                    "保存需要 UTF-8 和明确基础摘要")
        if action == "notes.list":
            require(payload["include_trash"] is False, "本切片不包含回收区")
        if action == "notes.search":
            require(isinstance(payload["query"], str) and 1 <= len(payload["query"]) <= 500,
                    "检索文字无效")
            require(payload["scope"] == "current_project", "跨项目检索须另行授权", "forbidden", 403)
            require(type(payload.get("limit", 200)) is int and 1 <= payload.get("limit", 200) <= 200,
                    "检索数量范围无效")

    def dispatch(self, command):
        self._validate(command)
        with self._locked(command["project_id"]) as session:
            action, payload = command["action"], command["payload"]
            if action in {"notes.create", "notes.write"}:
                guard = getattr(self._publication, "guard", None)
                if guard is not None and guard[3] == (command['project_id'], command['request_id']):
                    require(guard[0] == encoded(command), "笔记发布命令与鉴权绑定不一致", "integrity", 409)
                    # Consume once, so a nested dispatch cannot borrow authority.
                    self._publication.guard = None
                    journals, conflict = [], None
                    with self.store.transaction() as connection:
                        guard[1]()
                        try:
                            result = self._write(session, command, connection=connection,
                                                 committed_journals=journals)
                        except Problem as error:
                            if error.code != "notes_conflict":
                                raise
                            # Preserve the original observed external revision
                            # referenced by the conflict response and its draft.
                            conflict = error
                        else:
                            guard[2](connection, result)
                    # SQLite commit must precede removing the recovery journal.
                    # On any uncertain/failed commit it remains for _recover.
                    for journal in journals:
                        os.unlink(journal, dir_fd=session["pending"])
                    if journals:
                        os.fsync(session["pending"])
                    if conflict is not None:
                        raise conflict
                    return result
                return self._write(session, command)
            if action == "notes.read":
                document = self._document(session, payload["relative_path"],
                                          self._read_file(session, payload["relative_path"]))
                self._cache(session, [document], replace=False)
                return document
            if action == "notes.navigation":
                return self._navigation(session, payload)
            documents, directories = self._scan(session, payload.get("folder", "notes"))
            if action == "notes.index.rebuild":
                return {"project_id": session["project_id"], "indexed_files": len(documents),
                        "authority_kind": "derived", "freshness": "files_rechecked"}
            if action == "notes.list":
                entries = directories + [{"type": "file", "name": Path(d["relative_path"]).name,
                          "title": d["outline"][0]["title"] if d["outline"] else Path(d["relative_path"]).stem,
                          **{key: d[key] for key in ("relative_path", "content_sha256", "revision", "bytes", "outline")}}
                                         for d in documents]
                return {"project_id": session["project_id"], "folder": payload["folder"], "entries": entries,
                        "freshness": "files_rechecked", "include_trash": False}
            query, matches, total = payload["query"], [], 0
            limit = payload.get("limit", 200)
            for document in documents:
                # Recheck before producing matches, including files scanned
                # earlier while a large directory was being enumerated.
                actual = self._read_file(session, document["relative_path"])
                if _sha(actual) != document["content_sha256"]:
                    document = self._document(session, document["relative_path"], actual)
                    self._cache(session, [document], replace=False)
                # Literal substrings intentionally handle two-character Chinese,
                # punctuation, quotes and SQL-looking input without tokenization.
                for field, text in (("content", document["markdown"]), ("path", document["relative_path"])):
                    offset = 0
                    while True:
                        start = text.find(query, offset)
                        if start < 0:
                            break
                        end = start + len(query)
                        total += 1
                        if len(matches) < limit:
                            lo, hi = max(0, start - 45), min(len(text), end + 45)
                            matches.append({"project_id": session["project_id"],
                                            "relative_path": document["relative_path"], "field": field,
                                            "start_offset": start, "end_offset": end,
                                            "snippet": text[lo:hi], "snippet_start_offset": lo,
                                            "content_sha256": document["content_sha256"],
                                            "revision": document["revision"]})
                        offset = start + 1
            # Every candidate was reread from disk above; no stale cache result
            # is returned. A later unrelated editor can still change a file.
            return {"project_id": session["project_id"], "query": query, "matches": matches,
                    "total_matches": total, "truncated": total > len(matches),
                    "offset_unit": "unicode_code_point", "scope": "current_project",
                    "index_status": "literal_file_scan", "freshness": "files_rechecked"}
