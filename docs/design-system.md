---
name: "AcaPartner Workbench v0.17"
description: "统一科研工作台的视觉令牌与组件规范；以实际使用反馈持续调整。"
colors:
  surface-app: "#f5f5f4"
  surface-nav: "#f5f5f4"
  surface-editor: "#ffffff"
  surface-agent: "#f5f5f4"
  surface-toolbar: "#fafaf9"
  surface-input: "#ffffff"
  surface-hover: "#eaeae8"
  surface-raised: "#eeeeec"
  text-primary: "#27282c"
  text-secondary: "#51535a"
  text-muted: "#65676f"
  text-placeholder: "#74767d"
  border: "#dcdcd9"
  border-subtle: "#e9e9e6"
  accent: "#525eb2"
  accent-solid: "#5561b8"
  on-accent: "#ffffff"
  selection: "#e6e6e3"
  selection-text: "#292a2e"
  selection-ink: "#e4e8ff"
  focus: "#6572c8"
  success: "#37674f"
  success-bg: "#e5eee8"
  warning: "#79591f"
  warning-bg: "#f4ecd9"
  danger: "#a14542"
  danger-bg: "#f6e8e6"
  dark-surface-app: "#191a1d"
  dark-surface-nav: "#191a1d"
  dark-surface-editor: "#202124"
  dark-surface-agent: "#191a1d"
  dark-surface-toolbar: "#242528"
  dark-surface-input: "#242528"
  dark-surface-hover: "#2b2c30"
  dark-surface-raised: "#292a2e"
  dark-text-primary: "#eeeeef"
  dark-text-secondary: "#babcC3"
  dark-text-muted: "#989aa3"
  dark-text-placeholder: "#9b9da6"
  dark-border: "#38393f"
  dark-border-subtle: "#2c2d32"
  dark-accent: "#a4aef4"
  dark-accent-solid: "#5966bf"
  dark-on-accent: "#ffffff"
  dark-selection: "#303136"
  dark-selection-text: "#eeeeef"
  dark-selection-ink: "#3b426d"
  dark-focus: "#a4aef4"
  dark-success: "#a4c8b2"
  dark-success-bg: "#293b31"
  dark-warning: "#ddc38e"
  dark-warning-bg: "#3c3528"
  dark-danger: "#e8aaa6"
  dark-danger-bg: "#422e30"
  status-review: "#6e4b86"
  status-review-bg: "#eee7f3"
  dark-status-review: "#cfb4e0"
  dark-status-review-bg: "#352b3d"
typography:
  headline:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", \"PingFang SC\", \"Noto Sans CJK SC\", \"Microsoft YaHei\", sans-serif"
    fontSize: "28px"
    fontWeight: 650
    lineHeight: 1.5
    letterSpacing: "-0.025em"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", \"PingFang SC\", \"Noto Sans CJK SC\", \"Microsoft YaHei\", sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.6
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", \"PingFang SC\", \"Noto Sans CJK SC\", \"Microsoft YaHei\", sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.9
  ui:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", \"PingFang SC\", \"Noto Sans CJK SC\", \"Microsoft YaHei\", sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", \"PingFang SC\", \"Noto Sans CJK SC\", \"Microsoft YaHei\", sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
  auxiliary:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", \"PingFang SC\", \"Noto Sans CJK SC\", \"Microsoft YaHei\", sans-serif"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.5
  code:
    fontFamily: "\"SFMono-Regular\", Consolas, \"Liberation Mono\", monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.9
  review-body:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", \"PingFang SC\", \"Noto Sans CJK SC\", \"Microsoft YaHei\", sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.9
rounded:
  sm: "5px"
  md: "8px"
  lg: "12px"
spacing:
  step-1: "4px"
  step-2: "8px"
  step-3: "12px"
  step-4: "16px"
  step-5: "20px"
  step-6: "24px"
  step-8: "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent-solid}"
    textColor: "{colors.on-accent}"
    typography: "{typography.ui}"
    rounded: "{rounded.md}"
    padding: "5px 11px"
  button-secondary:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.text-primary}"
    typography: "{typography.ui}"
    rounded: "{rounded.md}"
    padding: "5px 11px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    typography: "{typography.ui}"
    rounded: "{rounded.md}"
    padding: "5px 11px"
  button-icon:
    textColor: "{colors.text-muted}"
    rounded: "{rounded.sm}"
    padding: "7px"
    size: "30px"
  field:
    backgroundColor: "{colors.surface-input}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: "9px 11px"
  nav-item-selected:
    backgroundColor: "{colors.selection}"
    textColor: "{colors.selection-text}"
    typography: "{typography.ui}"
    rounded: "0px"
    padding: "0 4px"
    height: "22px"
  badge:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.text-secondary}"
    typography: "{typography.auxiliary}"
    rounded: "{rounded.sm}"
    padding: "1px 6px"
  context-chip:
    textColor: "{colors.text-secondary}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "2px 0"
  composer:
    backgroundColor: "{colors.surface-input}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: "11px 10px 9px"
  comparison-container:
    backgroundColor: "{colors.surface-toolbar}"
    textColor: "{colors.text-primary}"
    typography: "{typography.review-body}"
    rounded: "{rounded.md}"
    padding: "16px"
  project-picker:
    textColor: "{colors.text-primary}"
    typography: "{typography.ui}"
    rounded: "{rounded.md}"
    padding: "0 4px"
    height: "30px"
  nav-view-tabs:
    textColor: "{colors.text-muted}"
    rounded: "999px"
    padding: "4px"
    height: "24px"
    width: "24px"
  qaec-section:
    textColor: "{colors.text-primary}"
    typography: "{typography.review-body}"
    padding: "25px 0 20px"
  source-references:
    textColor: "{colors.text-secondary}"
    typography: "{typography.label}"
  slide-preview:
    backgroundColor: "{colors.surface-toolbar}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: "34px 42px"
  question-status-compact:
    textColor: "{colors.status-review}"
    backgroundColor: "{colors.status-review-bg}"
    typography: "{typography.auxiliary}"
    rounded: "3px"
    padding: "0 4px"
    height: "16px"
  workspace-tab-active:
    backgroundColor: "{colors.surface-editor}"
    textColor: "{colors.text-primary}"
    typography: "{typography.ui}"
    rounded: "8px 8px 0 0"
    height: "40px"
