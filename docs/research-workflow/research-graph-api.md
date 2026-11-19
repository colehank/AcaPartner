# 独立研究图接口

工作台主画布使用 `workbench.graph.*`，与人和 Agent 共享 Store、项目权限、对象修订和 `graph_growth` 关系历史。根为项目主题对象，仍包含在 API 返回中；画布由项目标题提供上下文，不重复绘制根 Q，也不创建根 AEC。研究 Q 保留既有身份，A/E/C 是独立 concept 对象。父 Q 只组织子 Q，叶 Q 承载 A/E/C。布局采用本地 Graphviz 与 React Flow，见[布局接入](../architecture/research-graph-layout.md)；不引入另一套图数据库。

## 读取与修改

请求经 `POST /api/action`，沿用服务的身份认证及 CSRF 规则。读取：

```json
{"action":"workbench.graph.read","project_id":"PRJ-…"}
```

返回 `version:2`、项目当前修订、`nodes`、`edges`、迁移状态与 `source_refs`。节点含稳定 `id`、类型、展示编号、标题、正文、修订、当前/记录状态、确认、依赖签名和固定来源。Q 节点还含：

| 字段 | 含义 |
| --- | --- |
| `question_role` | `parent` 表示有有效直接子 Q；否则为 `leaf` |
| `child_question_ids` | 按当前 Q 顺序排列的有效直接子 Q ID |
| `needs_organization` | 旧父 Q 同时具有直接分析或回答结论，需整理；仍可读取原内容 |

关系含稳定 `id`、类型、端点、修订、依据、是否有效及是否兑现；已撤回关系仍在返回结果中，画布默认隐藏。A/E/C 编号随所属叶 Q 派生，E 继承产生它的 A 的后缀；编号不是身份，不能作为写入目标。编号投影不改正文、修订或状态，详见[模型与编号规则](free-research-graph.md)。

`workbench.graph.*` 修改要求 `project_id`、稳定 `request_key`、准确 `expected_project_revision`。同一请求重试返回同一结果，不能换内容重用请求标识。项目或节点冲突回滚整个事务。搭档成批图变更使用下述冻结输入 pin 与发布守卫，不逐个模拟这些 HTTP 操作。

| 操作 | 额外字段 |
| --- | --- |
| `workbench.graph.node.create` | `kind:Q/A/E/C`、`title`、`body`、`status`；可选 `parent_id`、`relation_kind`、`rationale`，同事务连接 |
| `workbench.graph.node.save` | `id`、`expected_revision`、`title`、`body`、`status` |
| `workbench.graph.question.organize` | 父/待拆分 Q 的 `id`、`expected_revision`、新子 Q 的 `title`；可选 `body`、`status`，见下节 |
| `workbench.graph.edge.create` | `src`、`dst`、`kind`、`rationale` |
| `workbench.graph.edge.save` | `id`、`expected_revision`、`active`、`rationale`；撤回保留原关系和历史 |
| `workbench.graph.history` | `id`；可选 `before_revision`，每页30条对象保存版，无修改字段要求 |
| `workbench.graph.migrate` | `expected_sources` 为读取时准确 `source_refs` 列表；仅允许未迁移项目 |

节点新增/保存可传 `source_refs:[{id,revision}]` 登记有权限读取的准确保存版（最多16项），服务核对权限、版本和对象 SHA。省略保留已有来源，空数组明确移除。来源属于内容签名，变更使旧确认及下游待复核；不从链接或文件名猜测来源。节点标题必填、最长500字符，正文最长128 KiB。

## 父问题与叶问题

父 Q 具有有效 `contains` 子 Q，不能同时直接拥有 `analyzes` A 或传入的 `answers` C。叶 Q 没有子 Q，可有多个 A、每 A 最多一项 E、多个 E 汇入 C，也允许共享叶问题分析和跨问题证据引用。综合判断约定为末尾的明确叶 Q，不给父 Q 再挂一套 AEC。

