# 从 GDV 网页到离线成品：执行流程

本流程使用能力名称描述操作，不假定你拥有 Codex 的 `functions`、`cua_repl`、`view_image` 或固定运行时路径。先查看你在 OpenCode 当前会话中实际拥有的工具说明。不要发出不存在的调用，也不要把虚构工具返回写入报告。

## 1. 环境和来源准备

- 只查任务相关路径。当前仓库示例位于 `4.知识库/01.检测体系准备/PCR与凝胶初筛/结果汇总/primer-blast-15/06.GDV/CAT_1增强示例/`；技能内 `assets/cat1-standard/` 是冻结副本。
- 先查看根 `AGENTS.md`、`git status --short`、`git branch --show-current`。不改现有无关文件。
- 新目标：拿到其 GDV 链接或用户确认的坐标表。若 URL 中有 Markdown 转义 `\&`，只去除 Markdown 转义，不能改变数值；用 URL 解析器解析 query，再做 URL 编码，不手工拼接多层 `%25`。
- 本脚本接受包含 `id / chr / from / to / mk` 的 GDV URL。Sequence Viewer 链接要先核实对应 assembly 后规范化为 GDV 链接。无明确标记时不要自动沿用猫的 F/R。
- 建一个独立任务临时目录；网络导出和元数据先保存于该目录，再交渲染器。临时依赖不写入全局 Python、项目 package.json 或 OpenCode 配置。

## 2. 浏览器工具与页面核实

优先用当前可用的浏览器 MCP/自动化工具。先读工具说明，列出当前标签页：已有正确且加载好的页面可直接读取，避免无必要刷新而丢失轨道状态；若要改动用户正在用的视图，优先另开一个任务页面。元素 ID 来自当次页面状态，不复制历史 ID。

打开来源页后依次核实：

1. 物种名称。
2. assembly 名称和版本号，如 `GCF_018350175.1`。
3. sequence accession 和染色体名，如 `NC_058371.1 / B1`。
4. 正确窗口和 F/R 标记（红/蓝只是当前来源颜色，不能推断链向）。
5. 图形真正出现；“Getting default tracks”还不是加载完成。

常规网页抓取只能读取页面壳时，不代表基因组不存在或没有轨道。没有浏览器能力时，可使用用户已有完整官方 SVG，或按当前工具文档提供的浏览器路线获取。不能用任意静态页面截图冒充导出成功。若两种来源都不可得，完成可独立的清单/元数据准备并明确报告缺口。

## 3. 轨道检查和选择

打开 `Tracks → Configure Tracks`（具体菜单文字以实时页面为准），检查以下类别并记录标题原文：

| 类别 | 看什么 | 记录什么 |
|---|---|---|
| RefSeq | 当前 NCBI gene/transcript model；看尺标下是否有独立基因绿条，其下是否仅一行合并转录本/CDS | Annotation Release、日期、转录本 ID、显示模式（绿条+合并 vs Merge all 无 gene bar vs Show all 三行） |
| Ensembl | 同组装的 Ensembl gene models | 轨道 release，不用 Ensembl 官网最新版本替代 GDV 旧版本 |
| RNA coverage | 覆盖度曲线 | study/sample 或 aggregate、filtered、linear/log 等 |
| RNA spanning | 跨内含子 reads | 同上，不能把总 reads 当作本样本表达量 |
| RNA features | 内含子/剪接特征 | 同上及 feature 过滤状态 |
| variants | EVA/dbSNP 或该物种相容来源 | 数据库和 release、是否窗口为空 |

页面如果已有这些轨道，不重复添加。按“RefSeq → Ensembl → coverage → spanning → features → variants”的顺序优先展示，允许官方顺序与类别可用性导致差异，不能为排版改数据。RefSeq 显示模式与“是否塞满全部转录本”不是同一件事：目标是**绿条 + 一行合并转录本/CDS**（与人/鸡/羊一致）。若为 `Merge all transcripts and CDSs, no gene bar`，改成带 gene bar 的合并后重导；不要为绿条改成 Show all 三行，也不要手绘。Ensembl 默认保留官方折叠并记录 `[+N]` 和窗口边缘截断。用户要求逐转录本细查时再展开或另页。

缺失判定：

- 标题和实际数据都已加载：`loaded`。
- 已完成请求并查看，轨道存在、当前区间没有特征：`available_empty`；不能写无 SNP、无表达。
- 配置面板/来源说明证实当前物种或组装不提供：`unavailable`，写明核查入口、日期和原因。
- 未加载、请求失败、没查：留在工作清单，不能提交渲染器为完成态。不要把错误转换为 `unavailable`。

