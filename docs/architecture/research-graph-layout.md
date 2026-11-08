# 研究图布局接入

当前研究图由 React Flow 承担节点、选择、平移缩放与检查器，Graphviz 负责排序、分组和连线路由。界面规则见[设计规范](../design-system.md#question-states--free-research-graph)，研究对象及完成条件见[自由研究图](../research-workflow/free-research-graph.md)；布局不改变科学内容、关系、状态、来源、历史或权限。

## 引擎与领域适配

使用精确锁定的 `@viz-js/viz` 3.31.0，内含 Graphviz 16.1.0。此前研究图直接用 Dagre 排位，再单独绘制曲线；当前要求同列顶层问题、按编号分区、综合节点居中，以及围绕最终节点边界的真实路由，因此改用成熟引擎的 compound/rank 与路由能力。适配层只表达研究图的归属、顺序和对齐约束，避免自建通用布局器。

| 入口 | 职责 |
| --- | --- |
| [researchGraphLayout.ts](../../frontend/src/workbench/researchGraphLayout.ts) | 将稳定 ID、节点类型/编号、关系与方向转换为引擎输入；返回节点、完整关系路径、共享绘制段、端口、分区和默认隐藏的归属线 ID |
| [researchGraphWires.ts](../../frontend/src/workbench/researchGraphWires.ts) | 为兼容关系规划出线分叉和入线汇合的几何接点；将共享段映射到真实关系 ID，保留每条完整路径 |
| [researchGraphLayout.worker.ts](../../frontend/src/workbench/researchGraphLayout.worker.ts) | 在本地模块 worker 中调用引擎，返回几何或错误 |
| [useResearchGraphLayout.ts](../../frontend/src/workbench/useResearchGraphLayout.ts) | 延迟建立 worker，处理空输入、错误重试、卸载与请求代次；晚到结果不能覆盖新范围 |
| [researchGraphView.ts](../../frontend/src/workbench/researchGraphView.ts) | 初始化并保留 Q 折叠选择，投影可见节点与折叠边界关系；共享 A/E/C 经任一展开路径保持可见，汇总路线保留真实关系 ID |
| [FreeResearchGraph.tsx](../../frontend/src/workbench/FreeResearchGraph.tsx) | 在同一连续画布内展开 Q 与已有 A/E/C，将引擎几何交给 React Flow；保留按项目的镜头、折叠及明确动作的返回快照，提供下部覆盖检查器 |
| [ResearchRelationMenu.tsx](../../frontend/src/workbench/ResearchRelationMenu.tsx) | 复用 Radix Dropdown Menu，在共享段触发位置列出真实关系，选择后打开原详情并恢复连线焦点 |

第一遍 `dot` 使用 compound 分组与 rank 约束；适配层对齐顶层 Q，按数字顺序把独立叶 Q 及其可见工作一起安排到分支位置，并将展开的综合工作放在可见前置工作之后。折叠边界投影关系不参与布局归属判断。单条独立叶问题路线沿同一行排列；多个分析按编号分行，结论按实际输入证据居中，共享工作保留引擎排位。节点矩形尺寸统一来自`researchGraphDimensions.ts`（宽256，通常高180，E高212），用于两遍引擎声明、范围/分支边界、避碰、共享主干、React Flow端口和镜头锚点。随后 `nop2` 固定最终位置，围绕最终节点边界计算正交层级线和有方向的依赖路由。React Flow 消费引擎路径及端口，不另算独立 Bézier 曲线。共享连线只在原节点位置固定后加入几何接点，由同一 `nop2` 路由；这些接点不成为研究节点、关系或新依赖。

Graphviz 的 [`concentrate`](https://graphviz.org/docs/attrs/concentrate/) 对部分平行边共享路径的能力仅适用于 `dot`；当前固定坐标的 `nop2` pass 不能直接依靠该能力完成共享主干。因此领域适配只为类型、方向、兑现状态和层级兼容的关系规划分叉/汇合接点；受阻或不规则情况保留独立原生路由。相同关系集合的连续段合并后只绘一次，实际正交顶点以最大5px局部圆角衔接，有向共享尾段只画一个目标箭头；完整单边路径及 ID 仍保留。

折叠时，隐藏端点映射到可见的收起 Q；多条同向同端点关系可汇总成一条显示路线，即使实际关系类型不同，仍逐项保留真实 ID、类型、端点和兑现状态。仅全部真实关系已兑现时，汇总路线才标为已兑现；它不产生新的关系、归属或依赖。点击共享段或折叠汇总路线，或在线上按 Enter/Space，打开锚定触发位置的 Radix 菜单；选择真实关系后打开原关系详情。菜单经 body portal 避开画布裁切，Escape 关闭后恢复 SVG 连线焦点，窄屏或粗指针菜单行至少44px。关系名称只在菜单和详情显示，不叠在短尾线上。

淡色分区框表达问题归属。父→综合子 Q 的重复归属线默认隐藏以免遮挡依赖汇合；对应关系 ID 和路由仍保留，可从父 Q 完成依据旁的关联按钮查看。此行为只改变投影，不撤回关系。桌面与手机共用从左向右的连续画布；项目根保留在数据中，由页头标题提供上下文。已完成 Q 初次收起、未完成 Q 初次展开，手动选择不随刷新重新初始化；Q卡片独立箭头就地折叠，卡片主体选中详情。初始镜头优先保持顶层 Q 可读，不保证所有展开工作同屏；切换折叠保留点击节点的镜头锚点，其他节点可随排版调整。下部覆盖检查器不改变画布尺寸，选择与异步排版保留键盘焦点；聚焦、全局查看、返回和恢复默认展开为明确动作，返回最多保留20次镜头及折叠快照，不逐次记录平移。

## 浏览器与部署边界

WASM 随前端构建从本地资源延迟加载，排版在 worker 中完成；不依赖 CDN 或服务端布局服务。输入只包含布局所需的ID、类型、编号和关系，矩形尺寸由类型派生，不传研究正文。卡片摘要在主线程复用既有Markdown解析器，缩放只改变文字披露，不重建排版或关系。加载或排版失败时显示“重新排版”；空输入返回空几何，范围切换或卸载后丢弃旧代次结果。

服务 CSP 的 `script-src` 使用 `'self' 'wasm-unsafe-eval'` 以允许本地 WASM，未加入通用 `unsafe-eval`；worker 沿用既有同源策略。新增部署需保留 WASM/worker 构建资源与对应 CSP，否则通过明确错误与重试入口处理，不以旧范围图冒充新结果。

## 许可证与核对范围

Viz.js 包装层为 MIT，内含 Graphviz 16.1.0（EPL-2.0）与 Expat（MIT）。完整原文保留于 [research-graph.txt](../../frontend/public/licenses/research-graph.txt)，随构建复制为 `research_partner/web/workdesk/licenses/research-graph.txt`，服务地址为 `/workdesk/licenses/research-graph.txt`；总览见[第三方声明](../../THIRD_PARTY_NOTICES.md)。

连续画布核对包括重复折叠、保存选择、共享对象及边界关系投影、同一横向窄屏画布、端口/避障几何、镜头与检查器稳定、树/搜索定位、草稿/只读历史和排版失败重试。忽略目录 `.private/continuous-research-canvas/` 保留13个最终截图、10项几何/投影及13项无头交互检查；触摸平移、捏合与取消仅为合成 CDP 验证，没有物理设备声明。此前分组与共享连线证据保留在 `.private/grouped-research-graph/` 和 `.private/bundled-research-edges/`；这些验证不代替科研判断，也不声明任意图规模或其他图组件的布局覆盖。
