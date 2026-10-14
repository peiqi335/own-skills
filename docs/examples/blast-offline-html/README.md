# BLAST 离线 HTML 测试夹具示例

输入 `tiny_blastn.xml` **原样复制**自仓库公开[测试夹具](../../../blast-offline-html/tests/fixtures/tiny_blastn.xml)：query 长 20 bp，共 2 hits。其中一个 hit 为部分覆盖。它是解析/展示测试数据，不代表本项目科研检索结论，也不是本次在线 BLAST 检索。

- [实际生成的离线页面](site/tiny_blastn.html)及 `viewer.css` 完整保留，可直接本地打开。
- [真实 Chrome 截图](../../images/blast-offline-html.png)显示 Query、Descriptions 和两个 Alignments，没有重新绘造结果。
- 入口：[render_blast_offline.py](../../../blast-offline-html/scripts/render_blast_offline.py)。

仓库根实际生成命令：

```bash
python3 -B blast-offline-html/scripts/render_blast_offline.py \
  docs/examples/blast-offline-html/tiny_blastn.xml \
  -o docs/examples/blast-offline-html/site
```

重放可把 `-o` 改到 `/tmp/opencode` 唯一任务目录下的新目录，避免覆盖保存示例。该脚本不调用 NCBI；页面仅使用本地资源和页内导航，离线查看无需联网。

截图：Chrome headless 实际打开 `site/tiny_blastn.html` 的 `file://` URI，使用 `--window-size=1400,1400 --hide-scrollbars --screenshot="$TASK/blast.png"`。Pillow 将原截图裁为 `(0,0,1400,1050)`，上方增加 65 px 来源提示“仓库 tiny_blastn.xml 测试夹具 · 20 bp / 2 hits · 非科研检索结论”。提示不属于 BLAST 原始报告；下方结果区域完全来自真实页面截图，无缩放、数据修改或 HTML 仿制。