---
# Design System: AcaPartner Workbench v0.17

## Overview

本规范用于当前统一科研工作台。共享视觉实现位于 `frontend/src/workbench/theme/`，页面行为见[工作台指南](workbench-guide.md)。前置令牌定义当前颜色、字号、间距与圆角；删除旧版工作桌和原型不改变这些视觉值。

首页与 `/workdesk/editors.html?project=项目ID` 共用统一工作台。论文直达入口打开当前论文主源，并尊重恢复的活动标签；两处沿用相同的左侧项目树、中央连接标签、右侧项目搭档与底部状态栏。

Apple UX 原则、熟悉的 IDE 导航和安静的文档阅读构成方向。保留左侧导航、中央内容与连接标签、右侧项目搭档；底栏仅显示服务、内容地址、用量与设置。组件使用真实状态，任务完成与科学结论分开，界面继续依据实际使用反馈调整。产品边界见 `docs/product/README.md`，实际文稿能力见 `docs/architecture/document-adapters.md`。

## Colors

默认浅色以中性外框衬托白色内容面；暗色以独立中性阶调保持同样的角色关系。精确颜色只以前置令牌为准。

### Primary

- `accent-solid` / `on-accent`：主要按钮和发送动作；`accent`：交互链接、分隔条反馈与示意图曲线。
- `focus`：键盘焦点和输入容器焦点边界；`selection-ink`：文字选择。活动文件使用中性 `selection` / `selection-text`，不与文字选择混用。

### Secondary

- `success`、`warning`、`danger` 与各自 `*-bg`：配合文字的状态反馈；success 也用于示意图的第二条曲线。
- `status-review` / `status-review-bg`：待判断的紫色文字与背景；浅色使用无前缀键，暗色使用 `dark-*` 对应值。阅读页与详情中的状态带文字和原因提示；图节点以颜色与符号概括，可访问名称保留状态文字。不把颜色当作可信度评分。

### Neutral

- `surface-app`、`surface-nav`、`surface-agent`：安静的工具外框；`surface-editor`：中央阅读面。
- `surface-toolbar`：局部工具与比较背景；`surface-input`：输入和对话框；`surface-hover`：悬停、活动标签与次要按钮；`surface-raised`：用户消息。
- `text-primary` 承载正文，`text-secondary` 用于引导与次级操作，`text-muted` 用于目录分组、图标、来源，`text-placeholder` 专用于占位符。`border` 用于输入，`border-subtle` 用于内容边界。
- 无前缀键为默认浅色，`dark-*` 为暗色精确对应值。运行时 `[data-theme]` 将两套值映射为相同 CSS 属性名，例如 `--surface-editor`，而非 `--dark-surface-editor`。

**The Semantic Pair Rule.** 切换主题时替换完整语义颜色组，组件不混用浅色与暗色的局部值。

## Typography

**Body / UI Font:** 使用前置令牌中的系统无衬线栈，包含 Windows、中文与通用回退。
**Label/Mono Font:** 代码使用 SFMono-Regular、Consolas、Liberation Mono、monospace。

### Hierarchy

- **Headline**：文档与任务标题（650，28px，行高 1.5）；窄屏为 25px。
- **Title**：阅读次级标题（600，17px，行高 1.6）；任务次级标题另用 16px。
- **Body**：基础正文令牌（16px，行高 1.9）；当前文档与研究阅读面局部使用行高（1.8）。正文使用 primary，导语使用 secondary。研究进展顶部摘要与节点正文（13px）、详情正文（14px）收紧节奏；这些是当前表面的局部分工，不扩充基础字阶。
- **UI / Label / Auxiliary**：操作与文件名（13px）、标签与目录分组（12px）、来源和状态（11px）。消息为 UI 字号、行高 1.85。
- **Code**：等宽源码（13px，行高 1.9）；笔记源码使用系统字体（15px，行高 1.95）。候选审阅正文使用 **Review body**（15px，行高 1.9），保留标题与列表层级。

**The Reading Rhythm Rule.** 紧凑操作与长文阅读使用独立字阶；弱化工具装饰，不弱化正文可读性。

## Layout

此表面采用左导航、中央内容、右 Agent 三块完整面板；四周外距（4px），各面板细边框（1px）与四角中圆角（8px），间隙（6px）提供居中三点拖柄与键盘调整，不另设系统标题栏。左栏首行类别导航、中央首行标签、右栏首行标题及控制均高（40px）；左栏上下文工具、中央实际工具栏、右栏讨论 / 委托次行均高（36px），状态栏（26px），面板内容独立滚动。没有已保存宽度时初始侧宽（280px / 350px；导航 CSS 默认值为 280px），中央最小宽（260px）。导航可调（180–380px），Agent 可调（300–520px），保存宽度优先，运行时按可用宽度收缩；键盘每步调整（12px）。