GDV 没有合适轨道时，先交付明确标缺的数据图。另下 Ensembl GFF、bigWig、VCF 并重新对齐属于不同实施路线，只有用户要求且参考组装对应已验证才扩展；不能为了“完整”静默换 assembly。

## 4. 获取官方 SVG

1. 在线窗口检查完毕后，选择图形工具栏 `Download → Printer-Friendly PDF/SVG`，不是浏览器“打印网页”。
2. 核对范围，勾选 `Include Title`，选择 `SVG`。渲染器要求 SVG 内出现序列 accession；缺标题须重导，不要手补。默认保留官方颜色和渐变。只有已证实渲染兼容问题才改 `Simplified color shading`，并记录。官方导出基准宽为 **1094 px**（与 CAT_1 标准一致），确保在 1700 画布中获得约 1.44x 舒适放大率；避免使用 1574 px 导致元素过小。轨道层级严格遵循 RefSeq → Ensembl → RNA-seq → Variants。
3. SVG 的 `Preview` 可能不可见；直接 `Download` 即可，不反复点击不存在的预览按钮。
4. 等待状态从 `Creating File` 转为下载完成；不能只看点击成功。
5. 若下载重定向到 `ncfetch.cgi`，这是本次生成文件的地址。可用浏览器下载，或在宿主允许且不是安全拦截的情况下用实际返回地址取回公共文件：

```bash
python3 .opencode/skills/gdv-offline-evidence/scripts/fetch_ncbi.py export '本次页面实际返回的完整HTTPS地址' -o /tmp/本次任务/official.svg
```

这不是固定 API 参数模板：**不得复用旧的 `NCID_...` key、猜导出地址、读取浏览器私有凭据，或绕过浏览器安全/证书/验证码拦截。** 若出现安全拒绝，保留页面并按宿主规则处理。普通下载处理失败也不能未经判断一律绕过。

浏览器 Download 失败或无法稳定点选时，可用 Sequence Viewer 同源接口作为备援，不得复用过期 `NCID`：

```bash
python3 .opencode/skills/gdv-offline-evidence/scripts/export_tracks.py /绝对路径/spec.json \
  --catalog /绝对路径/该组装_tracks.json --include-variants -o /tmp/本次任务/official.svg
```

`--catalog` 必须是本次从 `disptracks.cgi` 保存的该组装目录。导出后仍须打开 SVG/PNG，确认变异刻线或基因模型真正出现；接口与直播 GDV 不一致时，以直播页面为准并改回浏览器 Download。

6. XML 根必须为 SVG，不能是返回 HTTP 200 的错误 HTML。验证有目标 accession、标记、各已加载轨道标题。真正渲图确认轨道图形存在，且 RefSeq 尺标下有独立基因绿条（基因符号白字在带上），其下只有一行合并转录本/CDS，不是绿/紫/红三行；不能仅搜标题。缺绿条或行数不对则改显示模式后重导，不在增强版上涂色。
7. 保存原件哈希。正式排版不重画官方轨道，不改变柱高、外显子、SNP 或各轨道间的坐标位置。

## 5. 获取序列长度与填写 spec

```bash
python3 .opencode/skills/gdv-offline-evidence/scripts/fetch_ncbi.py metadata NC_058371.1 -o /tmp/本次任务/chromosome_metadata.json
```

上面 accession 只示范 CAT_1；处理其他物种必须替换。脚本请求官方 nuccore ESummary 并核对带版本的 accession。`slen` 是定位条的长度；组装对应和染色体名称仍要从 GDV/assembly report 核实。

按 `specification.md` 建 spec，文件路径相对于 spec 所在目录。为 CAT_1 标准回放可以直接用随附 spec，无需联网。

若要在 03 区标外显子，或 `mk` 已含 `exN`：用官方 SVG 中已出现的一条 `XM_`/`NM_`，取该转录本在当前序列上的外显子 `order/begin/end`。只保留「所有引物段都完整落在其外显子内」的转录本；仍多条且编号一致时优先 `NM_`；编号冲突则停该座。写入 `spec.exons`，不要从图上量坐标，也不要按 Ensembl/相邻基因/合并条上多出来的框给 `mk` 编号。`exN` 必须等于落入的 `order`；02 区尺标与 03 区同名。默认不改官方 SVG 几何；用户明确授权纠正错误标记名时，才等长替换尺标/`mk` 文字或重导。

