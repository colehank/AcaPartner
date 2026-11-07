# 后端开发与测试

后端要求 Python 3.12 或更新版本。当前测试依赖 POSIX 文件权限和 loopback HTTP，CI 覆盖 Linux、macOS 与 Python 3.12、3.14 的四种组合，不运行前端构建、科学计算环境或真实模型调用。

## 建立独立开发环境

在仓库根目录执行：

```sh
python3.12 -m venv /tmp/acapartner-backend-dev
. /tmp/acapartner-backend-dev/bin/activate
python -m pip install -e '.[dev]'
```

默认 `dependencies = []` 保持不变；`dev` 可选依赖固定为 `ruff==0.14.14` 和 `mypy==1.18.2`。测试使用标准库 `unittest`，不需要 pytest、Node.js、模型 SDK、真实账号或 API 密钥。

## 标准测试入口

从仓库根目录运行全部后端测试：

```sh
python -m unittest discover -s tests -t . -v
```

只运行本地启动和认证边界测试：

```sh
python -m unittest tests.integration.test_start_local tests.integration.test_http_auth tests.integration.test_local_accounts_http -v
```

`tests` 是可导入的测试包。共享 HTTP 环境放在 `tests/support/http_fixture.py`，其 mixin 不继承 `unittest.TestCase`，也不包含 `test_*` 方法。不要从另一个 `test_*.py` 模块导入测试类来复用 fixture，否则 `unittest` 会再次发现导入的测试类并重复执行用例。

测试的 workspace、SQLite 文件、账号、令牌和 HTTP 服务都在临时目录或随机 loopback 端口上创建。不要将测试切换为个人工作区，不要为测试注入真实凭据，也不要把外部服务可用性作为本地单元测试的前提。

## 静态检查与增量纳管

Ruff 的目标版本是 `py312`，基础规则配置为 `E4`、`E7`、`E9`、`F`。现有后端尚未全部满足该规则集合，因此 CI 分两层执行，而不是立即让全部历史风格问题阻塞开发。

全后端基础安全网检查语法及关键名称问题：

```sh
python -m ruff check --select E9,F63,F7,F82 src/research_partner tools tests
```

完整质量入口如下，CI 与本地共用相同的纳管清单和命令：

```sh
python tools/check_backend.py all
# 也可以分别执行 lint、format、types、test。
```

已纳管模块执行完整基础规则及格式门禁；精确清单在 `tools/check_backend.py` 的 `MAINTAINED_MODULES`。范围包括应用、Store、HTTP、渲染和 provider 主模块、全部本轮新增边界模块及测试，不扩展到所有历史领域文件。`TYPED_BOUNDARIES` 列出七个纯边界模块，使用 mypy 检查；`--follow-imports=skip` 明确不宣称历史动态业务代码已全部类型化。修改或新增后端模块时，先对相关文件运行：

```sh
python -m ruff check path/to/changed.py
python -m ruff format --check path/to/changed.py
```

逐个模块修复并验证后再加入 CI 清单；不要为绕过历史问题关闭未定义名称检查，不要全库格式化。纳管模块同时执行 `ruff format --check`；大型历史业务模块暂时只接受局部功能修改。CI 将 `ResourceWarning` 视为错误，以检查未关闭的文件、socket 和子进程句柄。

工作流只授予 `contents: read`，使用普通 `pull_request`，不使用 `pull_request_target`，也不读取仓库 secrets。GitHub Actions 固定到已核验的官方发布 SHA；升级时应再次核对官方 tag 对应的 SHA。

## 将可选运行时与后端测试隔离

普通后端测试不应安装或启动可选模型、渲染或科学运行时。确需开发这些功能时，使用单独的虚拟环境、独立临时 workspace 和不含真实凭据的配置；其依赖和端到端测试不要隐式混入上述默认入口。

`tools/start_local.py` 的正常启动使用 `--workbench-only`，不会启动 Runtime；启动测试会 mock Runtime，并验证待执行任务和已有预算不被消费。该工具的实际页面启动仍需要已构建的前端，因此不属于这个纯后端 CI 的运行步骤。后端启动测试自行构造临时前端资产，不依赖真实前端构建。

## 命令契约、诊断与运行时边界

- `commands.contract.validate_action_request` 是 HTTP、CLI 和应用分派共用的命令信封检查。`action` 必须是非空字符串；领域参数仍由各领域处理器校验。`TypedDict` 仅描述静态公共字段，不能代替运行时验证。未知的有效字符串命令仍返回 `not_implemented`，不自动纠正或重写命令。
- HTTP 未预期异常保持脱敏的 500 响应，并附带 `error_id`。`research_partner.execution.diagnostics` 日志记录相同编号、异常类型及末尾 24 个调用帧的模块、函数和行号；不记录异常文本、局部变量、源码行、请求内容或完整路径。宿主可以用标准库 logging 配置日志目的地。
- `Store.capture_file_results()` 管理单次命令中多个事务的文件同步结果。嵌套调用归入外层请求，并发请求按线程隔离；文件同步仍在提交后发生，其失败不回滚已提交数据。App 不再直接读写 Store 的私有线程状态。
- 公共分发没有 `tools.codex_thread_dispatch` 私有适配器，因此实验性 `app_server_dynamic` 路线明确不可用。状态查询将其标为不可用，图形任务配置预检和执行入口明确拒绝；普通任务仍可排队，但执行前会在预算预留之前停止，不启动模型、不自动回退到 CLI。已保存的回执核查逻辑保留。普通 Codex CLI 路线不受此限制。
- 渲染子进程的 stdout/stderr 共享默认 **4 MiB** 输出预算，每路仅保留 **12,000 bytes** 尾部；达到预算即失败。worker 的 Python 输出捕获使用同样预算，父进程另外限制绕过 Python 重定向的原始输出。超时、输出限额、非零退出和退出后管道仍被后代持有分别报告，清理不无限等待后代关闭管道。该机制不是恶意代码隔离沙箱，也不限制任意内存分配或后台文件写入。

