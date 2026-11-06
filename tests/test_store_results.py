"""提交后同步结果的作用域不改变数据库事务语义。"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from research_partner.app import App
from research_partner.store import Store


class StoreFileResults(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "workspace")

    def commit(self, project):
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO kv VALUES (?, ?)", (project, '"committed"')
            )
            connection.project_sync_ids.add(project)

    def test_collects_multiple_commits_and_starts_each_scope_empty(self):
        with mock.patch(
            "research_partner.project_files.sync_after_commit",
            side_effect=lambda _, ids: {
                key: {"status": "repair_required"} for key in ids
            },
        ):
            with self.store.capture_file_results() as results:
                self.commit("first")
                self.commit("second")
            self.assertEqual(set(results), {"first", "second"})
            self.assertEqual(self.store.setting("first"), "committed")
            with self.store.capture_file_results() as following:
                self.assertEqual(following, {})

    def test_nested_capture_merges_into_outer_scope(self):
        with mock.patch(
            "research_partner.project_files.sync_after_commit",
            return_value={"inner": {"status": "repair_required"}},
        ):
            with self.store.capture_file_results() as outer:
                with self.store.capture_file_results() as inner:
                    self.commit("inner")
                self.assertEqual(outer, inner)
                self.assertIsNot(outer, inner)

    def test_failed_dispatch_clears_its_scope_but_keeps_committed_data(self):
        with mock.patch(
            "research_partner.project_files.sync_after_commit",
            return_value={"first": {"status": "repair_required"}},
        ):
            with self.assertRaises(RuntimeError):
                with self.store.capture_file_results():
                    self.commit("first")
                    raise RuntimeError("after commit")
            with self.store.capture_file_results() as following:
                self.assertEqual(following, {})
        self.assertEqual(self.store.setting("first"), "committed")

    def test_rollback_does_not_sync_or_report_uncommitted_files(self):
        with mock.patch("research_partner.project_files.sync_after_commit") as sync:
            with self.store.capture_file_results() as results:
                with self.assertRaises(RuntimeError):
                    with self.store.transaction() as connection:
                        connection.execute("INSERT INTO kv VALUES ('rollback', '1')")
                        connection.project_sync_ids.add("rollback")
                        raise RuntimeError("rollback")
            sync.assert_not_called()
            self.assertEqual(results, {})
            self.assertIsNone(self.store.setting("rollback"))

    def test_capture_is_thread_local(self):
        barrier = threading.Barrier(2)

        def capture(project):
            with self.store.capture_file_results() as results:
                barrier.wait(timeout=5)
                self.commit(project)
                barrier.wait(timeout=5)
            return results

        with (
            mock.patch(
                "research_partner.project_files.sync_after_commit",
                side_effect=lambda _, ids: {key: {"status": "synced"} for key in ids},
            ),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first = pool.submit(capture, "first")
            second = pool.submit(capture, "second")
            self.assertEqual(set(first.result(timeout=10)), {"first"})
            self.assertEqual(set(second.result(timeout=10)), {"second"})

    def test_app_reports_only_this_dispatch_repairs(self):
        app = App(Path(self.tmp.name) / "app")
        with mock.patch(
            "research_partner.project_files.sync_after_commit",
            return_value={"project": {"status": "repair_required"}},
        ):
            first = app.dispatch({"action": "project.create", "title": "first"})
        self.assertEqual(first["project_files"]["project"]["status"], "repair_required")
        with mock.patch(
            "research_partner.project_files.sync_after_commit", return_value={}
        ):
            second = app.dispatch({"action": "project.create", "title": "second"})
        self.assertNotIn("project_files", second)


if __name__ == "__main__":
    unittest.main()
