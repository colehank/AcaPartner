# 仓库结构与开发入口

## 目录职责

本仓库同时保存应用源码、前端开发工程和可分发运行资源；构建产物不作为手工维护的源码。

| 路径 | 职责 |
| --- | --- |
| `src/research_partner/` | Python 应用源码，根层仅保留版本、CLI 和应用装配入口 |
| `frontend/workdesk/` | 当前 React/TypeScript 工作桌源码、锁文件与浏览器测试 |
| `frontend/legacy/` | 保留的静态界面源码；不等同于 React 的编译结果 |
| `build/frontend/workdesk/` | Vite 生成页面，不提交源码版本控制 |
| `integrations/extensions/` | 在应用中注册并按版本授权的功能扩展 |
| `integrations/codex/` | 外部 Codex/MCP 客户端集成，独立分发入口保持自包含 |
| `environments/` | 可选科学运行时的输入清单及锁文件，不是默认应用依赖 |
| `tests/unit/` | 契约与局部机制测试 |
| `tests/integration/` | 临时 SQLite、HTTP 和 CLI 的集成回归 |
| `tests/packaging/` | 冻结、安装、目录边界与发行完整性测试 |
| `tests/support/` | 不包含测试方法的共享 fixture |
| `tools/` | 启动、质量检查、构建、安装和交付验证 |
| `docs/user/` | 用户指南与快速开始 |
| `docs/development/` | 开发环境与质量门禁 |
| `docs/release/` | 交付、安装和发布说明 |
| `docs/product/` | 保留的产品范围与验收定义 |

## Python 包边界

- `app.py` 是公共应用协调入口，`commands/` 维护有序命令路由和核心命令协调。
- `domains/` 按稿件、图形、文献、生成、协作、工作区和证据归属业务模块。跨领域协作仍使用原有明确接口，不因为目录变化改写任务流程。
- `storage/` 拥有 SQLite 连接、事务、修订、租约和持久化策略；目录迁移不拆散原事务。
- `http/` 拥有 HTTP 服务、会话与协议；共享凭据文件校验位于 `security/`，领域代码不反向依赖 HTTP 传输。
- `execution/` 拥有执行协调、远程执行、预算和恢复支持；`providers/` 拥有提供者适配。
- `rendering/` 拥有成果导出、独立 worker 与跨进程契约，科学和 Office 依赖继续只在相应运行环境加载。
- `contracts/` 只描述跨边界的公共结构，不能替代运行时验证。
- `packaging/` 拥有运行能力与发行完整性校验；预检不导入目标发行代码。
- 子包 `__init__.py` 保持轻量，不隐式启动服务、模型、数据库或科学运行时。

本次调整的是文件归属和明确的资源边界，不宣称历史业务依赖已经成为完全无环的分层架构。已有领域间的延迟调用继续保留，不能为了消除静态边而改变权限或事务语义。

## 随包资源

`src/research_partner/resources/` 是运行资源的唯一归属：

- `fonts/`：固定字体及原许可证，参与稿件字体摘要校验。
- `agent_runtime/`：复制到独立 Agent 实例的 Python/JavaScript 脚本、插件和策略文本；不是桌面原生 UI，也不包含已安装的 Node/DSH 环境或真实凭据。
- `runtime-features.json`：该代码版本明确声明的运行能力。
- `web/`：只在 wheel 或离线源码包构建时装配的页面成品；开发源码树不生成第二份页面源码。

应用通过 `research_partner.resources` 定位上述资源、独立 worker 和页面，不依赖各业务文件所在目录的偶然邻接关系。

## 前端与安装包的关系

开发构建：

```sh
npm --prefix frontend/workdesk ci
npm --prefix frontend/workdesk run build -- --configLoader runner
```

Vite 输出 `build/frontend/workdesk/`。源码启动优先读取该成品以及 `frontend/legacy/`；已有构建目录不完整时明确失败，不静默切回旧页面。打包工具将它们分别装配为安装包里的 `resources/web/workdesk/` 和 `resources/web/legacy/`。离线源码包在没有开发构建目录时读取已装配页面；wheel 只读取包内页面。

`workdesk_w1a: true` 继续选择 React 工作桌。关闭时保留旧首页与既有静态资源 URL，目录名变化不改变公开页面地址。旧界面当前是兼容实现，不随本次目录迁移删除；退役需另行核对用户配置、入口和使用情况。

## 安装与开发

采用标准 `src/` 布局后，直接在仓库根执行 `python -m research_partner` 之前应安装应用：

```sh
python -m pip install -e '.[dev]'
python tools/check_backend.py all
```

`tools/start_local.py` 和统一质量入口会显式定位当前克隆的 `src/`，不依赖偶然从工作目录导入旧平铺包。安装发行包后可直接运行 `research-partner`，无需 Node。仅编辑 Python 的环境允许 editable 安装时没有前端成品；普通 wheel 和离线源码发行包则必须具有完整页面，缺失时明确失败，不偷偷下载或执行 npm。

内部 Python 模块改用新的分包路径；CLI、HTTP 命令、数据库与工作区格式保持。根包的 `App` 模块入口仍为 `research_partner.app`。未承诺把所有旧私有模块路径永久保留为空壳。

## 构建与冻结

`python tools/build.py --output dist` 生成离线源码包。源码白名单、生成页面输入和最终归档路径分别核对；冻结时必须绑定实际参与构建的前端成品，不能仅冻结 TypeScript 而放过被替换的 JavaScript。

`distribution-manifest.json` 由构建器生成在发行包中，记录最终文件摘要及输入映射。仓库根目录不维护一份会过期的发行快照。字体、许可证、Agent 策略、便携渲染 helper 与源码同样参与完整性校验。

构建结果、egg-info 与本机工具缓存不提交。本克隆的个人工具与缓存规则维护在 `.git/info/exclude`，不修改共享 `.gitignore` 来迁就个人环境。
