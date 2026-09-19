---
name: paper2ppt
description: >-
  Guide single-paper close reading, discussion, slide planning, and original-figure PowerPoint reporting. Use for 启动 paper2ppt 工作流, 单篇精读后汇报, 论文转PPT, 文献汇报, or continuing discussion, authoring, or revision in this workflow. Create an editable, source-traceable PPTX after narrative and slide-plan confirmation. Not for unrelated single-paper reading, searches, multi-source knowledge frameworks, or general-purpose decks.
---

# Paper2PPT：讲清实验，再做可靠的文献汇报

用户提供论文位置并说“启动 paper2ppt 工作流”即可。助手负责识别材料、完整阅读、讲解、提出主线与分页、制作和检查；用户负责科学判断、证据采纳及关键方案确认。默认中文。

## 核心合同

- 完整阅读正文、方法、全部图表图注及已提供补充材料，再取舍汇报内容。先交带原图的讲解：摘要中英对照 → 引言 → 主线框架 → 正文配图；覆盖和主张记录放文末，不让用户先读内部账本。
- 讲清每项实验如何产生结果：每个结果页在读图前上屏样本、分组、处理、测量与重复，缺一项该页内容验收不通过。分组表不是结果评价，读表符号也不是分组。术语、公式、单位和数字对应关系就地展开。讨论中澄清的内容回填笔记，并带入相应幻灯片，不能在制作时退化成只贴图。
- 保留原文实验依赖关系，按完整问题组织；重组时展示原顺序与新顺序的具体对照。不固定问题数、页数或论文类型，不补造因果与动机。
- 默认两个确认节点：主线确认后给逐页方案；分页确认后连续制作与验收。已有授权不重复询问，用户明确要求直接完成时可覆盖默认停点；“懂了”或含糊的“继续”不自动扩大授权。
- 主文图表默认完整展示，补充材料完整阅读后按主线安排去向。原始结果图表不重绘、不改结构；允许可编辑的分组、配样和标准对照表作为辅助解释，不能替代原始证据。
- 默认白底深蓝标题栏、简短主题标题、右上角问题归属、无页脚。图外保留足够实验解释。遵循用户参考风格，不把通用演示技能的装饰图等默认带入文献汇报。
- 区分论文事实、外部来源、教学示例和推断。标准要求、作者声称和实际结果分别核查。资料缺口只暂停受影响判断，不用常识填成论文事实。
- 原始资料只读，不自动摄入知识库或下游实验数据。修订以当前 PPT 为基准，保护用户手改。结构检查、实际看图与科学理解分别验收，不相互替代。

## 按阶段读取

启动与恢复：读 [工作流](references/workflow.md)、[引导](references/guidance.md)、[任务文件](references/task-files.md)。

- 精读与术语答疑：读 [完整精读](references/close-reading.md)。
- 主线组织：原文优先，需要候选路线时才读 [论文类型](references/paper-types.md)。
- 分页与制作：读 [排版](references/slide-design.md)、[原图](references/original-figures.md)、[工具路由](references/tool-routing.md)。
- 验收与交付：读 [质量门](references/quality-gates.md)。
- 维护本技能或做行为回归时：读 [行为验收案例](references/behavior-cases.md)，正常论文任务不额外加载。

窄范围修改只读相关规则、当前文件和来源位置，不重走全篇。阅读不受 PPT 工具缺失阻塞。制作前运行现有 `scripts/preflight.py`，`<SKILL_DIR>` 使用实际加载并解析符号链接后的目录。

默认归档 `/home/qi/文档/法医动物非人源/6.文献汇报/第一作者_年份_简短题名/`。临时文件放 `/tmp/paper2ppt/<任务标识>/<运行标识>/`；工作稿、检查点和正式版本按任务文件管理。默认中文课题组、15–20 分钟、无预设重点；这些默认不缩小阅读范围。
