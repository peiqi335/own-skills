# spec.json 输入契约

完整可运行例子为 [CAT_1 spec](../assets/cat1-standard/spec.json)；新目标复制结构后逐项核实，不复用事实。脚本运行路径与当前工作目录无关：两个来源路径都相对于 spec 文件目录解析。

| 字段 | 要求/来源 |
|---|---|
| locus_id | 文件名前缀，例如 CAT_1；只允许字母数字下划线短横线 |
| organism / display_name | 页面物种名 / 中文展示名；不让脚本猜物种 |
| assembly_name | 页面组装名称；与 URL 的 id 匹配 |
| source_url | HTTPS NCBI GDV，包含 id、chr、from、to、mk |
| chromosome | 权威染色体名如 B1；支架则填其实际名称 |
| sequence_role | chromosome 或 scaffold；不能假装每个 accession 都是染色体 |
| retrieved_date | 本次数据获取日期 YYYY-MM-DD；回放冻结快照时保留快照日期 |
| official_svg | 官方原件路径；优先含 accession 标题。无标题时使用下述 `titleless_export`。真实已显示轨道保留原样，CAT_1 的基因绿条模式是优先展示标准 |
| chromosome_metadata | NCBI ESummary JSON；accessionversion 必须精确匹配，slen 为正且覆盖窗口 |
| assembly_info | 可选。NCBI `getassemblyinfo.cgi` 原始 JSON；若填写，URL 的 `id` 必须等于其中 `assemblies[0].acc`。序列应出现在该清单中；unplaced scaffold 若清单未列，则 ESummary 标题必须含 `assembly_name` |
| export_title_to_remove | 可选。仅当确需替换时填写原 SVG 的完整唯一标题文字；不使用模糊匹配 |
| titleless_export | 仅无序列标题时填写；记录同次页面/导出证据、原件哈希和窗口刻度。不能与 `export_title_to_remove` 并用 |
| coordinate_note | 必填。坐标来源、口径、是否存在标题差异；没有差异也明确写明 |
| tracks | 六类轨道各一条，结构见下表 |
| exons | 可选。03 区与引物同轴的 RefSeq 外显子示意；缺省则不画。`mk` 含 `exN` 时必填。结构见下节 |
| product_report | 有 `exons` 时必填，相对于 spec 的路径。NCBI Datasets JSON，按 transcript accession.version + URL genomic accession 精确选择唯一 genomic_locations 记录；核对 strand 和完整 exon order/begin/end，缺失、歧义或 1 bp 差异均失败 |
| boundary_review | SVG 标题范围与 URL 不同时必填：`observed_range: [start,end]`、`url_range: [start,end]`、非空 `review`。绑定本次实际端点及已有人工核查，不以其他版本解释替代 |
| primer_evidence | 可选引物来源绑定；结构见下节。仅结构/hash 校验，准确结合仍 pending |
| notes | 字符串数组：汇总、折叠、过滤、边缘截断、未完成的解释性分析等真实边界 |

证据输出固定命名为 `assembly_info.json`、`product_report.json`，并同步改写输出 spec 引用；不沿用输入 basename，避免 `evidence/spec.json` 等与输出 spec 冲突。引物来源已使用独立的 `primer_evidence_source.<原后缀>`，同样不沿用 basename。输入接口和相对路径规则不变，输出 spec 可重新 `load_spec`。

## 无标题官方 SVG

先核对 SVG 的 F/R 标记、两个以上实际可见的 bp 刻度与目标窗口，再对照同次 GDV 页面和导出记录确认物种、组装、序列及窗口；身份无法确认时重新导出。`titleless_export` 包含：

```json
{
  "page_url": "与 source_url 完全一致的 GDV 页面链接",
  "exported_at": "2026-09-24T10:00:00+08:00",
  "page_capture": "同次页面与导出过程的截图或记录文件路径",
  "official_svg_sha256": "官方原件的 64 位小写 SHA-256",
  "ruler_labels": ["SVG 中实际出现的第一处 bp 刻度", "SVG 中实际出现的第二处 bp 刻度"],
  "identity_review": "人工核对页面组装、序列、窗口和 F/R 的简短记录"
}
```