阅读区最大宽（780px），内边距（32px 48px 72px）；次级标题前后留白（30px / 10px），段距（16px）。基本间距见前置 4px 步阶；光学微调不强行取整到该阶。宽度不超过 1100px 时缩减阅读左右留白、隐藏部分辅助说明，比较改为单列；不超过 800px 时中央满宽、一次按需覆盖一侧栏，隐藏分隔条，阅读边距（24px 22px 50px）；窄屏 Agent 覆盖工作区可用区域。窄屏不再保留独立的 76px 全局顶栏；中央面板以标签首行（40px）开头，有实际操作时接工具栏（36px）。面板仍保留四周外距（4px）、细边框和四角圆角。宽度 801–1100px 默认收起 Agent，打开一侧面板会收起另一侧；不超过 800px 时继续使用覆盖侧栏，导航与 Agent 均在工作区四边内缩（4px）、宽度自动填满，避免侧边露出可操作正文。这些结构尺寸用于当前工作台外壳。

左栏首行依次为收起、主页、项目、机器、智能体图标；当前类别以中性 selection 表面、accent 图标和明确按下态呈现；收起控件之后使用细竖线分组。每类拥有自己的侧栏：主页列项目与运行环境；项目显示结构 / 文件视角；机器列概览、本机与 SSH 配置；智能体列概览、接口与模型配置。项目图标返回最后的项目对象，不把跨项目页面伪装成项目树。

左栏第二行左侧为标题，右侧为搜索与新建。项目模式左侧依次为项目选择器及紧随的显微镜 / 文件药丸；搜索使用自动左外距，将搜索与新建作为一组推至行尾。主页、机器、智能体模式同样标题在左、搜索与新建在右；设置显示自身类别标题与专属导航，隐藏搜索 / 新建。搜索也可通过 Cmd / Ctrl + K 打开，按当前类别查询项目、机器、智能体或当前项目对象。新建浮层明确类型与归属：主页 / 项目在当前项目建立研究问题或笔记，文件视角在已选目录建立笔记并显示精确目标路径，机器添加 SSH 配置，智能体添加接口配置，不提供未实现的项目或目录创建。

项目导航不重复项目名根节点。默认结构视角直接呈现“研究”“交付”“笔记”三条可收起父枝：研究下为问题与递归子问题，交付下为稿件、汇报及其章节或页面，笔记汇集用户建立的笔记对象，不论其路径。文件视角按实际演示路径组织同一批对象。树容器顶部内距（8px），普通树外距（2px 0 8px），顶层父枝之间留白（8px）。问题以原生嵌套 UL / LI 表达父子关系，默认展开全部子问题，仅有子节点的问题提供展开控件；展开与打开对象分别操作。所有树共享紧凑行（22px），名称单行截断，完整名称、路径和状态原因通过提示保留，状态固定在右侧。每层缩进（8px，由左外距 6px、竖线 1px、内距 1px 组成），只显示竖向导线，不画水平支线。结构视角的研究父枝不混入 A / E / C、背景或材料目录；这些对象仍可由文件视角按路径访问。

项目概览使用中央面板全宽与可用高度：顶部为项目名、简短当前认识与实际工作提示；当前认识标明真正提供结论的叶 Q 编号（本例为 Q1.3），研究进展图占据主要空间；底部保留项目内容、背景、材料与记录、论文源稿入口。项目标题提供根上下文，画布不重复绘制项目根 Q，后端根对象保留。桌面与手机使用同一从左向右的连续画布：已完成 Q 初次收起、未完成 Q 初次展开，手动选择和镜头按项目记住。点击父Q卡片的独立箭头展开或收起子Q，点击叶Q箭头展开或收起已有AEC；点击卡片主体只选中并阅读详情，点击 A/E/C 读取详情及直接关联；不切换子图。初始镜头优先保持顶层 Q 可读，展开内容可能在屏外，通过平移、缩放、明确聚焦或查看全局继续阅读。返回上一视角恢复此前明确动作的镜头及展开快照；恢复默认展开重新按完成状态折叠。详情固定覆盖画布下部，正文与修订记录各自滚动，打开或关闭不缩小画布或自动重置镜头。外壳、左树、右侧搭档、标签与底栏保持原有语言，图使用 React Flow 承担鼠标、触控板与触摸平移缩放。原有 QAEC 记录编辑页继续连续阅读，最大宽（820px），内边距（28px 40px 56px）；1100px 以下内边距（26px 28px 50px），800px 以下为（24px 22px 48px）。项目概览与无实际操作的交付根页面隐藏冗余工具条；问题页不在标题上方重复上下文行，项目及父问题链接放入工具条，背景入口放入 Q 段。800px 以下问题标题使用完整横向空间自然换行，“添加子问题”置于标题下方，顶部留距（4px），不挤占标题宽度。
当前演示将草稿、选区、讨论、委托与来源核对状态按项目保存在 v3 浏览器存储；旧 v1 记录仅读取，后续修改写入 v3。主题与侧宽是共用偏好。机器与智能体配置及各类选中项保存在跨项目 vault.runtime；全局管理页面作为固定标签打开，不替换预览槽。v0.17 继续使用同一 v3 存储键，概览仍使用稳定 overview 身份，只改变项目内显示名；按问题记住段落定位，使用 collapsedQuestions 保存父节点收起状态，旧 projectTreeCollapsed 与 root:files 根收起状态不再控制展示；研究、交付、笔记父枝分别使用 structure:research / structure:deliverables / structure:notes，材料、文件路径及交付物分类继续保存各自收起键。旧交付视图映射到结构视角，旧文件视角保留；打开问题或交付对象时显露相应结构祖先；从树或搜索打开问题会在研究图内定位。视角切换只重画导航，保持当前正文、标签、草稿、编辑模式与选区，项目概览链接不重置视角；每个项目按标签保存 scrollPositions，切换标签、刷新与项目切换后恢复阅读位置；明确打开原有 QAEC 记录时仍从页首进入，不把旧论证位置误当新入口；只有保存值与草稿都精确匹配已知旧默认时才刷新演示内容，用户改写不被替换。这是本地交互边界，不是生产数据迁移或真实文件系统合同。

