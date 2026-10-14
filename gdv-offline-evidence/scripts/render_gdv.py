#!/usr/bin/env python3
"""Compose an archived NCBI SVG with source-backed context; never fetch live tracks."""
import argparse
import base64
import copy
import datetime
import hashlib
import json
import math
import platform
import subprocess
import time
import importlib.metadata
from pathlib import Path
import re
import shutil
import stat
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


def lexical_path(path, root=None, kind=None):
    """Check every lexical component BEFORE normalizing '..' or symlinks."""
    require(isinstance(path, (str, Path)), '路径类型无效')
    path = Path(path).absolute()
    require(not ({'3.记录', '.git'} & set(path.parts)), '禁止读取路径')
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current.parent if part == '..' else current / part
        require(not current.is_symlink(), f'symlink 路径拒绝：{current}')
    if root is not None:
        require(current.is_relative_to(root), f'输入路径逃逸 input-root：{path}')
    if kind == 'file': require(current.is_file() and stat.S_ISREG(current.stat().st_mode), f'来源文件不存在或非普通文件：{current}')
    if kind == 'directory': require(current.is_dir(), f'input-root 不是目录：{current}')
    return current


def evidence_path(s, spec_path, relative):
    require(isinstance(relative, str) and relative.strip(), '证据路径应为非空字符串')
    return lexical_path(Path(spec_path).parent / relative, s.get('_input_root', Path(spec_path).parent), 'file')


def output_path(output, s):
    out = lexical_path(output)
    require(not out.exists(), '输出目录已存在；请使用新的版本目录，禁止覆盖')
    require(not (PROTECTED & set(out.parts)), '输出位于受保护目录')
    for source in s['_input_files']:
        require(not out.is_relative_to(source.parent) and not source.is_relative_to(out), '输出与源目录 alias/嵌套')
    return out


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
    path = evidence_path(spec, spec_path, relative)
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
    if exons is None and not relative:
        return
    require(relative, '填写 exons 必须提供 product_report 路径')
    require(exons is not None, '填写 product_report 时必须同时填写 exons')
    require(isinstance(relative, str) and relative.strip() and not Path(relative).is_absolute(),
            'product_report 必须是相对路径字符串')
    path = evidence_path(spec, spec_path, relative)
    require(path.is_file(), f'product_report 不存在：{relative}')
    data = read_json(path)
    matches = []
    for report in data.get('reports', []):
        for transcript in report.get('product', {}).get('transcripts', []):
            if transcript.get('accession_version') != exons['transcript']:
                continue
            for location in transcript.get('genomic_locations', []):
                if location.get('genomic_accession_version') == spec['_accession']:
                    matches.append(location)
    require(len(matches) == 1, 'product_report 目标 transcript version + genomic accession 必须唯一匹配')
    location = matches[0]
    orientation = {'plus': '+', 'minus': '-'}
    require(orientation.get(location.get('genomic_range', {}).get('orientation')) == exons['strand'],
            'product_report strand 与 exons 不一致')
    intervals = []
    for item in location.get('exons', []):
        require(orientation.get(item.get('orientation')) == exons['strand'], 'product_report exon strand 不一致')
        order = item.get('order')
        require(type(order) is int and order > 0, 'product_report exon order 无效')
        def endpoint(key):
            value = item.get(key)
            require(type(value) is int or (isinstance(value, str) and re.fullmatch(r'[0-9]+', value)),
                    f'product_report exon {key} 无效')
            return int(value)
        intervals.append({'order': order, 'start': endpoint('begin'), 'end': endpoint('end')})
    require(sorted(intervals, key=lambda x: x['order']) == sorted(exons['intervals'], key=lambda x: x['order']),
            'product_report 完整 exon order/start/end 与 exons 不一致')
    spec['_product_report_sha256'] = sha(path)


