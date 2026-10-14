# GDV 离线证据回放

本技能组合既有官方 SVG 和来源 spec，不从模板伪造新实验、不联网加载字体、不改变官方轨道几何。来源说明、轨道内容与引物绑定是否科学成立仍需独立复查。

## 有限 profile 合约

`assets/render_profile.json` 是完整 schema v1。`load_profile`、`compose`、`render` API 和 CLI 的 `--profile` / `--validate-only` 均检查完整字段、未知字段、数值类型与有限性、颜色与字体字符串。

- `width.minimum`: 1000–10000；`source_scale`: 0.1–10。
- 可选 `width.canvas_width`: 1000–10000 范围整数的固定画布，不增加自动布局框架；省略时保留原默认公式与输出。`assets/recognized-standard-profile.json` 使用 1700，依据项目历史 15 份认可 SVG 的真实 width/viewBox；不按物种硬编码，也不靠猜 source_scale 调宽。
- **`width.padding` 固定为 126**，对应现有 63 px 两侧轨道留白。不是任意 layout API。
- 9 个字号槽位允许 1–128；13 个颜色槽位只允许 `white` 或六位十六进制颜色。
- 这些范围是输入合约，不是所有字号/宽度组合的视觉适配保证；不调整行高、折行或碰撞布局。官方 SVG 内部原有字体、颜色不被 profile 重写。

## 命令

```bash
/tmp/opencode/gdv-replay-venv/bin/python gdv-offline-evidence/scripts/render_gdv.py \
  gdv-offline-evidence/assets/cat1-standard/spec.json \
  --profile gdv-offline-evidence/assets/render_profile.json --validate-only
/tmp/opencode/gdv-replay-venv/bin/python -m unittest discover \
  -s gdv-offline-evidence/tests -p 'test_profile_batch.py' -v
```

实际批量回放用 `scripts/batch_replay.py --repo <项目根> --manifest <配置JSON> --output <新目录> [--profile <JSON>] [--validate-only]`。配置包含 repo 相对 `source_manifest`；其 loci 绑定 `locus`、`revised_spec`、`original_spec`。所有输入先 load/compose/sha，拒绝重复 ID、hardlink spec/SVG alias、source/destination 嵌套、路径逃逸和 symlink。任一输入失败不会创建输出目录；转换期故障则可能留下新目录的部分输出，保留用于诊断，不覆盖/删除再试。

## 归档与证据边界

每座输出可迁移的 `spec.json`（finalspec）和证据副本、实际 `render_profile.json`、`checks.json`（输入/输出 SHA）、`environment.json`（Python 二进制、CairoSVG 源文件、Cairo/Fontconfig/FreeType 实际加载库、字体解析及实际 mmap 字体 SHA）。系统文件位置使用 system-root 相对路径，包文件位置使用 distribution 相对路径；hash 才是身份键。`fc-match` 是 family/style 解析，不是逐字形 fallback 证明；实际 mmap 字体清单可能与 regular 查询不同。

本地审计时间只在 `execution.json`，不写入 SVG/spec/profile 内容。**真实 Cairo 仍会在 PDF 中写入 CreationDate**，因此不保证 PDF 原始字节可重复，且不剥 metadata 冒称原 PDF 一致。

批量输出 `actualmanifest.json` 的路径相对于该 manifest 目录（`source` / `input_sha256` 的路径相对于 repo）。每座有 `relative_directory`、SVG/PNG/PDF `relative_output`、独立 PDF 预览、`source_status`、原始 hash、decoded pixels、历史差分和科学字段差分。端点记录的 `mRNA_report_path` 已规范为 repo 相对路径，每条明示 `path_base=repository_root` 并存来源 hash，不升级科学 pending。两次 PDF 由 `pdftoppm` 独立栅格化；时间依赖差异保留原字节范围及解压 stream 诊断。

历史对照还输出 `historical_png_difference.png` 和同环境旧轨道声明控制 SVG/PNG：仅还原旧 tracks 声明，固定当前 renderer/profile/证据。声明修订（含历史来源文本、六项空轨道纠正）与历史 style/environment 聚合差异分列，不把后者武断归因某一个字体。不同尺寸按左上角对齐、透明补齐、不缩放比较。

`test_profile_batch.py` 含真实 CairoSVG/finalspec 集成及合约测试；原 33 tests 中 3 个转换局部回归现在 mock `convert_svg`，不能代替真实转换。`test_oracle5.py` 含 8 个最窄 M1–M5/认可标准反例，真实调用安装的 CairoSVG Tree/Surface，证明 escaped import 到达 fetch callback 后在外部 I/O 前被拒绝。真实 15 座边界/finalspec/字节与像素验证、PDF 原因诊断及 661 文件只读基准验证见项目 `README-final04.md`、版本化 delivery 和报告。

## 输入根策略与资源层防线（Oracle5 修订）

- `load_spec(spec, *, input_root=None)`、`render(spec, output, profile=None, *, input_root=None)` 和 CLI `--input-root` 默认根为 spec 所在目录。合法 `../` 证据跨目录时必须显式给可信根，批量 `--repo` 就是显式项目科学输入根。先逐词法分量检查 symlink（包括 `link/../`），再归一化并检查根包含和普通文件类型。兼容根内历史绝对 official/metadata 路径；product_report/primer 来源仍要求相对路径。
- 所有科学来源（spec、SVG、metadata、assembly、product_report、primer 来源、page capture）都经同一检查；direct API/CLI 不能把新输出放在任何科学来源目录内。`--validate-only -o` 也检查输出策略。OS 字体、Python 和系统库是环境依赖，不使用科学 input-root 去拦截它们。
- `safe_svg`/`compose` 用现有 tinycss2 递归检查 normalized at-keyword、URL/function/block，拒绝 CSS 转义 import、font-face 外部资源、active XML 元素、外部 href 和 xml:base。已知 NCBI 原字体 import 仅在本地副本移除。
- 最终转换唯一入口为 `PDFSurface/PNGSurface.convert(bytestring=..., url_fetcher=offline_fetch)`，不依赖高层 `svg2png` 的签名。fetcher 不调用任何外部 fetch/urlopen，仅可返回经签名/真实解码验证的嵌入 PNG/JPEG；拒绝 HTTP/file/样式/字体/dataSVG，内部 fragment 不需要外部 fetch。SVG/XML 混入栅格也拒绝，不让 Cairo 的嵌套 SVG 分支绕过。生成给 site 内联的 SVG 同样做 token/XML 校验。
- original JSON/tracks 的控制图必用 shape/字段在 batch preflight 解析、检查并提前 compose；非法原 JSON、缺 tracks 或坏 shape 在 mkdir 前失败，不把旧声明检查当科学批准。
- 字体 records 是审计身份，**不是跨机器字体锁或自动 pixel 一致保证**；`family_resolution` 显式标请求字体命中/替代 fallback，迁移后版本、文件或 fallback 不同都可能改变像素。
- `scientific_review` 始终未决，需要真实结合证据和用户科学审核；技术组件 review（包括 Oracle）不批准 marker 绑定。父任务仍负责视觉检查。
