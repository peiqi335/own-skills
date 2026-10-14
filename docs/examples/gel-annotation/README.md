# 合成凝胶孔位标注示例

**全部为 Pillow 合成图像，非真实实验，仅展示孔位标注。** Marker、样品1、样品2、NTC 均为演示标签；合成条带没有 bp 标尺，不得据此判断扩增、阴阳性或污染。

- [离线展示](index.html)：并排呈现合成输入和技能脚本实际输出。
- 输入：`synthetic-input.png`、`spec.json`；[合成输入小脚本](make_input.py)固定几何，无随机数据或科研资料。
- 输出：`synthetic（标注）.png`、`comparison.png`；[真实 Chrome 截图](../../images/gel-annotation.png)。
- 配置来源：[recognized_minimal 模板](../../../gel-annotation/assets/recognized_minimal.spec.template.json)；正常入口：[annotate_gel.py](../../../gel-annotation/scripts/annotate_gel.py)。

以下为原始生成记录，在仓库根运行；重放前先复制 spec，并将 `out` 修改为不存在的新输出路径：

```bash
python3 -B docs/examples/gel-annotation/make_input.py
python3 -B gel-annotation/scripts/annotate_gel.py docs/examples/gel-annotation/spec.json \
  --repo docs/examples/gel-annotation --manifest "$TASK/gel-manifest.json"
python3 -B docs/examples/gel-annotation/make_input.py --comparison
```

`TASK` 为事先在 `/tmp/opencode` 中创建的唯一任务目录。重放时可先在该目录保存 `spec.json` 副本，把 `out` 改为新的 `replay（标注）.png` 路径，然后通过同一 CLI 使用副本；源图仍由 `--repo docs/examples/gel-annotation` 解析。不要删除原产物来重跑。

输入和源图 hash 均保留在 spec。字体使用系统已有的 `/usr/share/fonts/opentype/noto/NotoSansCJK-{Regular,Bold}.ttc`，记录了实际 SHA-256，不打包几十 MB 字体；重放须有相同字体与 Pillow/RAQM。`portable_resources=false` 是为控制示例体积，静态图片和离线页本身无需字体或 Python。生成过程的完整机器环境 manifest 仅留于任务临时目录，不带入示例。

截图方法：Chrome headless 打开 `index.html` 的 `file://` URI，以 `--window-size=1400,750 --hide-scrollbars --screenshot="$TASK/gel.png"` 截取，然后 Pillow 原尺寸裁剪 `(0, 0, 1400, 660)`。并排图中的两幅凝胶分别来自输入 PNG 与真实输出 PNG；没有用 HTML 重绘标注结果。
