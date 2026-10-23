# 本地安装与首次使用

Research Partner 的本地工作桌运行在你的电脑上。基本启动需要 **Python 3.12 或更新版本**，以及产品包内已构建的前端。当前后端使用 POSIX 文件权限与文件锁，支持 Linux、macOS；Windows 请在 WSL2 的 Linux 文件系统中运行。

## 获取与启动

下载并解压完整产品包，或获取本仓库。在包含 `pyproject.toml` 的产品根目录运行：

```sh
python3 tools/start_local.py
```

终端确认启动后，在浏览器打开 [http://127.0.0.1:8877/](http://127.0.0.1:8877/)。保持这个终端运行；结束时按 `Ctrl+C`。再次运行同一命令会打开原来的资料。

此入口直接使用产品源码，基本工作桌不需要额外 Python 依赖。也可以先将 Python 包安装在独立虚拟环境，再用该环境启动：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python tools/start_local.py
```

安装命令是你主动执行的准备步骤。启动入口本身不会安装依赖、下载工具或配置模型服务。

如果终端提示前端构建缺失，请使用包含 `research_partner/web/workdesk/index.html` 和配套 `assets/` 的完整产品包。开发者从源码构建时，另外准备 Node.js 与 npm，保留仓库的 `frontend/package-lock.json`，在产品根目录运行：

```sh
npm --prefix frontend ci
npm --prefix frontend run build -- --configLoader runner
python3 tools/start_local.py
```

构建工具的版本与依赖约束以 `frontend/package.json`、锁文件为准。完整包已含构建时，不需要 Node.js 或 npm。修改前端源码后需重新构建，Python 包安装不会代为编译前端。

## 第一次注册与页面引导

首次进入页面时创建一个本地账号，之后使用相同账号密码登录。账号名为 3–32 位字母、数字、下划线、点或短横线，密码为 8–128 个字符。每个本地实例只开放一次所有者注册；已有账号时直接登录。

登录后，跟随页面中的入门引导认识项目、稿件、资料与意见入口。先建立自己的研究项目，再加入授权使用的资料、整理正文和笔记。需要 Agent 处理、科学计算或导出排版时，按页面显示的配置、权限与预算要求继续。

本地账号不需要 OpenAI、GitHub 或其他外站账号。浏览器登录使用账号密码，内部所有者 token 由启动入口随机创建，你无需输入或复制它。

## 数据位置与启动参数

默认数据目录：

| 系统 | 数据目录 |
| --- | --- |
| Linux / WSL2 | `$XDG_DATA_HOME/research-partner`；未设置绝对路径时为 `~/.local/share/research-partner` |
| macOS | `~/Library/Application Support/Research Partner` |

目录内的 `workspace/` 保存研究资料，`config.json` 保存实例配置，`auth/` 保存内部所有者凭据与本地账号密码哈希。账号凭据放在工作区之外。新目录为 `0700`，新配置与凭据文件为 `0600`；请使用能落实这些权限的本地文件系统。

```sh
# 指定独立资料目录与端口；路径含空格时加引号
python3 tools/start_local.py --data-dir "$HOME/my-research-partner" --port 8878

# 只读检查：不创建目录，不启动服务
python3 tools/start_local.py --plan

# 初始化私有目录与工作区后退出，不启动服务
python3 tools/start_local.py --prepare

python3 tools/start_local.py --help
```

重新启动时须使用同一个 `--data-dir`。已有配置、账号、token 和预算记录会保留。已有目录权限过宽、配置缺少登录字段或凭据损坏时，入口会报错并保留原件；请检查所选目录、手动修正权限或从私人备份恢复。不要通过删除账号或 token 来处理普通登录问题；token 更换会影响已有授权。

备份时先正常停止服务，再完整复制数据目录并保留私有权限；包含账号或模型配置的备份也应私有保存。不要把运行数据目录提交到公开仓库。当前版本没有在线密码找回或多用户注册流程。

## 需要单独配置的能力

本地入口始终以 **workbench-only** 模式启动：不创建任务运行器，不恢复旧任务，不执行模型调用。可以编辑、管理已有资料，并在所需工具可用且权限允许时主动导出；任务执行需要另行配置和明确启用。

| 能力 | 额外条件 |
| --- | --- |
| 中文稿件的 LaTeX/PDF 排版 | 可用的 XeLaTeX、稿件所需字体与宏包（如 `fontspec`、`xeCJK`）；在 `config.json` 的 `rendering.latex` 指定编译器 |
| 数值图与代码绘图 | 已安装相应科学依赖的 Python 环境；在 `rendering.scientific_python` 指定解释器。常用绘图需要 NumPy、Matplotlib，具体脚本可能需要其他依赖 |
| DOCX / PPTX 生成及部分格式转换 | `rendering.documents_python` 所指环境内的 `python-docx`、`python-pptx`；涉及 Office 格式转换时另需 LibreOffice 等对应工具 |
| 数据生成 / 依赖重做 | 符合产品运行时锁定记录的 Snakemake 环境、数据与代码授权、任务执行器及相应预算；只有安装 Snakemake 不等于运行时已就绪 |
| Agent 修订、模型协作 | 已配置的模型 provider、所需本地客户端或凭据、明确权限和预算，以及另行启用的执行器；只写入 provider 配置不会让本入口自动执行队列 |

可按需编辑私有的 `config.json` 后重启；保留 `workdesk_w1a`、`access_token_file` 和 `local_accounts_file`。可选工具缺失时，相应功能会显示不可用或返回具体错误；基本启动不会代为安装这些工具。更多操作参见 [使用说明](user-guide.md)。

## 常见启动问题

- **端口被占用**：用 `--port 8878` 等其他本地端口启动，不要结束来源不明的已有进程。
- **前端缺失或页面资源不全**：使用完整构建包，或按上面的源码构建命令生成前端后再启动。
- **权限检查失败**：检查是否把数据放在不支持 POSIX 权限的共享盘或 Windows 挂载盘；WSL2 中优先使用 Linux home 下的目录。入口不会自动更改已有文件权限。
- **看到一个空的新实例**：核对启动时的 `data_dir`，用原来的目录重新运行。不同数据目录各有独立账号与资料。
- **提交的 Agent / 生成任务没有执行**：本地入口关闭任务运行器。这是工作桌模式的边界；工具、模型及执行权限需另行准备。

服务固定监听 `127.0.0.1`。本入口没有公网监听、远程部署或自动升级选项；需要远程使用时，应另行设计认证、HTTPS 与访问范围。
