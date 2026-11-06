"""后端公共数据契约；领域内容保留扩展字段，运行时校验由入口负责。"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

JsonObject = dict[str, Any]
Scope = list[str] | None


class Principal(TypedDict, total=False):
    kind: Literal["loopback", "credential"]
    credential_sha256: str
    actor_kind: Literal["agent"]
    domain_task_id: str
    _execution_token: str
    allowed_actions: list[str]


class ResearchObject(TypedDict):
    id: str
    kind: str
    project_id: str | None
    title: str
    revision: int
    content: JsonObject
    metadata: JsonObject
    archived: bool
    created_at: str
    updated_at: str


TaskStatus = Literal[
    "queued",
    "running",
    "paused",
    "waiting_input",
    "waiting_resource",
    "waiting_authorization",
    "failed",
    "cancelled",
    "generated",
    "review",
    "deliverable",
]


class TaskBudget(TypedDict):
    max_model_calls: int
    timeout_seconds: float


class TaskPayload(TypedDict):
    project_id: str
    kind: str
    request: str
    context: JsonObject
    provider_id: str | None
    budget: TaskBudget
    target_id: NotRequired[str | None]
    base_revision: NotRequired[int | None]
    depends_on: NotRequired[list[str]]
    authorization: NotRequired[JsonObject]
    priority: NotRequired[int]
    feedback_id: NotRequired[str | None]
    workshop: NotRequired[JsonObject]
    literature_plan: NotRequired[JsonObject]


class TaskResult(TypedDict, total=False):
    object_id: str
    revision: int
    candidate: JsonObject
    provider: JsonObject
    composition_candidate: JsonObject | None
    independent_review: str
    user_acceptance: str
    human_feedback_requested: bool
    feedback_requested: str | None
    question_ids: list[str]
    failure_code: str
    details: JsonObject
    conflict: JsonObject
    process: JsonObject
    verification: str


class TaskRecord(TypedDict):
    id: str
    request_key: str
    payload_digest: str
    project_id: str | None
    status: TaskStatus
    payload: TaskPayload
    result: TaskResult
    error: str | None
    attempts: int
    created_at: str
    updated_at: str
    execution_token: NotRequired[str]
    steps: NotRequired[list[JsonObject]]
    acquisition: NotRequired[JsonObject]


class ObjectCreateRequest(TypedDict):
    action: Literal["object.create"]
    project_id: str
    kind: str
    title: str
    content: NotRequired[JsonObject]
    metadata: NotRequired[JsonObject]


class ObjectSaveRequest(TypedDict):
    action: str
    id: str
    expected_revision: int
    content: NotRequired[JsonObject | None]
    metadata: NotRequired[JsonObject | None]
    title: NotRequired[str | None]
    archived: NotRequired[bool | None]


class TaskSubmitRequest(TypedDict):
    action: str
    project_id: str
    request: NotRequired[str]
    prompt: NotRequired[str]
    provider_id: NotRequired[str]
    budget: NotRequired[TaskBudget]
    output_kind: NotRequired[str]
    request_key: NotRequired[str]
