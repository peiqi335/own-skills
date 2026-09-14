#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html as htmlmod
import re
import math
import sys
from urllib.parse import quote
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
CSS_SRC = SKILL_ROOT / "assets" / "viewer.css"
EMPTY_QUERY_DEF = {"", "No definition line", "None"}


def parse_xml(path: Path) -> dict:
    raw = path.read_text("utf-8")
    xml = re.sub(r"<!DOCTYPE[^>]*>", "", raw, count=1)
    root = ET.fromstring(xml)
    if root.tag != "BlastOutput":
        raise ValueError(f"{path}: unsupported XML format (expected BlastOutput)")
    if root.findtext("BlastOutput_program") != "blastn":
        raise ValueError(f"{path}: BlastOutput_program must be blastn")
    iterations = root.findall("BlastOutput_iterations/Iteration")
    if len(iterations) != 1:
        raise ValueError(f"{path}: expected exactly one Iteration/query")
    def number(node, field, cast=int):
        value = node.findtext(field)
        try:
            result = cast(value)
            if not math.isfinite(result):
                raise ValueError()
            return result
        except (TypeError, ValueError):
            raise ValueError(f"{path}: missing or invalid {field}: {value!r}") from None

    qlen_text = root.findtext("BlastOutput_query-len")
    if not qlen_text:
        raise ValueError(f"{path}: missing BlastOutput_query-len")
    qlen = number(root, "BlastOutput_query-len")
    if qlen <= 0:
        raise ValueError(f"{path}: BlastOutput_query-len must be positive")
    if number(iterations[0], "Iteration_query-len") != qlen:
        raise ValueError(f"{path}: Iteration_query-len differs from BlastOutput_query-len")
    if iterations[0].find("Iteration_hits") is None:
        raise ValueError(f"{path}: missing Iteration_hits")
    rec = {
        "stem": path.stem,
        "program": root.findtext("BlastOutput_program") or "",
        "version": root.findtext("BlastOutput_version") or "",
        "db": root.findtext("BlastOutput_db") or "",
        "qlen": qlen,
        "query_def": (root.findtext("BlastOutput_query-def") or "").strip(),
        "expect": root.findtext("BlastOutput_param/Parameters/Parameters_expect") or "",
        "hits": [],
    }
    used_ids = set()
    for hit in iterations[0].findall("Iteration_hits/Hit"):
        hid = hit.findtext("Hit_id") or ""
        gi = ""
        acc = hit.findtext("Hit_accession") or ""
        m = re.search(r"gi\|(\d+)\|", hid)
        if m:
            gi = m.group(1)
        m2 = re.search(r"\|([A-Z]{1,3}_?[0-9]+\.[0-9]+)\|?$", hid)
        if m2:
            acc = m2.group(1)
        elif "." not in acc:
            m3 = re.search(r"(?:ref|gb|emb|dbj)\|([^|]+)\|", hid)
            if m3:
                acc = m3.group(1)
        hlen = number(hit, "Hit_len")
        if hlen <= 0:
            raise ValueError(f"{path}: Hit_len must be positive")
        anchor = re.sub(r"[^A-Za-z0-9_.-]", "_", gi or acc) or "hit"
        original_anchor = anchor
        suffix = 2
        while anchor in used_ids:
            anchor = f"{original_anchor}_{suffix}"
            suffix += 1
        used_ids.add(anchor)
        hsps = []
        for hsp in hit.findall("Hit_hsps/Hsp"):
            hsps.append(
                {
                    "bits": number(hsp, "Hsp_bit-score", float),
                    "score": number(hsp, "Hsp_score", float),
                    "evalue": number(hsp, "Hsp_evalue", float),
                    "qfrom": number(hsp, "Hsp_query-from", int),
                    "qto": number(hsp, "Hsp_query-to", int),
                    "hfrom": number(hsp, "Hsp_hit-from", int),
                    "hto": number(hsp, "Hsp_hit-to", int),
                    "ident": number(hsp, "Hsp_identity", int),
                    "alen": number(hsp, "Hsp_align-len", int),
                    "gaps": number(hsp, "Hsp_gaps", int),

                    "qseq": hsp.findtext("Hsp_qseq") or "",
                    "mid": hsp.findtext("Hsp_midline") or "",
                    "hseq": hsp.findtext("Hsp_hseq") or "",
                }
            )
        if not hsps:
            raise ValueError(f"{path}: hit {hid or acc} has no HSP")
        for h in hsps:
            for field, limit in (("qfrom", qlen), ("qto", qlen), ("hfrom", hlen), ("hto", hlen)):
                if not 1 <= h[field] <= limit:
                    raise ValueError(f"{path}: hit {hid}: {field} out of range 1..{limit}")
            if h["alen"] <= 0 or any(len(h[k]) != h["alen"] for k in ("qseq", "hseq", "mid")):
                raise ValueError(f"{path}: hit {hid}: Hsp_align-len/qseq/hseq/midline length mismatch")
            for seq, start, end in (("qseq", "qfrom", "qto"), ("hseq", "hfrom", "hto")):
                if len(h[seq].replace("-", "")) != abs(h[end] - h[start]) + 1:
                    raise ValueError(f"{path}: hit {hid}: {seq} coordinate span mismatch")
            if not 0 <= h["ident"] <= h["alen"] or not 0 <= h["gaps"] <= h["alen"] or h["evalue"] < 0:
                raise ValueError(f"{path}: hit {hid}: invalid Hsp_identity/Hsp_gaps/Hsp_evalue")
            h["strand"] = ("Plus" if h["qto"] >= h["qfrom"] else "Minus") + "/" + ("Plus" if h["hto"] >= h["hfrom"] else "Minus")
        rec["hits"].append(
            {
                "gi": anchor,
                "acc": acc,
                "def": hit.findtext("Hit_def") or "",
                "len": hlen,
                "hsps": hsps,
                "best": max(hsps, key=lambda x: x["bits"]),
                "total": sum(x["bits"] for x in hsps),
            }
        )
    return rec