```bash
python3 .opencode/skills/gdv-offline-evidence/scripts/fetch_ncbi.py product_report XM_011281731.4 -o /tmp/本次任务/product_report.json
```

上面 accession 只示范 CAT_1；处理其他物种必须替换。返回 JSON 须含目标转录本。把文件写入 `spec.product_report` 并随目录归档。

## 6. 本地渲染依赖

校验模式只依赖 Python 标准库，实际 PDF/PNG 转换需要 CairoSVG 及系统 libcairo；中文推荐 `Noto Sans CJK SC`。

先检查，不要反复重装：

```bash
python3 -c 'import cairosvg; print(cairosvg.__version__)'
fc-match 'Noto Sans CJK SC'
```

若宿主已有文档运行时，用它的 Python。否则在独立临时目录建立环境，例如：

```bash
python3 -m venv /tmp/gdv-skill-venv-本次编号
/tmp/gdv-skill-venv-本次编号/bin/python -m pip install 'CairoSVG==2.9.1'
```

先把“本次编号”替换为实际唯一名字。如 venv/libcairo/字体缺失，使用现有环境或按宿主权限安装明确所需依赖；不未经授权改系统环境。`pip` 安装不自动提供 libcairo 或中文字体。若只能产出 SVG，就明确 PDF/视觉验收尚未完成，不能以 PNG 塞入 PDF 宣称矢量成功。

执行 `render_gdv.py spec.json --validate-only`，再以不存在的新目录 `-o` 渲染。脚本默认不覆盖任何输出；保留上一版，修正 spec 后选择新版本目录。

## 7. 视觉验收与归档

- 用图像工具打开生成的 PNG（不是文本读取）。再单独栅格化 PDF，例如 `pdftoppm -scale-to 1700 -png -singlefile 成品.pdf /tmp/本次任务/pdf-check`，打开结果图片。
- 对照 `quality-standard.md`；需要时看局部放大。轨道太密时增加官方导出画布高度、调整真实轨道显示或分成多页，不粗暴垂直拉伸原轨道。
- 更新 `source_notes.md` 的验收栏，记录看过哪些文件、真实缺口；更新 `checks.json` 的 `visual_review`、日期、查看工具/文件，并重算被修改文件的 SHA-256。
- 原件哈希必须一致。断网依然显示所有图形；网页超链接只是来源，不是渲染依赖。

## 故障恢复表

| 现象 | 已知含义 | 有限恢复动作与停止条件 |
|---|---|---|
| Failed to get default tracks | 默认轨道请求未成功，原因未定 | 保留已加载页面；隔数秒重试一次，再检查失败请求状态。不能说是坐标错或无注释 |
| 页面 500 / 导出 5xx | 本次服务器响应失败 | 对同一操作最多再试两次；记录实际响应，不把重试成功说成已定位上次根因 |
| 429 | 请求受限 | 按 Retry-After 等待（若宿主允许）；不并发放大请求或更换身份绕限 |
| Request failed | 导出尚未完成 | 一次重试；查看状态/响应。已有网页图不能当作成功 SVG |
| ERR_BLOCKED_BY_CLIENT | 客户端拦截，成因需要查明 | 区分安全策略与普通下载处理问题；不自动关扩展、代理或防护。遵守宿主规则 |
| SVG/PNG 黑色背景 | 可能透明图叠在黑底 | 在增强版根节点放实白底；不改原始轨道颜色或把黑区涂白掩盖数据 |
| 文字缺字 / 方框 | 字体未覆盖 | 使用已安装的中文字体，重渲 PDF 和 PNG 并实际查看 |
| 标题比窗口少 1 bp | 坐标约定可能不同，不能直接断定 | 保留原件，明确网页 1-based 坐标；只精确替换标题，不平移任何轨道 |

原流程中曾观察到临时轨道失败、500、下载拦截和成功重试。它们是不同阶段的真实现象，不代表所有错误都可通过刷新修复。

## 官方资料

- [OpenCode skills 路径、frontmatter、加载与权限](https://opencode.ai/docs/skills/)
- [GDV 配置轨道与页面说明](https://www.ncbi.nlm.nih.gov/gdv/browser/help/)
- [NCBI 矢量导出说明](https://www.ncbi.nlm.nih.gov/tools/sviewer/renderpdf/)
- [Sequence Viewer 标记及 URL 参数](https://www.ncbi.nlm.nih.gov/tools/sviewer/url_access/)

资料核对日期为 2026-09-12。实际 UI 变化时依据当前界面与官方文档调整，不凭记忆固定元素索引。
