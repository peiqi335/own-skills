# 维护说明

本页保存作者本机的标准样板、历史回放与运行时同步事实，不是安装前置步骤，也不表示重新验证了历史科学来源或完成了视觉验收。普通使用见 [根 README](../README.md)。

## 标准样板与模块 CLI 导航

本机项目标准样板位于 `/home/qi/文档/课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14/`；真实输入、身份、样本配置、回放报告和实验边界保留在项目，不灌入通用 skill。

以下模块命令从本仓库根目录执行，`SPEC.json`、`PROJECT`、`NEW_REVIEW`、`INPUT.xml`、`NEW_OUTPUT` 是待替换的实际路径，不是自带输入：

- **凝胶新输入**：见 [模块 README](../gel-annotation/README.md) 与 [规范参数模板](../gel-annotation/assets/recognized_minimal.spec.template.json)。`python -B gel-annotation/scripts/annotate_gel.py SPEC.json --repo PROJECT --review-dir NEW_REVIEW` 实际执行 opt-in `recognized_minimal_v1` 的前提是 spec 显式选择该 profile；历史图补丁重建使用独立 `replay_operations.py`，不能继承旧科学事实。
- **GDV**：见 [模块 README](../gdv-offline-evidence/README.md)。`python -B gdv-offline-evidence/scripts/render_gdv.py SPEC.json --input-root PROJECT --validate-only` 核验真实输入；需要绘图依赖时使用项目已有环境，不把缺 Cairo 的普通 Python 当科学输入失败。
- **BLAST XML**：`python -B blast-offline-html/scripts/render_blast_offline.py INPUT.xml -o NEW_OUTPUT`；不提交网络查询。
- **成对 Primer-BLAST／离线站点**：见 [接口](../primer-blast-results/INTERFACE.md)；总入口由项目整合流程维护。`runtime-sync.json` 保留阶段 partial 记录，当前四模块同步及窄验证见项目标准样板根的 `runtime-sync-final.json`；不能把模块检查当整体任务或最终视觉验收通过。

## 本机统一重建

项目统一重建使用已归档的 `standard-case.json` 与模块配置，不要求使用者再次提供历史样本 spec；新实验仍须提供本次真实输入与身份。下面是本机历史回放入口，依赖该项目文件与环境；命令须使用**不存在的新输出根**，不能因目录已存在而删除原归档：

```bash
P='/home/qi/文档/课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14'
python -B "$P/scripts/rebuild_standard.py" \
  --gdv-python /tmp/opencode/gdv-replay-venv/bin/python \
  --output "$P/统一回放/fresh-root"
```

`/tmp/opencode/gdv-replay-venv/bin/python` 是当时的本机环境路径，不是随仓库提供的 Python；重跑前须确认环境仍存在且满足转换依赖。

### 历史事实与未决边界

- GEL 的 legacy 旧图 → 定稿 14 张 byte 一致，原图 raw 链仍未通过；不能把旧图回放一致升级为原始科学来源认证。
- GDV 由模块真实转换；site 接入固定 rendered 资源时是字节复制，不能据复制同一 PDF 声称真实转换的 PDF 字节确定。真实 Cairo 会写 PDF CreationDate，环境和字体也可能影响输出。
- CLI 产物与机械比对不等于科学来源或最终视觉认证。站点整合、实际看图和科学审核仍分别承担自己的验收。

### 仅本机导航

下列链接跨出此仓库，仅在作者本机目录布局和文件仍存在时可用；它们不是可移植包字段，也不是公开在线展示入口。相对路径以本页所在的 `docs/` 为基准：

- [最终候选站点（仅本机）](../../课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14/统一回放/final/run-A/site/index.html)
- [整合交付报告（仅本机）](../../课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14/统一回放/final/交付/phase2-verification.json)
- [最终 runtime 同步审计（仅本机）](../../课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14/runtime-sync-final.json)

## 本地运行时同步

2026-10-14 原样同步本地运行时，排除 Python 缓存。前四个技能来自 `/home/qi/文档/课题实验/.agents/skills/`（凝胶、BLAST XML、Primer-BLAST、GDV）；`paper2ppt` 来自 `/home/qi/文档/法医动物非人源/.agents/skills/`。

同日依据实际结果修复凝胶、Primer-BLAST 与 GDV 技能，并同步上述实验仓库运行时副本。凝胶新增可选简洁版、真实样本与展示标签分离、随图回放清单及候选覆盖保护；未反推旧图配置或修改实验原件。技能变更在新的 OpenCode 会话中重新加载；如需立即使用，重启 OpenCode。

实际检查、独立审查及仍待核事项见 [修复验收记录](../修复验收_2026-10-14.md)。以上是历史同步记录，不代表当前所有运行时副本已再次检查一致。
