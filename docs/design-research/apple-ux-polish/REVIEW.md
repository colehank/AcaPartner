# v0.15 UI/UX反思与实施

2026-10-27。范围为独立科研工作台原型，沿用已确认视觉体系与产品结构。

## 问题与改进

| 观察 | 使用上的影响 | 本轮处理 |
| --- | --- | --- |
| 项目标题和工具互相挤占，标签文字偏小 | 身份和位置难扫读 | 新默认导航280px、收紧小药丸、13px标签及完整提示；已有侧宽保留 |
| 概览摘要纵向空间偏大 | 材料入口被推出首屏 | 摘要行距、段落和区间留白统一，保留完整文字 |
| 长研究页定位入口滚出画面 | 阅读QAEC容易失去方向 | 页内sticky导航、滚动高亮、64px定位避让；切标签与刷新保留位置 |
| 搜索只有鼠标选择和首项Enter | 键盘用户无法可靠选择目标 | combobox/listbox、上下选择、当前项Enter及明确空态 |
| 空发送、无效委托仍显得可操作 | 反馈滞后，需要点了才知道 | 真实禁用状态、输入自适应、方向键目录和菜单、Esc分层关闭 |
| 小图标缺少统一解释，触屏沿用桌面密度 | 学习成本和误触 | 延迟控件提示、触屏较大目标、保留桌面紧凑树 |

## 参考与取舍

参考Apple官方[Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars)、[Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)和[Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)。本轮采用的是内容优先、清楚分组、熟悉一致的操作与适配；用户已确定网页科研IDE结构，未照搬原生平台外观或Liquid Glass。

此解释是针对本产品的设计判断，不表示Apple认可本实现。SSH/API仍未接入，Token仍为0；没有改写科研判断或真实执行能力。

独立审查发现长C仍会把概览和当前认识变成全文。最终增加渐进展开：首段最多120Unicode字符的原文摘录、明确标识和完整结论入口；长文原始段落保持。对应修正评分Resolved，ship仅覆盖该项修正。\n