脚本核对页面链接、哈希、记录文件、刻度落在窗口内及 SVG 中的标记；页面截图内容和轨道是否真实加载仍须人工查看。记录文件与原件一同归档。有标题但标题 accession 错误时不得用此字段绕过。

## tracks 每项

- `role`：`refseq / ensembl / rna_coverage / rna_spanning / rna_features / variants`。
- `status`：`loaded / available_empty / unavailable / source_unverified_excluded`。最后一项用于页面可见但来源与当前组装的兼容性未核实、已从本次官方导出中排除的轨道；不得误写为 `unavailable`。
- `title`：`loaded` 与 `available_empty` 使用官方 SVG 中的完整标题或能唯一指认该轨道的标题片段；版本来自实际轨道。`unavailable` 可留空。`source_unverified_excluded` 保留原页面标题，且该标题不得出现在本次官方 SVG 中。
- `evidence`：实际观察/核查方式和日期；不可用时写查过的 `disptracks` 目录、配置面板或页面，以及日期。禁止套用“未收录密集公共变异数据”。不能写“默认如此”。`available_empty` 仍须填写官方标题；若 NCBI 导出省略了空轨道标题，不要改成 `loaded` 或 `unavailable`。`source_unverified_excluded` 须写明来源疑点和排除原因。
- `content_state`：`loaded` 必须为 `data`；`available_empty` 必须为 `empty`，明显状态矛盾失败。
- `content_evidence`：上述两种状态必填，声明实际模型、曲线、特征或空窗口内容及核查依据，不能只重复标题。来源声明不是脚本科学验证，冻结旧声明应注明待复核，不伪造新的观察。
- `notes` 只写 GDV 图能支持的坐标、折叠、过滤和轨道边界。禁止写入湿实验机制、阳性确证或“特异性高/良好”。

脚本验证标题、内容声明结构及明显状态矛盾，**不能识别曲线是否真的加载，也不能核实你填写的观察是否真实**；`track_content_review` 和 `visual_review` 仍为 `pending`。执行者承担原图与页面核对责任。所有六类都未查时不要填写虚假的不可用状态绕过校验。

## exons（可选）

03 区新增与 F/R 同轴的外显子行。当前接口必须绑定 Datasets `product_report`；其他格式需先另行核查，不能冒充该 JSON。不得从图上量、不得用 Ensembl 或窗口内其他转录本另编一套号。`mk` 名称中的 `exN` 必须等于该段完整落入的 `order`；02 区尺标、URL 与 03 区同名。坐标对、标签错仍失败。

- `transcript`：带版本 `XM_`/`NM_`，且必须出现在官方 SVG 文字中。
- `gene`：该转录本基因符号。
- `strand`：`+` 或 `-`。
- `source`：外显子表出处与日期，例如 `NCBI Datasets product_report 2026-09-12`。
- `intervals`：完整转录本外显子，每项 `order`（该转录本上的外显子号）、`start`/`end`（1-based 闭区间，基因组坐标）。`order` 为正整数且不重复。

每个引物分段必须**完整落在恰好一个**所列外显子内。跨内含子引物必须拆成多段 `mk`，不能把内含子算进引物。未写入 `exons` 时不画 03 区外显子；冻结 CAT_1 现含该字段。

## 标记解析与坐标

`checks.coordinate_observation` 从实际 official SVG 提取 `observed_title`、`observed_range`，同时记录 `url_range`、`delta_start_end`（有标题时）、`coordinate_convention: unknown` 及生成的说明。无标题时 observed 字段为 null。接受绑定人工核查的边界差异，不平移几何；不会复用另一版“终点+1”解释，也不宣称官方内部约定已知。`coordinate_note` 保留为人工原记录，不替代机械提取。

- `mk=起点-终点|名称|RRGGBB,起点-终点|名称|RRGGBB`，也接受冒号分隔起止和末尾锁定 `!`。
- 使用 1-based 闭区间，单段长度 `end-start+1`；绘图右边界用 `end+1` 表示完整碱基宽度。
- 必须有名称与颜色，最多 20 个标记；复杂转义/无颜色/单点标记需先根据当前来源人工规范化，不能猜默认值。
- `marker_display` 可选。键必须是 URL/`mk` 中已有名称，值只用于 03 区显示；官方 SVG 仍按原名核对，不改原件。不得把一个 `exN` 显示成另一个外显子号；纠正错误编号应改 URL/`mk` 与官方尺标，不能靠显示别名蒙混。
- 所有标记需位于窗口中。反向引物也按较小到较大坐标给范围，名字不用于推断链向。
- 一个跨内含子引物分成多个 `mk` 片段；脚本保持片段，不自动桥接中间距离。不自动合并重复/同名标记。
- 新图整体为坐标递增的标记示意；官方轨道不翻转，若原导出链向反转应在 notes 中明确并在视觉验收时检查，不把示意方向当作分子链向。

