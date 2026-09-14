---
name: paper2ppt
description: >-
  Guide single-paper close reading and original-figure PowerPoint reporting. Use for 启动 paper2ppt 工作流, 单篇精读后汇报, 论文转PPT, 文献汇报, or continuing discussion, authoring, or revision in this workflow. Create an editable, source-traceable PPTX after narrative confirmation. Not for unrelated single-paper reading, searches, multi-source knowledge frameworks, or general-purpose decks.
---

# Paper2PPT：完整精读、逻辑讨论与原图汇报

用户提供论文位置并说“启动 paper2ppt 工作流”即可。助手负责识别材料、引导、阅读、解释、管理文件、制作与检查；用户负责科学判断、证据采纳和主线确认。默认中文。

## 核心合同

- 完整精读先于汇报取舍：正文、方法、全部图表图注及已提供补充材料均须覆盖，不按是否进 PPT 跳读。
- 阅读覆盖、理解核查和原文定位留有实质记录；勾选、文件存在或自评不能证明理解全面。不承诺零遗漏、零误读。
- 文献已有清晰逻辑时沿用；没有清晰主线或存在断点时指出问题，由双方讨论确定，不静默补造因果、研究动机或隐藏反例。
- 先讲全貌，再聚焦讨论；主线明确确认后连续完成安排、制作和验收。“懂了，继续讲”不等于授权制作。
- 图片仅来自指定论文及补充材料，只允许忠实提取、裁切、等比例缩放和复用。禁止生成、重绘、重建机制图或外部装饰图；中文解释放图外。
- 默认白底简约、原图配文。中文课题组、15–20 分钟、无预设重点；页数不固定，默认值不缩小阅读范围。
- 科学判断或来源有缺口时，暂停受影响部分并报告，继续独立工作。原始资料只读，不自动摄入来源库、正式知识体系或下游实验材料。

## 按阶段读取

启动与恢复：读 [工作流](references/workflow.md)、[引导](references/guidance.md)、[任务文件](references/task-files.md)。

- 精读：读 [完整精读](references/close-reading.md)。
- 逻辑：原文优先，仅需后备组织参考时读 [论文类型](references/paper-types.md)。
- 制作：读 [原图](references/original-figures.md)、[排版](references/slide-design.md)、[工具路由](references/tool-routing.md)。
- 收敛与交付：读 [质量门](references/quality-gates.md)。

窄范围修改只读相关规则、决定和源位置，不重走全篇。保持已有授权，不重复询问。用户当次明确要求直接完成时可覆盖默认讨论停点，但不能省略阅读、逻辑和证据核查；原文无清晰逻辑且无已确认组织方式时，仍须提出方案讨论，不以“直接做”为任意补造逻辑的许可。

## 文件与能力

默认归档用户指定的汇报根目录下 `第一作者_年份_简短题名/`；未指定则在项目中查找 `6.文献汇报/`，找不到再询问。按阶段创建中文笔记、原图与版本化 PPT，详见任务文件。临时文件放 `/tmp/paper2ppt/<任务标识>/<运行标识>/`。

阅读和制作能力分开检查，缺少 PPT 工具不阻止阅读。制作前按工具路由运行现有 `scripts/preflight.py`。`<SKILL_DIR>` 解析为本技能实际目录，不从当前工作目录猜测脚本位置。

默认先完成精读与讨论，正常停在“待主线确认”；确认后交付实际可编辑 PPTX，不能仅给大纲。阶段进度和最终质量状态分开，等待确认不是技术失败。
