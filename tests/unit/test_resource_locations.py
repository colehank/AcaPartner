"""源码构建、源码发行和 wheel 的页面选择顺序必须一致。"""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from research_partner.resources import web_directory


class WebResourceLocations(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / "src/research_partner"
        self.package.mkdir(parents=True)
        (self.package / "__init__.py").write_text("")
        for interface in ("workdesk", "legacy"):
            packaged = self.package / "resources/web" / interface
            packaged.mkdir(parents=True)
            (packaged / "index.html").write_text("packaged")
        source = mock.patch(
            "research_partner.resources.source_root", return_value=self.root
        )
        resource = mock.patch(
            "research_partner.resources.resource_path",
            side_effect=lambda *parts: self.package.joinpath("resources", *parts),
        )
        source.start()
        resource.start()
        self.addCleanup(source.stop)
        self.addCleanup(resource.stop)

    def test_rebuilt_source_wins_and_incomplete_build_never_falls_back(self):
        built = self.root / "build/frontend/workdesk"
        built.mkdir(parents=True)
        (built / "index.html").write_text("rebuilt")
        self.assertEqual(web_directory("workdesk"), built)
        (built / "index.html").unlink()
        self.assertEqual(web_directory("workdesk"), built)
        self.assertFalse((web_directory("workdesk") / "index.html").exists())

    def test_source_legacy_wins_but_offline_package_can_use_assembled_pages(self):
        for interface in ("workdesk", "legacy"):
            self.assertEqual(
                web_directory(interface), self.package / "resources/web" / interface
            )
        legacy = self.root / "frontend/legacy"
        legacy.mkdir(parents=True)
        (legacy / "index.html").write_text("source legacy")
        self.assertEqual(web_directory("legacy"), legacy)

    def test_wheel_does_not_read_unrelated_build_or_frontend_directories(self):
        (self.package / "__init__.py").unlink()
        (self.root / "build/frontend/workdesk").mkdir(parents=True)
        (self.root / "frontend/legacy").mkdir(parents=True)
        for interface in ("workdesk", "legacy"):
            self.assertEqual(
                web_directory(interface), self.package / "resources/web" / interface
            )


if __name__ == "__main__":
    unittest.main()