## Elevation & Depth

通过中性表面、内容边界和留白形成主层级。项目选择、新建和状态浮层、对话框与 toast 使用 `--shadow`，精确明暗值见 `frontend/src/workbench/theme/tokens.css`；对话框遮罩为 `#10111640`。按钮、输入和分隔条使用短过渡（160ms）；toast 使用 ease-out 的轻微进入。项目、新建及状态浮层使用局部裁切揭示（140ms，ease-out），不增加玻璃或常驻模糊。减少动态效果偏好关闭动画和过渡。源码声明但未使用的 `--shadow-input` 不提炼为组件规则。

**The Quiet Divider Rule.** 分栏使用窄间隙与居中三点把手，静止时不画持续粗线；悬停增强表面与把手，键盘焦点保持清楚。

## Shapes

基础圆角仍用于图标、按钮、字段、消息与对话框，规范刻度见前置令牌。紧凑树行与选中背景采用直角；树内状态标记使用局部圆角（3px）。三个面板在所有视口使用细边框（1px）与 rounded.md 四角（8px），无常驻阴影；中央面板裁切内部内容。标签位于面板内部首行，一般使用顶部圆角（8px）与活动标签底部两侧内凹连接（各 8px），用与 editor 相同的表面接续正文。首标签自身左上圆角为 0，活动首标签不画左侧内凹脚，由外层面板的 8px 角裁切；标签和内容一起构成面板左上角，不叠第二个圆角或留前导空隙。视角药丸使用独立的全圆外形（999px）；这些局部几何不扩充基础圆角刻度。应用、文件夹及操作图标使用 Lucide 内联 SVG，常规尺寸（16px）、描边（1.65）；文件类型图标采用下述本地 Seti 资源。

## Components

- **Buttons**：常规最小高度（30px），无常驻描边。主要使用实心靛蓝与 on-accent；次要使用 hover 表面，悬停改 selection；轻量透明，悬停显露 hover 表面。主要与发送悬停亮度（0.93）；按钮按下位移（1px），禁用透明度（0.45）。
- **Icon buttons**：触区（30px）、小圆角、muted 图标；悬停增强文字和背景。每个图标动作保留可访问名称。共享提示在鼠标停留或可见键盘焦点后延迟（450ms）出现，使用 tooltip 语义、左右边界约束与上下翻转，不截获指针；触摸不触发悬停提示，操作、滚动和离焦会关闭提示。
- **Inputs / Fields**：输入表面、中圆角、细边界（1px）、最小高度（34px）、内边距（9px 11px）；悬停强化边界，只读使用 toolbar 表面，错误使用 danger 边界与文字说明。
- **Navigation**：研究问题、文件目录、交付目录和中央材料分类使用同一个树行与文件夹呈现：固定行高（22px）、UI 字号（13px）、对象图标（13px）、展开触区宽（12px），名称单行截断并保留完整提示。当前对象以直角整行 selection 背景标记，状态独立靠右。仅父节点有展开控件；问题子节点默认展开，收起状态可恢复。目录键盘上下 / Home / End 在可见行移动，右键展开或进入子项，左键收起或返回父项；焦点所在行使用 hover 表面，当前对象仍保持 selection。左栏上下文行的视角药丸使用 hover 表面、内距与间隔（各 2px）、局部圆角（999px）；药丸总宽（54px），两个图标标签各（24px × 24px），内距（4px）、SVG（15px），选中态使用 input 表面与 primary 文字。它使用 tablist / tab、单一可 Tab 焦点与 aria-selected，方向键及 Home / End 切换并显露对应视角。研究、交付、笔记、文件目录与全局配置树均不显示分支加号；左栏新建按钮与树节点菜单按当前位置提供创建入口，明确类型及目标，不提供独立目录创建功能。历史组件键 nav-view-tabs 保留为该视角切换身份。
- **Tree ordering / Alignment**：文件与笔记路径树的每层先目录、后文件，各组按数字自然序、不区分大小写排序。根层叶子不占展开控件空位，嵌套层保留同级对齐与缩进；研究类别与问题保留原有作者顺序。

