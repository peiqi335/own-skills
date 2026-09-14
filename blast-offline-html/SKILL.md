---
name: blast-offline-html
description: "Render NCBI BLAST XML into offline HTML directories with Graphic Summary, Descriptions, and pairwise alignments. Use when the user wants a USB-openable BLAST page, XML-to-HTML BLAST viewer, click-to-alignment Graphic Summary, or offline BLAST HTML. Do not use to run blastn, fetch RIDs, do Primer-BLAST pair PCR, gel annotation, or SequenceServer."
---

# BLAST XML 离线页

把已有单 query 的 BLASTN XML（`-outfmt 5` / `FORMAT_TYPE=XML`）渲成可双击、断网可用的结果页。权威数据是 XML；页面只是展示层。不跑 BLAST，不拉 RID，不覆盖源 XML 或 NCBI 原 HTML。

命中不是物种鉴定。坐标只来自 XML 的 HSP 字段，不从胶图或已保存的 NCBI HTML 反推。

## 何时读参考

画或改 Graphic Summary 前读 [graphic-summary.md](references/graphic-summary.md)。Query 必须是贯穿全长的黑色主条，刻度在条上方。

## 输入与输出

用户给出 XML 文件或目录。CLI 必须指定 `-o`；调用者未收到输出目录要求时，选择在 XML 旁建 `blast-offline/`。

每份 XML 生成 `{stem}.html`，共用 `viewer.css`，携带时复制整个目录。文件名形如 `{ABC}_1_...` 时写入 `{ABC}_1/` 子目录，CSS 与目录页用 `../`。单份结果隐藏目录入口。多于一份再写 `index.html`。不覆盖 XML、NCBI 原 HTML、`1.原始资料/`、`3.记录/`。

若当前项目存在相对路径 `4.知识库/01.检测体系准备/PCR与凝胶初筛/结果汇总/primer-blast-15/02.core_nt回贴/xml/`，默认用它作输入、输出到同级 `03.离线查看/`。否则必须由用户给出 XML 路径，且 CLI 必须指定 `-o`。

## 执行

用捆绑脚本，不要手写第二套渲染器：

```
python3 .opencode/skills/blast-offline-html/scripts/render_blast_offline.py \
  <xml 或 xml 目录> -o <输出目录>
```

脚本会复制 [assets/viewer.css](assets/viewer.css)。缺必需字段、坐标越界、序列长度不一致或输入不是单 query BLASTN XML 时，该文件失败并报告路径与字段，继续其他文件；最后列出成功和失败，存在失败时退出码为 1。合法无命中结果正常显示。

写入前拒绝同名输入输出冲突、保留名称 `index`、受保护目录及非本查看器 HTML；允许重新生成已有离线成品。

## 页面内容

- 页眉：`h1` 用文件名；下面是标签表（Job title、Query Length、Molecule type、Database Name、Program、Expect、Hits、类型）。Job title 来自 `BlastOutput_query-def`；空或 `No definition line` 显示 NCBI 默认 `Nucleotide Sequence`，不把文件名写成 Job title
- Graphic Summary：NCBI 色阶、黑色 Query 主条、刻度含 `1` 与 `qlen`、命中条按 query 覆盖对齐，点击跳 `#alnHdr_{gi}`
- Descriptions：Description / Max Score / Total Score / Query Cover / E / Ident / Acc. Len / Accession
- Alignments：`Query` / midline / `Sbjct`、Identities、Gaps、Strand；Query 与 Sbjct 均按各自方向推进坐标
- 无外链、无 NCBI `<base>`；`file://` 可用

Accession 用 `Hit_id` 里的完整 acc（如 `NG_012027.1`），不用截断的 `Hit_accession`。多 HSP 列在同一锚点下；色条用最佳 HSP并明确标注。Query Cover 使用全部 HSP 的 query 区间并集，重叠只计算一次；其余评分保持最佳 HSP / 总分口径。

## 不要做

- 不联网、不提交 NCBI、不跑本地 `blastn`
- 不镜像 NCBI CSS/JS，不画官网页眉登录
- 不把 BLAST 命中写成物种验证结论
- 不要另起 Graphic Summary 布局；规则在 graphic-summary.md

## 检查

0. 运行 `python3 -B -m unittest discover -s .opencode/skills/blast-offline-html/tests`。
1. 夹具：`tests/fixtures/tiny_blastn.xml` 渲到临时目录。页面有黑色 Query 条、刻度 `1` 和 `20`、两个 `alnHdr`、`Identities = 20/20`、无 `blast.ncbi.nlm.nih.gov`。
2. 用户指定的真实 XML：`alnHdr` 数等于 hit 数；抽查第一条 Description 能跳到对应 pairwise。
3. Graphic Summary 要看图：Query 是黑条而不是细线或灰底。
