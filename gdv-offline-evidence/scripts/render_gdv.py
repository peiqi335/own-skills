#!/usr/bin/env python3
"""Compose an archived NCBI SVG with source-backed context; never fetch live tracks."""
import argparse
import copy
import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
ROLES = {'refseq', 'ensembl', 'rna_coverage', 'rna_spanning', 'rna_features', 'variants'}
ROLE_PRIORITY = {
    'refseq': 1,
    'ensembl': 2,
    'rna_coverage': 3,
    'rna_spanning': 4,
    'rna_features': 5,
    'variants': 6,
}
PROTECTED = {'1.原始资料', '3.记录', '.git'}
BANNED_NOTE = re.compile(r'酶促阻断|湿实验|特异性高|特异性良好|阳性确证')
BANNED_UNAVAILABLE = re.compile(r'未收录密集公共变异数据')
EXON_LABEL = re.compile(r'ex(\d+)', re.I)
MIN_SEGMENT_PX = 8
CLUSTER_GAP = 400


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_url(url):
    u = urlparse(url)
    require(u.scheme == 'https' and u.hostname == 'www.ncbi.nlm.nih.gov', '需要 NCBI HTTPS GDV 链接')
    q = parse_qs(u.query)
    def one(k):
        require(k in q and len(q[k]) == 1, f'链接缺少或重复参数 {k}')
        return q[k][0]
    assembly, accession = one('id'), one('chr')
    require(re.fullmatch(r'GC[AF]_\d+\.\d+', assembly), 'id 应为带版本组装号')
    start, end = int(one('from')), int(one('to'))
    require(1 <= start <= end, '窗口必须为正整数 1-based 闭区间')
    markers = []
    for item in one('mk').split(','):
        m = re.fullmatch(r'(\d+)[-:](\d+)\|([^|]+)\|([0-9a-fA-F]{6})(?:!)?', item)
        require(m is not None, '标记需显式起止坐标、名称和六位颜色；复杂转义需人工规范化')
        a, b, label, color = m.groups()
        a, b = int(a), int(b)
        require(start <= a <= b <= end, f'标记 {label} 超出窗口或反向端点未规范化')
        markers.append({'start': a, 'end': b, 'label': label, 'display': label, 'color': '#' + color})
    require(len(markers) <= 20, '超过 20 个标记，应按基因座拆分')
    return assembly, accession, start, end, markers