科研问题按每层的 `metadata.workbench.order` 排列，旧问题无该字段时按建立顺序补位；编辑标题或QAEC不改变顺序。左树、概览、标签与搜索显示Q1、Q2和Q1.1等层级编号，编号由当前可见结构派生，不写进问题标题或替代稳定对象ID。新问题追加到当前父节点末尾；归档后可见编号重新连续排列。编号保持完整，长标题仍可截断并查看完整提示。
- **Chips / Badges**：状态使用辅助字号、文字和状态色对；上下文首项透明，后续选区项使用 hover 表面，长文本截断。静态状态不添加虚假点击反馈。
- **Cards / Containers**：比较内容使用 toolbar 表面、subtle 细边界、中圆角和内边距（16px），无常驻阴影。新增与移除摘录分别使用 success-bg 与 danger-bg，并提供文字标记；完整前后版本在原生 details 中展开。提示使用 toolbar 或 warning 背景。
- **Composer**：中圆角输入容器，内距（11px 10px 9px），focus-within 使用 focus 边界；输入提供多行编辑与内部滚动。空白输入禁用发送并使用 hover / muted 中性色，保留不透明控件而非实心强调色。一个输入支持讨论与有范围的分析，来源摘要明确列出将读取的保存内容；不把当前文件名或临时选区冒充已经读取的正文。无可用执行服务、只读权限、正在处理或提交结果未确认时，提供对应状态与恢复操作。发送按钮为圆角方形（27px，圆角 8px）。通用键盘焦点（2px，偏移 -2px）；输入文本区由容器提供焦点反馈。

### Scoped Creation / Personal Notes

项目树的“+”与节点菜单使用同一目标规则：选中可写目录时在目录内新建，选中文件时在父目录新建，选中研究问题时建立其子问题。笔记位于 `notes/`，Python 工作副本仅位于 `scripts/` 直属目录；交付入口仅添加尚不存在的 DOCX / LaTeX 源稿。无选中项时列出类型与各自目标。登记快照与系统目录明确说明只读，不伪装成通用文件管理器。

节点菜单复用 Radix Context Menu、既有中性表面、selection 高亮与 danger 删除文字；支持右键及 Shift + F10。菜单提供复制路径 / 名称（研究问题复制 ID）；重命名仅适用于笔记，先检查受影响的相对链接，正文不自动改写。删除前显示确认，初始焦点放在取消；笔记与 Python 工作副本移到回收站，研究问题归档，默认论文不可删除。笔记子目录操作只逐篇回收其下 `.md` 笔记。未保存的笔记或脚本先经版本校验保存，冲突时停止；通知提供撤销，回收站在刷新后仍可恢复。

### Project Picker / Workspace Tabs

项目名按钮位于左栏第二行左侧，单行截断，视角药丸紧随标题；搜索与新建位于该行右侧；项目列表通过原生 popovertarget / popover 切换，重复点击选择器可关闭，选中项提供 radio menu 状态。中央面板的第一行容纳内容标签（40px），活动标签与正文使用相同 editor 表面，不再跨三栏放置全局标题栏。实际文档工具栏在标签下方，概览与管理根页隐藏无动作工具栏。单击文件或搜索结果在一个可替换预览槽位中打开，只有标签名称使用斜体；双击文件或标签固定并恢复正体。已固定标签不会被单击改回预览，开始编辑、修改或保存也会固定；旧固定标签与草稿保留，预览替换不覆盖脏稿。标签在固定内容栏内分配可用宽度，不由文件名长度决定：flex（1 1 240px）、最大宽（240px），非活动最小宽（28px）、活动最小宽（64px）。标签区 gap 与左右内距均为 0，各视口行高均为 40px；首标签贴齐面板左缘。标签文字使用 UI 字号（13px），完整 aria-label 与标题提示保留可访问名称。单标签容器不宽于 110px 时收紧内距并隐藏非活动关闭按钮；不宽于 80px 时活动标题让位以保留关闭；不宽于 64px 时非活动标题隐藏、保留对象图标，脏稿标记仍保留。关闭按钮在可用时保持独立焦点。常规数量共同收缩，极端超量只在固定条内横向滚动，不撑宽工作区；仅活动标签被裁切时调整滚动，容器 ResizeObserver 覆盖拖动分栏导致的变化。正文标题不使用预览斜体。隐藏导航或 Agent 时，恢复按钮统一位于标签行右端，不再占据标签前方；主题入口统一在状态栏。跨项目主页、机器、智能体与设置页面使用固定标签，项目图标返回最后访问的项目对象。

### Search / Interaction Feedback

搜索输入采用 combobox，结果采用 listbox / option；焦点留在输入，aria-activedescendant 指向当前选项，选中行使用 selection 背景。上下键移动、Enter 打开当前结果，底部显示结果数和键盘提示；无结果时给出清楚标题与缩短关键词 / 切换视图的下一步，不留下空白面板。搜索仍按当前类别取范围，不声称完整实现所有辅助技术规范。

桌面保留紧凑树行（22px）；窄屏粗指针设备单独扩大触区，类别按钮（36px）、工具按钮（28px × 32px）、药丸按钮（32px × 30px）、展开触区宽（24px）、树行（30px），触摸屏标签关闭动作持续可见。触屏规格属于输入设备适配，不改变桌面密度与基础间距刻度。减少动态效果偏好关闭动画、过渡和滚动动画。

### Status Bar / Settings

底栏仅保留三组：左侧服务连接状态，中间当前内容地址，右侧依次为 Token 用量、设置、明暗切换，共四个按钮（26px 高，左右内距 8px，窄屏 6px）。两侧使用等宽弹性列，中间地址保持几何居中；地址随当前项目、文件、QAEC 定位和全局页面更新，单行省略并通过标题提示与可访问名称保留全文。图标与文字控件高（22px）；设置选中态使用 hover 表面。底栏不显示保存、草稿、数量或选区等额外项目。

