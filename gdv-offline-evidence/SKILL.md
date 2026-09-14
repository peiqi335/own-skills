---
name: gdv-offline-evidence
description: "将 NCBI GDV/Sequence Viewer 的指定基因座保存为多轨道离线 PDF、SVG 和 PNG，按已确认 CAT_1 标准加入染色体定位、RefSeq/Ensembl、RNA-seq、变异及引物示意。用于 GDV 离线增强、基因组浏览器矢量归档和引物基因座证据展示；不用于运行 BLAST、从图片猜测坐标或给出实验验证结论。"
metadata:
  target-runtime: opencode
---

# GDV 多轨道离线证据图

本技能面向 OpenCode 中执行任务的 Gemini 或其他模型。**不依赖之前的对话、Codex 私有工具或 `/tmp` 中曾存在的文件。** `assets/cat1-standard/` 是用户确认的视觉标准（含 02 区独立基因绿条）；使用真实的当前目标数据复现这个信息层级，不把 CAT_1 的数据复制到其他基因座。仓库里的 `CAT_1增强示例` 是工作副本，更新冻结目录须用户明确授权。

## 先明确交付目标

给定 GDV 链接或本地已核实的官方矢量导出，生成可断网打开的：

- `{locus_id}_enhanced.pdf`、`{locus_id}_enhanced.svg`、`{locus_id}_enhanced.png`。
- 未改动几何的 `{locus_id}_official_tracks.svg`、对应序列元数据 `chromosome_metadata.json`。
- `spec.json`、`source_notes.md`、`checks.json`，记录来源、版本、缺失轨道、坐标口径及实际检查。填写 `exons` 时另归档该 `XM_`/`NM_` 的 `product_report.json`。

默认在用户 GDV 结果目录下创建新的 `<基因座>增强示例` 或版本目录。原有 PDF/SVG 不覆盖；用户只要一个例子就只处理一个。不要自动批量更新索引、重写实验结论或推送 Git。

## 执行前必读与必看

1. 读 [操作流程](references/execution.md)，其中包括从网页到本地文件的完整步骤、工具适配和错误恢复。
2. 读 [成品标准与验收](references/quality-standard.md)，并用当前宿主提供的真实图像查看工具打开 [CAT_1 标准 PNG](assets/cat1-standard/CAT_1_enhanced.png)。必要时查看同目录 PDF/SVG。**读取文件名或提取文字不等于看过图片。**
3. 填写输入前读 [输入字段说明](references/specification.md)，不要凭字段名称猜含义。
4. 标准图只能作为布局参照；本次目标的 assembly、accession、窗口、标记、轨道及日期必须重新核实。

## 不能省略的证据规则

- 明确 `物种 → assembly accession/version → sequence accession/version → 染色体名/支架名 → window → primer markers`。未知字段不猜、不用其他物种代填。
- B1 是猫的染色体名，不是细胞遗传学带区；无权威带型数据时只画长度比例条，不能虚构着丝粒或条带。支架只标 scaffold，不编染色体号。
- 每个目标分别检查六类轨道：RefSeq、Ensembl、RNA-seq coverage、RNA-seq spanning reads、RNA-seq intron features、variants。并非每个物种都具备全部轨道。
- RefSeq 默认应对齐人/鸡/羊：尺标下独立基因绿条，其下**一行**合并转录本/CDS（深绿外显子、浅绿 UTR；XM_/XP_ 可同行）。若为 `Merge all transcripts and CDSs, no gene bar`，改成带 gene bar 的合并模式后重导，不要用 **Show all** 拆成绿/紫/红三行。绿条属于 02 区官方轨道，不是 01 定位条，也不是 03 区 `exon N`。禁止在现有 SVG 上涂绿带。Ensembl 默认仍保留官方折叠（如 `[+N]`）。
- 导出须勾 `Include Title`。渲染器要求官方 SVG 文字中出现序列 accession；缺标题就重导，不要手补标题或平移轨道。官方 SVG 导出基准宽为 **1094 px**（与 CAT_1 一致，使排版时获 ~1.44x 舒适放大率；避免 1574 px 导致字号偏小）。轨道层级必须严格遵循 RefSeq → Ensembl → RNA-seq → Variants，严禁顺序倒挂。
- 区分 `loaded`（已显示数据）、`available_empty`（轨道可用但当前窗口未显示特征）、`unavailable`（已查证不可用）。请求失败、未查看和尚未加载都不是不可用，更不是“无变异”。`unavailable` 必须写明查过的 NCBI 目录或配置面板，禁止套用“未收录密集公共变异数据”。
- URL 的组装号必须与序列 accession 对应；`NC_139399.1` 这类新序列不能沿用旧 `GCF_`。
- `notes` 和来源说明不得写入湿实验机制、阳性确证或“特异性高”。
- RNA-seq 是公共研究证据，保留汇总/过滤/比例等标题信息；不能直接当作本实验表达结果。变异轨道不是本样本的基因型。
- Ensembl 和 RefSeq 并列显示不自动构成“交叉验证通过”。若用户额外要求判定一致性，需逐转录本、外显子及链向比对，单独给出依据。
- 引物颜色、分段、身份、顺序和坐标以当前确认来源为准。跨内含子的分段不拉成连续引物；标签名不能用于推断正负链。外侧跨度不称为实测扩增子。
- 若 `mk` 含 `exN` 或要在 03 区标外显子：先选定官方 SVG 中已出现的一条 `XM_`/`NM_`，用 Datasets `product_report` 的 `order` 编号。`N` 必须等于该段完整落入的外显子 `order`，02 区尺标、URL `mk` 与 03 区同名。窗口里其他转录本、Ensembl 小框或合并基因条多出来的块不能另编一套号。坐标对、标签错仍算失败。默认不改官方 SVG 几何；仅当用户明确授权纠正错误 `mk` 名时，才等长替换尺标文字或重导。`marker_display` 只给非编号别名，不得把 `ex13` 显示成 `ex11`。冲突则停该座。
- 组装不同的数据不能直接叠加；默认只使用 GDV 中与当前组装相容的轨道。本技能不自动做 liftOver、重比对或原始 RNA-seq 分析。

