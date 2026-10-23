"""Explicit DatasetSnapshot adoption and fixed pages on existing member CAS.

The request uses the existing nested command fields. Levels, format and order
come from the complete frozen manifest, never inferred from CSV or ordinals.
These objects describe membership, not runnable CSV inputs or scientific proof.
"""
from collections import OrderedDict

from . import member_assets
from .desk_w1a import _project
from .store import Problem, digest, encoded, require


_DECLARED = {"id", "parent", "batch_refs", "member_manifest", "selection_rule",
             "membership_hash", "created_at"}


def _canonical(value):
    try:
        return encoded(value).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise Problem("数据声明必须是完整有效的UTF-8 JSON", "invalid", 400) from error


def _text(value):
    if type(value) is not str or not 1 <= len(value) <= 180:
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True


def _ref(value):
    return (type(value) is dict and set(value) == {"id", "revision"}
            and _text(value["id"]) and type(value["revision"]) is int
            and value["revision"] >= 0)


def _declaration(value):
    require(type(value) is dict and _DECLARED <= set(value)
            and set(value) <= _DECLARED | {"members"},
            "数据快照只接受原命令声明字段；成员层级/顺序来自固定manifest")
    require(_text(value["id"]) and (value["parent"] is None or _ref(value["parent"]))
            and type(value["batch_refs"]) is list and value["batch_refs"]
            and all(_ref(ref) for ref in value["batch_refs"]), "需要明确快照、父级与批次引用")
    pointer = value["member_manifest"]
    require(type(pointer) is dict and set(pointer) == {"path", "sha256", "count"}
            and _text(pointer["path"]) and type(pointer["sha256"]) is str
            and len(pointer["sha256"]) == 64
            and all(char in "0123456789abcdef" for char in pointer["sha256"])
            and type(pointer["count"]) is int and pointer["count"] >= 0,
            "需要准确有界manifest身份，path不授予文件读取权限")
    require(type(value["selection_rule"]) is str and type(value["created_at"]) is str
            and type(value["membership_hash"]) is str
            and len(value["membership_hash"]) == 64
            and all(char in "0123456789abcdef" for char in value["membership_hash"]),
            "需要原文选择规则、创建时间和准确有序成员hash")
    require("members" not in value or type(value["members"]) is list,
            "显式嵌入成员必须为完整有序数组")
    _canonical(value)
    return pointer["sha256"]


def _current_check(app, project_id, scope, principal, *, write=False):
    # Resolve current credential scope on every copy/check, not just at entry.
    _project(app, project_id, scope, principal, write)
    if app.config.get("development_budget"):
        from .development_budget import Budget
        Budget(app.config["development_budget"]).check()
    if principal and principal.get("domain_task_id"):
        with app.store.connect() as connection:
            app.store.assert_execution(connection, principal["domain_task_id"],
                                       principal.get("_execution_token"))
            require(app.store.task(principal["domain_task_id"], connection)["project_id"] == project_id,
                    "成员页委托任务与项目不同", "forbidden", 403)


def _source_resolver(app, project_id, scope, check, *, connection=None):
    # Only a create's BEGIN IMMEDIATE transaction can prevent another writer
    # changing a checked source's current sharing/archive state. Page reads do
    # not cache permissions, and no cache survives this individual request.
    cache = OrderedDict() if connection is not None else None

    def resolve(ref):
        check()
        require(_ref(ref) and ref["revision"] > 0,
                "此入口只支持可解析的已保存固定来源；未接外部registry或r0",
                "unresolved_reference", 422)
        key = (ref["id"], ref["revision"])
        if cache is not None and key in cache:
            cache.move_to_end(key)
            return
        try:
            # App.get checks current caller access before reading this exact
            # historical revision. A new head must never substitute the pin.
            app.get(ref["id"], scope, ref["revision"])
        except Problem as error:
            if error.code == "not_found":
                raise Problem("来源固定修订无法解析；外部registry尚未接线",
                              "unresolved_reference", 422) from error
            raise
        if connection is None:
            with app.store.connect() as reader:
                app.store.assert_source_access(reader, project_id, ref["id"])
                current = app.store.get(ref["id"], connection=reader)
        else:
            app.store.assert_source_access(connection, project_id, ref["id"])
            current = app.store.get(ref["id"], connection=connection)
        require(not current["archived"], "来源已归档；固定历史保留但不能重新接纳或披露",
                "source_unavailable", 409)
        check()
        if cache is not None:
            cache[key] = True
            if len(cache) > 4096:
                cache.popitem(last=False)

    return resolve


def _metadata_sources(snapshot, resolve):
    require(snapshot["parent"] is None or _ref(snapshot["parent"]), "父级固定引用不完整")
    require(type(snapshot["batch_refs"]) is list and snapshot["batch_refs"], "批次固定引用不完整")
    if snapshot["parent"] is not None:
        resolve(snapshot["parent"])
    for ref in snapshot["batch_refs"]:
        resolve(ref)


def _member_sources(member, resolve):
    resolve(member["batch_ref"])
    if member["annotation_ref"] is not None:
        resolve(member["annotation_ref"])


