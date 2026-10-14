# Primer-BLAST 工具接口（schema_version 2）

无第三方依赖，Python 标准库。`scripts/evidence.py` 是两入口共用的内部证据/解析模块。

## 命令行

- `fetch_and_prepare.py --assays PATH --output DIR [--db refseq_representative_genomes|refseq_rna] [--timeout 300] [--request-timeout 30] [--build-panel] [--panel-output DIR] [--title TEXT]`
  - `--assays` 必填：非空 JSON object，键仅字母/数字/`_`/`-`，值为 `forward`、`reverse`，可选 `target_species`。序列接受 A/C/G/T/N；物种 code 必须属于内置 panel。
  - 固定产品范围 50–2000 bp，总错配 3，3' 末端错配 2，末端区域 5 nt；请求原始参数完整记录在每条 query 的 `parameters`。更改参数需新目录重跑，不伪写旧档。
  - 网络单请求默认 30 秒；轮询预算默认 300 秒。网络异常记 `error`；轮询耗尽记 `timeout`，保留最后等待响应。
  - 新目录写 `status.json`；已存在目录必须有 `status.json`，只核查已有记录，写新的唯一 `status.resume-<uuid>.json`，不提交缺失项。参数不符 `error`、`error` 字段含 `needs rerun`；信息缺失 `unknown`。
  - 自动 build 不使用 `force=True`；构建失败不删除已完成抓取的证据。
- `build_panel.py STATUS_JSON --output NEW_DIR [--title TEXT] [--force]`
  - `--force` 为兼容选项，**仍拒绝任何已存在输出**。不存在原来的删除/覆盖语义。
  - 源目录为状态 JSON 的父目录。输出不能与源目录相同、位于源内或包含源。拒绝源路径、输入文件路径和输出路径上的符号链接。
  - JSON/schema、矩阵完整性、产物/状态/页面一致性、所有文件路径/hash、展示页可装饰性和文件目录冲突均在创建输出前检查。不删除任何文件。写入期间磁盘故障可能留下新的不完整目录；更换新目录重试，不自动清理。

## 状态 JSON

顶层字段：`schema_version`（抓取产生 2）、`created_utc`、`database`、非空 `species_panel`（`code` 唯一、`organism`），非空 `queries`。旧格式可离线构建，但必须符合矩阵、产物及终态检查；缺参数不生成查询链接，缺 raw 元数据不得安全 resume。

每个 query：

| 字段 | 含义 |
| --- | --- |
| `id`, `assay`, `species_code`, `organism`, `is_target` | 查询身份；矩阵每个 assay × species 恰一条；`is_target` 为 boolean |
| `forward`, `reverse`, `parameters` | 原归档的参数，不以本次请求替换。parameters 含 F/R、物种、数据库、产品上下限与全部错配约束及提交选项 |
| `requested_parameters` | resume 本次期望的完整参数；不代表旧查询采用过它们 |
| `requested_utc`, `finished_utc`, `job_key` | 抓取时间与作业 key；无 key 明确 null |
| `status` | 见下表 |
| `products` | `[{"template_accession":"NC_086024.1","length_bp":82}, ...]`；长度为正整数，允许同一 accession 多产物 |
| `parse_status` | `ok`、`needs_review`、`not_applicable`；解析异常不转为无产物 |
| `parse_error`, `error` | 解析待核说明或请求/归档错误 |
| `submission`, `raw_response` | 原始响应对象：`path`（批次内相对路径）、`sha256`、`received_utc`。`raw_response` 指向最后收到的响应，可能就是 submission；网络完全失败无响应则不虚构原文 |
| `submission_page` | submission 原始文件相对路径，兼容旧归档 |
| `result_page`, `display_sha256`, `display_is_derived` | 展示派生页、hash、true；不是原始响应。失败查询可为 null |
| `archived_input_page` | build 产生：未改动输入报告的备份路径；不能据此断言输入本来就是 raw |

`status` 枚举：

- `completed_results`：原始页面明确列出 product length；解析仍可待核。
- `completed_no_target_template`：原始页面明确返回无目标模板/无 primers/无 targets 的终态信息，且无产物；不从空列表推断。
- `waiting`：页面仍等待或排队（resume 核查可出现）。
- `timeout`：轮询预算耗尽，不是无产物。
- `error`：网络、HTTP、错误页面、无 key 且无直接终态、参数不符等。
- `unknown`：未识别页面或旧档证据/参数/hash 信息不足。

等待和错误标记优先于页面残留结果。没有 key 但直接返回可信完成页面可留证为 completed；没有 key 本身从不推断无产物。非完成状态不得附带产品。`completed_results` 空 products 必须显式 `needs_review`；所有已解析产物必须与归档清单相符，否则拒绝构建。页面新格式无法可靠解析时保留 raw 与解析待核，不猜 accession。

## 产物与导航

解析仅使用 `prPairDtl` 模板块内 `>` accession 标题与其后 `pre` 产物上下文；导航 accession 不参与全文 zip。一个 accession 的多个 `pre` 分别产生产物记录。无上下文、块截断、产物数量不符均待核。

展示页与 raw 各有 hash。CSS/livebar 注入幂等，gDNA 和 RNA 使用同一逻辑。可信完整参数才提供“按归档参数重新检索”及修改表单；不保证数据库更新后的结果一致。缺失参数显示 pending。`build_panel` 不使用旧的任意 result_url 生成新查询保证；保留旧 result_url 时仅作为可能过期的归档作业链接。