def check_primer_evidence(s, spec_path):
    """Check provenance structure, not sequence alignment or molecular binding."""
    s['_marker_validation'] = {'status': 'pending', 'reason': '未验证引物序列与基因组结合；mk 仅为来源标记。'}
    evidence = s.get('primer_evidence')
    if evidence is None:
        return
    require(isinstance(evidence, dict), 'primer_evidence 应为对象')
    require(re.fullmatch(r'(?:XM|NM)_\d+\.\d+', evidence.get('transcript', '')), 'primer_evidence transcript 须带版本')
    require(evidence.get('genomic_accession') == s['_accession'], 'primer_evidence genomic accession 不一致')
    if s['_exons']:
        require(evidence['transcript'] == s['_exons']['transcript'], 'primer_evidence transcript 与 exons 不一致')
    primers = evidence.get('primers')
    require(isinstance(primers, dict) and set(primers) == {'F', 'R'}, 'primer_evidence 需完整 F/R')
    bound = []
    for primer in primers.values():
        require(isinstance(primer, dict) and re.fullmatch(r'[ACGT]+', primer.get('sequence', '')),
                'primer_evidence sequence 须为完整大写 ACGT 序列（5′→3′）')
        segments = primer.get('segments')
        require(isinstance(segments, list) and segments, 'primer_evidence segments 不能为空')
        for segment in segments:
            require(isinstance(segment, dict) and type(segment.get('start')) is int and type(segment.get('end')) is int,
                    'primer_evidence segment 需整数端点')
            hit = [m for m in s['_markers'] if all(segment.get(k) == m[k] for k in ('label', 'start', 'end'))]
            require(len(hit) == 1, 'primer_evidence segment 与 mk 不唯一匹配')
            bound.append((segment['label'], segment['start'], segment['end']))
    require(sorted(bound) == sorted((m['label'], m['start'], m['end']) for m in s['_markers']),
            'primer_evidence 必须绑定全部 mk 且不重复')
    source = evidence.get('source')
    require(isinstance(source, dict) and source.get('kind') in {'report', 'alignment'}, 'primer_evidence source.kind 无效')
    relative = source.get('path')
    require(isinstance(relative, str) and relative.strip() and not Path(relative).is_absolute(), 'primer_evidence source.path 须为相对路径')
    path = evidence_path(s, spec_path, relative)
    require(path.is_file(), 'primer_evidence 来源文件缺失')
    require(re.fullmatch(r'[0-9a-f]{64}', source.get('sha256', '')) and sha(path) == source['sha256'],
            'primer_evidence 来源 hash 不一致')
    s['_primer_source'] = path
    s['_marker_validation']['provenance_structure'] = 'matched'
    s['_marker_validation']['source_sha256'] = source['sha256']


def embedded_raster(url):
    require(isinstance(url, str), '资源 URL 类型无效')
    match = re.fullmatch(r'data:image/(png|jpeg);base64,([A-Za-z0-9+/=\s]+)', url)
    require(match is not None, '只允许已知嵌入 PNG/JPEG；拒绝外部或 data SVG 资源')
    try: data = base64.b64decode(match.group(2), validate=True)
    except ValueError as exc: raise ValueError('嵌入 image base64 无效') from exc
    require(data.startswith(b'\x89PNG\r\n\x1a\n') if match.group(1) == 'png' else data.startswith(b'\xff\xd8\xff'), '嵌入 image 类型与内容不符')
    require(not any(marker in data for marker in (b'<svg', b'<?xml', b'<!DOC')), '嵌入栅格含 SVG/XML，拒绝 CairoSVG 的嵌套 SVG 分支')
    from PIL import Image
    import io
    with Image.open(io.BytesIO(data)) as image:
        require(image.format == {'png': 'PNG', 'jpeg': 'JPEG'}[match.group(1)], '嵌入 image 解码类型不符')
        image.verify()
    return data


def offline_fetch(url, resource_type):
    # No delegation to CairoSVG fetch/urlopen: denial occurs before any I/O.
    require(resource_type.startswith('image/'), '离线 fetch 拒绝样式/字体/外部资源')
    return embedded_raster(url)


def check_css(css):
    import tinycss2
    def walk(tokens):
        for token in tokens:
            require(token.type != 'error', 'CSS 解析错误')
            if token.type == 'at-keyword':
                require(token.lower_value not in {'import', 'font-face', 'namespace'}, 'CSS 含 normalized import/font-face/namespace')
            if token.type == 'url': require(token.value.startswith('#'), 'CSS 含外部 URL')
            if token.type == 'function':
                require(token.lower_name not in {'expression', 'image-set', '-webkit-image-set'}, 'CSS 含不支持的 active/resource 函数')
                if token.lower_name == 'url':
                    values = [t for t in token.arguments if t.type not in {'whitespace', 'comment'}]
                    require(len(values) == 1 and values[0].type in {'string', 'url'} and values[0].value.startswith('#'), 'CSS 含外部 URL')
                walk(token.arguments)
            if hasattr(token, 'content'): walk(token.content)
    walk(tinycss2.parse_component_value_list(css))