def score_color(bits: float) -> str:
    if bits >= 200:
        return "#ff0000"
    if bits >= 80:
        return "#cc00cc"
    if bits >= 50:
        return "#00cc00"
    if bits >= 40:
        return "#0000ff"
    return "#000000"


def scale_ticks(qlen: int) -> list[int]:
    if qlen <= 1:
        return [1]
    ticks = [1]
    for i in range(1, 5):
        ticks.append(max(1, int(round(qlen * i / 5))))
    ticks.append(qlen)
    out: list[int] = []
    for t in ticks:
        if t not in out:
            out.append(t)
    return out


def fmt_e(v: float) -> str:
    if v == 0:
        return "0.0"
    if v >= 0.001:
        return f"{v:.3g}"
    return f"{v:.2e}".replace("e-0", "e-").replace("e+0", "e+")


def fmt_ident(hsp: dict) -> str:
    if not hsp["alen"]:
        return ""
    return f"{100.0 * hsp['ident'] / hsp['alen']:.2f}%"


def fmt_cover(hsps: list[dict], qlen: int) -> str:
    intervals = sorted((min(h["qfrom"], h["qto"]), max(h["qfrom"], h["qto"])) for h in hsps)
    covered, last = 0, 0
    for start, end in intervals:
        covered += max(0, end - max(start, last + 1) + 1)
        last = max(last, end)
    return f"{100.0 * covered / qlen:.0f}%"


def aln_pre(hsp: dict) -> str:
    q, m, s = hsp["qseq"], hsp["mid"], hsp["hseq"]
    qpos, hpos = hsp["qfrom"], hsp["hfrom"]
    qdir = 1 if hsp["qto"] >= hsp["qfrom"] else -1
    hdir = 1 if hsp["strand"].endswith("Plus") else -1
    chunks = []
    for i in range(0, max(len(q), 1), 60):
        qq, mm, ss = q[i : i + 60], m[i : i + 60], s[i : i + 60]
        q_end = qpos + (len(qq.replace("-", "")) - 1) * qdir
        h_nongap = len(ss.replace("-", ""))
        h_end = hpos + (h_nongap - 1) * hdir
        w = max(len(str(qpos)), len(str(hpos)), len(str(q_end)), len(str(h_end)), 1)
        chunks.append(
            f"Query  {qpos:>{w}}  {qq}  {q_end}\n"
            f"       {' ' * w}  {mm}\n"
            f"Sbjct  {hpos:>{w}}  {ss}  {h_end}"
        )
        qpos = q_end + qdir
        hpos = h_end + hdir
    return "\n\n".join(chunks)


