# 公开开发预览包

此包包含 Research Partner 的完整生产 Python 模块、React 工作桌源码和预构建、前端锁文件、可再分发字体及其许可、插件/扩展源码、公开产品书与完整 C/S 范围，以及一组自包含测试。仓库名为 AcaPartner，Python 包名仍为 research-partner。

## 本次新增

- 工作桌首次进入的可跳过引导，按实际模块分步介绍；固定“使用引导”入口可重新打开。
- 每步说明目标、真实入口、可选练习及保存/资源边界；只有明确“打开此模块”才导航。
- 一条本地启动入口，首次创建私有数据目录及内部凭据，由用户注册账号，不要求复制 token。
- 公开发行的正向文件清单、哈希 manifest、完整前端源码与构建，以及 bundled dependencies 许可。

引导不代为填充论文、提交意见、批准脚本、开始 Agent、重算或编译。默认启动为 workbench-only，不消费历史任务队列。

## 范围与验证

自包含测试针对引导导航/键盘/存储失败/重开、认证与草稿保护、私有启动配置以及公开打包的边界。它们是工程检查，不是完整科研流程、独立身份签署、科学质量或指定设备验收。完整核心协作和全部后续阶段尚未签收，Windows 原生与参考硬件等原条件仍待验证。

本地启动依赖 POSIX 权限与锁；Windows 使用 WSL2。PDF、科学绘图、Snakemake、模型服务和特定格式出口需单独配置。完整产品范围见产品书及 C/S 文件；历史场景名称只为保留规范，不随包提供对应研究资料或工作空间。

## 不包含的材料

用户项目/数据库/原始科研资料、模型和账号凭据、本机 runtime inventory、旧开发 Git 历史、私有父账、接续流水及正式验收归档均不在发行包。规范的原始输入/评审来源档案仍在原私有现场；公开产品书和 C/S 不声称等于该现场完整判据归档。部分历史依赖本机资料的集成测试与控制脚本未随包发布。

`distribution-manifest.json` 对发行包中的每个文件记录 SHA-256。可通过现有离线安装器验证并安装到新空目录：

```sh
python3 tools/install.py research-partner.tar.gz --target /your/apps/acapartner-preview
cd /your/apps/acapartner-preview
python3 tools/start_local.py
```

也可在完整源码仓库构建前端后生成同一公开包：

```sh
python3 tools/build.py --output dist
```

运行数据请保存在源码目录之外，升级前备份私有数据。不要用发行包覆盖既有资料目录。

## 结构与发行验收

Python 使用 `src/research_partner/` 职责分包；React 源码在 `frontend/workdesk/`，旧静态页面在 `frontend/legacy/`。构建输出位于 `build/frontend/workdesk/`，仅在打包时装配为 Python 安装包的 `resources/web/`；字体与 Agent 执行材料也由统一资源入口定位。详细边界见[仓库结构](../architecture/repository-layout.md)。

构建前端后，可用临时目录执行完整离线源码包与标准 Python 安装验收：

```sh
python -m pip install build==1.3.0 setuptools==80.9.0 wheel==0.45.1
python tools/check_release.py --wheel
```

该命令检查确定性源码归档、逐文件摘要、包内测试、CLI、只读启动计划、sdist 离线重建 wheel，以及无应用依赖的隔离 wheel 安装、页面 URL 和 HTTP 认证边界。默认不带 `--wheel` 时仅运行源码发行验收，不需要额外打包工具。所有工作区与安装目录均为临时合成环境，不访问真实数据或模型，也不发布产物。

CI 分开执行纯后端四组平台/解释器检查、前端构建与隔离浏览器测试，以及四组源码包/wheel 交付验收。只做验证，不部署或自动发布。