def create(app, project, data, scope, principal):
    """Adopt a fully verified saved member manifest as a new dataset object."""
    require(type(data) is dict and data.get("action") == "dataset.snapshot"
            and data.get("project_id") == project.get("id"), "数据快照项目/命令身份不同")
    require("object_id" not in data and "expected_revision" not in data,
            "此成员manifest入口仅创建；不隐式覆盖旧数据修订", "unsupported_action", 422)
    require(set(data) == {"action", "request_id", "project_id", "payload"},
            "成员快照只接原命令的明确创建字段")
    require(not principal or type(principal) is dict
            and principal.get("kind") != "agent" and principal.get("actor_kind") != "agent",
            "Agent不能自行登记数据成员快照", "forbidden", 403)
    require(_text(data.get("request_id")), "数据快照需要原合同稳定请求身份")
    payload = data.get("payload")
    require(type(payload) is dict and set(payload) == {"dataset"},
            "成员快照需要显式payload.dataset，不接收路径或CSV推断")
    declaration = payload["dataset"]
    sha = _declaration(declaration)
    fingerprint = digest(_canonical(payload))
    project_id = project["id"]
    check = lambda: _current_check(app, project_id, scope, principal, write=True)
    authorize = lambda asset_sha: app.asset(asset_sha, scope, project_id)
    check()
    verify = getattr(member_assets, "verify_member_asset_manifest", None)
    require(callable(verify), "完整成员资产接纳核验尚未接线", "runtime_unavailable", 503)
    key = "dataset_request:" + project_id + ":" + data["request_id"]
    with app.store.transaction() as connection:
        row = connection.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if row:
            import json
            saved = json.loads(row[0])
            require(saved["input"] == fingerprint, "同一快照请求内容不同", "idempotency_conflict", 409)
        # Replays also recheck actual source bytes/current permissions. A saved
        # request key is not a new asset disclosure or integrity grant.
        resolve = _source_resolver(app, project_id, scope, check, connection=connection)
        _metadata_sources(declaration, resolve)
        snapshot = verify(app.store, sha, check=check, authorize=authorize,
                          expected_members=declaration.get("members"),
                          visit_member=lambda member: _member_sources(member, resolve))
        require(_canonical({key: snapshot[key] for key in _DECLARED})
                == _canonical({key: declaration[key] for key in _DECLARED}),
                "完整manifest与显式数据声明不同", "identity_mismatch", 409)
        check()
        content = {"asset_sha256": sha, "snapshot": snapshot,
                   "authority_kind": "immutable_member_manifest"}
        if row:
            result = app.access(app.store.get(saved["id"], 1, connection), scope)
            require(result["kind"] == "dataset" and result["project_id"] == project_id
                    and _canonical(result["content"]) == _canonical(content),
                    "快照重放登记身份不同", "identity_mismatch", 409)
            return result
        result = app.store.create("dataset", declaration["id"], project_id,
                                  content=content, connection=connection)
        connection.execute("INSERT INTO kv VALUES(?,?)",
                           (key, encoded({"input": fingerprint, "id": result["id"]})))
        check()
        return result


def page(app, project, payload, scope, principal):
    """Read bounded actual members of a fixed saved dataset revision."""
    require(type(payload) is dict and set(payload) == {"ref", "offset", "limit"},
            "成员页需要固定引用和明确有界范围")
    ref = payload["ref"]
    require(_ref(ref) and ref["revision"] > 0, "成员页必须绑定实际固定对象修订")
    require(type(payload["offset"]) is int and payload["offset"] >= 0
            and type(payload["limit"]) is int and 1 <= payload["limit"] <= 200,
            "成员页范围必须是准确有界整数")
    project_id = project["id"]
    check = lambda: _current_check(app, project_id, scope, principal)
    check()
    obj = app.get(ref["id"], scope, ref["revision"])
    require(obj["kind"] == "dataset" and obj["project_id"] == project_id,
            "成员修订不属于此项目", "forbidden", 403)
    content = obj["content"]
    require(type(content) is dict and content.get("authority_kind") == "immutable_member_manifest",
            "此页入口只支持已明确登记的成员manifest", "unsupported_format", 422)
    snapshot = content.get("snapshot")
    require(type(snapshot) is dict and _DECLARED <= set(snapshot), "保存的成员descriptor不完整")
    pointer = snapshot["member_manifest"]
    require(type(pointer) is dict and content.get("asset_sha256") == pointer.get("sha256"),
            "保存的成员manifest资产绑定不同", "identity_mismatch", 409)
    resolve = _source_resolver(app, project_id, scope, check)
    _metadata_sources(snapshot, resolve)
    result = member_assets.read_member_asset_page(
        app.store, pointer.get("sha256"), offset=payload["offset"], limit=payload["limit"],
        check=check, authorize=lambda sha: app.asset(sha, scope, project_id))
    require(_canonical(result["snapshot"]) == _canonical(snapshot),
            "实际成员页与固定保存descriptor不同", "identity_mismatch", 409)
    # Resolve the actual returned rows after copying. This also catches a
    # sharing withdrawal during the asset read, without inspecting other pages.
    for member in result["members"]:
        _member_sources(member, resolve)
    _metadata_sources(snapshot, resolve)
    check()
    return {**result, "ref": dict(ref), "executed": False}