`workbench.graph.question.organize` 用于已有直接分析或回答结论的 Q。除公共写字段外，需要目标 Q 的 `id`、准确 `expected_revision` 和新子 Q 的 `title`；`body` 默认原 Q 正文，`status` 默认 `active`，禁止 `completed`。成功返回 `node_id`、`organized_parent_id` 和最新 `graph`。原子操作会：

- 在目标 Q 下追加子 Q，撤回原 `analyzes/answers` 关系并保留历史，将同一批 A/E/C 重新连接到新叶 Q；保留对象 ID、正文、旧修订和科学确认记录。
- 将已有直接子 Q 作为新综合子 Q 的显式前置条件；撤回重复的“子 Q 前置于父 Q”关系，父级完成条件统一由 `contains` 签名表达。
- 将已完成父 Q 退回进行中，原已完成回答 C 退回待确认；分析范围和关系变化也会使旧确认失效，需按新范围重新核对。整理不自动确认科学完成。

操作复用同一权限、CAS、稳定请求、Store 事务与关系历史；没有可迁移分析/结论时返回 `not_ready`，可直接新建普通子 Q。旧混合父 Q 可读、可通过本接口修复，但不能完成或扩大混合关系；新增违规关系返回 `decomposition_required`。v2 的共享 `create_question` 路径也阻止从侧栏或旧 Q 创建入口绕过整理。

## 关系与完成依赖

| kind | 语义端点 | 完成依赖 |
| --- | --- | --- |
| `contains` | 项目/父 Q → Q | 项目根只组织内容；父 Q 的全部直接子 Q 反向作为父 Q 的完成条件 |
| `analyzes` | 叶 Q → A | 绑定问题范围；A 不需要等 Q 完成才能开展 |
| `produces` | A → E | E 需要 A 完成；每 A 最多一项 E，E 只有一个产生它的 A |
| `supports/limits/refutes` | E → C | C 需要声明依据均完成，绑定关系版本 |
| `answers` | C → 叶 Q | 叶 Q 需要回答结论完成，并明确确认足以作答；禁止直接回答父 Q |
| `prerequisite` | 前置 Q → 后续 Q | 后续 Q 完成需要前置 Q 完成；与问题拆解分开 |

`contains` 的语义连线仍为父→子；`dependencies` 返回的完成 pin 使用子→父，包含原组织边 ID/修订和子 Q 签名。子 Q 内容、范围、状态或确认改变后，可沿该签名使父 Q 及其下游待复核。子 Q 全部完成不会自动完成父 Q。

叶问题的 Q→A→E→C→Q 可以形成语义回指；完成依赖与问题拆解分别拒绝循环。关系保存复用 `graph_growth` 版本与历史，不覆盖同端点的既有科学决定。实线/虚线只表达该类关系是否兑现，不能代替科学支持判断；组织线保持较轻。

## 完成确认

普通状态为 `not_started/active/review/paused/unmarked`；新建和整理都不能直接完成。已有节点保存 `status:"completed"` 时，需要具体标题、非空正文及：

- E 有唯一已完成的产生分析，C 有明确且已完成的证据；叶 Q 有已完成回答结论，父 Q 无直接 A/回答 C 且全部直接子 Q 完成；所声明前置 Q 也须完成。
- `confirmation_note` 记录该节点自己的核对说明，`expected_dependencies` 原样携带最新节点的准确依赖签名列表。
- Q 另需 `answers_question:true`。父 Q 的确认说明子问题的结论足以共同回答父问题；阴性结果也可作答，证据不足不自动完成。

完成确认由已认证操作者记录，标为 Agent 的凭据不能自行确认科学完成。项目写权限或生成成功不等于科学确认授权。内容、标题、固定来源、问题范围、关系或依赖签名改变后，旧确认保留，当前节点及下游待复核；恢复旧正文不会恢复旧确认。叶 Q→A 的范围同样绑定准确内容与关系，但不要求 Q 先完成。

## 搭档图变更