本地保存、草稿与存储失败反馈归属当前内容工具栏，使用辅助字号，失败使用 danger 文字；在窄屏论文页改在标题下的信息行显示。隐藏的辅助技术 live status 同步播报，底栏地址保持原位。搭档来源贴近输入显示；未保存的临时选区尚不进入本轮读取合同。

服务与 Token 使用原生 popover，宽（320px）、内距（16px）、中圆角与现有 shadow，窄屏不超出可用宽度。服务状态取当前服务与运行器查询；已保存的 SSH / 模型偏好不等于已建立连接。Token 取实际任务回执，缺失用量或费用保留未知。不把配置数量、主题切换或浏览器存储冒充真实在线服务或使用量。

设置以固定全局标签打开，拥有“常规、服务连接、帮助与快捷键”侧栏；此上下文隐藏搜索与新建。常规页说明外观和本地存储，并提供组件参考；服务页复用连接详情。帮助与快捷键集中在设置侧栏，不在导航底部、底栏或搭档输入区重复铺设；发送快捷键保留在发送动作提示。主题按钮仅保留在应用底栏，面板顶部与恢复区不重复。

### Workspace Contexts / Local Configuration

主页、机器、智能体页面沿用已有阅读字阶、输入、表格与对话框语言，不建立新的视觉体系。管理阅读面最大宽（900px），内距（32px 40px 56px）；中等与窄屏分别沿用（26px 28px 50px）和（24px 22px 48px）。配置列表使用细底线表格，详情以标签和文本纵向组织，长地址可换行；空态与未连接说明使用 muted，不显示虚假的在线颜色或指标。

SSH 配置包含名称、地址、端口、工作目录；智能体包含名称、接口地址、模型，侧栏选中后中央显示详情及编辑。原生对话框宽（470px），外层上下内距（8px）；字段区左右内距（24px），标签留白（14px / 7px），操作区（16px 24px 16px）。字段复用现有 field 与校验状态。仅在浏览器保存配置和跨项目选中项，不连接 SSH、不读取实际机器指标、不调用 API，密钥未实现；保存失败明确说明仅保留当前页面。具体保存与接入边界见当前实现记录。

### Research Questions / Original QAEC Records

当前主图以项目为唯一根入口，父 Q 组织 Q1、Q1.1 等子问题，不直接拥有 A 或回答 C；叶 Q 承载一条或多条独立 A 路线，综合判断放在最后一个明确的叶子 Q；A/E/C 各自保留身份、正文和修订。项目名在页头提供上下文，后端根对象保留，画布不重复绘制根 Q；不把论文标题或背景改造成科学问题，不强制补齐根 QAEC。原总体研究问题从“项目内容”抽屉的“原有研究记录与历史”进入。独立节点与原 QAEC 记录的职责见[领域词表](product/glossary.md)。

原 QAEC 编辑页继续保留连续四段阅读，用于原记录与旧候选合同，不作为自由图的四槽模板。每段以字母窄栏和正文栏形成网格（22px / 自适应，间隔13px），使用 subtle 顶部分隔与留白；字母使用 UI 字阶，正文使用 review-body（15px）。窄屏字母栏与间隔为（18px / 9px），段落留白（25px 0 20px），定位滚动上边距（64px）。页内导航在阅读容器顶部吸附，当前位置使用 accent、字重（550）与底部细线（2px）；滚动同步定位、标签和搭档上下文，不切为互斥面板。

原问题页标题下显示状态和保存版“当前认识”，随后为“依据、正在进行、下一步”。认识摘录逐字取 C 首段，最多120个 Unicode 字符；仅首段被截短时追加省略号，有后续正文则明确标记“结论摘录”并提供全文定位。无 C 时显示 Q 或自由记录提示。摘要不改写原判断；引用子问题结论不替代父判断。段前文字、无法识别或重复段标的自由文本均完整保留，不要求为开始工作补齐四段。

### Question States / Free Research Graph

自由图沿用现有editor/toolbar中性表面、细边界、accent、focus和状态色，不新增调色板或装饰阴影。图标题标明“最新版本”；节点为带保存内容的卡片：首行编号与状态、两行内的标题、正文摘录或表格节选，底部说明子问题/工作/依据数量。卡片使用12px圆角、1px边框、14px内距；固定宽256px，Q/A/C高180px，表格型E高212px。标准标题14px/20px，摘录12px/18px，编号12px，状态与说明11px。主卡片为阅读按钮，选中以accent细线表达，状态只作用于小图标和文字，不整片着色。焦点使用既有focus令牌；触摸披露按钮在当前缩放下保留44px触区。

问题使用Q1/Q1.1编号，AEC随所属叶Q，例如A1.3-1/E1.3-1、A1.3-2/E1.3-2汇入C1.3；编号是投影，稳定ID、内容和修订不变。父Q卡片说明直接子问题及有效已回答数；叶Q说明分析/结论数量；A显示保存的方法摘录及是否已有结果，C显示正文摘录与声明依据数量。E复用Markdown解析器读取保存表格，预览最多四行，宽表保留首列与末列；列或行未完整呈现时明确标“节选”，计数与原有分母不改写。无正文显示未记录内容，代码/公式等非段落正文提示点击查看，不冒充空内容或新推断。

缩放不重新排版：80%以上显示两行摘录或最多四行表格；60%至80%保留一行摘录或两行表格并标明节选数量；40%至60%只保留编号、状态图标和两行标题；更远缩放保留一行短标题。编号与标题在缩远时提高相对字号，卡片宽高、端口和坐标始终不变。布局与避让按矩形真实边界计算；单一路线沿同一行，独立并行分析按编号分行再汇合，复用Graphviz计算路径。

