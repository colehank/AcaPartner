"""对象策略始终在原 SQLite 事务中、对象写入前执行。"""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from research_partner import compatibility, object_policies
from research_partner.store import Problem, Store


class ObjectPolicies(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name) / "workspace")

    def database_state(self):
        with self.store.connect() as connection:
            return {
                table: [
                    tuple(row) for row in connection.execute(f"SELECT * FROM {table}")
                ]
                for table in ("objects", "revisions", "events", "kv", "conflicts")
            } | {
                "triggers": [
                    tuple(row)
                    for row in connection.execute(
                        "SELECT name,sql FROM sqlite_schema WHERE type='trigger'"
                    )
                ]
            }

    def assert_rejected_without_writes(self, operation, code, status):
        before = self.database_state()
        with self.assertRaises(Problem) as raised:
            operation()
        self.assertEqual(
            (raised.exception.code, raised.exception.status), (code, status)
        )
        self.assertEqual(self.database_state(), before)

    def test_public_object_and_task_boundaries_expose_contracts(self):
        from typing import get_type_hints

        from research_partner.contracts import (
            ResearchObject,
            TaskPayload,
            TaskRecord,
            TaskResult,
            TaskStatus,
        )

        for name in ("get", "create", "save", "restore"):
            with self.subTest(method=name):
                self.assertIs(
                    get_type_hints(getattr(Store, name))["return"], ResearchObject
                )
        self.assertEqual(get_type_hints(Store.objects)["return"], list[ResearchObject])
        for name in ("task", "submit", "task_update"):
            with self.subTest(method=name):
                self.assertIs(
                    get_type_hints(getattr(Store, name))["return"], TaskRecord
                )
        self.assertEqual(get_type_hints(Store.tasks)["return"], list[TaskRecord])
        self.assertIs(get_type_hints(Store.submit)["payload"], TaskPayload)
        self.assertIs(get_type_hints(Store.task_update)["status"], TaskStatus)
        self.assertEqual(get_type_hints(Store.task_update)["result"], TaskResult | None)

    def test_task_contract_annotations_preserve_sql_roundtrip_and_statuses(self):
        from typing import get_args

        from research_partner.contracts import TaskPayload, TaskResult, TaskStatus

        payload: TaskPayload = {
            "project_id": "project",
            "kind": "draft",
            "request": "本地测试，不执行任务",
            "context": {},
            "provider_id": None,
            "budget": {"max_model_calls": 1, "timeout_seconds": 30},
        }
        result: TaskResult = {"verification": "pending", "provider": {"route": "test"}}
        for status in get_args(TaskStatus):
            with self.subTest(status=status):
                with self.store.transaction() as connection:
                    task = self.store.submit(
                        payload,
                        "request:" + status,
                        connection=connection,
                        initial_result=result,
                    )
                    self.assertEqual(
                        self.store.task(task["id"], connection)["result"], result
                    )
                    self.assertTrue(connection.in_transaction)
                updated = self.store.task_update(task["id"], status, result=result)
                self.assertEqual(updated["status"], status)
                self.assertEqual(updated["result"], result)
                self.assertEqual(updated["steps"], [])
                listed = next(
                    item for item in self.store.tasks() if item["id"] == task["id"]
                )
                self.assertEqual(listed["payload"], payload)

    def test_feature_policies_reject_create_and_save_atomically(self):
        cases = [
            ("report", {}, {"manuscript_format": {}}, "manuscript_format_v1"),
            (
                "figure",
                {"overlays": {"figure:root": {}}},
                {},
                "figure_visual_layout_v1",
            ),
            (
                "dataset",
                {"authority_kind": "immutable_member_manifest"},
                {},
                "chunked_member_snapshot_v1",
            ),
            (
                "paper",
                {"paper_source_mode": "structured"},
                {},
                "paper_source_selection_v1",
            ),
        ]
        for kind, content, metadata, feature in cases:
            with self.subTest(kind=kind):
                existing = self.store.create(kind, "已有对象")
                with mock.patch.object(
                    compatibility,
                    "SUPPORTED_FEATURES",
                    compatibility.SUPPORTED_FEATURES - {feature},
                ):
                    self.assert_rejected_without_writes(
                        lambda: self.store.create(
                            kind, "候选", content=content, metadata=metadata
                        ),
                        "runtime_incompatible",
                        409,
                    )
                    self.assert_rejected_without_writes(
                        lambda: self.store.save(
                            existing["id"], 1, content=content, metadata=metadata
                        ),
                        "runtime_incompatible",
                        409,
                    )

    def test_format_and_source_errors_preserve_codes_and_rollback(self):
        cases = [
            (
                "report",
                {},
                {"manuscript_format": {"columns": 3}},
                "invalid_format",
                422,
            ),
            ("figure", {}, {"manuscript_format": {}}, "invalid", 400),
            (
                "paper",
                {"paper_source_mode": "invalid"},
                {},
                "invalid_paper_source",
                422,
            ),
            ("paper", {"latex": 4}, {}, "invalid_paper_source", 422),
        ]
        for kind, content, metadata, code, status in cases:
            with self.subTest(kind=kind, content=content, metadata=metadata):
                obj = self.store.create(kind, "原对象")
                self.assert_rejected_without_writes(
                    lambda: self.store.create(
                        kind, "候选", content=content, metadata=metadata
                    ),
                    code,
                    status,
                )
                self.assert_rejected_without_writes(
                    lambda: self.store.save(
                        obj["id"], 1, content=content, metadata=metadata
                    ),
                    code,
                    status,
                )

    def test_policy_failure_rolls_back_earlier_feature_floor(self):
        manuscript = self.store.create(
            "report",
            "稿件",
            content={"blocks": [{"id": "heading", "kind": "heading", "text": "章节"}]},
            metadata={
                "article": {
                    "sections": [
                        {
                            "id": "section",
                            "heading_block_id": "heading",
                            "title": "章节",
                        }
                    ]
                }
            },
        )
        self.assert_rejected_without_writes(
            lambda: self.store.create(
                "workshop_note",
                "错误章节",
                content={
                    "manuscript_id": manuscript["id"],
                    "section_id": "section",
                    "section_block_id": "wrong",
                },
            ),
            "article_note_conflict",
            409,
        )
        self.assertNotIn("minimum_runtime_features", dict(self.database_state()["kv"]))

    def test_policies_see_same_live_connection_before_writes(self):
        original = object_policies.validate_object_policies
        calls = []
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with self.store.transaction() as connection:

                def validate(store, active, obj, **kwargs):
                    self.assertIs(store, self.store)
                    self.assertIs(active, connection)
                    self.assertTrue(active.in_transaction)
                    current = active.execute(
                        "SELECT revision FROM objects WHERE id=?", (obj["id"],)
                    ).fetchone()
                    if kwargs.get("saving"):
                        self.assertEqual(current["revision"], obj["revision"] - 1)
                    else:
                        self.assertIsNone(current)
                    calls.append(obj["revision"])
                    return original(store, active, obj, **kwargs)

                with (
                    mock.patch.object(
                        object_policies, "validate_object_policies", validate
                    ),
                    mock.patch.object(
                        self.store, "_connect", side_effect=AssertionError("新连接")
                    ),
                ):
                    created = self.store.create(
                        "report",
                        "事务内稿件",
                        metadata={"manuscript_format": {}},
                        connection=connection,
                    )
                    self.store.save(
                        created["id"], 1, title="更新稿件", connection=connection
                    )
                    self.assertEqual(calls, [1, 2])
                    self.assertTrue(connection.in_transaction)
                raise RuntimeError("rollback")
        state = self.database_state()
        self.assertEqual(state["objects"], [])
        self.assertEqual(state["revisions"], [])
        self.assertEqual(state["events"], [])
        self.assertEqual(state["triggers"], [])
        self.assertEqual(state["kv"], [("schema_version", "1")])

    def create_manuscript_and_note(self, connection=None):
        manuscript = self.store.create(
            "paper",
            "稿件",
            content={"blocks": [{"id": "heading", "kind": "heading", "text": "章节"}]},
            metadata={
                "article": {
                    "sections": [
                        {
                            "id": "section",
                            "heading_block_id": "heading",
                            "title": "章节",
                        }
                    ]
                }
            },
            connection=connection,
        )
        note = self.store.create(
            "workshop_note",
            "准备笔记",
            content={
                "manuscript_id": manuscript["id"],
                "section_id": "section",
                "section_block_id": "heading",
            },
            connection=connection,
        )
        return manuscript, note

    def test_article_lookup_observes_uncommitted_manuscript(self):
        before = self.database_state()
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with self.store.transaction() as connection:
                with mock.patch.object(
                    self.store, "_connect", side_effect=AssertionError("新连接")
                ):
                    manuscript, note = self.create_manuscript_and_note(connection)
                    self.assertEqual(note["content"]["manuscript_id"], manuscript["id"])
                    self.assertTrue(connection.in_transaction)
                raise RuntimeError("rollback")
        self.assertEqual(self.database_state(), before)

    def test_preparation_notes_cannot_become_output_dependencies(self):
        _, note = self.create_manuscript_and_note()
        for kind in (
            "paper",
            "report",
            "note",
            "figure",
            "diagram",
            "poster",
            "slides",
        ):
            with self.subTest(kind=kind):
                existing = self.store.create(kind, "已有成果")
                content = {"source_refs": [{"id": note["id"], "revision": 1}]}
                self.assert_rejected_without_writes(
                    lambda: self.store.create(kind, "候选", content=content),
                    "preparation_boundary",
                    409,
                )
                self.assert_rejected_without_writes(
                    lambda: self.store.save(existing["id"], 1, content=content),
                    "preparation_boundary",
                    409,
                )

    def test_layout_target_spellings_keep_the_same_feature_requirement(self):
        for overlays in (
            {"figure:root": {}},
            {"colorbar:main": {}},
            [{"target": "figure:root"}],
            [{"object_id": "colorbar:main"}],
            [{"id": "colorbar:main"}],
        ):
            with self.subTest(overlays=overlays):
                with mock.patch.object(
                    compatibility,
                    "SUPPORTED_FEATURES",
                    compatibility.SUPPORTED_FEATURES - {"figure_visual_layout_v1"},
                ):
                    self.assert_rejected_without_writes(
                        lambda: self.store.create(
                            "figure", "图件", content={"overlays": overlays}
                        ),
                        "runtime_incompatible",
                        409,
                    )

    def test_irrelevant_objects_do_not_raise_new_runtime_floors(self):
        with mock.patch.object(
            compatibility, "require_features", side_effect=AssertionError("多余门槛")
        ):
            for kind, content in (
                ("report", {}),
                ("figure", {"overlays": [{"target": "panel:one"}]}),
                ("paper", {"latex": "手写稿"}),
                ("paper", {"paper_source_mode": ""}),
            ):
                with self.subTest(kind=kind, content=content):
                    obj = self.store.create(kind, "普通对象", content=content)
                    self.store.save(obj["id"], 1, title="更新普通对象")

    def test_save_error_order_still_checks_title_before_paper_source(self):
        obj = self.store.create("paper", "稿件")
        self.assert_rejected_without_writes(
            lambda: self.store.save(
                obj["id"], 1, title="", content={"paper_source_mode": "wrong"}
            ),
            "invalid",
            400,
        )

    def test_missing_references_remain_allowed(self):
        self.store.create(
            "report", "缺失引用", content={"source_refs": [{"id": "ART-missing"}]}
        )

    def test_workshop_note_feature_and_binding_errors(self):
        manuscript, note = self.create_manuscript_and_note()
        with mock.patch.object(
            compatibility,
            "SUPPORTED_FEATURES",
            compatibility.SUPPORTED_FEATURES - {"article_workspace_v1"},
        ):
            self.assert_rejected_without_writes(
                lambda: self.store.save(note["id"], 1, title="新标题"),
                "runtime_incompatible",
                409,
            )
        self.assert_rejected_without_writes(
            lambda: self.store.save(
                note["id"], 1, content={**note["content"], "section_id": "wrong"}
            ),
            "article_note_conflict",
            409,
        )
        self.assert_rejected_without_writes(
            lambda: self.store.save(
                note["id"], 1, content={**note["content"], "manuscript_id": note["id"]}
            ),
            "article_note_conflict",
            409,
        )
        self.assertEqual(self.store.get(manuscript["id"])["revision"], 1)

    def test_public_methods_remain_compatibility_proxies(self):
        obj = {"kind": "report", "content": {}, "metadata": {}}
        with self.store.transaction() as connection:
            for name in (
                "require_member_snapshot_runtime",
                "require_figure_layout_runtime",
                "require_manuscript_format_runtime",
            ):
                with self.subTest(method=name):
                    with mock.patch.object(
                        object_policies, name, return_value="delegated"
                    ) as policy:
                        self.assertEqual(
                            getattr(self.store, name)(connection, obj), "delegated"
                        )
                        policy.assert_called_once_with(connection, obj)
            with mock.patch.object(
                object_policies, "validate_article_object", return_value="delegated"
            ) as policy:
                self.assertEqual(
                    self.store.validate_article_object(connection, obj), "delegated"
                )
                policy.assert_called_once_with(self.store, connection, obj)

    def test_optimistic_conflict_is_still_persisted_without_object_write(self):
        obj = self.store.create("report", "稿件", content={"text": "base"})
        current = self.store.save(obj["id"], 1, content={"text": "current"})
        before = self.database_state()
        with self.assertRaises(Problem) as raised:
            self.store.save(obj["id"], 1, content={"text": "candidate"})
        self.assertEqual(
            (raised.exception.code, raised.exception.status), ("conflict", 409)
        )
        self.assertEqual(self.store.get(obj["id"]), current)
        after = self.database_state()
        self.assertEqual(after["revisions"], before["revisions"])
        self.assertEqual(len(after["conflicts"]), len(before["conflicts"]) + 1)
        self.assertEqual(self.store.events(obj["id"])[0]["kind"], "edit.conflict")

    def test_disjoint_optimistic_merge_still_validates_merged_snapshot(self):
        obj = self.store.create("report", "稿件", content={"a": 1, "b": 1})
        self.store.save(obj["id"], 1, content={"a": 2, "b": 1})
        result = self.store.save(
            obj["id"], 1, content={"a": 1, "b": 2}, metadata={"manuscript_format": {}}
        )
        self.assertEqual(result["content"], {"a": 2, "b": 2})
        self.assertEqual(result["revision"], 3)
        self.assertTrue(self.store.events(obj["id"])[0]["data"]["merged"])

    def test_removed_assignments_keep_validation_side_effects(self):
        obj = self.store.create("report", "稿件")
        self.assert_rejected_without_writes(
            lambda: self.store.annotate(obj["id"], 99, {}, "批注"),
            "not_found",
            404,
        )
        with self.assertRaises(TypeError):
            self.store._verify_asset_blob(object(), 0)


