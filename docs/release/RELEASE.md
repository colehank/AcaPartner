# 开发预览与发布

默认入口打开统一科研工作台。兼容用静态资源保留在 `frontend/legacy/`。

## 生成安装包

先按 README 安装前端依赖并构建，再运行 `python3 tools/build.py --output dist`。工具使用公开文件正向清单收集 Python 模块、当前前端源码/公共许可、预构建、当前文档和自包含测试，生成带 SHA-256 的 manifest。仅在本机生成，不自动发布或上传。

安装器入口：`python3 tools/install.py dist/research-partner.tar.gz --target /空目录`；安装后运行 `python3 tools/start_local.py`。默认工作桌模式不启动任务执行器或消费旧队列。源码升级和旧界面删除均不代替私有资料备份或格式迁移。

## 范围

使用与实现入口见 [当前指南](../workbench-guide.md)、[产品文档](../product/README.md)与[文稿接入](../architecture/document-adapters.md)。原始研究数据、账号和凭据、本机运行台账、私有输入、临时验收输出不进入安装包。

正式分发前仍须核对实际包含依赖的许可证和支持范围；主项目 MIT 不重新授权 SuperDoc 的 AGPL 部分或必需的专有 DOCX 引擎。当前为本机开发集成，生成安装包不等于获得闭源再分发或生产许可。

## 源码包与 wheel 验收

Python 使用 `src/research_partner/` 职责分包；React 源码在 `frontend/workdesk/`，旧静态页面在 `frontend/legacy/`。构建输出位于 `build/frontend/workdesk/`，仅在打包时装配为 Python 安装包的 `resources/web/`；字体与 Agent 执行材料也由统一资源入口定位。详细边界见[仓库结构](../architecture/repository-layout.md)。

构建前端后，可用临时目录执行完整离线源码包与标准 Python 安装验收：

```sh
python -m pip install build==1.3.0 setuptools==80.9.0 wheel==0.45.1
python tools/check_release.py --wheel
```

该命令检查确定性源码归档、逐文件摘要、包内测试、CLI、只读启动计划、sdist 离线重建 wheel，以及无应用依赖的隔离 wheel 安装、页面 URL 和 HTTP 认证边界。默认不带 `--wheel` 时仅运行源码发行验收，不需要额外打包工具。所有工作区与安装目录均为临时合成环境，不访问真实数据或模型，也不发布产物。

CI 分开执行纯后端四组平台/解释器检查、前端构建与隔离浏览器测试，以及四组源码包/wheel 交付验收。只做验证，不部署或自动发布。
