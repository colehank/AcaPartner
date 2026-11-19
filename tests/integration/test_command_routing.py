"""领域分派迁移的权限、修订与响应兼容性回归。"""

from __future__ import annotations

from research_partner.resources import module_file

import ast
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from research_partner.app import App
from research_partner.commands.contract import (
    COMMAND_FIELDS,
    validate_command_parameters,
)
from research_partner.commands.routing import (
    COMMAND_ROUTES,
    DOMAIN_ROUTES,
    ID_AUTHORITY_IN_DOMAIN,
    Route,
    authorize_mutation,
    dispatch_command,
    resolve_route,
)
from research_partner.storage.store import Problem, digest


class CommandRouting(unittest.TestCase):
    def test_specific_routes_precede_prefix_fallback(self):
        cases = {
            "manuscript.format.render": "research_partner.domains.manuscripts.layout",
            "manuscript.format.source": "research_partner.domains.manuscripts.layout",
            "manuscript.format.update": "research_partner.domains.manuscripts.formatting",
            "manuscript.edit.update": "research_partner.domains.manuscripts.formatting",
            "manuscript.revision.recover_preview": "research_partner.domains.manuscripts.recovery",
            "manuscript.revision.submit": "research_partner.domains.manuscripts.revision",
            "task.recover_cli_checkpoint": "research_partner.execution.checkpoint_registration",
        }
        for action, module in cases.items():
            with self.subTest(action=action):
                self.assertEqual(resolve_route(action, DOMAIN_ROUTES).module, module)
        for action, module in {
            "feedback.record_external_action": "research_partner.domains.collaboration.feedback_external",
            "literature.fulltext.fetch": "research_partner.domains.literature.fulltext_service",
            "literature.search": "research_partner.commands.workspace",
        }.items():
            with self.subTest(action=action):
                self.assertEqual(resolve_route(action, COMMAND_ROUTES).module, module)

    def test_all_registered_routes_invoke_exact_signature_lazily(self):
        principal = {"kind": "credential", "actor_kind": "agent"}
        for route in (*DOMAIN_ROUTES, *COMMAND_ROUTES):
            action = (
                route.actions[0] if route.actions else route.prefixes[0] + "example"
            )
            data = {"action": action}
            app = mock.Mock()
            handler = mock.Mock(return_value={"sentinel": action})
            with (
                self.subTest(action=action),
                mock.patch("research_partner.commands.routing.import_module") as load,
            ):
                setattr(load.return_value, route.handler, handler)
                if route.invocation in {"method", "scope"}:
                    setattr(app, route.handler, handler)
                self.assertEqual(
                    route.invoke(app, data, ["project"], principal),
                    {"sentinel": action},
                )
                if route.invocation == "scope":
                    handler.assert_called_once_with(["project"])
                    load.assert_not_called()
                elif route.invocation == "method":
                    handler.assert_called_once_with(data, ["project"])
                    load.assert_not_called()
                elif route.invocation == "principal":
                    handler.assert_called_once_with(app, data, ["project"], principal)
                else:
                    handler.assert_called_once_with(app, data, ["project"])

    def test_specialized_authority_still_runs_before_common_id_rule(self):
        app = mock.Mock()
        principal = {"kind": "credential"}
        with mock.patch.object(Route, "invoke", return_value={"ok": True}) as invoke:
            result = dispatch_command(
                app,
                {"action": "manuscript.revision.recover", "id": "task-not-object"},
                ["project"],
                principal,
            )
        self.assertEqual(result, {"ok": True})
        app.writable.assert_not_called()
        self.assertIs(invoke.call_args.args[-1], principal)

    def test_common_authority_order_and_domain_exceptions(self):
        app = mock.Mock()
        fields = {
            key: key + "-value"
            for key in (
                "project_id",
                "object_id",
                "src",
                "source_id",
                "target_id",
                "id",
            )
        }
        authorize_mutation(app, {"action": "object.save", **fields}, ["scope"])
        self.assertEqual(
            app.writable.call_args_list,
            [mock.call(value, ["scope"]) for value in fields.values()],
        )
        for action in ID_AUTHORITY_IN_DOMAIN:
            app.reset_mock()
            authorize_mutation(
                app, {"action": action, "id": "task-or-relation"}, ["scope"]
            )
            app.writable.assert_not_called()
        for action in ("graph.inspect", "project.create", "extension.list"):
            app.reset_mock()
            authorize_mutation(app, {"action": action, "id": "not-object"}, ["scope"])
            app.writable.assert_not_called()

    def test_handled_none_is_not_unknown_and_unknown_remains_501(self):
        app = mock.Mock()
        with mock.patch.object(Route, "invoke", return_value=None):
            self.assertIsNone(
                dispatch_command(app, {"action": "system.verify"}, None, None)
            )
        with self.assertRaises(Problem) as caught:
            dispatch_command(app, {"action": "unknown.example"}, None, None)
        self.assertEqual(
            (caught.exception.code, caught.exception.status), ("not_implemented", 501)
        )

    def test_core_schemas_reject_missing_or_wrong_types_before_handler(self):
        for action, fields in COMMAND_FIELDS.items():
            for field in fields:
                with self.subTest(action=action, field=field):
                    data = {"action": action}
                    with self.assertRaises(Problem):
                        validate_command_parameters(data, None)
        for action in ("object.create", "project.create"):
            with self.assertRaises(Problem) as caught:
                validate_command_parameters(
                    {
                        "action": action,
                        "project_id": "p",
                        "title": "ok",
                        "kind": "note",
                        "content": [],
                    },
                    None,
                )
            self.assertEqual(caught.exception.details["field"], "content")
        for revision in (True, 0, -1, 1.2, "1"):
            with self.subTest(revision=revision), self.assertRaises(Problem) as caught:
                validate_command_parameters(
                    {
                        "action": "object.save",
                        "id": "object",
                        "expected_revision": revision,
                    },
                    None,
                )
            self.assertEqual(
                (caught.exception.code, caught.exception.status),
                ("version_required", 409),
            )

    def test_bad_scope_identifiers_are_invalid_before_database_binding(self):
        for field in ("project_id", "object_id", "src", "source_id", "target_id", "id"):
            for value in (["bad"], {"bad": "id"}, True, 3):
                app = mock.Mock()
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(Problem) as caught,
                ):
                    authorize_mutation(
                        app, {"action": "object.save", field: value}, ["scope"]
                    )
                self.assertEqual(caught.exception.code, "invalid")
                self.assertEqual(caught.exception.details["field"], field)
                app.writable.assert_not_called()

    def test_owner_only_permission_precedes_required_fields(self):
        for action in (
            "project.create",
            "object.authorize_code",
            "settings.update",
            "workspace.backup",
            "extension.list",
        ):
            with self.subTest(action=action), self.assertRaises(Problem) as caught:
                validate_command_parameters({"action": action}, ["project"])
            self.assertEqual(
                (caught.exception.code, caught.exception.status), ("forbidden", 403)
            )

    def test_app_dispatch_contains_no_business_sql_and_domains_use_no_private_app_members(
        self,
    ):
        import research_partner.app as app_module

        tree = ast.parse(Path(app_module.__file__).read_text())
        app_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "App"
        )
        dispatch = next(
            node
            for node in app_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "_dispatch"
        )
        self.assertLessEqual(dispatch.end_lineno - dispatch.lineno, 12)
        self.assertFalse(
            any(
                isinstance(node, ast.Attribute) and node.attr == "execute"
                for node in ast.walk(dispatch)
            )
        )
        for name in (
            "research_partner.commands.objects",
            "research_partner.commands.reviews",
            "research_partner.commands.assets",
            "research_partner.commands.tasks",
            "research_partner.commands.workspace",
        ):
            code = ast.parse(module_file(name).read_text())
            self.assertFalse(
                any(
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "app"
                    and node.attr.startswith("_")
                    for node in ast.walk(code)
                ),
                name,
            )