离线输出：总入口、`01.成对Primer-BLAST/` 矩阵、local assets、派生 `status.json`、原始响应、展示页、`_archived-input/` 原样输入报告/状态，以及 `checks.json`。checks 每条文件记录包含 `source_sha256`、`output_sha256` 和用途 `role`，源状态另有 hash。

## 返回绑定、legacy 与 URL 边界（oracle 修订）

`trusted_parameters()` 保留旧函数名，但**只检查请求参数格式**。实际页面关联使用 `response_binding(html, parameters)`，返回 `status=matched|pending|conflict`、`returned_parameters`（每字段值列表）、`missing_fields`、`conflicts`。`check_response_binding()` 对明确冲突抛 `BindingConflict`。不能把 HTML 字段一致称为传输真实性认证。

提取范围：

- HTML input 的全部 `IDENTITY_KEYS`，以及原生 `FW_PRIMER_SEQ_0` / `RV_PRIMER_SEQ_0`；重复且不同的值是冲突。
- table summary 中明确的 F/R、organism/database、`Product Size Range`、`Max Mismatches`，或规范参数键名称行。
- 原生 specificity summary 的 `selected database: … (Organism limited to …)`，以及 `ncbi_db` meta。仅支持代码列出的明确数据库别名，不泛化猜测。
- 只读 RAT 归档的原生 hidden inputs 可提取全部 9 个身份字段。其 searchInfo 表另有 `Min total mismatches=4`、`Min 3' end mismatches=3`、`Min PCR product size=60`，而 echoed request 是 3/2/50；这些可能是内部阈值/设计参数，不擅自当作同名 request 字段，也不据此声称服务端执行参数已经验证。没有 unambiguous echo 时保持 pending。未知 select/summary 格式同样保持 pending。

v2 完成项缺完整请求参数、submission/raw `path/sha256/received_utc`、`result_page` 或 `display_sha256` 时拒绝构建。存在记录但返回字段不足时仍可展示页面终态及产物，`response_binding.status=pending`、`evidence_status=pending`、`source_verified=false`，矩阵明确标注参数绑定 pending，不生成 v2 重新检索链接。resume 不能把这种记录复用为可信完成，返回 `unknown`。

`source_verified=true` 只用于 v2 必需归档完整、raw 返回字段全部与请求一致的项；不证明 NCBI 来源、传输真实性或服务端实际执行约束。legacy 可展示，但始终 `source_verified=false`；若有格式有效请求，链接只声明按归档请求参数重新检索，不声称经返回核验。legacy 明示字段与请求冲突仍拒绝构建。query 的 organism（若存在）及请求 ORGANISM 必须与 species_code 对应 panel organism 一致。

raw 与输入 display 必须有相同的终态、解析状态和 products（含 accession/length/order）；正确的独立 hash 不能豁免内容矛盾。比较通过后从 raw 生成本轮 display，旧 display 原样归档。checks 中展示文件的 `source_sha256` 是输入 display hash，`derivation_sha256` 是实际派生 raw hash，`output_sha256` 是本轮展示 hash。

`safe_job_url()` 只接受 HTTPS、host 为 `www.ncbi.nlm.nih.gov` 或 `ncbi.nlm.nih.gov`、path 为 `/tools/primer-blast/primertool.cgi`、单一非空字母数字/`_`/`-` job_key 的 URL；不允许 fragment、CMD=Put 或重检索身份参数，输出重建为规范 endpoint + job_key。其他旧 result_url 丢弃，不进入矩阵可点击 URL。重新检索只能由格式有效且符合上述绑定策略的参数生成，不能伪称 joblink。本地归档路径禁止冒号及既有越界/符号链接风险，不扩展成通用 HTML sanitizer。

测试全量命令：`PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning -m unittest discover -s primer-blast-results/tests -p 'test_*.py' -v`；新增 oracle 回归可仅运行 `-p 'test_evidence_binding.py'`。

## GDV 静态 SVG 接收边界（N1）

`gdv_delivery.static_svg()` 只接收受限 UTF-8 静态 SVG，不是通用 cleanser。解析前拒绝 DTD/entity 和除正常开头 XML 声明外的 processing instruction（包括 `xml-stylesheet`）；解析后对所有已解码 XML entities 的属性值以及 style 内容检查 CSS 资源，包括 fill/stroke/filter/clip-path/mask/marker/marker-start/mid/end/cursor 和未知属性。保守拒绝反斜线转义、`@import`、非本地 fragment 的 `url(...)`；保持原有 foreignObject/SMIL/script/event/xml:base 拒绝。

href/src 只接受非空本地 fragment，或 image 元素上的精确 `data:image/png|jpeg;base64,...`（严格 base64 与对应文件签名检查）；不接受相对文件、远程 URL、嵌入 SVG/HTML，也不声称完整解码或像素有效性。`mode=rendered` 和匹配 SHA-256 只说明模式声明与字节一致，不是资源安全或科学/视觉认证。所有检查仍在 builder 首次写入之前完成。窄回归：`python3 -B -m unittest discover -s primer-blast-results/tests -p 'test_gdv_static_n1.py' -v`。
