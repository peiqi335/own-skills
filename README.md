# own-skills

裴崎的 [OpenCode](https://opencode.ai) 自制 skills：给凝胶图标孔、把 BLAST XML 做成离线页、运行成对 Primer-BLAST 并生成离线看板、归档 GDV 基因座、把单篇论文做成原图 PPT。

本仓库是源码，不是运行时加载点。拷进 OpenCode 的 skills 目录后才会被发现。MIT。

## 目录

- [快速入门](#快速入门)
- [可选：不启动 OpenCode 看产物](#可选不启动-opencode-看产物)
- [Skills](#skills)
  - [gel-annotation](#gel-annotation)
  - [blast-offline-html](#blast-offline-html)
  - [primer-blast-results](#primer-blast-results)
  - [gdv-offline-evidence](#gdv-offline-evidence)
  - [paper2ppt](#paper2ppt)
- [安装位置](#安装位置)
- [边界](#边界)
- [License](#license)

## 快速入门

1. 克隆本仓库，把要用的 skill 拷到 OpenCode 能找到的位置（项目级优先）：

   ```bash
   git clone https://github.com/peiqi335/own-skills.git
   mkdir -p .agents/skills
   cp -a own-skills/paper2ppt .agents/skills/
   ```

2. 重启 OpenCode，或在当前会话重载 skills。
3. 把论文路径换成你的文件，直接说：

   ```text
   启动 paper2ppt 工作流，论文在 ./papers/example.pdf
   ```

其余 skill 同样只需要一句话：

```text
给这张第二批凝胶标孔，泳道从左到右是 Marker、样品1、NTC
把这份 BLAST XML 渲成可断网打开的 HTML
按 CAT_1 标准做这个 GDV 基因座的离线证据图
```

详细规则在各目录的 `SKILL.md`。未指定输出位置时，agent 按该 skill 的约定落盘，而不是写进本仓库。

### 标准样板与模块 CLI 导航

本机项目标准样板位于 `课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14/`；真实输入、身份、样本配置、回放报告和实验边界保留在项目，不灌入通用 skill。

- **凝胶新输入**：见 [模块 README](gel-annotation/README.md) 与 [规范参数模板](gel-annotation/assets/recognized_minimal.spec.template.json)。`gel-annotation/scripts/annotate_gel.py SPEC.json --repo PROJECT --review-dir NEW_REVIEW` 实际执行 opt-in `recognized_minimal_v1`；历史图补丁重建使用独立 `replay_operations.py`，不能继承旧科学事实。
- **GDV**：见 [模块 README](gdv-offline-evidence/README.md)。`gdv-offline-evidence/scripts/render_gdv.py SPEC.json --input-root PROJECT --validate-only` 核验真实输入；需要绘图依赖时使用项目已有环境，不把缺 Cairo 的普通 Python 当科学输入失败。
- **BLAST XML**：`blast-offline-html/scripts/render_blast_offline.py INPUT.xml -o NEW_OUTPUT`；不提交网络查询。
- **成对 Primer-BLAST／离线站点**：见 [接口](primer-blast-results/INTERFACE.md)；总入口由项目整合流程维护。`runtime-sync.json` 保留阶段partial记录，当前四模块同步及窄验证见项目标准样板根的 `runtime-sync-final.json`；不能把模块检查当整体任务或最终视觉验收通过。

项目统一重建使用已归档的 `standard-case.json` 与模块配置，不要求使用者再次提供历史样本spec；新实验仍须提供本次真实输入与身份。命令须使用**不存在的新输出根**：

```bash
P='/home/qi/文档/课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14'
python -B "$P/scripts/rebuild_standard.py" \
  --gdv-python /tmp/opencode/gdv-replay-venv/bin/python \
  --output "$P/统一回放/fresh-root"
```

分层边界：GEL的legacy旧图→定稿14张byte一致，原图raw链仍未通过；GDV由模块真实转换，site接入固定rendered资源时是字节复制，不能据复制同一PDF声称真实转换的PDF字节确定。CLI产物与机械比对不等于科学来源或最终视觉认证。

本机导航：[最终候选站点](../课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14/统一回放/final/run-A/site/index.html) · [整合交付报告](../课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14/统一回放/final/交付/phase2-verification.json) · [最终runtime同步审计](../课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14/runtime-sync-final.json)。这些跨目录链接只供本机导航，不是可移植包字段。

## 可选：不启动 OpenCode 看产物

脚本可以单独跑。下面用自带夹具生成一页离线 BLAST HTML：

```bash
git clone https://github.com/peiqi335/own-skills.git
cd own-skills
python3 blast-offline-html/scripts/render_blast_offline.py \
  blast-offline-html/tests/fixtures/tiny_blastn.xml \
  -o /tmp/own-skills-blast-demo
```

输出是 `/tmp/own-skills-blast-demo/tiny_blastn.html` 和同目录的 `viewer.css`。浏览器直接打开该 HTML（`file://` 可用），应看到 query 长度 20、黑色 Query 主条、两条命中。这只验证渲染器，不跑 `blastn`。

## Skills

### gel-annotation

给琼脂糖凝胶照片标孔位和泳道身份，另存 PNG。只定位、只标注，不解释条带，不改实验记录页。

**你说什么**

```text
给这张第二批凝胶标孔，泳道从左到右是 Marker、样品1、NTC
```

**得到什么**

原图旁一份新 PNG（引线准确落在孔心、支持分组层级、空孔避让与已核实的 Ladder 标尺，不覆盖原图）。

尚无确认方案时，agent 先给逐孔表和执行方案，等你确认再画。几何来自本轮对这张图的扫描；身份只能来自你的说明或你指定的记录。

**不要指望它**

从图上有没有条带来猜空孔，或把命中写成 PCR 结论。

### blast-offline-html

把已有单 query BLASTN XML（`-outfmt 5`）渲成可拷到 U 盘、断网双击打开的结果页。权威数据是 XML；页面只是展示层。

**你说什么**

```text
把 ./hits.xml 渲成可断网打开的 HTML
```

**得到什么**

一个目录，通常是 XML 旁的 `blast-offline/`（调用 CLI 时必须 `-o`）：

```text
blast-offline/
├── tiny_blastn.html
└── viewer.css
```

页面含 Graphic Summary、Descriptions、pairwise alignments。夹具 `tests/fixtures/tiny_blastn.xml` 的 query 长 20 bp、两条命中；渲染结果无 NCBI 外链。不跑 BLAST，不拉 RID。

**不要指望它**

把 BLAST 命中当成物种鉴定，或从胶图反推坐标。

### primer-blast-results

读取成对 F/R 引物，向 NCBI 提交 Primer-BLAST，或将已有报告与 `status.json` 打包成离线看板。支持基因组 `refseq_representative_genomes` 和转录组 `refseq_rna`；输出总入口、引物×物种矩阵、报告预览和哈希清单。详细输入及命令见 [SKILL.md](primer-blast-results/SKILL.md)。

2026-10-14 已补状态与来源保护：超时、错误和证据不足分别登记，不合成阴性；原始响应与展示页分开归档；复用前核对引物、物种、数据库、参数和哈希。看板必须写入新目录，`--force` 不再允许覆盖已有目录。接口与旧归档处理见 [INTERFACE.md](primer-blast-results/INTERFACE.md)。预测结果不是湿实验验证结论，历史重建页缺原始响应时保留为来源待核。

### gdv-offline-evidence

把 NCBI GDV / Sequence Viewer 的指定基因座做成可断网打开的多轨道 PDF、SVG、PNG，并留下来源与检查记录。

**你说什么**

```text
按 CAT_1 标准做这个 GDV 链接的离线证据图
```

**得到什么**

用户指定结果目录下的一套文件，例如 `{locus_id}_enhanced.png`、官方轨道 SVG、`spec.json`、`source_notes.md`。标准例（猫 B1 / SOWAHB，不是通用装饰图）：

![CAT_1 多轨道离线证据图](gdv-offline-evidence/assets/cat1-standard/CAT_1_enhanced.png)

轨道保持 NCBI 官方显示；RNA-seq 是公共证据，变异轨道不是本样本基因型。完整标准在 [`assets/cat1-standard/`](gdv-offline-evidence/assets/cat1-standard/)。

有外显子的输入须绑定 `product_report` 并按转录本版本、基因组 accession、链向及完整坐标校验。轨道内容与视觉验收仍需人工复核；原件标题端点观测不等于已知坐标约定。冻结 CAT 示例的空 EVA 窗口已更正登记，历史图像不重绘。

**不要指望它**

从截图猜坐标，或自动判定引物特异性、注释一致、实验验证通过。

### paper2ppt

单篇精读、讨论逻辑主线，确认后再做原图驱动的可编辑 PPTX。图只来自该论文及补充材料，允许裁切和等比缩放，禁止生成或重绘机制图。

**你说什么**

```text
启动 paper2ppt 工作流，论文在 ./papers/example.pdf
```

**得到什么**

先是精读笔记和讨论，正常停在「待主线确认」。你说「按这个主线制作」之后，才有 PPT。归档示例：

```text
第一作者_年份_简短题名/
├── 00.任务进度.md
├── 01.精读笔记.md
├── 02.讨论与汇报主线.md
├── 03.逐页安排.md
├── 04.原图清单.md
├── 05.验收记录.md
├── 原图/
└── 汇报/
    └── 第一作者_年份_文献汇报_v01.pptx
```

未指定根目录时，agent 会找项目里的 `6.文献汇报/`，找不到再问。「懂了，继续讲」只推进讨论，不等于授权做 PPT。

**不要指望它**

跳过精读直接出幻灯片，或用外部/生成图装饰。

## 安装位置

| 位置 | 作用 |
| --- | --- |
| `<项目>/.agents/skills/<name>/` | 仅该项目；优先用这个 |
| `<项目>/.opencode/skills/<name>/` | 仅该项目（OpenCode 布局） |
| `~/.config/opencode/skills/<name>/` | 当前用户所有项目 |

每个 skill 保持独立目录，不要打散 `SKILL.md`、`scripts/`、`references/`、`assets/`。拷完后重启或重载，否则 agent 仍看不到。

## 边界

- `gel-annotation`、`gdv-offline-evidence`、`blast-offline-html` 面向 PCR / 基因组 vault 的相对目录（如 `1.原始资料/`、`4.知识库/`），不是即插即用的通用工具。
- `paper2ppt` 需要你指定或确认汇报根目录。
- 胶图、BLAST 命中、GDV 轨道都不是湿实验结论。

## License

[MIT](LICENSE) © 2026 裴崎

## 本地运行时同步

2026-10-14 原样同步本地运行时，排除 Python 缓存。前四个技能来自 `/home/qi/文档/课题实验/.agents/skills/`（凝胶、BLAST XML、Primer-BLAST、GDV）；`paper2ppt` 来自 `/home/qi/文档/法医动物非人源/.agents/skills/`。

同日依据实际结果修复凝胶、Primer-BLAST 与 GDV 技能，并同步上述实验仓库运行时副本。凝胶新增可选简洁版、真实样本与展示标签分离、随图回放清单及候选覆盖保护；未反推旧图配置或修改实验原件。技能变更在新的 OpenCode 会话中重新加载；如需立即使用，重启 OpenCode。

实际检查、独立审查及仍待核事项见 [修复验收记录](修复验收_2026-10-14.md)。