GUI 右侧输入通过现有 `research_partner` 有限任务运行，不另建运行器或图数据库。`research.partner.preview/submit` 显式传 `graph_mode:"edit"`；可选 `graph_focus` 必须是当前图的真实节点 ID，包括独立 A/E/C。预览不调用模型：

```json
{"action":"research.partner.preview","project_id":"PRJ-…","request":"比较候选方法，再检验选定方法的适用范围。","graph_mode":"edit","graph_focus":"ART-…","materials":[],"questions":[],"native_paths":[]}
```

返回 `input`、`input_pin`、`executed:false`。`research.partner.submit` 原样携带同一输入字段及 `input_pin`，再传 `provider_id`、稳定 `request_key`、`budget:{"max_model_calls":1,"timeout_seconds":180}`。可用 `previous_task_id` 接续最近最多四轮；时限可在1至900秒内设置，当前路线为已授权 Codex CLI。重放相同提交核对原任务，不重复派发。

图快照固定项目修订、整图 pin、节点稳定 ID/类型/编号/标题/修订/状态，以及全部关系的 ID、端点、类型、修订和有效性。只有焦点、明确选中的 Q 或材料中对应图节点带保存正文；其余节点是摘要。提交复核预览后冻结输入，原生保存材料继续按路径/SHA形成不可编辑快照；本轮用户原话另存为不可编辑的 `CTX-…` 来源并加入固定来源集合。模型可用 `{id:"request",revision:1}` 引用该原话，服务会换成实际来源 ID、修订和 SHA。

模型返回 `partner_reply` 及 `graph_change:null` 或以下变更；不与旧 `research_proposal/research_update` 混用。

| 字段 | 当前合同 |
| --- | --- |
| `version`、`summary` | 版本为1，说明本轮整理 |
| `background` | `null` 保留背景；字符串为完整背景更新，应保留相关原内容 |
| `creates` | 本地临时 `id`、`kind:Q/A/E/C`、`title`、`body`、`quote`、`source_refs:[{id,revision}]`；应用后换为稳定 Store ID |
| `updates` | 准确已有节点 `id`、可空 `title/body`、`quote` 和可空 `source_refs`；`body:null` 保留正文，替换正文必须已在本轮图快照中读取；来源追加保留旧引用 |
| `edges` | `src/dst` 为本轮临时 ID、已有节点 ID 或根别名 `project`，附图关系 `kind` 与非空 `rationale`；类型和方向遵守上表 |

新 Q/A 状态固定为 `not_started`，新 E/C 固定为 `review`。创建 E/C 或替换其正文需要非空逐字 `quote`，且至少一项准确引用的本轮用户原话、选定保存材料或已有 E 确实包含该引文；Q、计划 A、已有 C 和此前对话不作为独立证据。Q/A 无需已有结果，仍登记本轮输入来源。引用存在只证明报告内容的来源，不证明结果已重算或科学判断成立。

新 Q 未指定 `contains` 时归项目；指定拆解关系时只允许一个父节点。新增关系可连接已有节点，重复的有效同类型关系为无操作；已有 Q 的 `contains` 只能重述原关系，不能隐式重新归属。新 A/E/C 须通过正确类型关系从研究 Q 可达。合同不接受状态/确认、删除、撤回、坐标、脚本、文件修改或任意动作；已有 AEC 叶 Q 的拆分仍须明确使用 `workbench.graph.question.organize`。

| 范围 | 当前上限与超限处理 |
| --- | --- |
| 冻结整图 | 80个节点（含项目根）、160条返回关系记录（含撤回记录）；超限 `context_limit`，不会截取局部图冒充全图 |
| 保存材料 | `materials + native_paths` 最多8项，原生文件最多4份；`questions` 最多4个。GUI 将所有选项合计限制为8项；用户原话来源另由服务加入 |
| 完整上下文 | 45000字节，计入序列化快照及材料的实际发送投影；冻结新增来源后再次检查，超限拒绝而不截断 |
| 单轮图变更 | 最多24项创建、24项更新、48条关系；序列化 `graph_change` 最多96000字节 |
| 单节点输出 | 标题最多500字符且不超过2000字节，正文最多12000字节，每项提交的来源最多16个；这些限制小于手工图编辑的正文上限 |

