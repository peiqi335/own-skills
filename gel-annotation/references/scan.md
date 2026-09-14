# 扫描定位

脚本路径为仓库根目录下 `.codex/skills/gel-annotation/scripts/scan_gel.py`。下列命令从仓库根目录执行；`SRC`、`RUN` 和坐标是占位符，需要替换，不是默认值。

本页扫描在 Build 阶段执行。Plan 只做必要读图和逐孔身份核对，不提前运行完整扫描或生成定位预览。

## 新运行与逐排预览

```text
python3 .codex/skills/gel-annotation/scripts/scan_gel.py grid SRC
```

默认为本次调用创建独立 `/tmp/codex/gel-annotation/<原名>-<随机后缀>/`。实际读取 stdout 中 `out` 指向的 grid；记下父目录作为 RUN。后续命令显式复用本次 RUN，不能去找上次同名图。全局参数 `--out-dir` 要放在子命令前。

```text
python3 .codex/skills/gel-annotation/scripts/scan_gel.py --out-dir RUN/row1 wells SRC --row y0,y1 --x0 x0 --x1 x1
python3 .codex/skills/gel-annotation/scripts/scan_gel.py --out-dir RUN/row1 zoom SRC --at x,y --size 240
python3 .codex/skills/gel-annotation/scripts/scan_gel.py --out-dir RUN/row1 lanes SRC --xs x1,x2,x3 --well y --ys y1,y2,y3 --span top,bottom
python3 .codex/skills/gel-annotation/scripts/scan_gel.py --out-dir RUN/row1 bp SRC --bands label:y,label:y --marker-x x
```

- 每个命令返回后实际读 `out`；`wells` 返回非空 `panels` 时逐张读取所有分栏。黄色刻度是原图绝对 x；记录裁图原点和 scale，不把显示缩放后的像素当原图坐标。
- 多排使用 `row1`、`row2` 各自目录，参数来自全图观察。当前轮修正可以覆盖同一阶段预览；保存最终坐标到本次 spec。
- `--ys` 可选，一孔一项；倾斜孔排用它标青色孔心。`--well` 是该排参考高度，`--span` 控制扫描线范围。它们都不是条带位置。
- 边缘孔的 `zoom` 十字对应请求的原图 x/y，不一定在裁图中心。
- `bp` 只负责核对位置，label 必须已有 ladder 依据。无法核实的尺寸不画。
- 不使用 `hint` 的亮度候选生成 `lane_x`。没有条带不是空孔依据。

## 原始像素局部核验

定位预览和最终候选图都必须实际读取覆盖全部孔槽的局部分栏，不能只看整图缩略图。“1:1”指裁取时保留原始像素细节，不把整图缩小后再放大。用现有 Pillow 裁图即可，不新增依赖；分栏尺寸应使读图工具不再缩小孔槽细节，必要时继续拆分。不必为每孔单独调用，但不能漏掉边缘孔或空孔位置。

定位阶段裁取 lanes，检查红线与青色终点；成图阶段裁取实际候选 PNG，检查最终引线和箭头，不能用原图或 lanes 代替成图核验。记录裁区原点，成图有 top_padding 时将其计入裁区 y，孔表仍使用原图坐标。参数来自当前图片，不能套用本会话的坐标。

## 继续与完成

看完 wells 将坐标追加到用户确认的逐孔表，再出 lanes；发现孔数或身份对应冲突先报告，不擅自改表。定位不准就改数重画并重读。只有已看到孔心对齐的 lanes 才进入最终渲染。PNG 还需单独读图验收。用户仅要求孔心定位时，交出孔表和 lanes 即完成。