点击卡片主体只选中并打开下部详情，不切换子图或改变展开状态。Q卡片右下独立箭头控制子Q或已有AEC，原生Enter/Space可操作，重复点击可收起；箭头与阅读按钮分别有可访问名称。拖动画布或卡片主体平移，普通滚轮以指针为中心缩放，触摸捏合保持可用，拖动不会改变科研对象位置。已完成Q初次收起，未完成Q初次展开；既有折叠与草稿按项目保留，卡片版本首次使用重新建立镜头。明确“聚焦所选节点”可放大阅读；桌面Q可聚焦可见工作，窄屏和AEC聚焦选中卡片，其他节点仍留在原画布，查看全局适应全部可见内容。

节点记录待开展、进行中、待确认、已完成或暂缓，兼容未标记旧内容；进行中使用 accent，待确认/待复核使用 warning，完成使用 success。人工进度、派生完成有效性与科研判断分开；任务成功、正文存在、父子状态或填满节点均不推断完成。树内原问题状态继续使用紧凑标记（行高16px、内距0 4px、圆角3px），不能把旧字段状态当成独立图节点确认。

画布用淡色分区框表达顶层 Q 的问题归属，复用 subtle 边界（1px）与现有大圆角（12px），不形成浮起卡片。顶层 Q 保持同列，各分支按数字顺序排列，展开的独立叶 Q 及其工作一起排位，综合工作位于可见前置工作之后。父子层级使用灰色、无箭头的正交线；依赖使用引擎路由的定向线，已兑现为实线、待推进为虚线。Q1.1、Q1.2 共同先于 Q1.3，兼容连线通过共享主干分叉或汇合，进入同一目标的共享尾段只保留一个箭头；端点展开时，类型、方向、兑现状态不同的关系不共用主干，受阻或不规则路径保留独立路由。折叠时，隐藏端点映射到可见的收起 Q，多条同向同端点关系可汇总为一条显示路线；仅全部真实关系已兑现才显示为已兑现。菜单保留实际类型、端点和各自兑现状态，汇总不新增研究关系或归属。共享 A/E/C 经任一展开的所属问题路径保持可见。节点位置不因合线改变，几何接点不画成科研节点；原生正交顶点仅作最大5px的局部圆角。重复的父→综合子 Q 归属线默认隐藏，仍可从父问题完成依据旁的关联按钮检查原关系。同一画布中的其他语义关系按兑现状态使用实线或虚线。叶 Q→A 看分析完成，A→E 看分析及结果完成，E→C 看当前证据和结论核对完成，前置 Q→后续 Q 看前置 Q 完成；点击共享主干或折叠汇总路线，或在线上按 Enter/Space，使用既有 Radix 菜单按编号列出真实关系；选择后高亮完整逻辑路径，详情列出端点、版本和依据，Escape 返回原 SVG 连线焦点。菜单使用既有表面、字阶与选中态，经 body portal 显示；触屏/窄屏行高至少44px。关系标签只在菜单与详情中显示，不覆盖短尾线。`answers` 回指默认隐藏，工具栏可明确显示。线条不替代科学支持判断。布局采用本地 Graphviz，React Flow 使用引擎返回的节点、路径和端口，具体边界见[布局接入](architecture/research-graph-layout.md)；节点不拖动、不直接拉线，关系通过详情表单建立或撤回并保留历史。

点击卡片主体在详情显示完整标题、状态和最新正文。详情固定覆盖画布下部，标题行高紧凑，正文独立滚动，打开与关闭不改变画布尺寸或自动重置镜头；“编辑与状态”复用现有输入、选择框、CM6 和按钮，“关联已有节点”要求说明关系含义，“引出新节点”按类型提供入口，父 Q 只提供 Q，叶 Q 提供 A 或 Q。已有 AEC 的叶 Q 新建子 Q 时，表单明确提示“原样迁入、历史保留、完成确认需重新核对”，使用“拆分并迁移”动作；旧混合父 Q 提供同一整理入口，不能新增混合关系或确认完成。提示沿用 label 字号（12px）、secondary 文字与既有输入/按钮，不另建警告视觉体系。完成需具体标题、非空正文、核对依据及准确依赖签名：E 有唯一已完成 A，C 有明确已完成 E，叶 Q 有已完成回答结论和所声明前置 Q；父 Q 的全部直接子 Q 及所声明前置 Q 已完成，无直接 A 或回答 C。两类 Q 均须自己的核对说明、准确依赖签名和足以作答确认；父 Q 勾选文字为“子问题的结论足以共同回答父问题”，不由子 Q 完成自动提交。父→子 `contains` 在完成条件中反向绑定每个子 Q→父 Q 的签名，变化沿父层级传播待复核。叶 Q→A 绑定问题范围而不等待 Q 完成；完成依赖和拆解分别无环，语义回指允许保留。版本、来源、范围或关系变化使当前确认及下游待复核，旧内容与确认保留，恢复旧文字仍需复核。

历史只在只读检查器中读取对象保存版，提供“更早版本”和“返回最新版本”；主图始终保持当前版本。节点、项目或详情状态变化会使旧读取失效，晚到历史不进入新选择；历史页面不显示编辑动作。原 QAEC 编辑器继续保留原记录的比较入口。新建与编辑草稿按项目、浏览器窗口及节点保留，切换、关闭、取消或刷新后由工具栏“草稿”恢复，可下载或明确删除；保存冲突保留输入，存储失败提示下载。草稿与保存反馈归当前内容，底栏不增加项目。

