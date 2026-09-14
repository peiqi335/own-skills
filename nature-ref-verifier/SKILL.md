---
name: nature-ref-verifier
description: >-
  对学术文献逐条执行多源交叉验证，逐字段对比作者、标题、年份、卷期、页码，
  标记卷年/DOI年冲突、作者顺序异常、页码偏差等问题，输出结构化验证报告。
  可批量处理整篇论文/开题报告的参考文献列表，也可单条校验，支持与 Zotero 同步修正。
---

# nature-ref-verifier — 学术参考文献多源验证技能

需要处理批量差异、反复出现的字段错误、DOI/标题冲突、作者顺序异常、页码漂移或
报告措辞时，读取 `references/common-patterns.md`。其他任务不要预加载该文件；
`manifest.yaml` 记录了同一按需路由，新增资源时必须同时在本文件中写明加载条件。

## 触发词

`verify references`、`校验文献`、`check references`、`核对参考文献`、`文献验证`、`ref check`

## 适用场景

- 开题报告/论文提交前，对全部参考文献做最终核查
- 收到审稿意见指出引用错误时，精准定位问题
- 从旧项目迁移参考文献到新论文时，批量验证有效性
- Zotero 库定期健康检查

## 工作流

### Step 1: 解析输入

支持三种输入格式：

**A. 整篇论文/开题报告**
- 提取所有 `[N]` 编号的参考文献列表
- 自动识别每条的 DOI（如有）

**B. 单条参考文献**
- 用户直接粘贴一条引用文本
- 或传入 Zotero item key

**C. BibTeX 文件**
- 直接解析 `.bib`，逐条校验

### Step 2: 多源并行查询

**Step 2.0（最便宜、最先做）：DOI 可解析性检查。** 对每条有 DOI 的文献先请求 `https://api.crossref.org/works/<DOI>`：404 → 仅说明 Crossref 未查得，继续检查 doi.org、出版方或其他注册机构，不能据此判定 DOI 错误；200 → 比对返回记录的标题/作者/卷期页与条目，不一致即"DOI 张冠李戴"。记录查询来源和实际返回；200 也必须比对文献身份。

对每条文献，并行查询以下来源（可用哪些取决于环境配置）：

| 来源 | 适用文献 | 典型覆盖率 |
|------|---------|-----------|
| **Crossref** | 有 DOI 的外文期刊 | ~70%（IEEE 老文献、中文期刊常有缺失）|
| **IEEE Xplore** | IEEE 期刊/会议 | IEEE DOI 404 时的备选 |
| **WebSearch (Bing/Google)** | 无 DOI 或来源缺失的文献 | 兜底方案 |
| **CNKI/万方** (kimi-datasource / webbridge) | 中文期刊、学位论文 | 中文文献必查 |
| **Zotero 本地库** (zotero-mcp) | 已入库文献 | 快速比对已有数据 |

**查询策略：** 优先用 DOI 查 Crossref，失败后降级用标题+作者搜 Web。

**批量策略：** 超过 20 条且环境允许时，可按 10–15 条一组交给独立子代理查询后汇总；遵守来源限流，不把单次耗时经验当作保证。

### Step 3: 字段级对比

对每条文献执行以下对比矩阵，按严重程度分为三级：

核对作者及顺序、标题、年份、卷期、页码/文章号和 DOI。文献身份错配与无法定位的字段错误优先处理；格式差异单独列出。严重程度取决于实际影响，不只看页码差值。具体模式见 [common-patterns.md](references/common-patterns.md)。

### Step 4: 置信度评估

每条文献最终给出一个综合置信度：

| 等级 | 含义 |
|------|------|
| ✅ **Verified** | 多源一致，无需修改 |
| ⚠️ **Check suggested** | 存在 🟡 级差异，需人工判断 |
| ❌ **Needs fix** | 存在 🔴 级差异，必须更正 |
| ❓ **Unverifiable** | 所有来源均无法查到（如内部报告、老旧学位论文）|

### Step 5: 输出报告

支持以下输出格式：

**Markdown 摘要报告：**
```markdown
## 验证结果：56 条文献

- ✅ Verified: 42
- ⚠️ Check suggested: 8
- ❌ Needs fix: 4
- ❓ Unverifiable: 2

### ❌ 必须修正
| # | 问题 | 当前值 | 正确值 | 来源 |
|---|------|--------|--------|------|
| [6] | 作者错误 | Smogavec P | Leckebusch J | Wiley |
| [42] | 作者顺序颠倒 | Vainikainen P… | Mikhnev V A… | IEEE |

### ⚠️ 建议核对
| # | 问题 | 详情 |
|---|------|------|
| [18] | 卷年/DOI年不一致 | 卷年2025，DOI年2024 |
```

**BibTeX Patch：** 直接生成修正后的 `.bib` 文件内容。

**Zotero 更新指令：** 核验任务默认报告差异或提供补丁，不自动修改外部库。用户已授权写入时，使用当前可用的 Zotero 连接能力并核对条目身份；接口能力以实际探测为准，不直接改数据库或用新增条目冒充修正。

## 已知局限与应对

| 局限 | 应对 |
|------|------|
| **中文 DOI 不在 Crossref 中** | 降级到 CNKI/万方（通过 webbridge 或 WebSearch）|
| **IEEE 老文献 DOI 返回 404** | 用 IEEE Xplore 直接搜（其 DOI 不在 Crossref 注册）|
| **学位论文无 DOI** | 用 CNKI / 万方 / ProQuest 验证标题+作者+年份 |
| **产品手册/专利** | 不验证元数据，只确认来源可访问 |
| **谷歌学术搜不到部分文献** | 切换搜索引擎（Bing、百度学术、Semantic Scholar）|

## 环境依赖

以下工具为可选，有则启用、无则降级：

- `pyzotero[cli]`：推荐的 Zotero 读写通道（本地只读 + Web 读写双模式，CLI 可直接被 agent 以 Bash 调用，无常驻进程）
- `zotero-cli` / `zotero-mcp`：Zotero 库读写（本地包装层，实测稳定性较差）
- `kimi-datasource`（scholar）：学术搜索
- `kimi-webbridge`：带登录态的 CNKI 查询
- 基础 WebSearch / FetchURL：通用兜底