def graphic_svg(rec: dict) -> str:
    qlen = rec["qlen"] or 1
    hits = rec["hits"]
    left = 118
    gw = 500
    query_bar_y = 58
    query_bar_h = 10
    tick_top = query_bar_y - 16
    bar_y0 = 84
    row_h = 16
    width = left + gw + 16
    height = bar_y0 + row_h * max(len(hits), 1) + 8
    ticks = scale_ticks(qlen)
    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" width="{width}">']
    parts.append('<text x="8" y="16" font-size="11" fill="#222">Color key for alignment scores</text>')
    keys = [
        ("#000000", "&lt;40", 8),
        ("#0000ff", "40-50", 92),
        ("#00cc00", "50-80", 184),
        ("#cc00cc", "80-200", 276),
        ("#ff0000", "&gt;=200", 380),
    ]
    for color, lab, x in keys:
        parts.append(f'<rect x="{x}" y="22" width="28" height="8" fill="{color}"/>')
        parts.append(f'<text x="{x + 32}" y="30" font-size="10" fill="#222">{lab}</text>')
    parts.append(
        f'<text x="8" y="{query_bar_y + 9}" font-size="12" fill="#111" font-weight="600">Query</text>'
    )
    parts.append(
        f'<rect x="{left}" y="{query_bar_y}" width="{gw}" height="{query_bar_h}" fill="#000000">'
        f"<title>Query {qlen} bp</title></rect>"
    )
    for t in ticks:
        x = left + (t - 1) / max(qlen - 1, 1) * gw if qlen > 1 else left
        parts.append(
            f'<line x1="{x:.1f}" y1="{tick_top}" x2="{x:.1f}" y2="{query_bar_y}" stroke="#111" stroke-width="1"/>'
        )
        anchor = "start" if t == 1 else ("end" if t == qlen else "middle")
        parts.append(
            f'<text x="{x:.1f}" y="{tick_top - 2}" font-size="10" fill="#111" text-anchor="{anchor}">{t}</text>'
        )
    for i, h in enumerate(hits):
        b = h["best"]
        y = bar_y0 + i * row_h
        q0 = min(b["qfrom"], b["qto"])
        q1 = max(b["qfrom"], b["qto"])
        x = left + (q0 - 1) / qlen * gw
        w = max((q1 - q0 + 1) / qlen * gw, 2)
        color = score_color(b["bits"])
        title = htmlmod.escape(
            f"{h['def']}\nScore {b['bits']:.1f}  E {fmt_e(b['evalue'])}  {h['acc']}"
        )
        acc = htmlmod.escape(h["acc"])
        gi = htmlmod.escape(h["gi"])
        parts.append(
            f'<text x="8" y="{y + 9}" font-size="9" fill="#444" font-family="ui-monospace,Menlo,Consolas,monospace">{acc}</text>'
        )
        parts.append(
            f'<a href="#alnHdr_{gi}"><title>{title}</title>'
            f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="10" fill="{color}"/></a>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def job_title(query_def: str) -> str:
    text = (query_def or "").strip()
    if text in EMPTY_QUERY_DEF:
        return "Nucleotide Sequence"
    return text


def species_dir(stem: str) -> str | None:
    m = re.match(r"^([A-Z]{3}_1)(?:_|$)", stem)
    return m.group(1) if m else None


def page_html(rec: dict, rid: str = "", has_index: bool = False, css_href: str = "viewer.css", nav_href: str = "index.html") -> str:
    hits = rec["hits"]
    stem = rec["stem"]
    desc_rows = []
    for i, h in enumerate(hits, 1):
        b = h["best"]
        desc_rows.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td><a href='#alnHdr_{htmlmod.escape(h['gi'])}'>{htmlmod.escape(h['def'])}</a></td>"
            f"<td>{b['bits']:.1f}</td>"
            f"<td>{h['total']:.1f}</td>"
            f"<td>{fmt_cover(h['hsps'], rec['qlen'])}</td>"
            f"<td>{fmt_e(b['evalue'])}</td>"
            f"<td>{fmt_ident(b)}</td>"
            f"<td>{h['len']}</td>"
            f"<td class='mono'>{htmlmod.escape(h['acc'])}</td>"
            "</tr>"
        )
    aln_blocks = []
    for h in hits:
        parts = []
        for hsp in h["hsps"]:
            ident_s = (
                f"{hsp['ident']}/{hsp['alen']} ({100.0 * hsp['ident'] / hsp['alen']:.0f}%)"
                if hsp["alen"]
                else ""
            )
            gaps_s = (
                f"{hsp['gaps']}/{hsp['alen']} ({100.0 * hsp['gaps'] / hsp['alen']:.0f}%)"
                if hsp["alen"]
                else "0"
            )
            parts.append(
                f"<div>Score = {hsp['bits']:.1f} bits ({hsp['score']:.0f}),  Expect = {fmt_e(hsp['evalue'])}<br>"
                f"Identities = {ident_s}, Gaps = {gaps_s}<br>"
                f"Strand={hsp['strand']}</div>"
                f"<pre>{htmlmod.escape(aln_pre(hsp))}</pre>"
            )
        aln_blocks.append(
            f"<section class='aln' id='alnHdr_{htmlmod.escape(h['gi'])}'>"
            f"<h3>&gt;{htmlmod.escape(h['acc'])} {htmlmod.escape(h['def'])}</h3>"
            f"<div class='meta'>Length={h['len']} <a class='back' href='#desc'>回到 Descriptions</a></div>"
            + "".join(parts)
            + "</section>"
        )
    kind = "扩增子 blastn" if stem.endswith("_amp") else "BLAST"
    if stem.endswith("_F") or stem.endswith("_R"):
        kind = "单引物 blastn-short"
    nav = f'<nav class="top"><a href="{htmlmod.escape(nav_href)}">离线结果目录</a></nav>' if has_index else ""
    empty = '<p>无命中</p>' if not hits else ""
    rid_row = (
        f"<div><dt>RID</dt><dd>{htmlmod.escape(rid)}</dd></div>\n"
        if rid
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{htmlmod.escape(stem)} 离线 BLAST</title>
<link rel="stylesheet" href="{htmlmod.escape(css_href)}">
</head>
<body>
<header>
{nav}
<h1>{htmlmod.escape(stem)}</h1>
<p class="sub">离线结果目录，由 NCBI BLAST XML 生成。携带时请复制整个目录（含 viewer.css）。点色条或 Description 跳到 pairwise。</p>
<dl class="summary">
<div><dt>Job title</dt><dd>{htmlmod.escape(job_title(rec.get("query_def", "")))}</dd></div>
{rid_row}<div><dt>Query Length</dt><dd>{rec['qlen']}</dd></div>
<div><dt>Molecule type</dt><dd>nucleic acid</dd></div>
<div><dt>Database Name</dt><dd>{htmlmod.escape(rec['db'])}</dd></div>
<div><dt>Program</dt><dd>{htmlmod.escape(rec['version'])}</dd></div>
<div><dt>Expect</dt><dd>{htmlmod.escape(rec['expect'])}</dd></div>
<div><dt>Hits</dt><dd>{len(hits)}</dd></div>
<div><dt>类型</dt><dd>{htmlmod.escape(kind)}</dd></div>
</dl>
</header>
<main>
<h2>Graphic Summary</h2>
<p class="hint">Mouse over to see the title, click to show alignments。图示最佳 HSP；详细比对列出全部 HSP。</p>
{empty}
<div class="graph">
{graphic_svg(rec)}
</div>
<h2 id="desc">Descriptions</h2>
<table class="desc">
<thead><tr><th>#</th><th>Description</th><th>Max Score</th><th>Total Score</th><th>Query Cover</th><th>E value</th><th>Per. Ident</th><th>Acc. Len</th><th>Accession</th></tr></thead>
<tbody>
{''.join(desc_rows)}
</tbody>
</table>
<h2>Alignments</h2>
{''.join(aln_blocks)}
</main>
</body>
</html>
"""


def rel_html(stem: str) -> str:
    folder = species_dir(stem)
    return f"{folder}/{stem}.html" if folder else f"{stem}.html"


def index_html(stems: list[str]) -> str:
    rows = "".join(
        f'<tr><td class="mono"><a href="{htmlmod.escape(quote(rel_html(s)))}">{htmlmod.escape(s)}</a></td></tr>'
        for s in stems
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>离线 BLAST</title>
<link rel="stylesheet" href="viewer.css">
</head>
<body>
<header>
<h1>离线 BLAST</h1>
<p class="sub">{len(stems)} 份离线结果页，由 XML 生成。携带时请复制整个目录（含 viewer.css）。</p>
</header>
<main>
<table class="desc">
<thead><tr><th>文件</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</main>
</body>
</html>
"""


def collect_xml(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        if item.is_dir():
            files.extend(sorted(item.glob("*.xml")))
        elif item.is_file():
            files.append(item)
        else:
            raise FileNotFoundError(item)
    if not files:
        raise FileNotFoundError("no XML files")
    return files


def render(xml_paths: list[Path], out_dir: Path, rids: dict[str, str] | None = None) -> tuple[list[Path], list[str]]:
    out_dir = out_dir.resolve()
    destinations = [out_dir / rel_html(p.stem) for p in xml_paths]
    if len(set(destinations)) != len(destinations) or any(p.name == "index.html" for p in destinations):
        raise ValueError("duplicate/reserved output filename")
    sources = {p.resolve() for p in xml_paths} | {CSS_SRC.resolve()}
    for dest in destinations + [out_dir / "viewer.css", out_dir / "index.html"]:
        resolved = dest.resolve()
        if any(part in resolved.parts for part in ("1.原始资料", "3.记录", "blastn-target")):
            raise ValueError(f"protected output path: {dest}")
        if resolved in sources or dest.is_symlink():
            raise ValueError(f"output conflicts with source/symlink: {dest}")
        if dest.exists() and dest.suffix == ".html":
            content = dest.read_text("utf-8")
            if '离线 BLAST' not in content or '<base' in content.lower() or 'blast.ncbi.nlm.nih.gov' in content:
                raise ValueError(f"refusing to overwrite non-viewer HTML: {dest}")
    records, failures = [], []
    for path in xml_paths:
        try:
            records.append(parse_xml(path))
        except (ValueError, ET.ParseError, OSError) as exc:
            failures.append(f"{path}: {exc}")
    if not records:
        return [], failures
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CSS_SRC, out_dir / "viewer.css")
    written = []
    rids = rids or {}
    for rec in records:
        dest = out_dir / rel_html(rec["stem"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        nested = dest.parent != out_dir
        dest.write_text(
            page_html(
                rec,
                rids.get(rec["stem"], ""),
                len(records) > 1,
                "../viewer.css" if nested else "viewer.css",
                "../index.html" if nested else "index.html",
            ),
            encoding="utf-8",
        )
        written.append(dest)
    if len(written) > 1 or (out_dir / "index.html").exists():
        (out_dir / "index.html").write_text(index_html([p.stem for p in written]), encoding="utf-8")
    return written, failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Render BLAST XML to offline HTML")
    parser.add_argument("xml", nargs="+", type=Path)
    parser.add_argument("-o", "--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        paths = collect_xml(args.xml)
        written, failures = render(paths, args.out)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"wrote {len(written)} html under {args.out}; failed {len(failures)}")
    for path in written:
        print(f"OK {path}")
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
