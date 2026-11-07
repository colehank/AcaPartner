"""集中定位安装包资源、独立 worker 与源码工作区。"""

from pathlib import Path


def package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def source_root() -> Path:
    package = package_root()
    return package.parent.parent if package.parent.name == "src" else package.parent


def resource_path(*parts: str) -> Path:
    return Path(__file__).resolve().parent.joinpath(*parts)


def module_file(module: str) -> Path:
    if not module.startswith("research_partner."):
        raise ValueError("只能定位本应用的模块")
    return package_root().joinpath(*module.split(".")[1:]).with_suffix(".py")


def web_directory(interface: str) -> Path:
    if interface not in {"workdesk", "legacy"}:
        raise ValueError("页面类型无效")
    root = source_root()
    if (root / "src/research_partner/__init__.py").is_file():
        source = (
            root / "build/frontend/workdesk"
            if interface == "workdesk"
            else root / "frontend/legacy"
        )
        # 已有源码构建必须优先；缺文件由启动器或 HTTP 明确拒绝，不读旧成品。
        if source.exists():
            return source
    return resource_path("web", interface)
