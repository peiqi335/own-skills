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
| official_svg | 官方原件路径；需有 accession 标题和已显示轨道。RefSeq loaded 时，图上应有独立基因绿条及其下合并转录本/CDS 一行，不是 Merge-all 无 gene bar，也不是 Show all 三行 |
| chromosome_metadata | NCBI ESummary JSON；accessionversion 必须精确匹配，slen 为正且覆盖窗口 |
| assembly_info | 可选。NCBI `getassemblyinfo.cgi` 原始 JSON；若填写，URL 的 `id` 必须等于其中 `assemblies[0].acc`。序列应出现在该清单中；unplaced scaffold 若清单未列，则 ESummary 标题必须含 `assembly_name` |
| export_title_to_remove | 可选。仅当确需替换时填写原 SVG 的完整唯一标题文字；不使用模糊匹配 |
| coordinate_note | 必填。坐标来源、口径、是否存在标题差异；没有差异也明确写明 |
| tracks | 六类轨道各一条，结构见下表 |
| exons | 可选。03 区与引物同轴的 RefSeq 外显子示意；缺省则不画。`mk` 含 `exN` 时必填。结构见下节 |
| product_report | 可选。该 `XM_`/`NM_` 的 NCBI Datasets `product_report` JSON。填写 `exons` 时应归档；若填写，必须含 `exons.transcript` |
| notes | 字符串数组：汇总、折叠、过滤、边缘截断、未完成的解释性分析等真实边界 |

## tracks 每项

- `role`：`refseq / ensembl / rna_coverage / rna_spanning / rna_features / variants`。
- `status`：`loaded / available_empty / unavailable`。
- `title`：前两种状态使用官方 SVG 中的完整标题或能唯一指认该轨道的标题片段；版本来自实际轨道。`unavailable` 可留空。
- `evidence`：实际观察/核查方式和日期；不可用时写查过的 `disptracks` 目录、配置面板或页面，以及日期。禁止套用“未收录密集公共变异数据”。不能写“默认如此”。`available_empty` 仍须填写官方标题；若 NCBI 导出省略了空轨道标题，不要改成 `loaded` 或 `unavailable`。
- `notes` 只写 GDV 图能支持的坐标、折叠、过滤和轨道边界。禁止写入湿实验机制、阳性确证或“特异性高/良好”。

脚本只验证状态填写及标题存在，**不能识别曲线是否真的加载，也不能核实你填写的观察是否真实**；执行者承担原图与页面核对责任。所有六类都未查时不要填写虚假的不可用状态绕过校验。

## exons（可选）

03 区新增与 F/R 同轴的外显子行。坐标必须来自 NCBI 该 RefSeq 转录本的基因组外显子表（如 Datasets `product_report` 或同等 GFF），不得从图上量、不得用 Ensembl 或窗口内其他转录本另编一套号。`mk` 名称中的 `exN` 必须等于该段完整落入的 `order`；02 区尺标、URL 与 03 区同名。坐标对、标签错仍失败。

- `transcript`：带版本 `XM_`/`NM_`，且必须出现在官方 SVG 文字中。
- `gene`：该转录本基因符号。
- `strand`：`+` 或 `-`。
- `source`：外显子表出处与日期，例如 `NCBI Datasets product_report 2026-09-12`。
- `intervals`：完整转录本外显子，每项 `order`（该转录本上的外显子号）、`start`/`end`（1-based 闭区间，基因组坐标）。`order` 为正整数且不重复。

每个引物分段必须**完整落在恰好一个**所列外显子内。跨内含子引物必须拆成多段 `mk`，不能把内含子算进引物。未写入 `exons` 时不画 03 区外显子；冻结 CAT_1 现含该字段。

## 标记解析与坐标

- `mk=起点-终点|名称|RRGGBB,起点-终点|名称|RRGGBB`，也接受冒号分隔起止和末尾锁定 `!`。
- 使用 1-based 闭区间，单段长度 `end-start+1`；绘图右边界用 `end+1` 表示完整碱基宽度。
- 必须有名称与颜色，最多 20 个标记；复杂转义/无颜色/单点标记需先根据当前来源人工规范化，不能猜默认值。
- `marker_display` 可选。键必须是 URL/`mk` 中已有名称，值只用于 03 区显示；官方 SVG 仍按原名核对，不改原件。不得把一个 `exN` 显示成另一个外显子号；纠正错误编号应改 URL/`mk` 与官方尺标，不能靠显示别名蒙混。
- 所有标记需位于窗口中。反向引物也按较小到较大坐标给范围，名字不用于推断链向。
- 一个跨内含子引物分成多个 `mk` 片段；脚本保持片段，不自动桥接中间距离。不自动合并重复/同名标记。
- 新图整体为坐标递增的标记示意；官方轨道不翻转，若原导出链向反转应在 notes 中明确并在视觉验收时检查，不把示意方向当作分子链向。

## 脚本适用边界

`render_gdv.py` 是多轨道图的**排版器**，不是 GDV 下载引擎、注释比较器或引物验证器。它不获取当前轨道、不执行 BLAST、不对 GCA/GCF 做序列等价验证、不判断变异重叠。

仅接受纯矢量 SVG（本地 fragment 渐变/裁剪引用可用）。对当前 NCBI 导出的固定 SVG 1.1 DTD 声明和 `https://www.ncbi.nlm.nih.gov/projects/sviewer/css/svg_fonts.css` 字体导入，脚本只在内存中的增强版副本中移除，不联网解析；原件保持原样。其他外部 CSS、声明、脚本、栅格 image 元素会被拒绝。不要为了通过检查删除真实轨道；若官方新版输出格式变化，先判断并有针对性扩展脚本及测试。

新输出目录必须不存在；受保护路径和符号链接被拒绝。脚本不修改输入文件。PDF/PNG 来自同一增强 SVG；更改文字后须一并重新生成三种格式。

非常长的物种/序列名称、多页超大轨道或超过 20 个标记需调整布局/拆图并真实验收；不能只因脚本退出 0 就交付。固定 CAT_1 模板追求同等信息层级，不要求每个目标有完全相同的画布高度。

排版器会裁掉官方 SVG 底部空网格，不改轨道路径。若总览上任一段引物矩形不足 8 px，额外按簇绘制独立局部窗；局部窗按该簇坐标比例，不把短片段拉成全跨度宽矩形。