def safe_svg_bytes(raw):
    require(b'\x00' not in raw, 'SVG 仅支持 UTF-8；拒绝 NUL/UTF-16/UTF-32 输入')
    try:
        raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('SVG 仅支持严格 UTF-8 编码') from exc
    # NCBI exports declare the standard SVG DTD. Remove that declaration locally;
    # never resolve remote DTDs or arbitrary entities.
    raw = raw.replace(b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">', b'')
    require(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'SVG 含不支持的外部声明')
    require(re.search(br'<\?(?!xml(?:\s|\?>))', raw, re.I) is None, 'SVG 含不支持的 processing instruction')
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
        require(tag in {'svg', 'g', 'defs', 'style', 'title', 'desc', 'metadata', 'rect', 'line', 'path', 'text', 'tspan', 'circle', 'ellipse', 'polygon', 'polyline', 'linearGradient', 'radialGradient', 'stop', 'clipPath', 'mask', 'pattern', 'use', 'symbol', 'image'}, 'SVG 含不支持的 active/外部元素')
        for k, v in node.attrib.items():
            require(not k.split('}')[-1].lower().startswith('on'), 'SVG 含事件处理器')
            require(k != '{http://www.w3.org/XML/1998/namespace}base', 'SVG 含 xml:base')
            if k.split('}')[-1] == 'href':
                if tag == 'image': embedded_raster(v)
                else: require(v.startswith('#'), 'SVG 含非本地资源引用')
            # Presentation attributes are CSS too; escaped url functions normalize.
            if k.split('}')[-1] in {'style', 'fill', 'stroke', 'filter', 'clip-path', 'mask', 'cursor', 'font-family', 'marker', 'marker-start', 'marker-mid', 'marker-end', 'color-profile'}: check_css(v)
        if tag == 'style': check_css(node.text or '')
    return root


def safe_svg(path):
    return safe_svg_bytes(lexical_path(path, kind='file').read_bytes())


def convert_svg(svg, format):
    from cairosvg.surface import PDFSurface, PNGSurface
    safe_svg_bytes(svg)  # Also protects generated SVG intended for site inlining.
    return {'pdf': PDFSurface, 'png': PNGSurface}[format].convert(bytestring=svg, url_fetcher=offline_fetch)


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
    warnings = []
    for i in range(len(loaded_roles) - 1):
        r1, r2 = loaded_roles[i][1], loaded_roles[i + 1][1]
        p1, p2 = ROLE_PRIORITY[r1], ROLE_PRIORITY[r2]
        if p1 > p2:
            warnings.append(f'官方 SVG 轨道顺序与推荐顺序不同：{r1} (y={loaded_roles[i][0]:.1f}) 位于 '
                            f'{r2} (y={loaded_roles[i+1][0]:.1f}) 之上；原件保持不变，需目视核对。')
    return warnings


def check_svg_identity(s, texts, spec_path):
    titles = [match for t in texts
              if (match := re.match(r'^([A-Z]{1,4}_\d+\.\d+):(\d+)\.\.(\d+)', t.strip()))]
    if titles:
        require(len(titles) == 1, 'SVG 有多个序列窗口标题，无法确定原件身份')
        accession, start, end = titles[0].groups()
        require(accession == s['_accession'], f'SVG 标题与目标序列 {s["_accession"]} 不符')
        observed, requested = [int(start), int(end)], [s['_start'], s['_end']]
        if observed != requested:
            review = s.get('boundary_review', {})
            require(review.get('observed_range') == observed and review.get('url_range') == requested
                    and isinstance(review.get('review'), str) and review['review'].strip(),
                    'SVG 标题窗口与 source_url 不符；差异须绑定本次 observed_range/url_range 人工核查记录')
        s['_coordinate_observation'] = {
            'observed_title': titles[0].string.strip(), 'observed_range': observed,
            'url_range': requested, 'delta_start_end': [observed[0] - requested[0], observed[1] - requested[1]],
            'coordinate_convention': 'unknown',
            'note': f'本次 SVG 标题范围 {start}–{end}；URL 范围 {requested[0]}–{requested[1]}。边界差异仅记录，不推断官方内部坐标约定，不平移轨道。'}
        require(not s.get('titleless_export'), '有标题 SVG 不应填写无标题核实记录')
        return
    evidence = s.get('titleless_export')
    require(isinstance(evidence, dict), 'SVG 无序列标题；需提供同次导出的 titleless_export 核实记录')
    for key in ('page_url', 'exported_at', 'page_capture', 'official_svg_sha256', 'identity_review'):
        require(isinstance(evidence.get(key), str) and evidence[key].strip(), f'titleless_export 缺少 {key}')
    require(evidence['page_url'] == s['source_url'], '无标题 SVG 的页面链接与 source_url 不一致')
    datetime.datetime.fromisoformat(evidence['exported_at'].replace('Z', '+00:00'))
    require(re.fullmatch(r'[0-9a-f]{64}', evidence['official_svg_sha256']), 'SVG SHA-256 格式错误')
    require(evidence['official_svg_sha256'] == sha(s['_official_svg']), '无标题 SVG 哈希与导出记录不符')
    labels = evidence.get('ruler_labels')
    require(isinstance(labels, list) and len(labels) >= 2 and all(isinstance(x, str) for x in labels),
            '无标题 SVG 须记录至少两个窗口刻度标签')
    ruler_positions = set()
    for label in labels:
        require(label in texts, f'SVG 中缺少记录的窗口刻度 {label}')
        match = re.fullmatch(r'([\d,]+(?:\.\d+)?)\s*([KM]?)', label.strip(), flags=re.I)
        require(match is not None, f'窗口刻度不是 bp 坐标：{label}')
        position = float(match.group(1).replace(',', '')) * {'': 1, 'K': 1000, 'M': 1000000}[match.group(2).upper()]
        require(position.is_integer(), f'窗口刻度不是整数 bp 坐标：{label}')
        position = int(position)
        require(s['_start'] <= position <= s['_end'], f'窗口刻度 {label} 与 source_url 不符')
        ruler_positions.add(position)
    require(len(ruler_positions) >= 2, '窗口刻度须为两个不同坐标')
    capture = evidence_path(s, spec_path, evidence['page_capture'])
    require(capture.is_file() and capture != s['_official_svg'], '缺少独立的同次页面/导出记录')
    require(capture.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.pdf', '.html', '.md'},
            '同次页面/导出记录格式应可人工查看')
    s['_page_capture'] = capture
    s['_coordinate_observation'] = {'observed_title': None, 'observed_range': None,
                                  'url_range': [s['_start'], s['_end']], 'coordinate_convention': 'unknown',
                                  'note': '本次 SVG 无窗口标题；以同次页面记录核查身份，不推断内部坐标约定。'}


def load_spec(spec_path, *, input_root=None):
    spec_path = lexical_path(spec_path, kind='file')
    root_path = lexical_path(input_root if input_root is not None else spec_path.parent, kind='directory')
    require(spec_path.is_relative_to(root_path), 'spec 逃逸 input-root')
    s = read_json(spec_path)
    require(isinstance(s, dict), 'spec 应为对象')
    s['_input_root'] = root_path
    s['_input_files'] = [spec_path]
    relatives = [s[k] for k in ('official_svg', 'chromosome_metadata', 'assembly_info', 'product_report') if s.get(k)]
    if s.get('primer_evidence'):
        require(isinstance(s['primer_evidence'], dict) and isinstance(s['primer_evidence'].get('source'), dict), 'primer_evidence source shape 无效')
        relatives.append(s['primer_evidence']['source'].get('path'))
    if s.get('titleless_export'):
        require(isinstance(s['titleless_export'], dict), 'titleless_export shape 无效')
        relatives.append(s['titleless_export'].get('page_capture'))
    s['_input_files'] += [evidence_path(s, spec_path, p) for p in relatives]
    for k in ['locus_id', 'organism', 'display_name', 'assembly_name', 'source_url', 'chromosome',
              'sequence_role', 'retrieved_date', 'official_svg', 'chromosome_metadata', 'coordinate_note']:
        require(isinstance(s.get(k), str) and s[k].strip(), f'缺少字符串字段 {k}')
    require(re.fullmatch(r'[A-Za-z0-9_-]+', s['locus_id']), 'locus_id 只允许字母、数字、_、-')
    datetime.date.fromisoformat(s['retrieved_date'])
    require(s['sequence_role'] in {'chromosome', 'scaffold'}, 'sequence_role 应为 chromosome 或 scaffold')
    s['_assembly'], s['_accession'], s['_start'], s['_end'], s['_markers'] = parse_url(s['source_url'])
    apply_marker_display(s)
    for key in ['official_svg', 'chromosome_metadata']:
        s['_' + key] = evidence_path(s, spec_path, s[key])
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
    check_svg_identity(s, texts, spec_path)
    tracks = s.get('tracks', [])
    require(len(tracks) == 6 and {t.get('role') for t in tracks} == ROLES, '需记录六种轨道类别各一次')
    for t in tracks:
        require(t.get('status') in {'loaded', 'available_empty', 'unavailable', 'source_unverified_excluded'},
                '轨道尚未检查，不可当作完成')
        evidence = t.get('evidence', '').strip()
        require(evidence, f'{t["role"]} 缺少核验依据或不可用原因')
        if t['status'] == 'unavailable':
            require(not BANNED_UNAVAILABLE.search(evidence),
                    f'{t["role"]} 不可用声明过于笼统；需写明查过的目录或配置面板')
        if t['status'] == 'loaded':
            require(t.get('title') and any(t['title'] in x for x in texts), f'{t["role"]} 未出现在官方 SVG 文字中')
        if t['status'] in {'loaded', 'available_empty'}:
            require(isinstance(t.get('content_evidence'), str) and t['content_evidence'].strip()
                    and t['content_evidence'].strip() != t.get('title', '').strip(),
                    f'{t["role"]} 需声明内容证据，不能只记录标题')
            require(t.get('content_state') == ('data' if t['status'] == 'loaded' else 'empty'),
                    f'{t["role"]} status 与 content_state 矛盾')
        if t['status'] == 'available_empty':
            require(t.get('title', '').strip(), f'{t["role"]} 空窗口仍需记录官方轨道标题')
        if t['status'] == 'source_unverified_excluded':
            require(t.get('title', '').strip() and not any(t['title'] in x for x in texts),
                    f'{t["role"]} 来源未核实的轨道必须从官方导出中排除')
    s['_track_order_warnings'] = check_track_order(root, tracks)
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
    check_primer_evidence(s, spec_path)
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
    tokens = {token for text in texts for token in re.findall(r'(?<![A-Za-z0-9_.])(?:XM|NM)_\d+\.\d+(?![A-Za-z0-9_.])', text)}
    require(data['transcript'] in tokens, '官方 SVG 中缺少精确版本 RefSeq 转录本')
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


def validate_profile(profile):
    require(isinstance(profile, dict) and set(profile) == {'schema_version', 'font_family', 'width', 'font_sizes', 'colors'}, 'render_profile 字段不完整或未知')
    require(type(profile['schema_version']) is int and profile['schema_version'] == 1, 'render_profile schema_version 无效')
    require(isinstance(profile['font_family'], str) and re.fullmatch(r'[A-Za-z0-9 ,_-]{1,200}', profile['font_family']) and profile['font_family'].strip(), 'font_family 无效')
    require(isinstance(profile['width'], dict) and set(profile['width']) in ({'minimum', 'source_scale', 'padding'}, {'minimum', 'source_scale', 'padding', 'canvas_width'}), 'width 字段无效')
    if 'canvas_width' in profile['width']:
        require(type(profile['width']['canvas_width']) is int and 1000 <= profile['width']['canvas_width'] <= 10000, 'width.canvas_width 无效；仅有限整数固定画布')
    for key, lo, hi in (('minimum', 1000, 10000), ('source_scale', 0.1, 10), ('padding', 126, 126)):
        value = profile['width'][key]
        require(type(value) in (int, float) and math.isfinite(value) and lo <= value <= hi, f'width.{key} 无效；允许 {lo}–{hi}')
    sizes = {'13', '15', '16', '17', '18', '19', '20', '24', '32'}
    require(isinstance(profile['font_sizes'], dict) and set(profile['font_sizes']) == sizes, 'font_sizes 字段不完整或未知')
    require(all(type(v) in (int, float) and math.isfinite(v) and 1 <= v <= 128 for v in profile['font_sizes'].values()), 'font_sizes 无效')
    colors = {'#334155', '#cbd5e1', '#64748b', '#86efac', '#166534', '#4ade80', 'white', '#0f766e', '#0f172a', '#e2e8f0', '#dc2626', '#b91c1c', '#b45309'}
    require(isinstance(profile['colors'], dict) and set(profile['colors']) == colors, 'colors 字段不完整或未知')
    require(all(isinstance(v, str) and (v == 'white' or re.fullmatch(r'#[0-9a-fA-F]{6}', v)) for v in profile['colors'].values()), 'colors 无效')
    return copy.deepcopy(profile)


def load_profile(path=None):
    if isinstance(path, dict):
        return validate_profile(path)
    return validate_profile(read_json(lexical_path(path or Path(__file__).resolve().parents[1] / 'assets/render_profile.json', kind='file')))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def environment_record(svg):
    """Portable identity; local paths are not identity keys."""
    import ctypes
    import ctypes.util
    libraries = {}
    for name, symbol in (('cairo', 'cairo_version_string'), ('fontconfig', 'FcGetVersion'), ('freetype', None)):
        lib = ctypes.CDLL(ctypes.util.find_library(name))
        if symbol == 'cairo_version_string':
            fn = getattr(lib, symbol); fn.restype = ctypes.c_char_p
            version = fn().decode()
        elif symbol:
            version = str(getattr(lib, symbol)())
        else:
            handle = ctypes.c_void_p()
            require(lib.FT_Init_FreeType(ctypes.byref(handle)) == 0, 'FreeType 初始化失败')
            a, b, c = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
            lib.FT_Library_Version(handle, ctypes.byref(a), ctypes.byref(b), ctypes.byref(c))
            lib.FT_Done_FreeType(handle)
            version = f'{a.value}.{b.value}.{c.value}'
        libraries[name] = {'version': version}
    maps = Path('/proc/self/maps').read_text().splitlines()
    for name, record in libraries.items():
        paths = sorted({line.split()[-1] for line in maps if '/lib' + name in line and line.split()[-1].startswith('/')})
        record['loaded_files'] = [{'name': Path(p).name, 'system_root_relative': str(Path(p).relative_to('/')), 'sha256': sha(p)} for p in paths]
    root = ET.fromstring(svg)
    families = {n.get('font-family') for n in root.iter() if n.get('font-family')}
    fonts = []
    for family in sorted(families):
        for weight in ('regular', 'bold'):
            pattern = family.split(',')[0].strip() + ':style=' + weight
            result = subprocess.check_output(['fc-match', '-f', '%{file}\t%{index}\t%{family}\t%{style}\n', pattern], text=True).strip()
            file, index, resolved_family, style = result.split('\t')
            requested_family = family.split(',')[0].strip()
            fonts.append({'request': pattern, 'name': Path(file).name, 'system_root_relative': str(Path(file).relative_to('/')), 'index': index, 'family': resolved_family, 'style': style, 'sha256': sha(file),
                          'family_resolution': 'requested_family_found' if requested_family.lower() in [f.strip().lower() for f in resolved_family.split(',')] else 'fallback_family_not_requested_font'})
    deps = {}
    for name in ('CairoSVG', 'cairocffi', 'cffi', 'cssselect2', 'defusedxml', 'Pillow', 'tinycss2', 'webencodings', 'pycparser'):
        try: deps[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: deps[name] = 'unavailable'
    distribution = importlib.metadata.distribution('CairoSVG')
    converter_files = {str(p): sha(distribution.locate_file(p)) for p in distribution.files if str(p).startswith('cairosvg/') and str(p).endswith('.py')}
    return {'python': platform.python_version(), 'python_implementation': platform.python_implementation(),
            'CairoSVG_source_sha256': converter_files,
            'python_binary_sha256': sha(Path(sys.executable).resolve()), 'platform': platform.platform(),
            'renderer_sha256': sha(__file__), 'dependencies': deps, 'libraries': libraries,
            'actual_mapped_font_files': [{'name': Path(p).name, 'system_root_relative': str(Path(p).relative_to('/')), 'sha256': sha(p)} for p in sorted({line.split()[-1] for line in maps if line.split()[-1].lower().endswith(('.ttf', '.ttc', '.otf')) and line.split()[-1].startswith('/')})],
            'font_resolution': fonts, 'font_resolution_method': 'local Fontconfig fc-match family/style; not per-glyph fallback proof',
            'font_portability': 'auditable_identity_not_cross_machine_lock; fallback/different_files_can_change_pixels',
            'network_resources': 'normalized_CSS_validation_and_mandatory_offline_url_fetcher'}


def compose(s, original, profile=None):
    profile = load_profile(profile)
    dimensions = profile['width']
    width = dimensions.get('canvas_width', max(dimensions['minimum'], math.ceil(s['_viewbox'][2] * dimensions['source_scale']) + dimensions['padding']))
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
        attrs = dict(attrs)
        for key in ('fill', 'stroke'):
            if key in attrs:
                attrs[key] = profile['colors'].get(attrs[key], attrs[key])
        if 'font-size' in attrs:
            attrs['font-size'] = profile['font_sizes'].get(str(attrs['font-size']), attrs['font-size'])
        n = ET.SubElement(root, f'{{{NS}}}{tag}', {k: str(v) for k, v in attrs.items()})
        n.text = value
        return n
    def text(x, y, value, size=18, color='#334155', weight='normal'):
        return elem('text', {'x': x, 'y': y, 'font-family': profile['font_family'],
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
    chrom_label = s['chromosome']
    if s['sequence_role'] == 'chromosome' and not chrom_label.lower().startswith('chr '):
        chrom_label = 'Chr ' + chrom_label
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
    text(60, footer_y + 36, '阅读边界：官方轨道只反映当前参考组装与窗口；公共数据不代表本次样本结果。', 17)
    text(60, footer_y + 67, '未自动判定注释一致、引物无变异或实验验证通过。染色体定位线为可见性放宽的中心标记。', 17)
    miss_y = footer_y + 95
    if s.get('_exons'):
        e = s['_exons']
        text(60, footer_y + 98, f'外显子编号来自 {e["transcript"]}（{e["gene"]}，{e["strand"]}），{e["source"]}；仅该转录本。', 17)
        miss_y = footer_y + 126
    for i, message in enumerate(missing):
        text(60, miss_y + i * 25, message[:85] + ('…（完整说明见 source_notes.md）' if len(message) > 85 else ''), 16, '#b45309')
    text(60, height - 18, f'获取日期：{s["retrieved_date"]}  |  官方轨道 + 本地定位排版  |  原始导出及来源说明随附', 15, '#64748b')
    result = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    safe_svg_bytes(result)
    return result


def render(spec_path, output, profile=None, *, input_root=None):
    started = time.monotonic()
    profile = load_profile(profile)
    s, raw = load_spec(spec_path, input_root=input_root)
    out = output_path(output, s)
    try:
        import cairosvg
    except ImportError as exc:
        raise ValueError('缺少 CairoSVG；请按 references/execution.md 使用临时虚拟环境') from exc
    svg = compose(s, raw, profile)
    # All rendering occurs before any output is published.
    pdf = convert_svg(svg, 'pdf')
    png = convert_svg(svg, 'png')
    out.mkdir(parents=True, exist_ok=False)
    prefix = s['locus_id']
    (out / f'{prefix}_enhanced.svg').write_bytes(svg)
    (out / f'{prefix}_enhanced.pdf').write_bytes(pdf)
    (out / f'{prefix}_enhanced.png').write_bytes(png)
    shutil.copyfile(s['_official_svg'], out / f'{prefix}_official_tracks.svg')
    shutil.copyfile(s['_chromosome_metadata'], out / 'chromosome_metadata.json')
    if s.get('assembly_info'):
        dest = out / 'assembly_info.json'
        shutil.copyfile(evidence_path(s, Path(spec_path), s['assembly_info']), dest)
    if s.get('product_report'):
        dest = out / 'product_report.json'
        shutil.copyfile(evidence_path(s, Path(spec_path), s['product_report']), dest)
    if s.get('_page_capture'):
        capture_name = 'export_page_capture' + s['_page_capture'].suffix.lower()
        shutil.copyfile(s['_page_capture'], out / capture_name)
    if s.get('_primer_source'):
        primer_source_name = 'primer_evidence_source' + s['_primer_source'].suffix
        shutil.copyfile(s['_primer_source'], out / primer_source_name)
    clean = copy.deepcopy({k: v for k, v in s.items() if not k.startswith('_')})
    clean['official_svg'] = f'{prefix}_official_tracks.svg'
    clean['chromosome_metadata'] = 'chromosome_metadata.json'
    if s.get('assembly_info'):
        clean['assembly_info'] = 'assembly_info.json'
    if s.get('product_report'):
        clean['product_report'] = 'product_report.json'
    if s.get('_page_capture'):
        clean['titleless_export']['page_capture'] = capture_name
    if s.get('_primer_source'):
        clean['primer_evidence']['source']['path'] = primer_source_name
    (out / 'spec.json').write_text(json.dumps(clean, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    final, final_raw = load_spec(out / 'spec.json')
    require(compose(final, final_raw, profile) == svg, 'finalspec 回放不等于已渲染 SVG')
    write_json(out / 'render_profile.json', profile)
    write_json(out / 'environment.json', environment_record(svg))
    notes = [f'# {prefix} 来源与边界', '', f'来源：{s["source_url"]}', f'数据获取日期：{s["retrieved_date"]}',
             f'序列：{s["_accession"]}；长度：{s["_length"]:,} bp（随附 ESummary）。', '', '## 坐标与排版',
             s['_coordinate_observation']['note'],
             '人工原记录（非脚本推断）：' + s['coordinate_note'], '轨道几何未重绘；如指定则仅替换原始导出的标题。原件随附。',
             '增强版移除官方 SVG DTD 声明和已知 NCBI 在线字体导入，采用本地字体；原件未改。',
             '全序列条不表示着丝粒或细胞遗传学带区；红线仅为加宽的窗口中心位置。',
             '引物分段长度来自各段闭区间；最外侧跨度不等于合成引物长度或实测产物。', '', '## 轨道清单']
    if s.get('titleless_export'):
        notes += [f'无标题官方 SVG：{s["titleless_export"]["identity_review"]}；同次页面记录随附。']
    notes += s['_track_order_warnings']
    notes += [f'- {t["role"]} | {t["status"]} | {t.get("title", "")} | {t["evidence"]}' for t in s['tracks']]
    notes += [f'- {t["role"]} 内容声明：{t["content_evidence"]}' for t in s['tracks'] if t.get('content_evidence')]
    notes += ['', '## 引物来源校验', 'marker_validation: pending；来源结构/hash 匹配不等于准确结合，未运行序列比对。']
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
             'source_identity': 'verified_titleless_export' if s.get('_page_capture') else 'svg_title',
             'track_order_warnings': s['_track_order_warnings'], 'visual_review': 'pending',
             'track_content_review': 'pending', 'coordinate_observation': s['_coordinate_observation'],
             'marker_validation': s['_marker_validation'],
             'input_spec_sha256': sha(spec_path), 'finalspec_sha256': sha(out / 'spec.json'),
             'profile_sha256': sha(out / 'render_profile.json'),
             'input_sha256': {key: sha((Path(spec_path).resolve().parent / s[key]).resolve()) for key in ('official_svg', 'chromosome_metadata', 'assembly_info', 'product_report') if s.get(key)},
             'outputs': {f.name: sha(f) for f in out.iterdir() if f.is_file()}}
    if s.get('_page_capture'):
        audit['source_page_capture_sha256'] = sha(s['_page_capture'])
    if s.get('_product_report_sha256'):
        audit['product_report_sha256'] = s['_product_report_sha256']
    (out / 'checks.json').write_text(json.dumps(audit, indent=2) + '\n', encoding='utf-8')
    write_json(out / 'execution.json', {'finished_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'elapsed_seconds': time.monotonic() - started})
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path)
    parser.add_argument('-o', '--output', type=Path)
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--profile', type=Path, help='完整本地 render_profile JSON；padding 固定为 126')
    parser.add_argument('--input-root', type=Path, help='显式科学输入根；默认 spec 目录，跨目录 ../ 证据必须显式指定')
    args = parser.parse_args()
    try:
        profile = load_profile(args.profile)
        if args.validate_only:
            s, _ = load_spec(args.spec, input_root=args.input_root)
            if args.output is not None: output_path(args.output, s)
            print(f'输入通过：{s["locus_id"]}；仍需检查视觉效果及真实坐标对应。')
        else:
            require(args.output is not None, '必须指定新输出目录 -o')
            print(render(args.spec, args.output, profile, input_root=args.input_root))
    except (ValueError, KeyError, TypeError, OSError, ET.ParseError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