def numbers(text):
    return [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', text or '')]


def content_bottom(root, vb):
    bottom = 0.0
    full_h, full_w = vb[3], vb[2]
    for node in root.iter():
        tag = node.tag.split('}')[-1]
        if tag == 'rect':
            w = float(node.get('width') or 0)
            h = float(node.get('height') or 0)
            y = float(node.get('y') or 0)
            if w >= full_w * 0.95 and h >= full_h * 0.45:
                continue
            bottom = max(bottom, y + h)
        elif tag == 'line':
            y1 = float(node.get('y1') or 0)
            y2 = float(node.get('y2') or 0)
            if abs(y2 - y1) >= full_h * 0.45:
                continue
            bottom = max(bottom, y1, y2)
        elif tag == 'text':
            bottom = max(bottom, float(node.get('y') or 0))
        elif tag == 'path':
            ys = numbers(node.get('d'))[1::2]
            if ys:
                bottom = max(bottom, max(ys))
    return bottom


def crop_empty_canvas(root, vb):
    bottom = content_bottom(root, vb)
    new_h = min(vb[3], max(math.ceil(bottom + 8), 120))
    if new_h < vb[3] - 1:
        root.set('viewBox', f'{vb[0]:g} {vb[1]:g} {vb[2]:g} {new_h}')
        height = root.get('height', '')
        if height.endswith('px'):
            root.set('height', f'{new_h}px')
        elif height:
            root.set('height', str(new_h))
        return [vb[0], vb[1], vb[2], float(new_h)]
    return vb


def cluster_markers(markers):
    ordered = sorted(markers, key=lambda m: (m['start'], m['end']))
    groups, current = [], [ordered[0]]
    for item in ordered[1:]:
        if item['start'] - current[-1]['end'] > CLUSTER_GAP:
            groups.append(current)
            current = [item]
        else:
            current.append(item)
    groups.append(current)
    return groups


def collect_accessions(node, found):
    if isinstance(node, dict):
        acc = node.get('acc')
        if isinstance(acc, str):
            found.add(acc)
        for value in node.values():
            collect_accessions(value, found)
    elif isinstance(node, list):
        for value in node:
            collect_accessions(value, found)


def check_assembly_info(spec, assembly, accession, spec_path, meta_hit):
    relative = spec.get('assembly_info')
    if not relative:
        return
    require(isinstance(relative, str) and relative.strip(), 'assembly_info 必须是相对路径字符串')
    path = (spec_path.parent / relative).resolve()
    require(path.is_file(), f'assembly_info 不存在：{relative}')
    data = read_json(path)
    assemblies = data.get('assemblies') or []
    require(len(assemblies) == 1, 'assembly_info 应含恰好一个 assemblies 条目')
    record = assemblies[0]
    require(record.get('acc') == assembly, f'URL id {assembly} 与 assembly_info {record.get("acc")} 不一致')
    found = set()
    collect_accessions(record, found)
    if accession in found:
        return
    title = meta_hit.get('title') or ''
    require(spec['assembly_name'] and spec['assembly_name'] in title,
            f'{accession} 不在组装 {assembly} 的序列清单中，且 ESummary 标题不含 {spec["assembly_name"]}')


def exon_claim(text):
    hit = EXON_LABEL.search(text or '')
    return int(hit.group(1)) if hit else None


def check_product_report(spec, spec_path, exons):
    relative = spec.get('product_report')
    if not relative:
        return
    require(exons is not None, '填写 product_report 时必须同时填写 exons')
    require(isinstance(relative, str) and relative.strip(), 'product_report 必须是相对路径字符串')
    path = (spec_path.parent / relative).resolve()
    require(path.is_file(), f'product_report 不存在：{relative}')
    data = read_json(path)
    blob = json.dumps(data, ensure_ascii=False)
    require(exons['transcript'] in blob, f'product_report 未含转录本 {exons["transcript"]}')


def safe_svg(path):
    raw = Path(path).read_bytes()
    # NCBI exports declare the standard SVG DTD. Remove that declaration locally;
    # never resolve remote DTDs or arbitrary entities.
    raw = raw.replace(b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">', b'')
    require(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'SVG 含不支持的外部声明')
    root = ET.fromstring(raw)
    require(root.tag == f'{{{NS}}}svg', '不是标准 SVG：可能下载了 HTML 错误页')
    # The official font import is optional presentation, not genomic evidence.
    # Keep the raw archive intact, but make the composed copy truly offline.
    font_import = '@import url("https://www.ncbi.nlm.nih.gov/projects/sviewer/css/svg_fonts.css");'
    for node in root.iter():
        if node.tag == f'{{{NS}}}style' and node.text:
            node.text = node.text.replace(font_import, '')
    for node in root.iter():
        tag = node.tag.split('}')[-1]
        require(tag not in {'script', 'foreignObject', 'image'}, '不能将脚本、外部 HTML 或栅格图片作为矢量轨道')
        for k, v in node.attrib.items():
            require(not k.lower().startswith('on'), 'SVG 含事件处理器')
            if k.split('}')[-1] == 'href':
                require(v.startswith('#'), 'SVG 含非本地资源引用')
        content = ' '.join(node.attrib.values()) + ' ' + (node.text or '')
        require('@import' not in content.lower(), 'SVG 含外部样式导入')
        for ref in re.findall(r'url\((.*?)\)', content, flags=re.I):
            require(ref.strip(' \"\'').startswith('#'), 'SVG 含外部 CSS资源')
    return root


def check_track_order(root, tracks):
    loaded_roles = []
    for t in tracks:
        if t.get('status') == 'loaded':
            role = t.get('role')
            title = t.get('title')
            if role in ROLE_PRIORITY and title:
                matching_ys = []
                for n in root.iter():
                    if n.tag == f'{{{NS}}}text' and title in ''.join(n.itertext()):
                        matching_ys.append(float(n.get('y') or 0))
                if matching_ys:
                    loaded_roles.append((min(matching_ys), role, title))
    loaded_roles.sort(key=lambda x: x[0])
    for i in range(len(loaded_roles) - 1):
        r1, r2 = loaded_roles[i][1], loaded_roles[i + 1][1]
        p1, p2 = ROLE_PRIORITY[r1], ROLE_PRIORITY[r2]
        require(p1 <= p2,
                f'官方 SVG 轨道顺序倒挂：{r1} (y={loaded_roles[i][0]:.1f}) 位于 {r2} (y={loaded_roles[i+1][0]:.1f}) 之上；必须符合 RefSeq -> Ensembl -> RNA-seq -> Variants 规范')


def load_spec(spec_path):
    spec_path = Path(spec_path).resolve()
    s = read_json(spec_path)
    for k in ['locus_id', 'organism', 'display_name', 'assembly_name', 'source_url', 'chromosome',
              'sequence_role', 'retrieved_date', 'official_svg', 'chromosome_metadata', 'coordinate_note']:
        require(isinstance(s.get(k), str) and s[k].strip(), f'缺少字符串字段 {k}')
    require(re.fullmatch(r'[A-Za-z0-9_-]+', s['locus_id']), 'locus_id 只允许字母、数字、_、-')
    datetime.date.fromisoformat(s['retrieved_date'])
    require(s['sequence_role'] in {'chromosome', 'scaffold'}, 'sequence_role 应为 chromosome 或 scaffold')
    s['_assembly'], s['_accession'], s['_start'], s['_end'], s['_markers'] = parse_url(s['source_url'])
    apply_marker_display(s)
    for key in ['official_svg', 'chromosome_metadata']:
        s['_' + key] = (spec_path.parent / s[key]).resolve()
        require(s['_' + key].is_file(), f'来源文件不存在：{s[key]}')
    meta = read_json(s['_chromosome_metadata'])
    hits = [v for v in meta.get('result', {}).values() if isinstance(v, dict)
            and v.get('accessionversion') == s['_accession']]
    require(len(hits) == 1, 'ESummary 没有唯一匹配的带版本序列号')
    check_assembly_info(s, s['_assembly'], s['_accession'], spec_path, hits[0])
    length = hits[0].get('slen')
    require(type(length) is int and length >= s['_end'], '元数据序列长度缺失或窗口越界')
    s['_length'] = length
    root = safe_svg(s['_official_svg'])
    texts = [''.join(n.itertext()) for n in root.iter() if n.tag == f'{{{NS}}}text']
    require(any(s['_accession'] in t for t in texts), 'SVG 内未找到匹配的序列号；请含标题重新导出')
    tracks = s.get('tracks', [])
    require(len(tracks) == 6 and {t.get('role') for t in tracks} == ROLES, '需记录六种轨道类别各一次')
    for t in tracks:
        require(t.get('status') in {'loaded', 'available_empty', 'unavailable'}, '轨道尚未检查，不可当作完成')
        evidence = t.get('evidence', '').strip()
        require(evidence, f'{t["role"]} 缺少核验依据或不可用原因')
        if t['status'] == 'unavailable':
            require(not BANNED_UNAVAILABLE.search(evidence),
                    f'{t["role"]} 不可用声明过于笼统；需写明查过的目录或配置面板')
        if t['status'] == 'loaded':
            require(t.get('title') and any(t['title'] in x for x in texts), f'{t["role"]} 未出现在官方 SVG 文字中')
        if t['status'] == 'available_empty':
            require(t.get('title', '').strip(), f'{t["role"]} 空窗口仍需记录官方轨道标题')
    check_track_order(root, tracks)
    for m in s['_markers']:
        require(m['label'] in texts, f'官方 SVG 中缺少标记 {m["label"]}')
    title = s.get('export_title_to_remove')
    if title:
        require(texts.count(title) == 1 and title.startswith(s['_accession'] + ':'), '待替换官方标题不精确或非唯一')
    vb = [float(v) for v in root.get('viewBox', '').split()]
    require(len(vb) == 4 and vb[0:2] == [0, 0] and all(math.isfinite(v) for v in vb)
            and vb[2] > 0 and vb[3] > 0, 'SVG viewBox 无效')
    s['_viewbox'] = crop_empty_canvas(root, vb)
    notes = s.get('notes', [])
    require(isinstance(notes, list) and all(isinstance(v, str) for v in notes), 'notes 应为字符串数组')
    for note in notes:
        require(not BANNED_NOTE.search(note), 'notes 不得写入湿实验机制、阳性确证或无 GDV 证据的特异性结论')
    s['_exons'] = load_exons(s, texts)
    if any(exon_claim(m['label']) is not None or exon_claim(m.get('display')) is not None for m in s['_markers']):
        require(s['_exons'] is not None, 'mk 或显示名含 exN 时必须填写 exons，且 N 等于该 XM_/NM_ 的 order')
    if s['_exons']:
        for m in s['_markers']:
            shown = exon_claim(m.get('display'))
            if shown is None:
                continue
            hits = [e for e in s['_exons']['intervals'] if e['start'] <= m['start'] and m['end'] <= e['end']]
            require(len(hits) == 1 and shown == hits[0]['order'],
                    f'显示名 {m.get("display")} 的外显子号须等于落入外显子 {hits[0]["order"]}')
    check_product_report(s, spec_path, s['_exons'])
    return s, root


def load_exons(s, texts):
    data = s.get('exons')
    if data is None:
        return None
    require(isinstance(data, dict), 'exons 应为对象')
    for key in ['transcript', 'gene', 'strand', 'source']:
        require(isinstance(data.get(key), str) and data[key].strip(), f'exons 缺少字符串字段 {key}')
    require(re.fullmatch(r'(?:XM|NM)_\d+\.\d+', data['transcript']), 'exons.transcript 应为带版本 XM_/NM_')
    require(data['strand'] in {'+', '-'}, 'exons.strand 应为 + 或 -')
    require(any(data['transcript'] in t for t in texts), '官方 SVG 中缺少该 RefSeq 转录本')
    intervals = data.get('intervals')
    require(isinstance(intervals, list) and intervals, 'exons.intervals 不能为空')
    seen = set()
    cleaned = []
    for item in intervals:
        require(isinstance(item, dict), '外显子区间必须为对象')
        order, start, end = item.get('order'), item.get('start'), item.get('end')
        require(type(order) is int and order > 0 and order not in seen, '外显子 order 须为正整数且不重复')
        require(type(start) is int and type(end) is int and 1 <= start <= end <= s['_length'],
                f'外显子 {order} 坐标越界或反向')
        seen.add(order)
        cleaned.append({'order': order, 'start': start, 'end': end})
    for m in s['_markers']:
        hits = [e for e in cleaned if e['start'] <= m['start'] and m['end'] <= e['end']]
        require(len(hits) == 1, f'标记 {m["label"]} 必须完整落在恰好一个所列外显子内')
        claimed = exon_claim(m['label'])
        if claimed is not None:
            require(claimed == hits[0]['order'],
                    f'标记 {m["label"]} 的外显子号须等于落入外显子 {hits[0]["order"]}，不能按窗口内其他模型另编号')
    return {'transcript': data['transcript'], 'gene': data['gene'], 'strand': data['strand'],
            'source': data['source'], 'intervals': cleaned}


def draw_axis(elem_fns, x0, baseline, w, lo, hi, items, ident_prefix, shared_row=None, min_w=0):
    text, rect, line, width = elem_fns
    def X(n): return x0 + (n - lo) / (hi - lo + 1) * w
    line(x0, baseline, x0 + w, baseline, '#64748b', 2)
    for i in range(5):
        n = round(lo + (hi - lo) * i / 4)
        line(X(n), baseline - 5, X(n), baseline + 6, '#64748b')
        text(X(n) - 48, baseline + 31, f'{n:,}', 13)
    for i, m in enumerate(items):
        row = baseline - 20 if shared_row else baseline + 74
        a, b = X(m['start']), X(m['end'] + 1)
        rect(a, row, max(min_w, b - a), 15, m['color'], 2, f'{ident_prefix}-{m.get("_i", i)}')
        shown = m.get('display') or m['label']
        label = f'{shown}  {m["start"]:,}–{m["end"]:,}  ({m["end"]-m["start"]+1} bp)'
        text(max(60, min(a - 25, width - 650)), row - 11, label, 15, m['color'])


def marker_shown(m):
    return m.get('display') or m['label']


def apply_marker_display(s):
    data = s.get('marker_display')
    if data is None:
        return
    require(isinstance(data, dict) and data, 'marker_display 应为非空对象')
    labels = {m['label'] for m in s['_markers']}
    for key, value in data.items():
        require(isinstance(key, str) and key in labels, f'marker_display 未知标记 {key}')
        require(isinstance(value, str) and value.strip(), f'marker_display[{key}] 须为非空字符串')
        claimed, shown = exon_claim(key), exon_claim(value)
        require(claimed is None or shown is None or claimed == shown,
                f'marker_display 不得把 {key} 改写成不同外显子号 {value}')
    for marker in s['_markers']:
        marker['display'] = data.get(marker['label'], marker['label'])


def draw_exons(elem_fns, x0, y, w, lo, hi, exons, ident_prefix):
    text, rect, line, width = elem_fns
    def X(n): return x0 + (n - lo) / (hi - lo + 1) * w
    visible = []
    for e in sorted(exons, key=lambda item: item['start']):
        a, b = max(lo, e['start']), min(hi, e['end'])
        if a <= b:
            visible.append({**e, 'draw_start': a, 'draw_end': b})
    for i, e in enumerate(visible):
        xa, xb = X(e['draw_start']), X(e['draw_end'] + 1)
        rect(xa, y, max(2, xb - xa), 14, '#86efac', 2, f'{ident_prefix}-{e["order"]}')
        text(max(x0, min(xa, x0 + w - 90)), y - 12, f'exon {e["order"]}', 13, '#166534')
        if i:
            prev = visible[i - 1]
            line(X(prev['draw_end'] + 1), y + 7, xa, y + 7, '#4ade80', 2)


def compose(s, original):
    width = max(1700, math.ceil(s['_viewbox'][2]) + 126)
    left, right = 60, width - 60
    track_y = 285
    scale = (width - 126) / s['_viewbox'][2]
    track_end = track_y + s['_viewbox'][3] * scale
    markers = s['_markers']
    compact = (len(markers) == 2 and markers[0]['end'] < markers[1]['start']
               and (markers[1]['start'] - markers[0]['start']) /
               (markers[1]['end'] - markers[0]['start'] + 1) > 0.4)
    start = min(m['start'] for m in markers)
    end = max(m['end'] for m in markers)
    overview_w = width - 480
    overview_tiny = any((m['end'] - m['start'] + 1) / (end - start + 1) * overview_w < MIN_SEGMENT_PX for m in markers)
    clusters = cluster_markers(markers) if overview_tiny else []
    exon_row = 46 if s.get('_exons') else 0
    overview_h = (145 if compact else 129 + 54 * len(markers)) + exon_row
    cluster_h = 0 if not clusters else 36 + (168 if s.get('_exons') else 118) * len(clusters)
    focus_y = track_end + 90
    focus_h = overview_h + cluster_h
    footer_y = focus_y + focus_h + 22
    missing = [f'{t["role"]}：{t["status"]}；{t["evidence"]}' for t in s['tracks'] if t['status'] != 'loaded']
    extra = 28 if s.get('_exons') else 0
    height = math.ceil(footer_y + 140 + extra + 25 * len(missing))
    root = ET.Element(f'{{{NS}}}svg', {'width': str(width), 'height': str(height), 'viewBox': f'0 0 {width} {height}'})
    def elem(tag, attrs, value=None):
        n = ET.SubElement(root, f'{{{NS}}}{tag}', {k: str(v) for k, v in attrs.items()})
        n.text = value
        return n
    def text(x, y, value, size=18, color='#334155', weight='normal'):
        return elem('text', {'x': x, 'y': y, 'font-family': 'Noto Sans CJK SC, sans-serif',
                            'font-size': size, 'fill': color, 'font-weight': weight}, value)
    def rect(x, y, w, h, color, rx=0, ident=None):
        a = {'x': x, 'y': y, 'width': w, 'height': h, 'fill': color, 'rx': rx}
        if ident: a['id'] = ident
        return elem('rect', a)
    def line(x, y, x2, y2, color='#cbd5e1', weight=1):
        return elem('line', {'x1': x, 'y1': y, 'x2': x2, 'y2': y2, 'stroke': color, 'stroke-width': weight})
    helpers = (text, rect, line, width)
    rect(0, 0, width, height, 'white')
    rect(0, 0, width, 9, '#0f766e')
    seq_label = ('染色体' if s['sequence_role'] == 'chromosome' else 'scaffold')
    text(60, 63, f'{s["locus_id"]}  |  {s["display_name"]} {s["chromosome"]} {seq_label} · 多轨道离线示例', 32, '#0f172a', 'bold')
    text(60, 99, f'{s["organism"]}  ·  {s["assembly_name"]}  ·  {s["_assembly"]}  ·  {s["_accession"]}', 19)
    text(60, 130, f'窗口 {s["_start"]:,}–{s["_end"]:,} bp（{s["_end"]-s["_start"]+1:,} bp）；新增坐标说明采用 1-based 闭区间。')
    text(60, 175, f'01  全{seq_label}定位', 20, '#0f766e', 'bold')
    bx, bw = 300, width - 500
    mark = bx + bw * (((s['_start'] + s['_end']) / 2 - 1) / max(1, s['_length'] - 1))
    chrom_label = ('Chr ' if s['sequence_role'] == 'chromosome' else '') + s['chromosome']
    text(60, 212, chrom_label, 16 if len(chrom_label) > 12 else 24, '#0f172a', 'bold')
    rect(bx, 195, bw, 17, '#e2e8f0', 8)
    line(mark, 182, mark, 218, '#dc2626', 4)
    text(bx, 241, '1 bp', 15); text(bx + bw - 165, 241, f'{s["_length"]:,} bp', 15)
    text(max(bx, min(mark - 145, bx + bw - 340)), 173,
         f'当前窗口 ≈ {(s["_start"]+s["_end"])/2/1e6:.3f} Mb', 17, '#b91c1c')
    text(60, 274, '02  NCBI 官方轨道快照', 20, '#0f766e', 'bold')
    track = copy.deepcopy(original)
    removed = s.get('export_title_to_remove')
    if removed:
        for parent in track.iter():
            for child in list(parent):
                if child.tag == f'{{{NS}}}text' and ''.join(child.itertext()) == removed:
                    parent.remove(child)
    track.set('x', '63'); track.set('y', str(track_y))
    track.set('width', str(width - 126)); track.set('height', str(s['_viewbox'][3] * scale))
    root.append(track)
    text(63, track_end + 26, '轨道保持官方显示；来源版本、折叠状态及数据可用性见 source_notes.md。', 16)
    line(left, track_end + 48, right, track_end + 48)
    text(60, focus_y, '03  引物结合区放大示意', 20, '#0f766e', 'bold')
    text(width - 650, focus_y, '按链接标记绘制；分段保留，不补全引物。', 16)
    margin = max(10, math.ceil((end - start + 1) * 0.1))
    lo, hi = max(1, start - margin), min(s['_length'], end + margin)
    x0, w = 230, overview_w
    indexed = [{**m, '_i': i} for i, m in enumerate(markers)]
    axis_y = focus_y + 60 + exon_row
    if s.get('_exons'):
        draw_exons(helpers, x0, focus_y + 42, w, lo, hi, s['_exons']['intervals'], 'exon-overview')
    if compact:
        draw_axis(helpers, x0, axis_y, w, lo, hi, indexed, 'primer-segment', shared_row=True)
    else:
        draw_axis(helpers, x0, axis_y, w, lo, hi, [], 'primer-segment')
        def X(n): return x0 + (n - lo) / (hi - lo + 1) * w
        for i, m in enumerate(indexed):
            row = axis_y + 74 + i * 54
            a, b = X(m['start']), X(m['end'] + 1)
            rect(a, row, b - a, 15, m['color'], 2, f'primer-segment-{i}')
            shown = marker_shown(m)
            label = f'{shown}  {m["start"]:,}–{m["end"]:,}  ({m["end"]-m["start"]+1} bp)'
            text(max(60, min(a - 25, width - 650)), row - 11, label, 15, m['color'])
    if clusters:
        cluster_y = focus_y + overview_h
        text(60, cluster_y, '分段局部窗：各簇独立标尺；矩形按该窗比例，不按全跨度放宽。', 16, '#0f766e')
        step = 168 if s.get('_exons') else 118
        for g_i, group in enumerate(clusters):
            g_start = min(m['start'] for m in group)
            g_end = max(m['end'] for m in group)
            g_margin = max(20, math.ceil((g_end - g_start + 1) * 0.8))
            glo, ghi = max(1, g_start - g_margin), min(s['_length'], g_end + g_margin)
            gy = cluster_y + 28 + g_i * step
            text(60, gy, f'局部 {g_i + 1}：{glo:,}–{ghi:,} bp', 15, '#334155')
            if s.get('_exons'):
                draw_exons(helpers, x0, gy + 38, w, glo, ghi, s['_exons']['intervals'], f'exon-cluster-{g_i}')
                axis_cluster = gy + 98
            else:
                axis_cluster = gy + 48
            items = [{**m, '_i': markers.index(m)} for m in group]
            draw_axis(helpers, x0, axis_cluster, w, glo, ghi, items, f'cluster-{g_i}', shared_row=True, min_w=MIN_SEGMENT_PX)
    text(60, footer_y - 15, f'标记最外侧坐标跨度：{end-start+1:,} bp（坐标计算值，不代表实测扩增产物）。', 17)
    line(left, footer_y + 4, right, footer_y + 4)
    text(60, footer_y + 36, '阅读边界：两套注释供并列比较；RNA-seq 为公共证据；数据库变异不代表本次样本基因型。', 17)
    text(60, footer_y + 67, '未自动判定注释一致、引物无变异或实验验证通过。染色体定位线为可见性放宽的中心标记。', 17)
    miss_y = footer_y + 95
    if s.get('_exons'):
        e = s['_exons']
        text(60, footer_y + 98, f'外显子编号来自 {e["transcript"]}（{e["gene"]}，{e["strand"]}），{e["source"]}；仅该转录本。', 17)
        miss_y = footer_y + 126
    for i, message in enumerate(missing):
        text(60, miss_y + i * 25, message[:85] + ('…（完整说明见 source_notes.md）' if len(message) > 85 else ''), 16, '#b45309')
    text(60, height - 18, f'获取日期：{s["retrieved_date"]}  |  官方轨道 + 本地定位排版  |  原始导出及来源说明随附', 15, '#64748b')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def render(spec_path, output):
    s, raw = load_spec(spec_path)
    out = Path(output).absolute()
    require(not out.is_symlink() and not out.exists(), '输出目录已存在；请使用新的版本目录，禁止覆盖')
    require(not any(p.is_symlink() for p in out.parents), '输出祖先含符号链接')
    out = out.resolve()
    require(not (PROTECTED & set(out.parts)), '输出位于受保护目录')
    try:
        import cairosvg
    except ImportError as exc:
        raise ValueError('缺少 CairoSVG；请按 references/execution.md 使用临时虚拟环境') from exc
    svg = compose(s, raw)
    # All rendering occurs before any output is published.
    pdf = cairosvg.svg2pdf(bytestring=svg)
    png = cairosvg.svg2png(bytestring=svg)
    out.mkdir(parents=True, exist_ok=False)
    prefix = s['locus_id']
    (out / f'{prefix}_enhanced.svg').write_bytes(svg)
    (out / f'{prefix}_enhanced.pdf').write_bytes(pdf)
    (out / f'{prefix}_enhanced.png').write_bytes(png)
    shutil.copyfile(s['_official_svg'], out / f'{prefix}_official_tracks.svg')
    shutil.copyfile(s['_chromosome_metadata'], out / 'chromosome_metadata.json')
    if s.get('assembly_info'):
        dest = out / Path(s['assembly_info']).name
        shutil.copyfile((Path(spec_path).resolve().parent / s['assembly_info']).resolve(), dest)
    if s.get('product_report'):
        dest = out / Path(s['product_report']).name
        shutil.copyfile((Path(spec_path).resolve().parent / s['product_report']).resolve(), dest)
    clean = {k: v for k, v in s.items() if not k.startswith('_')}
    clean['official_svg'] = f'{prefix}_official_tracks.svg'
    clean['chromosome_metadata'] = 'chromosome_metadata.json'
    if s.get('assembly_info'):
        clean['assembly_info'] = Path(s['assembly_info']).name
    if s.get('product_report'):
        clean['product_report'] = Path(s['product_report']).name
    (out / 'spec.json').write_text(json.dumps(clean, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    notes = [f'# {prefix} 来源与边界', '', f'来源：{s["source_url"]}', f'数据获取日期：{s["retrieved_date"]}',
             f'序列：{s["_accession"]}；长度：{s["_length"]:,} bp（随附 ESummary）。', '', '## 坐标与排版',
             s['coordinate_note'], '轨道几何未重绘；如指定则仅替换原始导出的标题。原件随附。',
             '增强版移除官方 SVG DTD 声明和已知 NCBI 在线字体导入，采用本地字体；原件未改。',
             '全序列条不表示着丝粒或细胞遗传学带区；红线仅为加宽的窗口中心位置。',
             '引物分段长度来自各段闭区间；最外侧跨度不等于合成引物长度或实测产物。', '', '## 轨道清单']
    notes += [f'- {t["role"]} | {t["status"]} | {t.get("title", "")} | {t["evidence"]}' for t in s['tracks']]
    if s.get('_exons'):
        e = s['_exons']
        notes += ['', '## 外显子示意',
                  f'- 转录本 {e["transcript"]}（{e["gene"]}，{e["strand"]}）；来源：{e["source"]}。',
                  '- 编号仅对该 RefSeq 转录本；Ensembl 不另编一套。引物分段必须完整落在所列外显子内。mk 的 exN 必须等于该 order，02/03 同名。']
        notes += [f'- exon {item["order"]}: {item["start"]:,}–{item["end"]:,}' for item in e['intervals']]
    notes += ['', '## 其他限制'] + ['- ' + n for n in s.get('notes', [])]
    notes += ['', '## 视觉验收', '待执行：实际打开 PDF 渲染及 PNG，对照标准图检查；脚本成功不等于视觉验收通过。']
    (out / 'source_notes.md').write_text('\n'.join(notes) + '\n', encoding='utf-8')
    audit = {'source_svg_sha256': sha(s['_official_svg']), 'source_metadata_sha256': sha(s['_chromosome_metadata']),
             'visual_review': 'pending', 'outputs': {f.name: sha(f) for f in out.iterdir() if f.is_file()}}
    (out / 'checks.json').write_text(json.dumps(audit, indent=2) + '\n', encoding='utf-8')
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path)
    parser.add_argument('-o', '--output', type=Path)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    try:
        if args.validate_only:
            s, _ = load_spec(args.spec)
            print(f'输入通过：{s["locus_id"]}；仍需检查视觉效果及真实坐标对应。')
        else:
            require(args.output is not None, '必须指定新输出目录 -o')
            print(render(args.spec, args.output))
    except (ValueError, KeyError, TypeError, OSError, ET.ParseError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
