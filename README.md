# AcaPartner · Research Partner

一个本地优先的科研协作工作桌：在同一项目里阅读和编辑稿件、整理意见、查看图与来源、记录 Markdown 笔记，并按明确授权调用科研任务。

**这是开发预览版。** 基础编辑与局部工作流已有验证，完整科研协作、全部成果类型和跨平台交付仍在完善；不把运行成功当作科学结论或正式验收。

## 开始使用

需要 **Python 3.12+**，使用 Linux/macOS；Windows 当前请用 WSL2。从本仓库下载或解压完整发布包，在根目录运行：

```sh
python3 tools/start_local.py
```

打开启动输出的本机地址（默认 `http://127.0.0.1:8877`）。首次点 **注册本地账号** 设置用户名和密码，以后直接登录。项目与账号默认保存在用户主目录的私有数据目录，源码升级不会覆盖它们。不要把该数据目录上传 GitHub。

首页使用统一科研工作台，从项目导航进入研究、笔记和论文。

```sh
python3 tools/start_local.py --data-dir /your/private/acapartner --port 8877
```

发布包包含前端构建。若从仅有源码的版本开始，需要 Node.js 22.12+，先在 `frontend` 运行：

```sh
npm ci
npm run build -- --configLoader runner
```

更多说明：[快速开始](docs/quickstart.md) · [当前工作台指南](docs/workbench-guide.md) · [文档总览](docs/README.md)。


## 在工作桌里做什么

当前工作台覆盖项目、研究、笔记和原生论文。

| 模块 | 用途 |
| --- | --- |
| 项目与研究 | 项目导航、背景、并列和递归 Q，各自的 QAEC |
| 原生论文 | SuperDoc DOCX 编辑、批注和修订；独立 LaTeX 与 PDF 预览 |
| 笔记和文件 | 原生 Markdown、文件读取、固定来源与版本 |
| 委托与任务 | 复用已配置路线、授权和任务读取；实时对话尚未接通 |
| Agent 文件交接 | 准备隔离工作副本，按基础修订提交，保护未保存草稿 |

服务首页 `/` 现在直接打开统一科研工作台：主页、研究结构/文件目录、笔记、委托与原生论文共用同一套三栏界面。`/workdesk/editors.html?project=项目ID` 是同一工作台的论文直达入口；从“交付”打开真实项目论文。论文绑定一份主源，打开时自动进入对应编辑器；其他 DOCX/LaTeX 在文件树和独立标签中分别编辑。保存或编译只更新该文件，更换主源通过明确的“设为论文源稿”，不自动转换内容。DOCX 统一使用 SuperDoc 在浏览器内上传、编辑、修订、批注、保存和下载；没有批注等审阅内容时不预留右侧空列，纸面按可用宽度缩放并居中。“打开”建立独立本地副本，不替换项目论文。SuperDoc / React 的 AGPL 与必需 DOCX Engine 的专有许可并存，当前是本机开发集成，生产或对外分发范围见[第三方声明](THIRD_PARTY_NOTICES.md#superdoc-文档编辑依赖)。Agent 可用普通文件工具编辑工作副本后，经版本检查提交回项目。旧 Univer 数据保留并可下载。接入方式与边界见[文档适配记录](docs/architecture/document-adapters.md)。

完整示例见[科学煮蛋](examples/scientific-egg/README.md)：480枚合成样本、7个父子研究问题、实际运行的分析与绘图脚本、4张图及带表格和公式的中文文章。可重建全部结果，再通过现有接口导入工作台，沿问题→数据→代码→证据→论文浏览；DOCX与LaTeX分别保存。模拟数据、实际本机计算与尚未提交的Agent工作明确区分。

## 可选运行时与限制

默认启动是 **仅工作桌模式**，不构造任务执行器、不消费旧队列、不自动调用模型。模型、外站取得全文、绘图与数据重算需另行配置运行时、凭据和数据权限。新建项目可以保留空稿与笔记；没有 XeLaTeX 时当前 PDF 编译会明确受阻。

- PDF：XeLaTeX / BibTeX 及中文字体。
- 科学图：配置的 Python、Matplotlib 等；只能对有可验证来源的元素做对应编辑。
- 生成链：与锁定版本及安装记录匹配的 Snakemake 环境。
- Agent：已有提供者适配、明确凭据、授权材料和有限预算；本地账号不等于模型服务账号。

本预览不承诺完整科学质量、Windows 原生输入/打印、参考硬件性能、所有来源变体或完整 W4/W5 交付。产品方向、领域词义和工程边界见[文档入口](docs/README.md)。

## 开发与发行

后端是 Python 标准库实现，前端使用 React、Dockview、CodeMirror 与 SuperDoc。前端锁文件在 `frontend/package-lock.json`。测试和发布包含范围见 [发布说明](docs/RELEASE.md)。

仓库提供产品源码、前端构建、可分发字体和许可证及自包含测试。**不包含**使用者项目、科研数据、模型凭据、本机账号、内部运行台账、历史验收材料或旧开发 Git 历史。公开版本不改变原项目已有证据或验收结论。

## 许可证

主项目使用 [MIT](LICENSE)。附带字体的许可证位于 `research_partner/fonts`；前端依赖声明及第三方许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 文档维护

产品上下文、领域词表、设计规范、实现记录和原始资料统一从 [docs/README.md](docs/README.md) 阅读，正文集中在 docs。根目录的 AGENTS.md 仅提供开发规则与文档导航。
