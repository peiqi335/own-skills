# Primer-BLAST 合成状态夹具看板

**合成测试夹具，未提交 NCBI，不代表检索结论。** 没有读取课题实验目录、真实引物或私有报告。`ACGT` / `TGCA` 是公开测试中的四碱基字符串，不是实验引物设计。

- [离线总入口](site/index.html)、[真实生成的矩阵](site/01.成对Primer-BLAST/index.html)、[Chrome 截图](../../images/primer-blast-results.png)。
- [最小输入状态](input/status.json)与合成报告保留；[make_fixture.py](make_fixture.py)可重现这些字节及 SHA-256。
- 入口：[build_panel.py](../../../primer-blast-results/scripts/build_panel.py)。已先核对[INTERFACE](../../../primer-blast-results/INTERFACE.md)与[公开测试](../../../primer-blast-results/tests/test_build_panel.py)中的 PRODUCT、解析异常和错误字符串结构；**没有导入或读取测试中提到的私有 REAL 文件**。

状态契约：单一 assay × RAT/CAT/DOG 的完整矩阵，`schema_version=2`；原始响应及展示页 hash/时间字段齐全。时间固定为合成时间戳，不是实际请求时间；`job_key=null`。

| 夹具 | 实际状态 | 含义与边界 |
| --- | --- | --- |
| RAT | `completed_results` / `ok` | 模板上下文中列出 82、52 bp，仅演示解析，不称“阳性”或设计达标 |
| CAT | `completed_results` / `needs_review` | 有 product length 字符串但缺模板上下文，products 空，明确解析待核，绝不当作阴性 |
| DOG | `error` / `not_applicable` | 合成离线失败；无 products，不伪造完成结果 |

所有 raw 故意不回显请求参数，因此实际 builder 计算出的 `response_binding=pending`、`source_verified=false`；不伪造参数绑定或 NCBI 来源认证。失败页未生成重新检索链接。保留实际输出 `checks.json`、原始字节、派生页与 `_archived-input`，可核验而非只有截图。

仓库根生成命令：

```bash
python3 -B docs/examples/primer-blast-results/make_fixture.py
python3 -B primer-blast-results/scripts/build_panel.py \
  docs/examples/primer-blast-results/input/status.json \
  --output docs/examples/primer-blast-results/site \
  --title '合成测试夹具 · 未提交 NCBI · 不代表检索结论'
```

builder 拒绝已有输出。重放时将 `--output` 指向 `/tmp/opencode` 唯一任务目录内不存在的 `site` 子目录，不删除已保存示例。

截图为两个真实 Chrome 页面截图的拼接：矩阵页在 1400×900 窗口截屏后裁 `(0,0,1400,420)`；`DOG-display.html` 在 1400×650 窗口截屏后裁 `(0,0,1400,180)`。两图原像素拼接，中间增加 55 px 文字，注明“DOG · error 展示派生页（下方为另一张真实 Chrome 截图；非 NCBI 响应）”。没有用 HTML 绘造看板、修改页面或把错误当作无产物。直接打开本地页面即可预览报告；不要点击 NCBI 外部导航进行真实提交。
