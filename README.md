# own-skills

裴崎的 [OpenCode](https://opencode.ai) 自制 skills。本仓库是技能源码与备份，不是运行时加载点。

把某个 skill 目录拷到项目的 `.agents/skills/` 或 `.opencode/skills/`，或用户级 `~/.config/opencode/skills/`，OpenCode 才会加载。

## Skills

| skill | 用途 | 依赖 |
| --- | --- | --- |
| [gel-annotation](gel-annotation/) | 琼脂糖凝胶照片孔位标注；独立 PNG，不解释条带 | Python 3.10+、Pillow、Noto Sans CJK、能读图的模型 |
| [blast-offline-html](blast-offline-html/) | BLASTN XML 渲成可断网打开的 HTML | Python 3.10+ |
| [gdv-offline-evidence](gdv-offline-evidence/) | NCBI GDV 基因座离线 PDF/SVG/PNG 证据图 | Python 3.10+；需官方 SVG 导出 |
| [nature-ref-verifier](nature-ref-verifier/) | 参考文献多源交叉验证 | 网络；Zotero/CNKI 可选 |
| [paper2ppt](paper2ppt/) | 单篇精读后做原图驱动的可编辑 PPTX | Python 3.10+；制作阶段另需 PPT 工具 |

`gel-annotation`、`gdv-offline-evidence` 和 `blast-offline-html` 面向 PCR / 基因组 vault 的相对目录约定，不是即插即用的通用工具。`paper2ppt` 需要用户指定或确认汇报根目录。

## 安装

```bash
git clone https://github.com/peiqi335/own-skills.git
cp -a own-skills/paper2ppt ~/.config/opencode/skills/
```

或只拷进当前项目：

```bash
cp -a own-skills/gel-annotation .agents/skills/
```

License: [MIT](LICENSE)
