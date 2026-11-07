"""有序的惰性命令路由；领域鉴权与公共作用域检查的先后顺序固定。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Literal, TYPE_CHECKING

from research_partner.commands.contract import validate_command_parameters
from research_partner.contracts import JsonObject, Principal, Scope
from research_partner.storage.store import Problem, require

if TYPE_CHECKING:
    from research_partner.app import App


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
        handler = getattr(import_module(self.module), self.handler)
        if self.invocation == "principal":
            return handler(app, data, scope, principal)
        return handler(app, data, scope)


# 这些领域先自行核验项目、任务和租约，不能提前套用通用 id 写权限规则。
DOMAIN_ROUTES = (
    Route(
        "research_partner.domains.evidence.claims",
        prefixes=("claim.",),
        invocation="principal",
    ),
    Route(
        "research_partner.domains.generation.generation",
        prefixes=("dataset.", "recipe.", "build."),
        invocation="principal",
    ),
    Route(
        "research_partner.domains.workspace.desk",
        prefixes=("desk.", "notes."),
        invocation="principal",
    ),
    Route("", "verify_state", actions=("system.verify",), invocation="scope"),
    Route(
        "research_partner.domains.figures.commit",
        actions=("figure.visual.commit", "figure.visual.receipt"),
        invocation="principal",
    ),
    Route(
        "research_partner.domains.figures.preview",
        actions=("figure.preview",),
        invocation="principal",
    ),
    Route(
        "research_partner.domains.manuscripts.layout",
        actions=("manuscript.format.render", "manuscript.format.source"),
        invocation="principal",
    ),
    Route(
        "research_partner.domains.manuscripts.formatting",
        prefixes=("manuscript.format.", "manuscript.edit."),
        invocation="principal",
    ),
    Route(
        "research_partner.domains.manuscripts.render", actions=("manuscript.render",)
    ),
    Route(
        "research_partner.domains.evidence.trace", "inspect", actions=("trace.inspect",)
    ),
    Route(
        "research_partner.domains.manuscripts.workspace",
        prefixes=("article.",),
        invocation="principal",
    ),
    Route(
        "research_partner.domains.workspace.workbench",
        prefixes=("workbench.",),
        invocation="principal",
    ),
    Route(
        "research_partner.domains.manuscripts.recovery",
        actions=("manuscript.revision.recover_preview", "manuscript.revision.recover"),
        invocation="principal",
    ),
    Route(
        "research_partner.execution.checkpoint_registration",
        actions=("task.recover_cli_checkpoint_preview", "task.recover_cli_checkpoint"),
        invocation="principal",
    ),
    Route(
        "research_partner.domains.manuscripts.revision",
        prefixes=("manuscript.revision.",),
        invocation="principal",
    ),
    Route(
        "research_partner.domains.workspace.management",
        prefixes=("project.management.",),
        invocation="principal",
    ),
)


COMMAND_ROUTES = (
    Route(
        "research_partner.domains.collaboration.cycle_child_revision",
        actions=("cycle.revise_failed_child_preview", "cycle.revise_failed_child"),
    ),
    Route(
        "research_partner.domains.collaboration.cycle_final_handoff",
        actions=("cycle.stage_final_revision_preview", "cycle.stage_final_revision"),
    ),
    Route(
        "research_partner.domains.collaboration.cycle_handoff",
        actions=("cycle.stage_revision_preview", "cycle.stage_revision"),
    ),
    Route(
        "research_partner.execution.recovery",
        actions=("task.recover_candidate", "task.recover_candidate_preview"),
    ),
    Route(
        "research_partner.commands.objects",
        "create_project",
        actions=("project.create",),
    ),
    Route(
        "research_partner.commands.workspace",
        "cycle_command",
        actions=("cycle.submit", "cycle.view", "cycle.control"),
    ),
    Route(
        "research_partner.commands.objects",
        "feature_project",
        actions=("project.feature",),
    ),
    Route(
        "research_partner.commands.objects",
        "accept_workshop",
        actions=("workshop.accept",),
    ),
    Route(
        "research_partner.commands.objects",
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
    Route(
        "research_partner.commands.objects", "create_object", actions=("object.create",)
    ),
    Route(
        "research_partner.commands.objects",
        "restore_object",
        actions=("object.restore",),
    ),
    Route(
        "research_partner.commands.reviews",
        "add_annotation",
        actions=("annotation.add",),
    ),
    Route(
        "research_partner.commands.reviews", "record_review", actions=("review.record",)
    ),
    Route(
        "research_partner.commands.reviews",
        "update_annotation",
        actions=("annotation.update",),
    ),
    Route("", "graph", prefixes=("graph.",), invocation="method"),
    Route(
        "research_partner.commands.reviews",
        "change_dependency",
        actions=("dependency.accept", "dependency.retain"),
    ),
    Route(
        "research_partner.commands.assets", "inspect_asset", actions=("asset.inspect",)
    ),
    Route(
        "research_partner.commands.assets", "import_asset", actions=("asset.import",)
    ),
    Route(
        "research_partner.commands.assets", "import_object", actions=("object.import",)
    ),
    Route(
        "research_partner.commands.assets",
        "authorize_code",
        actions=("object.authorize_code",),
    ),
    Route(
        "research_partner.commands.assets",
        "export_object",
        actions=("object.export", "figure.render"),
    ),
    Route(
        "research_partner.domains.collaboration.feedback_external",
        "record",
        actions=("feedback.record_external_action",),
        invocation="principal",
    ),
    Route("", "feedback", prefixes=("feedback.",), invocation="method"),
    Route(
        "research_partner.domains.collaboration.resolver",
        "resolve",
        actions=("task.resolve",),
    ),
    Route(
        "research_partner.commands.tasks",
        "submit_task",
        actions=("task.submit", "workshop.submit", "commission.submit"),
    ),
    Route(
        "research_partner.execution.stopped_candidate",
        actions=(
            "task.recover_stopped_candidate_preview",
            "task.recover_stopped_candidate",
        ),
        invocation="principal",
    ),
    Route(
        "research_partner.commands.tasks",
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
        "research_partner.domains.literature.fulltext_service",
        actions=("literature.fulltext.fetch", "literature.fulltext.status"),
        invocation="principal",
    ),
    Route(
        "research_partner.commands.workspace",
        "literature_command",
        prefixes=("literature.",),
    ),
    Route("", "growth", prefixes=("growth.",), invocation="method"),
    Route(
        "research_partner.commands.workspace",
        "extension_command",
        prefixes=("extension.",),
    ),
    Route(
        "research_partner.commands.workspace",
        "layer_settings",
        actions=("settings.layer_preview", "settings.layer_update"),
    ),
    Route(
        "research_partner.commands.workspace",
        "update_settings",
        actions=("settings.update",),
    ),
    Route(
        "research_partner.commands.workspace",
        "backup_workspace",
        actions=("workspace.backup",),
    ),
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
    if route.module.startswith("research_partner.commands."):
        validate_command_parameters(data, scope)
    return route.invoke(app, data, scope, principal)