## primer_evidence（可选；没有 marker_evidence 别名）

```json
{
  "transcript": "XM_011281731.4",
  "genomic_accession": "NC_058371.1",
  "source": {"kind": "alignment", "path": "alignment.txt", "sha256": "64位小写SHA-256"},
  "primers": {
    "F": {"sequence": "ACGTACGTACGTACGTACGT", "segments": [{"label": "F", "start": 142725183, "end": 142725202}]},
    "R": {"sequence": "TGCATGCATGCATGCATGCA", "segments": [{"label": "R", "start": 142725246, "end": 142725265}]}
  }
}
```

此为结构示例，不是猫的真实引物。`sequence` 为完整大写 ACGT、5′→3′ 序列；source.kind 为 `report` 或 `alignment`，path 必须相对于 spec，文件须存在且 hash 匹配。transcript 带版本并与 exons（若有）一致；genomic_accession 与 URL 一致。F/R segments 覆盖全部 mk，label/start/end 精确唯一匹配且不重复；跨内含子保留多个 segments。脚本不检验文件中的 alignment 内容，不用长度算术冒充结合验证。

未提供证据仍可渲染；提供但结构/hash/端点矛盾则失败。无论是否提供，`checks.marker_validation.status` 都为 `pending`，成功绑定时另记 `provenance_structure: matched` 和 `source_sha256`；不接受调用者自填 passed 绕过。来源文件归档为 `primer_evidence_source.<原后缀>` 并改写输出 spec 相对路径。最外侧跨度仍只是算术值。不运行 BLAST、liftOver 或自动比对。

## 脚本适用边界

输入字节仅支持严格 UTF-8（可带 UTF-8 BOM）。NUL、UTF-16／UTF-32及无效 UTF-8 在 DOCTYPE／PI 检查和 XML parse 前拒绝；不自动转码或改写原件。

`render_gdv.py` 是多轨道图的**排版器**，不是 GDV 下载引擎、注释比较器或引物验证器。它不获取当前轨道、不执行 BLAST、不对 GCA/GCF 做序列等价验证、不判断变异重叠。

接受有限静态 SVG 子集（本地 fragment 渐变/裁剪引用可用），另允许经过类型、签名与实际解码核验的 `data:image/png;base64,...`／`data:image/jpeg;base64,...` 内嵌 image；拒绝外部 image、data SVG 或伪装／混入 XML 的栅格。对当前 NCBI 导出的固定 SVG 1.1 DTD 声明和 `https://www.ncbi.nlm.nih.gov/projects/sviewer/css/svg_fonts.css` 字体导入，脚本只在内存中的增强版副本中移除，不联网解析；原件保持原样。正常 XML 声明可用，其他 processing instruction（含 xml-stylesheet）在 XML parse 前拒绝。其他外部 CSS、声明、脚本会被拒绝；marker／marker-start／marker-mid／marker-end／color-profile／cursor 等资源属性经 normalized CSS 检查，仅允许本地 fragment URL，不新增 marker 元素支持。不要为了通过检查删除真实轨道；若官方新版输出格式变化，先判断并有针对性扩展脚本及测试。

新输出目录必须不存在；受保护路径和符号链接被拒绝。脚本不修改输入文件。PDF/PNG 来自同一增强 SVG；更改文字后须一并重新生成三种格式。

非常长的物种/序列名称、多页超大轨道或超过 20 个标记需调整布局/拆图并真实验收；不能只因脚本退出 0 就交付。固定 CAT_1 模板追求同等信息层级，不要求每个目标有完全相同的画布高度。

排版器会裁掉官方 SVG 底部空网格，不改轨道路径。若总览上任一段引物矩形不足 8 px，额外按簇绘制独立局部窗；局部窗按该簇坐标比例，不把短片段拉成全跨度宽矩形。
