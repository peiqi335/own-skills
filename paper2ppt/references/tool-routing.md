# 阅读与制作能力分离

按实际能力选择工具，不按客户端名称猜测。不改变现有脚本 CLI、返回结构或代码。

## 阅读阶段

先检查来源可读性、转换覆盖与图像查看能力；优先已有 full.md 和原图，按需主 PDF 定点裁决。没有转换时用当前可用 PDF 能力或 PyMuPDF。图片忠实裁切可用 Pillow。不得使用生成图工具重建论文图。

`preflight.py` 是制作预检，不是开始阅读的前置门。缺少 PPT 工具时完成可开展的精读/讨论并说明制作限制。

## 制作前

1. 发现原生可编辑 PPT、备注、重开和渲染能力后读取对应技能合同，优先使用。通用技能中的装饰图、生成图、固定页数等默认由用户本次已明确要求覆盖；不同时套用冲突工具链。
2. 默认先调用现有制作预检，不用 `--create-output` 创建空目录；阶段所需目录明确创建后使用实际路径。
3. 原生能力不满足时，且当前宿主/技能允许，后备用 `python-pptx` 1.0.2+，备注用 `slide.notes_slide.notes_text_frame`。不绕过宿主限制。
4. 渲染优先环境渲染器，再已有 LibreOffice/soffice；不强制 GUI、不要求独立 LLM API key、不自动装依赖。

```text
python "<SKILL_DIR>/scripts/preflight.py" INPUT --output PATH [--create-output] [--native-authoring] [--native-pdf] [--json]
```

`<SKILL_DIR>` 是实际加载的技能目录。INPUT 使用已核实主 PDF/文本等受支持文件，不把证据包目录直接当脚本输入。脚本支持 PDF、Markdown/text、PPTX 模板、DOI、PMID/PMCID、arXiv 和 HTTP(S) 标识；不负责远程下载。远程标识返回并不证明全文可读，先解决实际来源访问。

脚本检查模块发现与版本元数据，不导入依赖代码；python-pptx 1.0.2+、PyMuPDF 1.24+、Pillow 10+。检查输出位置，只有显式 `--create-output` 才创建。渲染能力单独报告。

JSON 键保持 `ok`、`source`、`output`、`capabilities`、`warnings`、`errors`；退出 0 表示来源与本地制作路线预检可用，1 表示缺输入/能力/可写输出，2 为参数错误。预检通过不证明制作或视觉通过。

缺 python-pptx 时，只有实际确认原生可编辑、备注、重开及 QA 能力后才加 `--native-authoring`；缺本地 PDF 提取依赖时，确认原生页级文字和忠实图片提取后才加 `--native-pdf`。二者分别只豁免其依赖，不忽略来源或输出失败。

## 检查与故障

按 [质量门](quality-gates.md) 使用现有 inspector。原始结构报告放临时目录，汇总进中文验收文件，不直接用脚本覆盖综合记录。渲染失效时尝试现有可用路线，不能因工具报错就声称无渲染器。

缺制作能力只阻塞制作。来源失败只暂停受影响内容，不绕过访问控制；缺文件引导补充。无渲染器可以提供披露限制的结构已核验稿，但不得宣布完整视觉验收。任务路径、临时文件、版本按 [文件合同](task-files.md)。
