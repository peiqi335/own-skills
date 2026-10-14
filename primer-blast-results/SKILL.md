---
name: primer-blast-results
description: 成对 NCBI Primer-BLAST 检索、原始响应留证、产物解析与离线矩阵构建；区分 gDNA 与 mRNA 数据库，不用于单序列 blastn。
---

# 成对 Primer-BLAST 检索与离线成果看板

## 证据与安全约束

1. **原始响应与展示页分离**：submission/poll 原始字节必须留存，不注入 CSS，不以手写无产物页面代替官方响应。展示派生页另存，加入本地 CSS 和幂等 `.ncbi-live-bar`，不得冒充 raw。
2. **不把失败当阴性**：只有原始终态明确支持，才标记 `completed_no_target_template`。超时、错误、等待及未知页面分别记录；产物解析异常标记 `parse_status=needs_review`，保留原文。
3. **区分请求格式与返回绑定**：参数格式完整不代表属于该页面。核对 raw/submission/display 明示的 F/R、organism/database 和可识别长度/错配字段，明确冲突拒绝复用/发布。字段不足标记参数绑定 pending；v2 此时不生成重新检索链接。legacy 仅可提供明确标注“仅按归档请求参数”的导航，不声称返回核验通过。重新检索不保证复现旧结果。
4. **归档只追加，不覆盖、不删除**：看板输出必须使用不存在的新目录。`--force` 仅保留兼容入口，不再覆盖。拒绝源/输出相同、祖先/后代关系及符号链接路径；所有输入校验完成后才写看板。
5. **安全 resume**：已有批次只读核查，不自动重新提交。仅参数身份、原始响应 hash/终态、submission 和展示页 hash 全部可核验时复用。参数不符为 `error`/needs rerun，证据不全为 `unknown`；核查结果写入唯一的 `status.resume-<uuid>.json`，不改原 `status.json`。需要重跑时使用新准备目录。
6. **判读边界**：指标只称报告有产物、报告无产物、未完成或解析待核，不声称完全特异、设计达标或湿实验阴性。保留 `refseq_representative_genomes` 与 `refseq_rna` 的区别；状态、原始终态和产物矛盾时阻止构建。

## 已有报告生成看板（离线）

```bash
python3 .agents/skills/primer-blast-results/scripts/build_panel.py \
  /绝对路径/准备目录/status.json \
  --output /绝对路径/新的离线成果目录 --title '本批次标题'
```

- 总入口 `index.html`；矩阵 `01.成对Primer-BLAST/index.html`。
- 原始响应按归档相对路径逐字节复制；展示报告注入本地 CSS/livebar。
- `_archived-input/` 保留输入展示报告和原始状态 JSON，不将旧展示页宣称为原始 NCBI 响应。
- `status.json` 是派生状态，`checks.json` 记录源状态、归档及展示页 hash 与用途。

## 新查询（会真实访问 NCBI，须有用户授权）

```bash
python3 .agents/skills/primer-blast-results/scripts/fetch_and_prepare.py \
  --assays /绝对路径/assays.json --db refseq_rna \
  --output /绝对路径/新的准备目录 --timeout 300 --request-timeout 30 \
  --build-panel --panel-output /绝对路径/新的最终看板目录 \
  --title '本批次 mRNA 成对 Primer-BLAST'
```

`assays.json` 示例：

```json
{"RAT_1": {"forward": "ACGTACGT", "reverse": "TGCATGCA", "target_species": "RAT"}}
```

默认查询内置 15 个物种。每个请求有网络 timeout；一个查询失败不阻断其余查询。不自动重新提交缺 key、旧参数不符或非终态的归档。

## 验证

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s primer-blast-results/tests -p 'test_build_panel.py' -v
```

测试全部离线，mock 网络；临时产物仅放 `/tmp/opencode` 并保留，不使用自动递归清理。真实 RAT 82/52 fixture 只读核对，缺失时明确 skip。验收仍需核对首页状态措辞、数据库、矩阵产物、展示页 CSS/livebar、pending 和 raw/display 分离；单元测试不代替真实科学判读或视觉验收。

接口与兼容行为见 [INTERFACE.md](INTERFACE.md)。

## oracle 修复后的证据边界

- `schema_version=2` 完成项必须有完整请求参数、submission/raw 的 path/hash/time、展示页及 display hash；缺项拒绝构建，不再退回展示页假作 raw。
- `species_code` 对应的 `species_panel.organism` 必须与 query 及请求 ORGANISM 一致。
- raw/display 各自 hash 正确也不够：终态、解析状态及产物必须一致。本轮展示页从 raw 派生，旧展示输入原样放 `_archived-input/`，manifest 记录派生源 hash。
- `source_verified=true` 仅表示必需归档完整且页面明示字段与请求一致；**不是 NCBI 来源、传输真实性或服务端实际执行参数的证明**。legacy 永不自动获得此标记。
- 作业链接仅允许 HTTPS NCBI Primer-BLAST endpoint 的有效 `job_key`。`CMD=Put` 不是作业链接；`javascript:`、`data:`、非 NCBI URL 丢弃，本地报告相对路径拒绝冒号。
