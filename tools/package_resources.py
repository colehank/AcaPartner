"""setuptools 钩子：只向构建目录装配 web 资源，不触发 Node 或网络。"""

from pathlib import Path
import shutil

from setuptools.build_meta import (
    build_editable as build_editable,
    build_sdist as build_sdist,
    build_wheel as build_wheel,
    get_requires_for_build_editable as get_requires_for_build_editable,
    get_requires_for_build_sdist as get_requires_for_build_sdist,
    get_requires_for_build_wheel as get_requires_for_build_wheel,
    prepare_metadata_for_build_editable as prepare_metadata_for_build_editable,
    prepare_metadata_for_build_wheel as prepare_metadata_for_build_wheel,
)
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

from tools.build import WEB_RESOURCES, distributed_source, distribution_inputs
from tools.start_local import check_frontend


ROOT = Path(__file__).resolve().parents[1]


def resource_inputs(root):
    inputs = distribution_inputs(root)
    check_frontend(root, included=set(inputs.values()))
    if f"{WEB_RESOURCES}/legacy/index.html" not in inputs:
        raise ValueError(
            "Missing legacy frontend: frontend/legacy/index.html or assembled resources/web/legacy/index.html"
        )
    return {
        name: source
        for name, source in inputs.items()
        if name.startswith("src/research_partner/resources/")
    }


class AssembleBuildPy(build_py):
    """普通 wheel 需要完整静态资源；editable 后端开发不要求编译前端。"""

    def find_data_files(self, package, src_dir):
        return [
            name
            for name in super().find_data_files(package, src_dir)
            if distributed_source(Path(name).resolve().relative_to(ROOT).as_posix())
        ]

    def run(self):
        if self.editable_mode:
            return super().run()
        inputs = resource_inputs(ROOT)
        super().run()
        target = Path(self.build_lib) / "research_partner/resources"
        if target.is_symlink():
            raise ValueError("Resource build output must not be a symlink")
        if target.exists():
            # 仅清理已检查的生成目录，避免旧构建的已删除资源混入新 wheel。
            if any(path.is_symlink() for path in target.rglob("*")):
                raise ValueError("Resource build output must not contain symlinks")
            shutil.rmtree(target)
        for name, source in inputs.items():
            destination = Path(self.build_lib) / Path(name).relative_to("src")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, destination)


class AssembleSdist(sdist):
    """PEP 517 源码包沿用产品白名单，并带离线 wheel 重建所需的已装配资源。"""

    def make_release_tree(self, base_dir, files):
        resource_inputs(ROOT)
        destination = Path(base_dir)
        destination.mkdir(parents=True, exist_ok=True)
        for name, source in distribution_inputs(ROOT).items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, target)
        self.distribution.metadata.write_pkg_info(base_dir)
