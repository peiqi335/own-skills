# 第二批标注风格与绘图接口

参考目录：`1.原始资料/实验数据/电泳 第二批/`。先实际看与本次形态接近的图：

- 双排整胶：`9.5凝胶1（标注）（第四批4.1）.jpg`。
- 宽半胶、空孔和梯度：`9.6凝胶2（标注）（第七批兔引物用量梯度、鸡）.png`。
- 小胶、单孔与双孔：`9.7凝胶2（标注）（兔、鸡1、同排阴性、异排兔NTC）.png`。

继承文字层次和配色，不照抄绝对坐标；已有引线偏心也必须重新校正。画布尺寸不能决定胶型。

## 版式

组名、参数、孔名最多三层，居中于相应孔或组；相同孔名可合并居中。两个及以上孔才画组括号，单孔只有引线。空孔占坐标但不绘文字或线。Marker 白字白箭头；已核实的 bp 尺用红色并指向清晰的一侧。

默认 purple 实验组、yellow 鸡 PC/NTC、red bp/底部说明、white Marker；整胶可用 cyan、green、orange、pink 区分 assay，遵循相近参考图。同一 assay 保持同色，用户明确配色优先。

字体使用 Noto Sans CJK Regular/Bold；默认组名 46、参数 38、孔名 31、Marker 36、bp 32、底部说明 38。可按密度设置每排 `font_scale`，不能靠无限缩小掩盖重叠；优先分层及必要的留白。字体缺失明确报错。

## JSON 接口

调用：`python3 .codex/skills/gel-annotation/scripts/annotate_gel.py SPEC.json`。相对 src/out 路径以仓库根目录为基准；临时测试用绝对 out 路径。输出必须是带 `（标注）` 的 `.png`，已存在默认拒绝覆盖。

旧单排 spec 保留：顶层 `src`、`out`、`well`、`lane_x`、`groups`。新多排使用顶层 `src`、`out`、可选 `top_padding` 及 `rows`；每个 row 使用相同的单排字段。不要混用 rows 与顶层单排字段。

每排字段：

| 字段 | 含义 |
| --- | --- |
| `well` | 此排参考孔槽 y |
| `lane_x` | 左到右每孔原图 x，包含空孔，严格递增 |
| `lane_y` | 可选，逐孔原图 y；省略则全排采用 well |
| `groups` | 标签组列表；每组 lanes 包含 0-based index 和 name |
| `marker_indices` | 本排 0-based Marker 索引 |
| `font_scale` | 本排字号比例，默认 1 |
| `y` | 可选，各标签层原图绝对 y，用于避开条带及拥挤布局 |
| `bp_guide` | 可选 label/y 列表；只填已知规格并在图上核实的位置 |
| `bp_source` | 新 spec 有 bp 尺时记录 ladder 规格的用户说明或文件依据 |
| `bp_marker_index` | bp 尺指向哪个 Marker，默认本排首个 Marker |
| `bp_label_x` / `bp_arrow_x` | bp 文字左边位置 / 箭头起点 x |
| `primer_line` | 可选底部说明，不自动补引物名 |

`y` 支持 head、param、lane、bracket、bracket_end、marker、marker_arrow、primer。未设置时分别采用相对 well 的 −450、−370、−280、−220、−100、−250、−210，以及 image_height−122。**这些是兼容默认值，不是所有胶都适合的布局。** 根据当前图空白区域设置 y；多排尤其不能让下一排标签覆盖上一排条带。

`top_padding` 默认 0，可按需要增加顶部黑色留白。所有 x/y 始终填写未加边的原图坐标；渲染器统一平移，不能手动重复加偏移。原图像素不缩放。新增留白区可用负的原图 y 排字。

组支持 color、head、param、lanes，以及可选 y_shift（只移组名/参数）、draw_lines、draw_bracket、bar。总组标题可用 draw_lines=false、draw_bracket=false 的组横跨多个孔；实际引线组不得重复占用孔或 Marker。参考 [lane_spec.example.json](../assets/lane_spec.example.json) 的字段结构，示例不提供可套用孔坐标或 ladder 数值。

## 验收

Build 按确认孔表和本页风格确定具体参数；Plan 不试排版。配置必须逐孔对应最近确认表，检查1-based孔号到0-based索引、各 NTC 参数及空孔位置，不能因为调整布局而改变身份。

先渲染临时图，实际查看全图和覆盖全部孔槽的原始像素局部分栏。逐孔检查样品引线是否缺失、箭头及线是否落在孔心、线长是否与整体层次协调；同时检查所有标签、括号、bp标尺的重叠、裁切及条带遮挡。局部分栏方法见 [scan.md](scan.md)。

几何错误返回 Build 步骤3修正坐标并重新核验定位；排版错误返回步骤4调整 y、font_scale 和文字层，保持已核验坐标不变。随后重新渲染、读取并检查成图。脚本参数检查无法替代视觉核查，不能仅凭整图缩略图宣布对齐。