## 领域边界与兼容性

### 应用命令

`App.dispatch()` 继续是 GUI、CLI 和代理的共同入口，负责命令信封与提交后文件结果收集。`commands/routing.py` 维护有序、惰性加载的路由，并保留两个鉴权阶段：专用领域先验证其项目/任务/租约；普通命令先执行公共写作用域检查，再交给领域处理器。精确路由必须先于对应前缀回退，例如稿件恢复、格式渲染、外部反馈和文献全文入口。不要将路由按字母排序或提前统一查询所有 `id`。

核心命令从 `_dispatch()` 中迁移到五个内聚模块：

- `commands/objects.py`：项目初始化、置顶及对象创建、保存、恢复、归档。
- `commands/reviews.py`：批注、审阅记录与依赖采用；批注更新通过 Store 的公开 API 持久化。
- `commands/assets.py`：资产检查/导入、脚本授权及成果导出。
- `commands/tasks.py`：已有任务提交和明确控制，保留预算、租约与候选修订的原有规则。
- `commands/workspace.py`：周期、文献、扩展、设置与备份的领域协调。

`commands.contract.COMMAND_FIELDS` 为本次迁移的核心命令提供必填字段与基本类型校验，未知扩展字段不被裁剪。其他专门领域仍在自己的入口执行细化校验。来源、修订、权限和科学有效性不能仅用字段类型推导。

### 事务内存储策略

`storage/policies.py` 通过公开的 `ObjectPolicyStore` Protocol 读取对象与引用，承载文章准备边界、稿件格式、图形布局、成员快照和稿件来源特性策略。`Store.create()` / `save()` 在原写事务、原写入前位置调用统一策略清单；策略复用传入的连接，不新开连接或在事务外预检后直接写入。已有的 Store 校验方法保留兼容代理。

资产归属清理、SQLite 提交/回滚、修订三方合并、任务执行租约和提交后文件同步仍由 Store 管理，不随领域拆分搬离原事务。`Store.update_annotation()` 将批注更新与其事件放在同一事务，必须同时匹配批注和对象身份。

### 数据与协议

`contracts/__init__.py` 描述研究对象、任务载荷/状态/结果、权限上下文及核心请求类型，并用于 App、Store、HTTP 的公开边界注解。开放的正文、元数据和领域结果保留 JSON 扩展字段；这些 TypedDict 不是完整的业务 schema，也不自动执行运行时校验。

`http/boundary.py` 只拥有请求体校验和安全响应编码，不拥有凭据、会话和业务路由。无效长度、短请求体、非法 UTF-8/JSON 和非对象 JSON 返回受控参数错误，不回显原始请求。Origin、跨站、CSRF、媒体类型和长度检查顺序保留。

`rendering/contract.py` 独立于 App、Store 和科学库，定义 worker 请求、成功/失败结果及进程记录。父进程和 worker 都校验公共信封，非法操作或字段返回 `invalid`；正常渲染器内的业务异常保持其原有错误类型。直接脚本启动和便携 runtime 均包含此辅助模块。

### 四阶段验收范围

第一阶段建立可重复测试和跨平台门禁；第二阶段修复已确认的入口、依赖、输出与诊断问题；第三阶段完成上述纳管模块的分批风格治理；第四阶段完成应用路由、对象策略、HTTP/渲染边界和公共数据契约的职责拆分。纯格式化使用独立提交，并核对 AST 等价；领域处理器初始迁移也逐项核对业务 AST。

上述四阶段治理没有更换框架、数据库格式或科学运行时，也没有承诺全库静态类型化或真实科学/模型环境验收。其后的仓库结构重构将 Python 模块迁入 `src/research_partner/` 的职责子包，并分离前端源码、构建成品与运行资源，详见[仓库结构](../architecture/repository-layout.md)。后续业务模块按相同的测试、评审与增量纳管流程继续维护。

## 个人配置不进入提交

个人工具配置、图谱索引与缓存只写入本地 `.git/info/exclude` 的精确路径，不为个人环境修改共享 `.gitignore`，也不提交 `.claude/settings.local.json`、真实配置、令牌、账号文件或工作区数据库。不要使用会掩盖团队配置的整个目录通配忽略规则。

提交前检查：

```sh
git diff --check
git status --short
```

确认变更只包含团队需要的源码、测试、开发工具配置、工作流和文档。CI 不负责部署、发布或启动用户的本地工作区。
