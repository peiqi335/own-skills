# Gel annotation：新输入与历史回放

默认视觉仍由 `assets/style_profiles/second_batch_v1.json` 提供；没有改色、字体或几何默认值。

## 新实验输入机制

使用本次原图的 spec（身份、孔位、日期和 Ladder 依据必须由项目提供），不能复制历史补丁当默认规则。

```bash
python -B gel-annotation/scripts/annotate_gel.py /absolute/path/spec.json --repo /absolute/path/project
python -B gel-annotation/scripts/batch_replay.py /absolute/path/batch.json --output /absolute/path/new-run
```

`batch.json` 的格式：

```json
{"schema_version":1,"items":[{"id":"sample-01","spec":"spec.json","spec_sha256":"SPEC_SHA256"}]}
```

spec 需要 `src`、`source_sha256`、包含 `（标注）` 的 PNG `out` 和当前原图对应的 `rows`。所有项目内容留在项目目录。可指定 `style_profile`、`font_paths`、`font_sha256`、`font_layout_engine`、`font_face_index`；默认值保持原样。executor 对全批真实字体/图像/绘制先预检，然后只写全新输出目录，保存 finalspec、annotation manifest 和 review。普通旧调用保留明示的字体绝对路径契约；可携带配置使用 `portable_resources: true`，归档相对字体路径，并须携带实际字体文件与 SHA（不 fallback）。

公共 Python `preflight/replay` API 与 CLI 均以调用者 cwd 解释相对 batch/output/repo；spec 的相对输入仍以 spec 目录（或明示 repo）解释。全批文件、manifest、finalspec、review 目录及文件/目录祖先冲突在第一次写入之前拒绝；输入可合法共享，但 write/input alias、词法路径 symlink、非普通文件、`3.记录` 均拒绝。

## 已知历史操作回放（不是新实验默认）

```bash
python -B gel-annotation/scripts/replay_operations.py /absolute/path/historical-batch.json --output /absolute/path/new-run
python -B gel-annotation/scripts/compare_replay.py left.png right.png --roi 0,700,1600,1600 --diff /absolute/path/new-diff.png
```

项目 recipe 明确提供 hash-bound `inputs`、`start`、字体和按序 `operations`。通用 executor 只支持显式 rectangle、text、paste、expand_bottom、restore_gray，不内置物种、日期、框或历史修补参数，不执行 Python/JS/shell。`restore_gray` 严格按旧像素 `r == g == b > 0` 恢复；不能用大黑框代替。

`text` 支持显式 `language`、`layout_engine`（`RAQM`/`BASIC`）、`face_index`、`direction`、`features`；省略 language 仍为旧 Pillow 默认 `None`。最终 spec 保存实际 engine、文字 bbox、language/face、Python/Pillow/FreeType/RAQM 及可用 HarfBuzz/FriBidi 版本、进程 locale。Pillow 未暴露的版本保存 null，不编造。`canonical_footer_v3.json` 仅是显式 opt-in 的日期/引物 footer role（`language=en`），不是新物种事实或对未记录历史 locale 的断言；`second_batch_v1` 默认不变。

crop/paste/文字/rectangle/restore_gray 均检查有限坐标与源/目标边界，expand_bottom 必须正整数。仅历史 rectangle 的精确 W/H 一 past inclusive 端点允许数学等效规范化，finalspec 同存 original_box/effective_bounds。`signal_roi` 默认验证 start source 到输出同位置像素不变；可提供 `signal_preservation={source,source_roi,offset}` 明示源/目标 ROI。不再只登记字段。canonical 禁止作为 start 或 paste 来源。

可移植资源应只携带一份 fonts（及版权）、profile、原始 data、代码/helper snapshots、身份映射和历史片段，以相对 spec/bundle 路径与 SHA 绑定。`bindings` 的 executor 字段同时核验实际运行的代码 SHA；identity binding核验 id/date/sample_mapping。更换依赖/locale 需重新做 pixel 对比，记录环境不等于保证任意环境均字节一致。

最终 byte、decoded pixel、明确注册的 signal ROI、记录的 geometry 分开比较。decoded 对比只支持 RGB/RGBA/L；palette/transparency 不以索引字节冒充颜色相等。缺失 canonical spec 时 geometry 是 missing；diffPNG 或重复渲染一致不等于视觉审批，更不能把不一致改成通过。

## 窄验证

```bash
python -B -m unittest discover -s gel-annotation/tests -p 'test_*.py'
```

37 个现有 + 原4项 + M1–M4及profile/finalspec有效参数测试10项 = **51 passed**。新增覆盖末项保留名冲突、batch/recipe/direct-input symlink零写入、异spec目录的相对API、操作边界/ROI/扩展、明确edge normalization、字体错误SHA、palette限制、字号参数真实影响及保存spec重放。新输入测试使用合成图，不冒充新实验验证。

真实项目 v3：旧图→定稿14/14 byte与pixel相同、双run14/14、注册ROI14/14；搬移独立 bundle 后实际重放保存finalspec也是14/14。raw→old→final仅4项有记录，locale-only尝试仍0/4严格匹配，另外10项缺raw→old spec。旧两版0/14失败报告保留。具体命令与证据见项目 `标准样板_2026-10-14/凝胶/README_v3.md`，视觉验收仍属父代理。
