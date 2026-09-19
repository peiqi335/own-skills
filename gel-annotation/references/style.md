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

调用：`python3 .agents/skills/gel-annotation/scripts/annotate_gel.py SPEC.json --review-dir RUN/review`。`.codex/skills` 若为指向 `.agents/skills` 的符号链接也可用，但同一轮命令统一一种路径。相对 src/out 路径以仓库根目录为基准；临时测试用绝对 out 路径。输出必须是带 `（标注）` 的 `.png`，已存在默认拒绝覆盖。`--review-dir` 自动生成候选全图、孔槽原图/叠线对照、标签区和 bp 局部，以及 JSON review manifest；这些产物必须实际读取。

新流程顶层必须有 `source_sha256`，值为本轮原图真实 SHA-256；脚本会校验它与 `src` 一致。旧单排 spec 保留：顶层 `src`、`out`、`well`、`lane_x`、`groups`；不使用 `--review-dir` 的旧调用可省略 `source_sha256`，若提供 hash 也必须匹配。有 bp 尺时所有调用均需 `bp_source`。新多排使用顶层 `src`、`out`、`source_sha256`、可选 `top_padding` 及 `rows`；每个 row 使用相同的单排字段。不要混用 rows 与顶层单排字段。

`RUN/review/review.json` 的 `out` 是实际候选全图路径；`panels` 列出每张 `path`、`category`（wells/labels/bp）、原图 `source_box`、含留白的 `canvas_box` 和 `scale=1`。`geometry_sha256` 可与定位输出比较，确认坐标未被重抄改变；它不验证孔心或身份。`visual_status=not_reviewed` 只说明脚本尚未做视觉判断，读完图片后在工作记录中写真实结论，不靠改状态字段代替验收。review 目录不得位于原始资料或个人记录中。

每排字段：

| 字段 | 含义 |
| --- | --- |
| `well` | 此排参考孔槽 y；只作兼容参考高度，不代替逐孔孔壁定中心 |
| `lane_x` | 按物理孔号从左到右的每孔原图 x，包含空孔，严格递增；不是实验上样顺序 |
| `lane_y` | 可选，按物理孔逐孔的原图 y；省略则全排采用 well |
| `groups` | 标签组列表；每组 lanes 包含 0-based index 和 name |
| `marker_indices` | 本排按物理孔建立的 0-based Marker 索引；Marker 必须锚定实际孔位 |
| `font_scale` | 本排字号比例，默认 1 |
| `y` | 可选，各标签层原图绝对 y，用于避开条带及拥挤布局 |
| `review_box` | 可选，原图孔排区域 `[x0,y0,x1,y1]`；用于 review 分栏，不表示已经覆盖该区域之外的所有孔 |
| `bp_guide` | 可选 label/y 列表；只填已知规格并在图上核实的位置 |
| `bp_source` | 新 spec 有 bp 尺时必填；明确 ladder 规格来自用户记录、图中标尺或具体文件依据。图中有标尺时必须实际读图记录 |
| `bp_marker_index` | bp 尺指向哪个 Marker，默认本排首个 Marker |
| `bp_label_x` / `bp_arrow_x` | bp 文字左边位置 / 箭头起点 x |
| `bp_target_x` | 红色 bp 箭头实际指向的 x；必须从本图条带外侧读出并在原图宽度内校验，不能按模板或 `marker_x` 偏移推算 |
| `primer_line` | 可选底部说明，不自动补引物名 |

`y` 支持 head、param、lane、bracket、bracket_end、marker、marker_arrow、primer。未设置时分别采用相对 well 的 −450、−370、−280、−220、−100、−250、−210，以及 image_height−122。**这些是兼容默认值，不是所有胶都适合的布局。** 根据当前图空白区域设置 y；多排尤其不能让下一排标签覆盖上一排条带。

`top_padding` 默认 0，可按需要增加顶部黑色留白。所有 x/y 始终填写未加边的原图坐标；渲染器统一平移，不能手动重复加偏移。原图像素不缩放。新增留白区可用负的原图 y 排字。

组支持 color、head、param、lanes，以及可选 y_shift（只移组名/参数）、draw_lines、draw_bracket、bar。总组标题可用 draw_lines=false、draw_bracket=false 的组横跨多个孔；实际引线组不得重复占用孔或 Marker。参考 [lane_spec.example.json](../assets/lane_spec.example.json) 的字段结构，示例不提供可套用孔坐标或 ladder 数值；其中 hash 是明显占位符，不能直接运行。

## 验收

Build 按确认孔表和本页风格确定具体参数；Plan 不试排版。配置必须逐孔对应最近确认表，检查1-based孔号到0-based索引、各 NTC 参数及空孔位置，不能因为调整布局而改变身份。

先渲染临时图，按 review manifest 实际查看候选全图、未覆盖原图与叠线孔槽对照、标签区及 bp 局部分栏。逐孔、逐 x/y 检查样品引线是否缺失、箭头及线是否落在孔壁围成的中心、线长是否与整体层次协调；同时检查所有标签、括号、bp 标尺的重叠、裁切及条带遮挡。局部分栏方法见 [scan.md](scan.md)。一次检查不能宣称 100% 准确，也不能把文字/图元边界检查说成已证明孔心正确。

几何错误返回 Build 步骤3修正坐标并重新核验定位；排版错误返回步骤4调整 y、font_scale 和文字层，保持已核验坐标不变。局部修正只复查受影响局部并重新读取整体。文字碰撞或图元越界时，按报告中的具体对象修正。随后重新渲染、读取并检查成图。脚本参数检查无法替代视觉核查，不能仅凭整图缩略图宣布对齐。