实际执行与回执仍归共享 Runtime/Providers。`research_tasks.publish` 核对授权、来源、执行身份和匹配的实际模型回执后，在同一 Store 写事务中保存回复并应用整批图变化。应用先核对当前整图 pin；节点或关系不合法时整批图写入回滚。任务结果的 `graph_change` 回执为：

- `applied`：返回 `summary`、`created_ids`、`updated_ids`、`edge_ids`、`project_revision`，GUI 自动刷新图与左树，无第二次采用。
- `conflict`：当前图有变化，或关系等应用规则冲突；回复及候选保留，图未覆盖。
- `unapplied`：如旧 QAEC 尚未明确导入，或其他应用规则未通过；回复及候选保留。
- `undone`：本轮已应用变化已撤销，历史保留。普通 `graph_change:null` 不产生图回执。

整轮撤销使用且仅使用以下字段，不接受 Agent 身份：

```json
{"action":"research.partner.graph.undo","project_id":"PRJ-…","task_id":"TASK-…","request_key":"undo-…"}
```

服务检查项目写权限和任务归属，并要求当前整图 pin 仍等于应用后记录；后续修改存在时返回 `conflict`，不抹去后来工作。成功时归档新节点、撤回新关系、将被更新节点和项目原内容保存为新修订，保留原回复、来源与历史。返回 `graph_change` 及 `replayed`，已撤销重试返回相同撤销状态；恢复旧文字也不恢复旧科学确认的有效性。源码所有权、事务和验证范围见[搭档图变更接入](../architecture/partner-graph-changes.md)。

## 迁移、兼容与当前边界

`workbench.graph.migrate` 保留原 Q ID、全部 QAEC 正文与历史、原总体问题、论文、材料、笔记和任务。非空 AEC 提取为独立对象并记录原问题/修订/段落；父 Q 的原 AEC 自动整理到末尾子 Q，返回 `organization_questions` 映射。空槽不创建假结果。仅此前已认证、且满足新依赖的完成记录可以转移，不能从文本或搬移推断完成。已是 v2 的项目通过整理接口调整，不能重复执行迁移。

当前运行时功能标识为 `leaf_research_questions_v1`，图写入标记项目 `research_graph_question_model:leaf_v1`，复用已有运行时兼容性检查；不增加数据库或任务执行器。旧总体问题从“项目内容”抽屉读取原记录与历史，不另画一行 QAEC；画布折叠与关系边界投影仅是本地显示，不修改本页 API 或旧 QAEC 合同。

原 `workbench.question.*` 保留 QAEC 记录合同；`research.work.*` 及省略 `graph_mode` 的旧 `research.partner.*` 候选与采用仍是每 Q 一组 QAEC，**尚未自动映射到独立多 A 图**。GUI 新发送使用上述独立图合同，旧 QAEC 必须明确导入后才可自动应用；原编辑器继续查阅原记录，独立 A/E/C 不隐式双向覆盖。有限图变更不包括自动多轮科研、科学确认、脚本执行或文件修改。

科学煮蛋的新导入经 `05_publish_demo.py` / `free_graph.py` 接入；已有独立图用 `leaf_graph.py` 整理结构，用 `revise_graph.py` 修订案例正文与关系，均限定 `demo=scientific_egg_v1`，避免重复导入并保留旧修订。当前图有34个节点、47条有效关系；Q1.3的联合计数与缺失上界分别支持、限制C1.3，原单项E直接支持综合C的迁移残留边已撤回。Q2.4的综合缺口分析进行中，独立验证A2.4-2尚未开展且没有虚构E。具体状态与边界见[案例说明](../../examples/scientific-egg/README.md)，浏览器草稿和历史保护见[工作台指南](../workbench-guide.md)。
