# 扫描定位

脚本路径为仓库根目录下 `.agents/skills/gel-annotation/scripts/scan_gel.py`。`.codex/skills` 若为指向 `.agents/skills` 的符号链接也可用，但同一轮命令统一一种路径。下列命令从仓库根目录执行；`SRC`、`RUN`、`SPEC.json` 和坐标是占位符，需要替换，不是默认值。

本页扫描在 Build 阶段执行。Plan 只做必要读图和逐孔身份核对，不提前运行完整扫描或生成定位预览。

## 新运行与逐排预览

```text
python3 .agents/skills/gel-annotation/scripts/scan_gel.py grid SRC
```

默认为本次调用创建独立 `/tmp/codex/gel-annotation/<原名>-<随机后缀>/`。实际读取 stdout 中 `out` 指向的 grid；记下父目录作为 RUN。后续命令显式复用本次 RUN，不能去找上次同名图。全局参数 `--out-dir` 要放在子命令前。

```text
python3 .agents/skills/gel-annotation/scripts/scan_gel.py --out-dir RUN/row1 wells SRC --row y0,y1 --x0 x0 --x1 x1
python3 .agents/skills/gel-annotation/scripts/scan_gel.py --out-dir RUN/row1 detect-wells SRC --row y0,y1 --x0 x0 --x1 x1 [--n N]
python3 .agents/skills/gel-annotation/scripts/scan_gel.py --out-dir RUN/row1 detect-bp SRC --marker-x x --y-range y0,y1 [--n-bands 7]
python3 .agents/skills/gel-annotation/scripts/scan_gel.py --out-dir RUN/row1 zoom SRC --at x,y --size 240
python3 .agents/skills/gel-annotation/scripts/scan_gel.py --out-dir RUN/position lanes --spec SPEC.json
python3 .agents/skills/gel-annotation/scripts/scan_gel.py --out-dir RUN/row1 lanes SRC --xs x1,x2,x3 --well y --ys y1,y2,y3 --span top,bottom
python3 .agents/skills/gel-annotation/scripts/scan_gel.py --out-dir RUN/row1 bp SRC --bands label:y,label:y --marker-x x
```

- **`detect-wells` 候选辅助**：通过一维灰度列积分与周期自相关输出候选 pitch、孔心 `lane_x` 及 `detect_wells.jpg`。结果不能代替原图逐孔孔壁核验，不能直接认定孔心或所有物理孔。
- **`detect-bp` 候选辅助**：沿 Marker 提取亮度峰及预览，不能代替原图条带核验或证明 Ladder 身份。输出中的推荐 500bp 列表只是已有候选模板，不是全球默认；课题实验项目可引用已核实的 `AGENTS.md:65`，其他项目必须另有规格依据。
- 新流程的 `lanes --spec SPEC.json` 读取 spec 的全部 `rows`，不再手抄 `--xs`。spec 顶层 `source_sha256` 为新流程必填；它必须与本轮原图一致。旧命令继续保留，旧 spec 可没有该字段；若旧 spec 提供了 hash 也必须匹配。
- `lanes --spec` 自动输出未覆盖原图和叠线对照的 1:1 自适应分栏，必要时按重叠边界继续拆分；同时覆盖全部给定孔和边缘孔，不把一张只含给定坐标的图说成保证识别所有孔。批量读取同一阶段的全部分栏，不把不同阶段的预览混用。
- `wells` 读取 `panels`，`lanes` 读取 `review_panels[*].path` 中的全部分栏；已有完整分栏时无需重复读取同内容长条或整张定位 `out`。其他命令实际读 `out`。分栏保留原始像素，不固定三分；顶部黄色刻度为原图 x，左侧黄色刻度为原图 y，刻度位于图像外。记录裁图原点和 scale，不把显示缩放后的像素当原图坐标。
- 多排使用 `row1`、`row2` 各自目录，参数来自全图观察。当前轮修正可覆盖同一阶段预览；保存最终坐标到本次 spec。
- `--ys` 可选，一孔一项；倾斜孔排用它标青色孔心。`--well` 是该排参考高度，`--span` 控制扫描线范围。它们都不是条带位置。
- 孔心逐孔读孔壁边界确定：工作孔表记录 `左壁 x | 右壁 x | 中点 x | 孔腔中心 y`，检查引线到左右孔壁的距离是否相称。不使用均分孔距、亮度峰、向下延伸的条带或相邻孔推算。`hint` 的亮度候选只能作提示，不能生成 `lane_x`；最暗点可能偏在孔腔一侧，不能当作中心证据。
- 物理孔号按本图左→右 1-based；脚本索引为 0-based。上样顺序只来自用户或记录，不能用它重排 `lane_x`；Marker 锚定实际物理孔。
- 边缘孔的 `zoom` 十字对应请求的原图 x/y，不一定在裁图中心。局部修正后只重读受影响孔的分栏，并再次读取整体分栏。
- `bp` 只负责核对位置，`label` 必须已有 ladder 依据；无法核实的尺寸不画。用于最终 bp 箭头的 `bp_target_x` 必须由本图实际条带外侧位置读出并做原图宽度边界校验。
- 没有条带不是空孔依据。

## 原始像素局部核验

定位预览和最终候选图都必须实际读取覆盖全部孔槽的未覆盖原图和叠线对照分栏，不能只看整图缩略图。“1:1”指裁取时保留原始像素细节，不把整图缩小后再放大。用现有 Pillow 裁图即可，不新增依赖；分栏尺寸应使读图工具不再缩小孔槽细节，必要时继续拆分。不必为每孔单独调用，但不能漏掉边缘孔或空孔位置。默认优先批量读同一阶段的分栏，减少临时裁图；每次分栏批次读完并完成验收后再进入下一阶段。

若 row 提供 `review_box: [x0,y0,x1,y1]`，它是该排在原图中的孔排区域，用于限制 review 分栏；必须仍包含边缘孔。未提供时按全部给定孔自动扩展到两侧边缘。指定坐标区域只说明 review 覆盖范围，不能把“包含给定坐标”误称为已识别原图中的所有孔。

定位阶段裁取 lanes，检查红线与青色终点；成图阶段裁取实际候选 PNG，检查最终引线和箭头，不能用原图或 lanes 代替成图核验。记录裁区原点，成图有 top_padding 时将其计入裁区 y，孔表仍使用原图坐标。参数来自当前图片，不能套用本会话的坐标。

## 继续与完成

看完 wells 将坐标追加到用户确认的逐孔表，再出 lanes；发现孔数或身份对应冲突先报告，不擅自改表。定位不准就只改受影响的 x/y，重画并复查受影响孔及整体分栏；不能用一次看图宣称 100% 正确，孔壁不清时记录不确定。只有实际看到孔壁中心与叠线对齐的 lanes 才进入最终渲染。PNG 还需单独读图验收；检查脚本或 manifest 不能证明孔心正确。用户仅要求孔心定位时，交出孔表和 lanes 即完成。
