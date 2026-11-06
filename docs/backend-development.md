# 后端开发与测试

后端要求 Python 3.12 或更新版本。当前测试依赖 POSIX 文件权限和 loopback HTTP，CI 覆盖 Linux、macOS 与 Python 3.12、3.14 的四种组合，不运行前端构建、科学计算环境或真实模型调用。

## 建立独立开发环境

在仓库根目录执行：

```sh
python3.12 -m venv /tmp/acapartner-backend-dev
. /tmp/acapartner-backend-dev/bin/activate
python -m pip install -e '.[dev]'
```

默认 `dependencies = []` 保持不变；`dev` 可选依赖仅安装固定版本 `ruff==0.14.14`。测试使用标准库 `unittest`，不需要 pytest、Node.js、模型 SDK、真实账号或 API 密钥。

## 标准测试入口

从仓库根目录运行全部后端测试：

```sh
python -m unittest discover -s tests -t . -v
```

只运行本地启动和认证边界测试：

```sh
python -m unittest tests.test_start_local tests.test_http_auth tests.test_local_accounts_http -v
```

`tests` 是可导入的测试包。共享 HTTP 环境放在 `tests/http_fixture.py`，其 mixin 不继承 `unittest.TestCase`，也不包含 `test_*` 方法。不要从另一个 `test_*.py` 模块导入测试类来复用 fixture，否则 `unittest` 会再次发现导入的测试类并重复执行用例。

测试的 workspace、SQLite 文件、账号、令牌和 HTTP 服务都在临时目录或随机 loopback 端口上创建。不要将测试切换为个人工作区，不要为测试注入真实凭据，也不要把外部服务可用性作为本地单元测试的前提。

## 静态检查与增量纳管

Ruff 的目标版本是 `py312`，基础规则配置为 `E4`、`E7`、`E9`、`F`。现有后端尚未全部满足该规则集合，因此 CI 分两层执行，而不是立即让全部历史风格问题阻塞开发。

全后端基础安全网检查语法及关键名称问题：

```sh
python -m ruff check --select E9,F63,F7,F82 research_partner tools tests
```

已纳管模块执行完整基础规则；其精确清单维护在 `.github/workflows/backend.yml` 的 `Check maintained backend modules` 步骤中。修改或新增后端模块时，先对相关文件运行：

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

- `action_contract.validate_action_request` 是 HTTP、CLI 和应用分派共用的命令信封检查。`action` 必须是非空字符串；领域参数仍由各领域处理器校验。`TypedDict` 仅描述静态公共字段，不能代替运行时验证。未知的有效字符串命令仍返回 `not_implemented`，不自动纠正或重写命令。
- HTTP 未预期异常保持脱敏的 500 响应，并附带 `error_id`。`research_partner.diagnostics` 日志记录相同编号、异常类型及末尾 24 个调用帧的模块、函数和行号；不记录异常文本、局部变量、源码行、请求内容或完整路径。宿主可以用标准库 logging 配置日志目的地。
- `Store.capture_file_results()` 管理单次命令中多个事务的文件同步结果。嵌套调用归入外层请求，并发请求按线程隔离；文件同步仍在提交后发生，其失败不回滚已提交数据。App 不再直接读写 Store 的私有线程状态。
- 公共分发没有 `tools.codex_thread_dispatch` 私有适配器，因此实验性 `app_server_dynamic` 路线明确不可用。状态查询将其标为不可用，图形任务配置预检和执行入口明确拒绝；普通任务仍可排队，但执行前会在预算预留之前停止，不启动模型、不自动回退到 CLI。已保存的回执核查逻辑保留。普通 Codex CLI 路线不受此限制。
- 渲染子进程的 stdout/stderr 共享默认 **4 MiB** 输出预算，每路仅保留 **12,000 bytes** 尾部；达到预算即失败。worker 的 Python 输出捕获使用同样预算，父进程另外限制绕过 Python 重定向的原始输出。超时、输出限额、非零退出和退出后管道仍被后代持有分别报告，清理不无限等待后代关闭管道。该机制不是恶意代码隔离沙箱，也不限制任意内存分配或后台文件写入。

本轮只建立上述清晰边界，不整体拆分 App/Store，不迁移 HTTP 框架、数据库层或科学运行时。剩余大型领域处理器和历史格式债应按模块补测试后逐步收敛，避免把风格变更与权限、事务规则的大规模重写混在一起。

## 个人配置不进入 PR

个人工具配置、图谱索引与缓存只写入本地 `.git/info/exclude` 的精确路径，不为个人环境修改共享 `.gitignore`，也不提交 `.claude/settings.local.json`、真实配置、令牌、账号文件或工作区数据库。不要使用会掩盖团队配置的整个目录通配忽略规则。

提交前检查：

```sh
git diff --check
git status --short
```

确认变更只包含团队需要的源码、测试、开发工具配置、工作流和文档。CI 不负责部署、发布或启动用户的本地工作区。
