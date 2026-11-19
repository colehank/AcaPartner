"""任务提交和显式控制；调用前由公共分派层完成作用域检查。"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from research_partner.contracts import JsonObject, Scope
import json
from research_partner.storage.store import require, now

if TYPE_CHECKING:
    from research_partner.app import App


def submit_task(app: App, data: JsonObject, scope: Scope) -> Any:
    return app.submit(data, scope)


def control_task(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    action = data["action"]
    task = s.task(data["id"])
    if task["payload"].get("kind") == "manuscript_revision":
        from research_partner.domains.manuscripts.revision import task_access

        with s.connect() as connection:
            task_access(app, task, scope, connection)
    elif task["payload"].get("kind") == "project_management":
        from research_partner.domains.workspace.management import task_access

        with s.connect() as connection:
            task_access(app, task, scope, connection)
    else:
        app.writable(task["project_id"], scope)
    if action == "task.revise_candidate":
        require(
            data.get("approved") is True,
            "需要明确选择按当前回答修订候选；此操作可能消耗既定剩余额度",
            "authorization_required",
            403,
        )
        require(task["payload"]["kind"] != "workshop", "工具任务不使用模型候选修订")
        with s.transaction() as c:
            current = s.unpack(
                c.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone()
            )
            if current["payload"].get("kind") == "manuscript_revision":
                from research_partner.domains.manuscripts.revision import may_revise

                may_revise(app, current, c)
            require(
                current["status"] in {"waiting_input", "paused", "failed"},
                "请先停止执行并检查已保存候选",
                "conflict",
                409,
            )
            require(
                current["attempts"] < 3,
                "有限尝试次数已耗尽；未扩额度或新建会话",
                "budget_exhausted",
                409,
            )
            committed = c.execute(
                "SELECT value FROM kv WHERE key=?", ("commit:" + task["id"],)
            ).fetchone()
            produced = c.execute(
                "SELECT id FROM objects WHERE id=?",
                ("ART-" + task["id"].removeprefix("TASK-"),),
            ).fetchone()
            require(
                not current["result"].get("object_id")
                and not committed
                and not produced,
                "此任务已有保存成果；请在成果旁发起修订以保留用户编辑和版本，未消耗模型额度",
                "conflict",
                409,
            )
            snapshot = s.execution_inputs(c, task["id"])
            require(
                not s.question_blockers(c, task["id"]),
                "必要问题或来源尚待明确重新评估；未授权新的模型调用",
                "conflict",
                409,
            )
            require(
                data.get("input_snapshot") == snapshot,
                "回答或指导已变化，请重新读取后选择",
                "conflict",
                409,
            )
            grant = {
                "input_snapshot": snapshot,
                "state": "authorized",
                "at": now(),
                "permissions_changed": False,
                "budget_extended": False,
            }
            c.execute(
                "INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (
                    "candidate_revision_authorized:" + task["id"],
                    json.dumps(grant),
                ),
            )
            lease_row = c.execute(
                "SELECT value FROM kv WHERE key=?", ("execution:" + task["id"],)
            ).fetchone()
            if lease_row:
                lease = json.loads(lease_row[0])
                lease.update(
                    state="revoked",
                    reason="explicit candidate revision",
                    revoked_at=now(),
                )
                c.execute(
                    "UPDATE kv SET value=? WHERE key=?",
                    (json.dumps(lease), "execution:" + task["id"]),
                )
            c.execute(
                "UPDATE tasks SET status='queued',error=NULL,updated_at=? WHERE id=?",
                (now(), task["id"]),
            )
            s.event(
                c,
                "task.candidate_revision_authorized",
                task["id"],
                grant,
                "user",
            )
        if app.runner:
            app.runner.wake()
        return {
            "task": s.task(task["id"]),
            "revision_authorized": True,
            "budget_extended": False,
            "permissions_changed": False,
        }
    if action == "task.extend_budget":
        require(
            scope is None and data.get("approved") is True and data.get("reason"),
            "增加额度需要空间所有者明确确认范围与理由",
            "authorization_required",
            403,
        )
        require(
            task["status"]
            in {
                "failed",
                "waiting_resource",
                "waiting_authorization",
                "paused",
            },
            "仅可在执行停止后调整额度",
            "conflict",
            409,
        )
        route = (
            app.config.get("providers", {})
            .get(task["payload"].get("provider_id"), {})
            .get("route")
        )
        require(
            route == "codex",
            "原生Harness额度须核对其独立授权账本，不能从此入口绕过",
            "authorization_required",
            403,
        )
        calls = data.get("additional_invocations", 0)
        seconds = data.get("additional_seconds", 0)
        require(
            type(calls) is int
            and 0 <= calls <= 5
            and isinstance(seconds, (int, float))
            and 0 <= seconds <= 900
            and calls + seconds > 0,
            "需要有限新增额度",
        )
        previous = s.setting(
            "budget_extension:" + task["id"], {"invocations": 0, "seconds": 0}
        )
        value = {
            "invocations": previous["invocations"] + calls,
            "seconds": previous["seconds"] + seconds,
            "reason": data["reason"],
            "at": now(),
        }
        s.set_setting("budget_extension:" + task["id"], value)
        with s.transaction() as c:
            s.event(
                c,
                "budget.explicit_extension",
                task["id"],
                {"previous": previous, "current": value},
                "owner",
            )
        return {
            "task_id": task["id"],
            "extension": value,
            "consumption_preserved": True,
            "automatically_resumed": False,
        }
    if action == "task.guide":
        require(data.get("text", "").strip(), "指导不能为空")
        require(
            task["status"] not in {"cancelled", "deliverable"},
            "已结束任务不能接收新指导",
            "conflict",
            409,
        )
        author = data.get("source", "user")
        require(
            author in {"user", "coordinator", "independent_review"},
            "指导来源不支持",
        )
        with s.transaction() as c:
            s.event(
                c,
                "task.guidance",
                task["id"],
                {
                    "text": data["text"],
                    "source": author,
                    "source_reference": data.get("source_reference"),
                    "scope": "next execution handoff; cannot grant permissions",
                },
                author,
            )
        return {
            "task_id": task["id"],
            "guidance_saved": True,
            "takes_effect": "next execution handoff",
        }
    require(app.runner, "执行服务没有启动", "runtime_unavailable", 503)
    if "expected_status" in data:
        require(
            data["expected_status"] in ("queued", "running")
            and data.get("operation") == "pause",
            "暂停需要明确的执行中状态",
            "conflict",
            409,
        )
        return app.runner.control(
            task["id"],
            data["operation"],
            expected_status=data["expected_status"],
        )
    return app.runner.control(task["id"], data["operation"])