旧项目的“导入研究图”只在明确操作后提取已有 AEC；保留原 Q 身份、全部正文与历史、论文和笔记，父 Q 原有 AEC 整理到末尾子 Q，不为空槽创建假结果；整理保留 A/E/C 身份、正文与关系历史，范围变化需重新核对，仅已认证且满足新条件的旧完成记录可在迁移时转移。授权 Agent 通过[独立图 API](research-workflow/research-graph-api.md)操作相同对象，GUI 搭档的有限图变更直接刷新同一画布；省略图模式的旧搭档任务和旧工作候选仍是每 Q 一组 QAEC，尚未自动映射为多 A 图。页面载入只读，不触发模型或生成内容。

### Project Companion

右侧是项目上下文、讨论草稿与逐轮有限任务入口。新消息可将有来源的临时研究结构直接保存到现有图；普通讨论可只回复。图变化的回执留在回复中，科学完成仍在节点详情核对。本机文件交接提供隔离副本、提交和新版载入，未接入的 SSH 执行明确显示不可用。普通任务状态和科研问题的证据/判断分别表达，不使用模拟成功冒充实际执行。

### Sources / Deliverables

项目默认保留论文。DOCX 与 LaTeX 分别保存，主源通过明确操作绑定；打开本地文件生成独立标签。DOCX 的工具栏、评论、分页与导出交给 SuperDoc；宿主保留单一浅色命令栏和文件动作，文稿纸面保留源文件的颜色与排版，不把上游页型刻度改成全局 UI 令牌。

文件与项目保存、下载副本、编译 PDF、恢复草稿采用各自的明确动作。批注按内容显示，无审阅内容时收回空列。各能力和未实现边界见文稿适配记录。

### Code and file surfaces

编辑中的代码使用 CM6 与其语言解析器，按文件名识别并延迟加载；编辑器 GitHub 明暗主题跟随工作台。阅读中的代码块使用 Shiki TextMate 语法与 `github-light-default` / `github-dark-default`，保留 DOMPurify 与来源定位约定。未知语言和资源失败采用纯文本。

文件树、文件标签和搜索结果共用本地 Seti 图标与文件名映射；图标占 16px 方框，沿用原字体 150% 绘制比例。文件夹及操作按钮沿用 Lucide。差异比较复用 `@codemirror/merge`，明确标注保存版与当前草稿；比较本身不保存、执行或采用研究结果。

## Do's and Don'ts

### Do:

- Do 通过语义 CSS 变量同步表面、文字、选择、状态和焦点的主题变化。
- Do 保留长文件名截断、全文名称提示、正文换行和面板独立滚动。
- Do 为鼠标、键盘和错误状态提供清楚反馈，状态同时提供文字。
- Do 清楚标记本地演示；讨论回复和候选不冒充真实科研执行。

### Don't:

- Don't 将视觉示例当作已实现能力或科学验收结论。
- Don't 把用户授权实施调研方向表述为用户批准了当前像素身份。
- Don't 为装饰扩大强调色覆盖、堆叠常驻边框或把正文变成卡片墙。
- Don't 将研究截图、QA 截图或未批准的生成图加入工作台运行资源。


### 项目接手与统一搭档输入

项目概览先展示保存版当前认识与研究进展图，实际工作提示和“一起确定下一步”入口服务接续。空项目邀请描述想法或直接记录问题；已有内容允许先阅读再讨论。新进入首页时先打开记住且当前可见的项目，没有可用记录时选择最近更新的可见项目；切换项目回进展图，浏览器刷新尊重工作标签与草稿。背景、材料、论文与项目内容保留直接入口。

右侧“讨论与工作”共用输入和真实回复；“记录”保存历史。来源摘要贴近输入，展开说明当前图摘要及实际采用的 Q、登记材料和原生保存版；勾选状态与提交一致，未保存草稿明确提示。画布选中节点的编号与标题放在输入框内上方，沿用 secondary 与 label 字阶，长名称单行截断并保留可访问说明。执行路线和时限放入次级折叠项，不在发送前弹出独立设置表单。提交不确定时冻结原消息并提供同请求核对；运行、失败、图应用、冲突及撤销使用可读中文状态。

用户消息使用 raised 表面，搭档正文直接落在侧栏表面。图变更回执以 subtle 顶部分隔、原有小字阶与留白接在回复下方；“研究图已更新 / 本轮未修改研究图 / 本轮图变更已撤销”使用 primary 字重，节点数量和说明使用 secondary，错误使用 danger 并以 alert 播报。查看画布、撤销本轮、按当前图重新整理沿用文字动作和 Lucide，不增加成功横幅、浮起卡片或新的状态色。回执通过 status 播报，撤销期间原生按钮禁用；小于600px或粗指针时动作触区至少44px。旧候选入口继续用细线与文字表示，中央保留既有版本比较与局部采用组件。

输入为13px、行高1.85。此扩展复用前置令牌、明暗语义颜色、字体、焦点与原有三栏尺寸；不增加全局令牌或入场动画。桌面保留中间的连续研究画布与右侧回复，手机沿用既有 Agent 覆盖侧栏及相同横向画布。直接保存结构沿用内容卡片、独立披露箭头或Graphviz共享连线语言；E/C 待核对与科学确认的界面含义保持分开。
