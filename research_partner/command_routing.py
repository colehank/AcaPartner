"""有序的惰性命令路由；领域鉴权与公共作用域检查的先后顺序固定。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Literal, TYPE_CHECKING

from .action_contract import validate_command_parameters
from .contracts import JsonObject, Principal, Scope
from .store import Problem, require

if TYPE_CHECKING:
    from .app import App


@dataclass(frozen=True)
class Route:
    module: str
    handler: str = "dispatch"
    actions: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    invocation: Literal["domain", "principal", "method", "scope"] = "domain"

    def matches(self, action: str) -> bool:
        return action in self.actions or bool(
            self.prefixes and action.startswith(self.prefixes)
        )

    def invoke(
        self, app: App, data: JsonObject, scope: Scope, principal: Principal | None
    ) -> Any:
        if self.invocation == "scope":
            return getattr(app, self.handler)(scope)
        if self.invocation == "method":
            return getattr(app, self.handler)(data, scope)
        handler = getattr(import_module("." + self.module, __package__), self.handler)
        if self.invocation == "principal":
            return handler(app, data, scope, principal)
        return handler(app, data, scope)


# 这些领域先自行核验项目、任务和租约，不能提前套用通用 id 写权限规则。
DOMAIN_ROUTES = (
    Route("claims", prefixes=("claim.",), invocation="principal"),
    Route(
        "generation", prefixes=("dataset.", "recipe.", "build."), invocation="principal"
    ),
    Route("desk_w1a", prefixes=("desk.", "notes."), invocation="principal"),
    Route("", "verify_state", actions=("system.verify",), invocation="scope"),
    Route(
        "figure_commit41",
        actions=("figure.visual.commit", "figure.visual.receipt"),
        invocation="principal",
    ),
    Route("figure_preview40", actions=("figure.preview",), invocation="principal"),
    Route(
        "manuscript_layout40",
        actions=("manuscript.format.render", "manuscript.format.source"),
        invocation="principal",
    ),
    Route(
        "manuscript_format40",
        prefixes=("manuscript.format.", "manuscript.edit."),
        invocation="principal",
    ),
    Route("manuscript_render", actions=("manuscript.render",)),
    Route("scientific_trace", "inspect", actions=("trace.inspect",)),
    Route("article_workspace", prefixes=("article.",), invocation="principal"),
    Route("workbench", prefixes=("workbench.",), invocation="principal"),
    Route(
        "manuscript_recovery39",
        actions=("manuscript.revision.recover_preview", "manuscript.revision.recover"),
        invocation="principal",
    ),
    Route(
        "codex_checkpoint_registration",
        actions=("task.recover_cli_checkpoint_preview", "task.recover_cli_checkpoint"),
        invocation="principal",
    ),
    Route(
        "manuscript_revision",
        prefixes=("manuscript.revision.",),
        invocation="principal",
    ),
    Route(
        "project_management", prefixes=("project.management.",), invocation="principal"
    ),
)


COMMAND_ROUTES = (
    Route(
        "cycle_child_revision",
        actions=("cycle.revise_failed_child_preview", "cycle.revise_failed_child"),
    ),
    Route(
        "cycle_final_handoff",
        actions=("cycle.stage_final_revision_preview", "cycle.stage_final_revision"),
    ),
    Route(
        "cycle_handoff",
        actions=("cycle.stage_revision_preview", "cycle.stage_revision"),
    ),
    Route(
        "native_recovery",
        actions=("task.recover_candidate", "task.recover_candidate_preview"),
    ),
    Route("command_objects", "create_project", actions=("project.create",)),
    Route(
        "command_workspace",
        "cycle_command",
        actions=("cycle.submit", "cycle.view", "cycle.control"),
    ),
    Route("command_objects", "feature_project", actions=("project.feature",)),
    Route("command_objects", "accept_workshop", actions=("workshop.accept",)),
    Route(
        "command_objects",
        "save_object",
        actions=(
            "project.update",
            "project.archive",
            "project.restore",
            "object.save",
            "object.rename",
            "object.archive",
        ),
    ),
    Route("command_objects", "create_object", actions=("object.create",)),
    Route("command_objects", "restore_object", actions=("object.restore",)),
    Route("command_reviews", "add_annotation", actions=("annotation.add",)),
    Route("command_reviews", "record_review", actions=("review.record",)),
    Route("command_reviews", "update_annotation", actions=("annotation.update",)),
    Route("", "graph", prefixes=("graph.",), invocation="method"),
    Route(
        "command_reviews",
        "change_dependency",
        actions=("dependency.accept", "dependency.retain"),
    ),
    Route("command_assets", "inspect_asset", actions=("asset.inspect",)),
    Route("command_assets", "import_asset", actions=("asset.import",)),
    Route("command_assets", "import_object", actions=("object.import",)),
    Route("command_assets", "authorize_code", actions=("object.authorize_code",)),
    Route(
        "command_assets", "export_object", actions=("object.export", "figure.render")
    ),
    Route(
        "feedback_external",
        "record",
        actions=("feedback.record_external_action",),
        invocation="principal",
    ),
    Route("", "feedback", prefixes=("feedback.",), invocation="method"),
    Route("resolver", "resolve", actions=("task.resolve",)),
    Route(
        "command_tasks",
        "submit_task",
        actions=("task.submit", "workshop.submit", "commission.submit"),
    ),
    Route(
        "stopped_candidate",
        actions=(
            "task.recover_stopped_candidate_preview",
            "task.recover_stopped_candidate",
        ),
        invocation="principal",
    ),
    Route(
        "command_tasks",
        "control_task",
        actions=(
            "task.control",
            "task.guide",
            "task.extend_budget",
            "task.revise_candidate",
        ),
    ),
    Route("", "answer", actions=("decision.answer",), invocation="method"),
    Route(
        "",
        "question_action",
        actions=(
            "question.materialize",
            "question.bind",
            "question.candidate_preview",
            "question.reassess",
        ),
        invocation="method",
    ),
    Route(
        "literature_fulltext_service",
        actions=("literature.fulltext.fetch", "literature.fulltext.status"),
        invocation="principal",
    ),
    Route("command_workspace", "literature_command", prefixes=("literature.",)),
    Route("", "growth", prefixes=("growth.",), invocation="method"),
    Route("command_workspace", "extension_command", prefixes=("extension.",)),
    Route(
        "command_workspace",
        "layer_settings",
        actions=("settings.layer_preview", "settings.layer_update"),
    ),
    Route("command_workspace", "update_settings", actions=("settings.update",)),
    Route("command_workspace", "backup_workspace", actions=("workspace.backup",)),
)


ID_AUTHORITY_IN_DOMAIN = frozenset(
    {
        "cycle.revise_failed_child_preview",
        "cycle.revise_failed_child",
        "task.control",
        "task.guide",
        "task.revise_candidate",
        "task.extend_budget",
        "task.recover_candidate",
        "task.recover_candidate_preview",
        "task.recover_stopped_candidate",
        "task.recover_stopped_candidate_preview",
        "cycle.view",
        "cycle.control",
        "cycle.stage_revision_preview",
        "cycle.stage_revision",
        "cycle.stage_final_revision_preview",
        "cycle.stage_final_revision",
        "annotation.update",
        "dependency.accept",
        "dependency.retain",
        "question.candidate_preview",
    }
)


def resolve_route(action: str, routes: tuple[Route, ...]) -> Route | None:
    return next((route for route in routes if route.matches(action)), None)


def authorize_mutation(app: App, data: JsonObject, scope: Scope) -> None:
    action = data["action"]
    if scope is None or action == "project.create" or action.startswith("graph."):
        return
    # 共享材料只授予证据读取；公共字段的核验顺序影响权限错误优先级。
    for key in ("project_id", "object_id", "src", "source_id", "target_id"):
        if data.get(key):
            require(
                isinstance(data[key], str), "对象标识需要字符串", details={"field": key}
            )
            app.writable(data[key], scope)
    if (
        data.get("id")
        and action not in ID_AUTHORITY_IN_DOMAIN
        and not action.startswith(("extension.", "graph."))
    ):
        require(
            isinstance(data["id"], str), "对象标识需要字符串", details={"field": "id"}
        )
        app.writable(data["id"], scope)


def dispatch_command(
    app: App, data: JsonObject, scope: Scope, principal: Principal | None
) -> Any:
    route = resolve_route(data["action"], DOMAIN_ROUTES)
    if route is not None:
        return route.invoke(app, data, scope, principal)
    authorize_mutation(app, data, scope)
    route = resolve_route(data["action"], COMMAND_ROUTES)
    if route is None:
        raise Problem("未实现的操作：" + data["action"], "not_implemented", 501)
    if route.module.startswith("command_"):
        validate_command_parameters(data, scope)
    return route.invoke(app, data, scope, principal)