## 实施顺序

### 1. 建立输入清单

检查当前仓库、分支及已有改动；只读本任务所需记录，遵守根 `AGENTS.md`。读取用户链接，保留 F/R 的全部 `mk` 内容。先打开相同组装/窗口核实页面，不为了增加轨道偷偷换参考版本。

同时记录原有文件哈希。若是首次使用技能，可先用下面的离线回放验证环境，再处理用户目标；回放不要求重新访问 NCBI。

### 2. 获取真实官方轨道

在 GDV 完成六类轨道检查；等待图形加载，实际看图确认有基因结构、coverage 或变异特征，而非只有轨道名称。按流程文档通过 `Download → Printer-Friendly PDF/SVG` 导出 SVG，保留原件。

不要用网页截图包装成 SVG，不要按想象手绘 Ensembl、RNA-seq 曲线、SNP 或基因绿条。确有不可用轨道时明示缺口；服务暂时错误则按恢复步骤处理，不能伪造完整成果。

### 3. 取得元数据并填写 spec

`fetch_ncbi.py metadata` 获取正确 sequence accession 的 NCBI ESummary。确认 `accessionversion` 与链接一致、`slen` 足够覆盖窗口，并另从页面或 assembly report 核实染色体名称与组装关系。若标外显子或 `mk` 含 `exN`，再用 `fetch_ncbi.py product_report` 取该转录本外显子表。

以 [CAT_1 spec](assets/cat1-standard/spec.json) 的结构创建本次 spec；所有数据字段都换成当前目标。不要复制样例的“已检查”证据、时间或去标题字符串。

### 4. 使用捆绑脚本排版

默认调用 `scripts/render_gdv.py`，而非临时重写布局。它保留官方轨道数据和相对几何，裁掉底部空网格，增加白底页眉、序列定位、标记示意、来源说明；远距离短引物另画局部窗。`spec.exons` 存在时，03 区同轴画出该 RefSeq 转录本的外显子。

```bash
python3 .opencode/skills/gdv-offline-evidence/scripts/render_gdv.py /绝对路径/spec.json --validate-only
python3 .opencode/skills/gdv-offline-evidence/scripts/render_gdv.py /绝对路径/spec.json -o /绝对路径/新的输出目录
```

实际执行时用当前可用的 Python 或临时虚拟环境 Python 替换 `python3`，依赖见操作流程。不要把示例中的占位路径原样执行。输出目录必须不存在；不以删除用户目录的方式解决冲突。

### 5. 真正验收后交付

查看新 PNG；将 PDF 另外渲成图片并查看，核实字体、裁剪和轨道。有 `exN` 时同时看 02 区官方尺标与 03 区标签是否同号。对照本技能的固定标准图及当前在线/官方源图。检查原件哈希、离线资源及输入对应。

脚本只做静态校验，`checks.json` 默认 `visual_review: pending`。执行者只有实际看过新产物后才能记录 `passed`、日期、查看的文件及发现/修正情况；最终源说明也同步写明实际检查。修改说明后更新其哈希，不伪造检查。

最终直接给 PDF/SVG 链接和 PNG 预览，简述本次新增信息与真实缺口。视觉工具不可用时照实交付“待视觉验收”，不能称为已达到标准。

## 本技能自检与离线回放

```bash
python3 -B -m unittest discover -s .opencode/skills/gdv-offline-evidence/tests
python3 .opencode/skills/gdv-offline-evidence/scripts/render_gdv.py .opencode/skills/gdv-offline-evidence/assets/cat1-standard/spec.json --validate-only
python3 .opencode/skills/gdv-offline-evidence/scripts/render_gdv.py .opencode/skills/gdv-offline-evidence/assets/cat1-standard/spec.json -o /tmp/gdv-cat1-replay-新编号
```

离线回放验证渲染与数据保护，不声称验证了 Gemini 的浏览器操作、最新 NCBI 服务或其他物种数据。完整维护验收见 [测试场景](references/quality-standard.md#技能维护测试场景)。
