# 文稿与当前科研工作台

## 当前选择

首页 `/` 与 `/workdesk/editors.html` 使用 `frontend/src/workbench/main.tsx`。仅构建这一工作台；旧版工作桌、独立文稿试用页和浏览器模拟原型已移除。共享视觉样式位于 `frontend/src/workbench/theme/`。

| 能力 | 实现与边界 |
| --- | --- |
| DOCX | SuperDoc 2.28.0 / React 2.23.0，必需 DOCX Engine 0.27.0；编辑、阅读、批注和修订；整个栈并非完全开源 |
| 应用文件菜单 | Radix Dropdown Menu 2.2.1；只管理打开、保存、下载、主源和恢复 |
| 树节点菜单 | Radix Context Menu 2.4.1；按节点类型提供复制、新建、笔记重命名和可恢复删除 |
| LaTeX | CodeMirror，单主文件保存后主动编译；PDF.js 6.4.299 预览保存版本 |
| 草稿 | idb-keyval / IndexedDB，按窗口身份和文件身份隔离 |
| 项目保存 | 既有 Store、不可变资产、准确版本、CAS 与幂等请求 |

DOCX 文本、排版、分页、评论和 OOXML 导出由上游引擎负责；宿主不重建 DOCX。导出使用 `review-preserving`、`comments: preserve`、`contentControls: preserve`。新批注作者为匿名的 `本机用户 <local-user@acapartner.invalid>`，不是已认证账号或 Agent 身份。遥测关闭，未连接实时协作服务。许可见[第三方声明](../../THIRD_PARTY_NOTICES.md#superdoc-文档编辑依赖)。

无审阅内容时不预留右侧空列；上游有批注或待审内容时按宽度显示侧栏或浮层。文稿层 flex 占据可用空间，纸面居中；公开 fit-width 配置为 padding40 / max200，仍可手动缩放。主题只改变外框，工具区和纸面保持浅色。

## 保存与文件权威

一个项目保留默认论文对象。DOCX、LaTeX 和结构内容分别存储，保存或编译不自动切换主源；明确的“设为论文源稿”才更换绑定。当前每格式一份服务端源，不宣称任意多服务端 DOCX 或格式互转。

首次明确导入成为项目论文草稿，已有 DOCX 保存版时拒绝替换。文件 → 打开建立独立本地标签；保存副本是下载，不回写操作系统原件，不替换项目论文。相同文件名不代表相同文件身份。

DOCX 上限32MiB；服务端验证 OPC 容器、CRC、路径、内容类型及展开限制，拒绝宏格式、加密、重复部件和路径穿越。验证不转换收到的字节。首次保存记录编辑器序列化后的文件，导入前原件目前没有在服务器另行归档。

文件树通过既有 ProjectFiles 展示保存版镜像，带来源格式和对象身份。镜像不是直接写入论文数据库的另一个入口。历史 Univer JSON 与对象修订仍保留，可只读查看；删除旧界面不会删除项目资料。

## 应用接口

所有接口沿用当前项目/论文身份、项目授权、准确基础修订与稳定请求标识；没有任意路径导入或数据库直写入口。

- `document.read(project_id)`：读取默认论文、独立来源、当前 DOCX 资产 URL、预览和适配器状态。读取不转换或写入。
- `document.save(project_id, object_id, expected_revision, request_key, format, source)`：DOCX 的 `source={base64, filename}`；LaTeX 为文本。拒绝过期版本，相同请求可重放；当前主源与其他文件保留。首次原生保存建立绑定。
- `document.select(project_id, object_id, expected_revision, request_key, format)`：明确把一份已保存的 DOCX/LaTeX 设为论文主源。需要源文件存在，采用独立事务、权限检查、CAS 和幂等记录，不转换内容。历史 Univer 也可通过此接口兼容选择。
- `document.checkout(project_id, object_id, expected_revision, request_key)`：将保存版 DOCX 复制到服务端工作区 `document-work/<id>.docx`，返回 `id/path/base_revision/source_sha256`。工作副本与不可变资产隔离。
- `document.commit(project_id, object_id, expected_revision, request_key, checkout_id)`：只读取已登记、属于此论文的工作副本，要求项目版本仍等于副本基础版本。拒绝链接、非普通文件、读期间修改及过大文件；验证后保存新的 DOCX 资产和修订。文件在失败后保留。
- `document.render(...)`：编译明确保存的 LaTeX 文件，返回标有 `format=latex` 的 PDF 回执与准确修订。独立 LaTeX 也可编译，不改变 DOCX 主源；其 PDF 不登记为当前 DOCX 的通用导出。

Agent 无需专用编辑 SDK。普通 `python-docx` / LibreOffice 工具可编辑 checkout 返回的本机路径，再通过 commit 提交。GUI 的“准备 DOCX 工作副本”和“提交 DOCX 文件修改”使用同一接口。当前适用于 Agent 与服务同机的文件工具；SSH 传输、远程运行器、Agent 工具目录发现及新版右栏会话仍待后续集成。


## 草稿、冲突与 Agent

编辑与审阅后650ms捕获浏览器草稿；关闭标签、切换项目、保存与下载时主动捕获。保存后的标题或状态不会重新加载旧字节。突然退出仍可能丢失最后一次快照后的输入。

新窗口分配独立草稿身份；复制标签的草稿复制后隔离。远端修订变化提示载入新版，先备份未保存稿；恢复保留原基础修订，不能绕过 CAS。失败导入保留原件与已有草稿，并提供打开其他 DOCX 的实际入口。

本机 Agent 通过 checkout 获取隔离工作副本，普通文件工具修改后 commit；基础修订过期会拒绝覆盖。可从命令行调用 `python3 -m research_partner --workspace /实际工作区 action`，也可使用右栏文件交接。不要直接改资产 blob 或数据库。实时对话、SSH 执行、远程工作副本传输和多人协作仍未接通。

## 研究对象与验证

当前科研 Q 是显式标记的 concept；父子 Q 各自有 QAEC、人工状态与版本。背景独立保存，笔记复用原生 Session。研究 Q 与等待人工决策的 question 类型分开，不把状态当作科学证据。

`workbench.research.read` 按同级 `metadata.workbench.order`（旧记录按建立顺序补位）返回问题的树序，并派生 `number` 与 `tree_parent_id`，如 Q1、Q1.1；归档父问题后仍显示其可见子问题。编号仅用于当前结构的显示，不改标题、对象 ID 或科学修订。新问题在父节点下追加，普通内容编辑不重排。

当前测试输入统一在 `tests/fixtures/documents/`，结构检查器为 `tests/helpers/inspect_docx.py`；二者应随源码提交。浏览器回归覆盖保存/重开、批注与修订、接受/拒绝、只读、独立本地文件、Agent 提交、双窗口冲突、恢复与 LaTeX。合成样本覆盖公式、域、图片、脚注、页眉页脚、书签和 customXML；这些检查不等于任意科研 DOCX 无损。

Microsoft Word、真实 Zotero / EndNote 刷新、系统 IME、长论文性能、复杂公式编辑、DOCX→PDF、多文件 LaTeX 和格式互转尚未完成全面验收。本机测试日志与截图留在忽略的 `.private/` 中，当前支持范围在本页维护。

## Source code and Markdown adapters

CM6 is shared by notes, QAEC, LaTeX, managed Python working copies and read-only file snapshots. `@codemirror/language-data` resolves filenames/extensions and loads upstream parsers on demand; `@uiw/codemirror-theme-github` supplies light/dark highlighting. Compartments update language, theme, permissions and optional `@codemirror/merge` comparison without rebuilding editor history. Note comparison reads the saved note, keeps the original CAS base, and never implicitly adopts a newer revision.

Shiki 4.5.0 with its official markdown-it integration handles reading-mode fenced blocks. Selected scientific/web grammars and both GitHub Default themes are bundled locally. Unknown grammars, oversized blocks and failed highlighting fall back to escaped text; Markdown sanitization and existing source offsets remain in place.

Seti filename/extension/language mappings and the font are copied byte-for-byte from the pinned VS Code source commit recorded in `frontend/public/licenses/seti/UPSTREAM.json`. Both original licenses ship beside it. File tree, file tabs and search results share a small adapter; application controls remain Lucide.

`article.files` now separately returns `working_scripts`, enumerated from the actual project script directory through the existing notebook directory lock. Listing uses no-follow stat, rejects links/oversized files and does not execute scripts or infer mutable file identity from a globally deduplicated blob. The mirrored `entries` remain immutable/source-revision views.

The Python editor reuses `recipe.script.read/write`: explicit project/file identity, a 1 MiB UTF-8 save limit, expected SHA and old-byte snapshot protection. Browser drafts use the existing per-window IndexedDB namespace; closing/switching flushes drafts, and stale saves expose comparison and backup/reload/restore. Agent callers use the same existing action API. A save changes only the working file; old registered assets, pinned object revisions and results stay unchanged. General R/Julia/config file saving, Git commit-history views and Jupyter execution are not implemented by this adapter.


树节点操作复用既有笔记与对象接口。笔记重命名使用 `notes.move.inspect/move`，保留笔记身份与原文；检查仅涵盖围栏代码外的行内 Markdown 链接 / 图片，列出传入与受影响的传出链接，确认后也不改写链接。笔记删除 / 恢复沿用 `notes.trash/restore`；子目录操作逐篇处理 `.md` 笔记，可能部分完成，不回收目录或其他文件。研究问题通过准确修订归档与恢复，默认论文及登记投影受界面保护。

Python 回收与恢复使用 `recipe.script.trash/trash.list/restore`，仅接受当前项目 `scripts/` 下的 `.py` 文件名和明确回收身份。操作复用 notebook 目录锁、SHA 校验与无覆盖原子移动：Linux 的 `renameat2(NOREPLACE)` 或 macOS 的 `renameatx_np(EXCL)`；缺少该原语时失败，不降级为覆盖移动。笔记 / 脚本删除前先保存未保存草稿，保存冲突停止删除；回收记录支持刷新后恢复，目标已存在时保留双方。新建、回收与恢复不执行脚本，不修改已登记源码快照、旧证据或研究结果；脚本重命名与通用目录 / 资产文件管理尚未提供。