class DomainCommands(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.app = App(
            Path(tmp.name) / "workspace",
            {"providers": {"offline": {"route": "codex", "authorized": True}}},
        )
        self.project = self.call("project.create", title="project")
        self.other = self.call("project.create", title="other")

    def call(self, action, *, scope=None, **fields):
        return self.app.dispatch({"action": action, **fields}, scope)

    def note(self, title="note", **fields):
        return self.call(
            "object.create",
            project_id=self.project["id"],
            kind="note",
            title=title,
            **fields,
        )

    def test_object_lifecycle_revision_merge_restore_and_scope(self):
        note = self.note()
        changed = self.call(
            "object.save", id=note["id"], expected_revision=1, title="changed"
        )
        self.assertEqual((changed["revision"], changed["title"]), (2, "changed"))
        merged = self.call(
            "object.save",
            id=note["id"],
            expected_revision=1,
            metadata={"tag": "merged"},
        )
        self.assertEqual(
            (merged["revision"], merged["title"], merged["metadata"]["tag"]),
            (3, "changed", "merged"),
        )
        restored = self.call(
            "object.restore", id=note["id"], revision=1, expected_revision=3
        )
        self.assertEqual((restored["revision"], restored["title"]), (4, "note"))
        with self.assertRaises(Problem) as caught:
            self.call(
                "object.save",
                scope=[self.other["id"]],
                id=note["id"],
                expected_revision=4,
                title="denied",
            )
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(self.app.get(note["id"])["revision"], 4)
        archived = self.call("object.archive", id=note["id"], expected_revision=4)
        self.assertTrue(archived["archived"])
        self.assertEqual(self.app.get(note["id"], revision=1)["title"], "note")

    def test_conflicting_edits_preserve_both_versions(self):
        note = self.note()
        self.call("object.save", id=note["id"], expected_revision=1, title="first")
        with self.assertRaises(Problem) as caught:
            self.call("object.save", id=note["id"], expected_revision=1, title="second")
        self.assertEqual(caught.exception.code, "conflict")
        self.assertIn("conflict_id", caught.exception.details)
        self.assertEqual(self.app.get(note["id"])["title"], "first")

    def test_project_feature_and_unfeature_are_explicit(self):
        note = self.note()
        current = self.app.get(self.project["id"])
        featured = self.call(
            "project.feature",
            project_id=self.project["id"],
            object_id=note["id"],
            expected_revision=current["revision"],
            featured=True,
        )
        self.assertIn(note["id"], featured["metadata"]["featured_objects"])
        cleared = self.call(
            "project.feature",
            project_id=self.project["id"],
            object_id=note["id"],
            expected_revision=featured["revision"],
            featured=False,
        )
        self.assertEqual(cleared["metadata"]["featured_objects"], [])
        with self.assertRaises(Problem):
            self.call(
                "project.feature",
                project_id=self.project["id"],
                object_id=note["id"],
                expected_revision=cleared["revision"],
                featured=1,
            )

    def test_project_initialization_failure_rolls_back_all_objects(self):
        before = self.app.store.objects()
        with (
            mock.patch(
                "research_partner.domains.manuscripts.workspace.initialize_output",
                side_effect=RuntimeError("stop"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.call("project.create", title="not committed")
        self.assertEqual(self.app.store.objects(), before)

    def test_annotation_update_is_bound_to_exact_object(self):
        note = self.note()
        other = self.note("second")
        annotation = self.call(
            "annotation.add", object_id=note["id"], revision=1, text="before"
        )
        ident = annotation["id"]
        updated = self.call(
            "annotation.update",
            id=ident,
            object_id=note["id"],
            text="after",
            status="resolved",
        )
        self.assertEqual(
            (updated[0]["text"], updated[0]["status"]), ("after", "resolved")
        )
        with self.assertRaises(Problem) as caught:
            self.call(
                "annotation.update",
                id=ident,
                object_id=other["id"],
                text="cross object",
            )
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(self.app.store.annotations(note["id"])[0]["text"], "after")

    def test_export_records_object_revision_and_preserves_response(self):
        note = self.note()
        result = self.call("object.export", id=note["id"], format="md")
        self.assertEqual(result["object"]["id"], note["id"])
        self.assertEqual(result["status"], "generated")
        self.assertEqual(result["asset"]["filename"], "document.md")
        self.assertEqual(result["provenance"]["source_sha256"], digest(note))
        self.assertEqual(len(self.app.store.export_records(note["id"])), 1)

    def test_task_controls_do_not_implicitly_start_runtime(self):
        task = self.call(
            "task.submit",
            project_id=self.project["id"],
            request="offline",
            provider_id="offline",
            output_kind="note",
            budget={"max_model_calls": 1, "timeout_seconds": 30},
        )
        guided = self.call("task.guide", id=task["id"], text="keep evidence")
        self.assertTrue(guided["guidance_saved"])
        with self.assertRaises(Problem) as caught:
            self.call("task.control", id=task["id"], operation="pause")
        self.assertEqual(
            (caught.exception.code, caught.exception.status),
            ("runtime_unavailable", 503),
        )
        self.assertEqual(self.app.store.task(task["id"])["status"], "queued")

    def test_budget_extension_rejects_boolean_call_count(self):
        task = self.call(
            "task.submit",
            project_id=self.project["id"],
            request="offline",
            provider_id="offline",
            output_kind="note",
            budget={"max_model_calls": 1, "timeout_seconds": 30},
        )
        self.app.store.task_update(task["id"], "paused")
        with self.assertRaises(Problem) as caught:
            self.call(
                "task.extend_budget",
                id=task["id"],
                approved=True,
                reason="explicit",
                additional_invocations=True,
            )
        self.assertEqual(caught.exception.code, "invalid")
        self.assertIsNone(self.app.store.setting("budget_extension:" + task["id"]))
        result = self.call(
            "task.extend_budget",
            id=task["id"],
            approved=True,
            reason="explicit",
            additional_invocations=1,
        )
        self.assertTrue(result["consumption_preserved"])
        self.assertFalse(result["automatically_resumed"])

    def test_settings_allowlist_and_owner_permission_are_unchanged(self):
        with self.assertRaises(Problem) as caught:
            self.call(
                "settings.update", scope=[self.project["id"]], key="domain", value={}
            )
        self.assertEqual(caught.exception.status, 403)
        with self.assertRaises(Problem) as caught:
            self.call("settings.update", key="providers", value={})
        self.assertEqual(caught.exception.status, 403)
        self.assertIsNone(self.app.store.setting("providers"))


if __name__ == "__main__":
    unittest.main()