class AnnotationUpdates(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name) / "workspace")
        self.obj = self.store.create("report", "稿件")
        self.annotation = self.store.annotate(self.obj["id"], 1, {}, "原始批注")

    def update(self, **kwargs):
        return self.store.update_annotation(
            self.annotation["id"], self.obj["id"], **kwargs
        )

    def test_status_text_and_events_preserve_omitted_fields(self):
        rows = self.update(status="resolved")
        self.assertEqual(rows[0]["text"], "原始批注")
        self.assertEqual(rows[0]["status"], "resolved")
        rows = self.update(text="修订批注")
        self.assertEqual(rows[0]["status"], "resolved")
        event = self.store.events(self.obj["id"])[0]
        self.assertEqual(event["kind"], "annotation.updated")
        self.assertEqual(
            event["data"], {"id": self.annotation["id"], "previous_text": "原始批注"}
        )
        self.update()
        self.assertEqual(
            self.store.events(self.obj["id"])[0]["data"]["previous_text"], "修订批注"
        )

    def test_all_original_statuses_and_empty_text_are_allowed(self):
        for status in ("anchored", "orphaned", "text_changed", "resolved"):
            with self.subTest(status=status):
                self.assertEqual(self.update(status=status)[0]["status"], status)
        self.assertEqual(self.update(text="")[0]["text"], "")

    def test_wrong_object_binding_and_invalid_status_do_not_write(self):
        other = self.store.create("report", "其他稿件")
        before_rows = self.store.annotations(self.obj["id"])
        before_events = self.store.events()
        for operation, code, status in (
            (
                lambda: self.store.update_annotation(
                    self.annotation["id"], other["id"], text="越界"
                ),
                "not_found",
                404,
            ),
            (lambda: self.update(status="unsupported"), "invalid", 400),
            (lambda: self.update(status=None), "invalid", 400),
        ):
            with self.subTest(code=code, status=status):
                with self.assertRaises(Problem) as raised:
                    operation()
                self.assertEqual(
                    (raised.exception.code, raised.exception.status), (code, status)
                )
                self.assertEqual(self.store.annotations(self.obj["id"]), before_rows)
                self.assertEqual(self.store.events(), before_events)

    def test_outer_transaction_rolls_back_annotation_and_event(self):
        before_rows = self.store.annotations(self.obj["id"])
        before_events = self.store.events()
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with self.store.transaction() as connection:
                with mock.patch.object(
                    self.store, "_connect", side_effect=AssertionError("新连接")
                ):
                    rows = self.update(
                        text="事务内批注", status="resolved", connection=connection
                    )
                    self.assertEqual(rows[0]["text"], "事务内批注")
                    self.assertTrue(connection.in_transaction)
                raise RuntimeError("rollback")
        self.assertEqual(self.store.annotations(self.obj["id"]), before_rows)
        self.assertEqual(self.store.events(), before_events)

    def test_supplied_connection_must_be_managed(self):
        with self.store.connect() as connection:
            with self.assertRaises(Problem) as raised:
                self.update(text="不可写", connection=connection)
        self.assertEqual(
            (raised.exception.code, raised.exception.status), ("asset_transaction", 409)
        )


if __name__ == "__main__":
    unittest.main()
