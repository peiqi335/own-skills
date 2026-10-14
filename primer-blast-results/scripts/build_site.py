#!/usr/bin/env python3
"""Manifest-driven offline site; no network, overwrite, or scientific inference."""
import argparse
import copy
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import posixpath
import re
from string import Template
import sys
import platform
from urllib.parse import urlsplit

from evidence import (STATES, check_response_binding, classify, no_symlinks,
                      parse_products, safe_file, sha256, same_result, live_urls, response_binding, trusted_parameters)

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
BLAST = Path(__file__).resolve().parents[2] / 'blast-offline-html'
sys.path.insert(0, str(BLAST / 'scripts'))
import render_blast_offline as blast
from history_policy import binding as site_binding, validate as validate_history, warning as parameter_warning
from gdv_delivery import unique_ids, static_svg, load_delivery

CSP = ("default-src 'self'; script-src 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self'; connect-src 'none'; frame-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'none'")


def dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


def relative(target, page):
    return posixpath.relpath(target, str(Path(page).parent))


def path_name(name):
    if (not isinstance(name, str) or not name or ':' in name or '\\' in name
            or Path(name).is_absolute() or '..' in Path(name).parts
            or str(Path(name)) != name or any(ord(c) < 32 for c in name)):
        raise ValueError('无效输出相对路径：' + str(name))
    return name


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('无效 ID：' + str(value))
    return value


def policy(text):
    return re.sub(r'</head>', '<meta http-equiv="Content-Security-Policy" content="' +
                  escape(CSP, quote=True) + '"></head>', text, count=1, flags=re.I)


class SafeBody(HTMLParser):
    """Retain archived body blocks, never its scripts/resources/events/forms."""
    ALLOWED = {'div', 'span', 'p', 'br', 'hr', 'table', 'thead', 'tbody', 'tr', 'td',
               'th', 'pre', 'code', 'b', 'strong', 'em', 'i', 'u', 'h1', 'h2', 'h3',
               'h4', 'ul', 'ol', 'li', 'dl', 'dt', 'dd', 'a', 'sup', 'sub', 'section'}
    DROP = {'head', 'script', 'style', 'iframe', 'object', 'svg', 'noscript'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.drop = []

    def handle_starttag(self, tag, attrs):
        if tag in self.DROP:
            self.drop.append(tag)
        if self.drop or tag not in self.ALLOWED:
            return
        keep = []
        for k, v in attrs:
            if v is None:
                continue
            if k in ('class', 'colspan', 'rowspan', 'title'):
                keep.append((k, v))
            if tag == 'a' and k == 'href' and urlsplit(v).scheme == 'https':
                keep.extend([('href', v), ('target', '_blank'), ('rel', 'noopener noreferrer')])
        self.out.append('<' + tag + ''.join(' ' + k + '="' + escape(v, quote=True) + '"' for k, v in keep) + '>')

    def handle_endtag(self, tag):
        if self.drop:
            if tag == self.drop[-1]:
                self.drop.pop()
            return
        if tag in self.ALLOWED and tag not in ('br', 'hr'):
            self.out.append('</' + tag + '>')

    def handle_data(self, data):
        if not self.drop:
            self.out.append(escape(data))


def provenance(q):
    labels = {
        'reconstructed_display_no_raw_response': '重建式展示页，无 raw/submission/jobkey 指针；历史无产物登记保留，来源待核 pending',
        'decorated_ncbi_body_not_raw_response': '较完整 NCBI 正文但已装饰；不是 raw，也不是37重建式页；来源待核 pending',
        'historical_decorated_report_not_raw_response': '历史装饰报告，非 raw；来源待核 pending',
    }
    return labels.get(q['provenance'], q['provenance'] + '；来源待核 pending') + '；source_verified 不证明 NCBI 认证或传输真实性'


def result_label(q):
    if q['products']:
        return '、'.join(str(p['length_bp']) for p in q['products']) + ' bp'
    if q['provenance'] == 'reconstructed_display_no_raw_response':
        return '历史登记无产物 · pending'
    if q['status'] == 'completed_no_target_template':
        return '未报告产物'
    return '待核：' + q['status']


def notes_text(raw):
    """Strict UTF-8 plain text only; never interpret Markdown or raw HTML."""
    return escape(raw.decode('utf-8-sig'))


def strip_legacy_navigation(text):
    """Remove only old decorated live bars, preserving all scientific raw markup."""
    class Bars(HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth, self.start, self.spans = 0, None, []
            self.offsets = [0]
            for line in text.splitlines(keepends=True):
                self.offsets.append(self.offsets[-1] + len(line))
        def position_offset(self):
            line, col = self.getpos()
            return self.offsets[line - 1] + col
        def handle_starttag(self, tag, attrs):
            if tag == 'div':
                self.depth += 1
                if self.start is None and 'ncbi-live-bar' in (dict(attrs).get('class') or '').split():
                    self.start = (self.depth, self.position_offset())
            if self.start is not None and tag in ('pre', 'table'):
                raise ValueError('旧导航区域包含科学字段，拒绝自动剥离')
        def handle_endtag(self, tag):
            if tag == 'div':
                if self.start is not None and self.depth == self.start[0]:
                    end = text.index('>', self.position_offset()) + 1
                    self.spans.append((self.start[1], end))
                    self.start = None
                self.depth -= 1
    parser = Bars()
    parser.feed(text)
    if parser.start is not None:
        raise ValueError('旧导航区域不闭合')
    for start, end in reversed(parser.spans):
        text = text[:start] + text[end:]
    return text


def build(manifest_path, output, gdv_dir=None):
    manifest_path = no_symlinks(manifest_path).resolve()
    root = manifest_path.parent
    output = no_symlinks(output).resolve()
    source_roots = (root, ASSETS.parent, BLAST)
    if output.exists() or any(output.is_relative_to(r) or r.is_relative_to(output) for r in source_roots):
        raise ValueError('输出必须为独立且不存在的新目录')
    m = json.loads(manifest_path.read_text('utf-8'))
    if m.get('schema_version') != 1 or not m.get('datasets'):
        raise ValueError('需要 schema_version=1 和非空 datasets')
    m = copy.deepcopy(m)
    files, roles, inputs = {}, {}, {}

    def put(name, raw, role='regenerated'):
        path_name(name)
        if name in files:
            raise ValueError('重复或 raw/display 输出冲突：' + name)
        files[name] = raw.encode('utf-8') if isinstance(raw, str) else raw
        roles[name] = role

    def archive(record, source_root=root, prefix=''):
        p = safe_file(source_root, record['path'])
        raw = p.read_bytes()
        if sha256(raw) != record['sha256']:
            raise ValueError('输入 hash 不符：' + record['path'])
        name = '_archive/' + prefix + record['path']
        # HTML preserved bytes are downloads, never executable report views.
        if p.suffix.lower() in ('.html', '.htm'):
            name += '.bin'
        if name not in files:
            put(name, raw, 'archive_copy')
        elif files[name] != raw:
            raise ValueError('输入归档冲突')
        inputs[prefix + record['path']] = {'sha256': sha256(raw), 'archive': name}
        record['path'] = name
        return raw, name, p

    for name in ('site.css', 'matrix.css', 'gdv.css', 'report.css'):
        raw = safe_file(ASSETS, name).read_bytes()
        if re.search(rb'@import|https?://|url\s*\(', raw, re.I):
            raise ValueError('CSS 包含隐式资源请求：' + name)
        put('assets/' + name, raw, 'template_copy')
    templates = {}
    for name in ('page', 'modal', 'card', 'section', 'table', 'row', 'cell', 'notes'):
        raw = safe_file(ASSETS, 'templates/' + name + '.html').read_bytes()
        put('_replay/tools/primer-blast-results/assets/templates/' + name + '.html', raw, 'template_copy')
        templates[name] = Template(raw.decode())
    put('_replay/style-config.json', safe_file(ASSETS, 'style-config.json').read_bytes(), 'template_copy')
    for name in ('site.css', 'matrix.css', 'gdv.css', 'report.css', 'style-config.json'):
        put('_replay/tools/primer-blast-results/assets/' + name, safe_file(ASSETS, name).read_bytes(), 'template_copy')
    put('_replay/tools/blast-offline-html/assets/viewer.css', safe_file(BLAST / 'assets', 'viewer.css').read_bytes(), 'template_copy')

    def tpl(name, **values):
        return templates[name].substitute(values)

    def cell(content, **attrs):
        return tpl('cell', attributes=' '.join(k.replace('_', '-') + '="' + escape(str(v), quote=True) + '"' for k, v in attrs.items()), content=content)

    def row(cells):
        return tpl('row', cells=''.join(cells))

    def table(headers, rows, class_name=''):
        return tpl('table', headers=''.join('<th>' + escape(h) + '</th>' for h in headers), rows=''.join(rows), class_name=class_name)

    def section(title, body, description=''):
        return tpl('section', heading=escape(title), description=escape(description), table=body)

    nav_items = [('index.html', '总入口')]
    ids = set()
    qids = set()
    maps = {}
    for d in m['datasets']:
        identifier(d['id'])
        if d['id'] in ids:
            raise ValueError('分库 ID 重复')
        ids.add(d['id'])
        path_name(d['index'])
        nav_items.append((d['index'], d['title']))
        codes = [identifier(s['code']) for s in d['species']]
        assays = [identifier(a) for a in d['assays']]
        if not codes or not assays or len(set(codes)) != len(codes) or len(set(assays)) != len(assays):
            raise ValueError('行列为空或重复')
        qm = {}
        for q in d['queries']:
            key = (q['assay'], q['species_code'])
            if key in qm or q['id'] in qids or q['status'] not in STATES or type(q['is_target']) is not bool:
                raise ValueError('query ID/状态重复或错误')
            qids.add(q['id'])
            qm[key] = q
            sp = next((s for s in d['species'] if s['code'] == q['species_code']), None)
            if sp is None or q['organism'] != sp['organism'] or q['database'] != d['database']:
                raise ValueError('查询身份与列/分库冲突')
            params = q['parameters']
            if not trusted_parameters(params):
                raise ValueError('查询参数无效：' + q['id'])
            for k, field in [('PRIMER_LEFT_INPUT', 'forward'), ('PRIMER_RIGHT_INPUT', 'reverse'), ('ORGANISM', 'organism'), ('PRIMER_SPECIFICITY_DATABASE', 'database')]:
                if params.get(k) != q[field]:
                    raise ValueError('查询与请求字段冲突：' + k)
            raw, archived, _ = archive(q['display_input'])
            text = raw.decode('utf-8-sig')
            if q.get('parameter_policy'):
                registration, _, _ = archive(q['parameter_policy']['registration_input'])
                binding = validate_history(q, text, registration)
            else:
                binding = site_binding(text, params)
            if classify(text) != q['status'] or parse_products(text)[:2] != (q['products'], q['parse_status']):
                raise ValueError('报告与登记状态/产物/解析状态冲突：' + q['id'])
            if q['products'] and q['status'] != 'completed_results':
                raise ValueError('失败状态包含产物')
            for field in ('raw_response', 'submission'):
                if q.get(field):
                    raw_evidence, _, _ = archive(q[field])
                    site_binding(raw_evidence.decode('utf-8-sig'), params)
                    if field == 'raw_response':
                        same_result(raw_evidence.decode('utf-8-sig'), text)
                        text = raw_evidence.decode('utf-8-sig')
            # Legacy adapter never promotes hashes/content matching into authenticity.
            q.update(source_verified=False, evidence_status='pending', response_binding=binding,
                     archived_input=archived, display_is_derived=True)
            report_page = path_name(q['result_page'])
            if not report_page.endswith('.html'):
                raise ValueError('展示页必须为 HTML')
            body = SafeBody()
            body.feed(strip_legacy_navigation(text))
            body.close()
            preserved = ''.join(body.out)
            if parse_products(preserved)[:2] != (q['products'], q['parse_status']):
                raise ValueError('安全派生改变了产物字段')
            rerun, form = live_urls(params)
            navigation = '<a href="' + escape(relative(d['index'], report_page), quote=True) + '">← 返回检索矩阵</a>'
            navigation += ' · <a download href="' + escape(relative(archived, report_page), quote=True) + '">下载原样归档（非 raw 认证）</a>'
            for url, label in ((rerun, '按历史请求登记发起新查询（不保证与归档一致）'), (form, '打开历史登记参数表单（可修改）')):
                if url:
                    navigation += ' · <a target="_blank" rel="noopener noreferrer" href="' + escape(url, quote=True) + '">' + label + '</a>'
            param_table = table(['参数', '归档值'], [row([cell(escape(k)), cell(escape(str(v)))]) for k, v in sorted(params.items())])
            if q.get('parameter_policy'):
                hp = q['parameter_policy']
                param_table += '<p>' + escape(parameter_warning(q) or '展示及新查询参数来自历史请求登记；报告返回字段另列，不保证与归档一致') + '</p>'
                param_table += table(['参数', '请求登记', '报告返回', '状态'], [row([cell(escape(k)), cell(escape(str(hp['registered_parameters'].get(k, params.get(k, '未登记'))))), cell(escape('/'.join(v))), cell('冲突 pending' if k in hp['conflicts'] else '来源待核 pending')]) for k, v in sorted(hp['returned_parameters'].items())])
            if q['provenance'] == 'reconstructed_display_no_raw_response':
                # Do not republish the reconstructed page's “特异性阴性” as a conclusion.
                preserved = '<p>仅保留历史无产物登记；原重建展示文件可下载。无原始响应，不能认证其终态或来源。</p>'
            payload = dumps(q).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
            content = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>' + escape(q['id']) + '</title><link rel="stylesheet" href="' + relative('assets/report.css', report_page) + '"></head><body><div class="ncbi-live-bar">' + navigation + '<p>' + escape(provenance(q)) + '</p><p>' + escape(result_label(q)) + '</p></div>' + param_table + preserved + '<script type="application/json" id="query-record">' + payload + '</script></body></html>\n'
            put(report_page, policy(content), 'derived_display')
            q['display_sha256'] = sha256(files[report_page])
        if set(qm) != {(a, c) for a in assays for c in codes}:
            raise ValueError('矩阵缺项或多项')
        maps[d['id']] = qm

    nav_items.extend([('02.blastn/index.html', m['blast_title']), ('03.GDV/index.html', m['gdv_title'])])

    def page(name, title, content, subtitle='', css='site.css', modal=False):
        navigation = ' '.join('<a href="' + escape(relative(p, name), quote=True) + '">' + escape(t) + '</a>' for p, t in nav_items)
        text = tpl('page', title=escape(title), css=escape(relative('assets/' + css, name)), navigation=navigation,
                   subtitle=escape(subtitle), boundary=escape(m['boundary']), content=content)
        if modal:
            text = text[:text.index('</body>')] + tpl('modal', boundary=escape(m['boundary']))
        put(name, policy(text))

    cards = []
    for d in m['datasets']:
        rows = []
        qm = maps[d['id']]
        for a in d['assays']:
            cells = [cell('<strong>' + escape(a) + '</strong>')]
            for s in d['species']:
                q = qm[a, s['code']]
                shown = result_label(q)
                cl = ('cell-target' if q['is_target'] else 'cell-cross-strong') if q['products'] else ('cell-target-empty' if q['is_target'] else 'cell-specific')
                if q['status'] not in ('completed_results', 'completed_no_target_template'):
                    cl = 'cell-cross-weak'
                live, _ = live_urls(q['parameters'])
                warning = provenance(q) + ('；' + parameter_warning(q) if parameter_warning(q) else '')
                cells.append(cell(escape(shown), **{'class': cl}, role='button', tabindex='0',
                                  data_query_id=q['id'], data_report=relative(q['result_page'], d['index']),
                                  data_title=a + ' → ' + s['code'] + ' · ' + shown,
                                  data_live=live, data_provenance=warning, title=shown + '；' + warning))
            rows.append(row(cells))
        params_description = '；'.join(k + '=' + ','.join(sorted({str(q['parameters'].get(k, '未记录')) for q in qm.values()})) for k in ('PRIMER_PRODUCT_MIN', 'PRIMER_PRODUCT_MAX', 'TOTAL_PRIMER_SPECIFICITY_MISMATCH', 'PRIMER_3END_SPECIFICITY_MISMATCH', 'MISMATCH_REGION_LENGTH'))
        page(d['index'], d['title'], section('成对检索矩阵', table(['引物 / 模板'] + [s['code'] + ' ' + s.get('cn', s['organism']) for s in d['species']], rows, 'matrix'), params_description),
             f"数据库：{d['database']} · {len(d['assays'])}×{len(d['species'])} = {len(qm)}；来源待核", 'matrix.css', True)
        cards.append(tpl('card', label=escape(d['id'] + ' 成对检索'), count=str(len(qm)) + ' 份', description=escape(f"{len(d['assays'])}×{len(d['species'])}；文件完整不等于来源已核"), href=escape(d['index'], quote=True)))

    xml_records, xml_rows, xml_ids = [], [], set()
    put('02.blastn/viewer.css', safe_file(BLAST / 'assets', 'viewer.css').read_bytes(), 'template_copy')
    for item in m['blast_xml']:
        identifier(item['id'])
        if item['id'] in xml_ids:
            raise ValueError('XML ID 重复')
        xml_ids.add(item['id'])
        _, archived, source = archive(item['input'])
        rec = blast.parse_xml(source)
        rec['stem'] = item['id']
        dest = '02.blastn/' + blast.rel_html(item['id'])
        text = blast.page_html(rec, item.get('rid', ''), True, relative('02.blastn/viewer.css', dest), relative('02.blastn/index.html', dest))
        put(dest, policy(text), 'xml_reparsed')
        xml_records.append(dict(id=item['id'], record=rec, input_archive=archived, output=dest,
                                coverage=[blast.fmt_cover(h['hsps'], rec['qlen']) for h in rec['hits']]))
        xml_rows.append(row([cell('<a href="' + escape(relative(dest, '02.blastn/index.html'), quote=True) + '">' + escape(item['id']) + '</a>'), cell(str(rec['qlen'])), cell(escape(rec['db'])), cell(str(len(rec['hits']))), cell(escape(item.get('rid', '未登记')))]))
    page('02.blastn/index.html', m['blast_title'], section('XML 重解析索引', table(['查询', '长度', '数据库', 'Hits', 'RID'], xml_rows)), str(len(xml_records)) + ' 份；所有 HTML 均本轮从 XML 生成')
    put('02.blastn/parsed-records.json', dumps(xml_records))

    gdv_rows, gdv_ids = [], set()
    if gdv_dir:
        gdv_dir = no_symlinks(gdv_dir).resolve()
        if gdv_dir.is_file():
            delivery_path = gdv_dir
            if output.is_relative_to(delivery_path.parent) or delivery_path.parent.is_relative_to(output):
                raise ValueError('GDV delivery 源与输出重叠')
            gdv_dir, gm, delivery_record, actual_record = load_delivery(delivery_path)
            archive(delivery_record, delivery_path.parent, 'gdv-delivery/')
            archive(actual_record, delivery_path.parent, 'gdv-delivery/')
        else:
            gm = None
        if output.is_relative_to(gdv_dir) or gdv_dir.is_relative_to(output):
            raise ValueError('GDV 源与输出重叠')
        if gm is not None:
            pass
        elif (gdv_dir / 'site-resources.json').exists():
            gm = json.loads(safe_file(gdv_dir, 'site-resources.json').read_text('utf-8'))
        else:
            # Direct adapter for the sibling lane's established locus render outputs.
            gm = {'gdv': []}
            for old in m['gdv']:
                locus = identifier(old['id'])
                def record(rel):
                    return dict(path=rel, sha256=sha256(safe_file(gdv_dir, rel).read_bytes()))
                spec_record = record(locus + '/spec.json')
                gm['gdv'].append(dict(id=locus, mode='rendered', spec=spec_record,
                                     metadata=json.loads(safe_file(gdv_dir, spec_record['path']).read_text()),
                                     product_report=record(locus + '/product_report.json'),
                                     resources=[dict(input=record(locus + '/' + locus + '_enhanced.' + suffix),
                                                     output='03.GDV/' + locus + '/' + locus + '_enhanced.' + suffix)
                                                for suffix in ('svg', 'png', 'pdf')],
                                     evidence_inputs=[record(locus + '/' + name) for name in
                                                      ('checks.json', 'environment.json', 'execution.json', 'render_profile.json', 'source_notes.md')]))
        unique_ids(gm['gdv'])
        unique_ids(m['gdv'])
        replacement = {g['id']: g for g in gm['gdv']}
        if set(replacement) != {g['id'] for g in m['gdv']}:
            raise ValueError('GDV ID 必须全量对应')
        for previous in m['gdv']:
            replacement[previous['id']]['historical_outputs'] = [r['output'] for r in previous['resources']]
        m['gdv'] = [replacement[g['id']] for g in m['gdv']]
    for g in m['gdv']:
        identifier(g['id'])
        if g['id'] in gdv_ids or g['mode'] not in ('archive_copy', 'rendered'):
            raise ValueError('GDV ID/模式错误')
        gdv_ids.add(g['id'])
        if gdv_dir and g['mode'] != 'rendered':
            raise ValueError('--gdv-dir 必须标明 rendered，不能冒充 archive_copy')
        if gdv_dir:
            # Rendering provenance is orthogonal to a new export or binding review.
            g.setdefault('source_status', 'unspecified_render_source_pending')
            if g['source_status'] not in ('historical_revised_input_not_new_export', 'unspecified_render_source_pending'):
                raise ValueError('GDV 来源状态不能升格为新导出或 scientific passed')
            for field in ('marker_validation', 'endpoint_status', 'public_RNA_status'):
                if g.get(field, 'pending') != 'pending':
                    raise ValueError('site 不接受 GDV scientific pending 升格：' + field)
                g[field] = 'pending'
            g['scientific_binding_review'] = 'pending_Oracle'
            g['visual_review'] = 'pending_parent'
        sr = gdv_dir or root
        raw_spec, archived_spec, _ = archive(g['spec'], sr, 'gdv-render/' if gdv_dir else '')
        spec = json.loads(raw_spec)
        if spec != g['metadata'] or spec['locus_id'] != g['id']:
            raise ValueError('GDV 元数据冲突')
        if g.get('product_report'):
            archive(g['product_report'], sr, 'gdv-render/' if gdv_dir else '')
        notes_links = []
        g['notes_viewers'] = []
        for record in g.get('evidence_inputs', []):
            raw_notes, archived_notes, _ = archive(record, sr, 'gdv-render/' if gdv_dir else '')
            if Path(record['path']).name == 'source_notes.md':
                viewer = '03.GDV/' + g['id'] + '/source_notes.html'
                page(viewer, g['id'] + ' · 来源说明',
                     tpl('notes', raw=escape(relative(archived_notes, viewer), quote=True),
                         text=notes_text(raw_notes)),
                     '原始来源说明；历史修订输入，非新导出；scientific pending')
                source_meta = dict(raw_archive=archived_notes, raw_sha256=sha256(raw_notes),
                                   viewer=viewer, viewer_sha256=sha256(files[viewer]),
                                   encoding='UTF-8', rendering='html.escape plain text; no Markdown interpretation')
                put('03.GDV/' + g['id'] + '/source_meta.json', dumps(source_meta))
                g['notes_viewers'].append(source_meta)
                notes_links.append('<a href="' + escape(relative(viewer, '03.GDV/index.html'), quote=True) + '">来源说明（UTF-8）</a>')
        links = list(notes_links)
        for resource in g['resources']:
            raw, _, _ = archive(resource['input'], sr, 'gdv-render/' if gdv_dir else '')
            dest = path_name(resource['output'])
            if Path(dest).suffix not in ('.svg', '.png', '.pdf'):
                raise ValueError('仅接收 GDV 静态 SVG/PNG/PDF')
            if dest.endswith('.svg'):
                static_svg(raw)
            put(dest, raw, g['mode'])
            links.append('<a class="btn" href="' + escape(relative(dest, '03.GDV/index.html'), quote=True) + '">' + Path(dest).suffix[1:].upper() + '</a>')
        exons = spec.get('exons', {})
        live = spec.get('source_url', '')
        if live and urlsplit(live).scheme == 'https':
            links.append('<a target="_blank" rel="noopener noreferrer" href="' + escape(live, quote=True) + '">Live GDV（人工联网）</a>')
        links.append('<a download href="' + escape(relative(archived_spec, '03.GDV/index.html'), quote=True) + '">spec</a>')
        source_label = g['mode'] + '；' + g.get('source_status', 'historical_archive') + '；端点/RNA/marker pending；科学绑定 pending_Oracle'
        gdv_rows.append(row([cell(escape(g['id'])), cell(escape(spec['organism'])), cell(escape(spec['assembly_name'])), cell(escape(exons.get('gene', ''))), cell(escape(exons.get('transcript', ''))), cell(escape(source_label)), cell(' '.join(links))]))
    page('03.GDV/index.html', m['gdv_title'], section('GDV 基因座', table(['引物', '物种', '参考版本', '基因', '转录本', '资源来源', '证据'], gdv_rows)), '；'.join(sorted({g['mode'] for g in m['gdv']})) + '；archive_copy 是历史字节保全；rendered 接自独立 lane；端点与兼容性仍待核')

    for label, count, href in ((m['blast_title'], len(xml_records), '02.blastn/index.html'), (m['gdv_title'], len(gdv_rows), '03.GDV/index.html')):
        cards.append(tpl('card', label=escape(label), count=str(count), description='归档证据，不代表实验验证', href=href))
    if gdv_dir:
        m['notes'] = [n for n in m['notes'] if '暂为 archive_copy' not in n]
        m['notes'].append('GDV ' + str(len(m['gdv'])) + ' 座接入独立 lane 本轮 rendered 资源；本构建器不重渲染 GDV，也不宣称视觉或科学核验完成。')
    primer_rows = []
    gdv_by_id = {g['id']: g for g in m['gdv']}
    if len(set(m['primer_rows'])) != len(m['primer_rows']):
        raise ValueError('引物概览行重复')
    for assay in m['primer_rows']:
        identifier(assay)
        all_queries = [q for d in m['datasets'] for q in d['queries'] if q['assay'] == assay]
        if not all_queries or len({(q['forward'], q['reverse']) for q in all_queries}) != 1:
            raise ValueError('引物表缺查询或 F/R 不一致')
        cells = [cell('<strong>' + escape(assay) + '</strong><br><code>F ' + escape(all_queries[0]['forward']) + '<br>R ' + escape(all_queries[0]['reverse']) + '</code>')]
        for d in m['datasets']:
            qs = [q for q in d['queries'] if q['assay'] == assay]
            for target in (True, False):
                selected = [q for q in qs if q['is_target'] == target]
                if not selected:
                    shown = '未包含该目标查询' if target else '未包含非目标查询'
                else:
                    shown = '<br>'.join(escape(q['species_code']) + ' <a title="' + escape(provenance(q), quote=True) + '" href="' + escape(q['result_page'], quote=True) + '">' + escape(result_label(q)) + '</a>' for q in selected)
                cells.append(cell(shown))
        g = gdv_by_id.get(assay)
        cells.append(cell(escape(g['metadata']['assembly_name']) + ' · ' + escape(g['mode']) if g else '未登记'))
        primer_rows.append(row(cells))
    headers = ['引物 / 序列'] + [d['id'] + ' ' + suffix for d in m['datasets'] for suffix in ('目标', '非目标')] + ['GDV 参考']
    pending_queries = [q for d in m['datasets'] for q in d['queries'] if q['provenance'] == 'reconstructed_display_no_raw_response']
    pending_links = '<p>历史无产物登记但来源 pending：' + str(len(pending_queries)) + ' 项（缺 raw，非实验阴性）</p>'
    for d in m['datasets']:
        selected = [q for q in d['queries'] if q in pending_queries]
        if selected:
            pending_links += '<p><a href="' + escape(d['index'], quote=True) + '">' + escape(d['id']) + ' pending 矩阵</a></p>'
            pending_links += ''.join('<p><a data-pending-query="' + escape(q['id'], quote=True) + '" href="' + escape(q['result_page'], quote=True) + '">' + escape(q['assay'] + ' → ' + q['species_code']) + ' 历史无产物登记 · pending</a></p>' for q in selected)
    conflict_queries = [q for d in m['datasets'] for q in d['queries'] if q.get('parameter_policy', {}).get('conflicts')]
    conflict_links = '<p>请求登记与报告返回参数冲突 pending：' + str(len(conflict_queries)) + ' 项；无纠正依据，不覆盖历史登记</p>' + ''.join('<p><a href="' + escape(q['result_page'], quote=True) + '">' + escape(q['assay'] + ' → ' + q['species_code']) + '</a> ' + escape(parameter_warning(q)) + '</p>' for q in conflict_queries)
    content = '<div class="cards">' + ''.join(cards) + '</div>' + section('引物：目标与非目标预测', table(headers, primer_rows)) + section('历史无产物登记与参数冲突', pending_links + conflict_links) + section('区别与待核项', ''.join('<p>' + escape(n) + '</p>' for n in m['notes']))
    page('index.html', m['title'], content, str(len(primer_rows)) + ' 对引物 · 本地归档驱动 · 未进行新检索')
    for record in m.get('historical_inputs', []):
        archive(record)
    for record in m.get('provenance_inputs', []):
        archive(record)
    put('projectspec.json', dumps(m))
    put('finalspec.json', dumps(m))
    put('_replay/input-manifest.json', manifest_path.read_bytes(), 'archive_copy')
    renderer_paths = [('primer-blast-results/scripts/build_site.py', Path(__file__)), ('primer-blast-results/scripts/evidence.py', Path(__file__).with_name('evidence.py')),
                      ('primer-blast-results/scripts/prepare_site_archive.py', Path(__file__).with_name('prepare_site_archive.py')),
                      ('blast-offline-html/scripts/render_blast_offline.py', BLAST / 'scripts/render_blast_offline.py')]
    for name, src in renderer_paths:
        put('_replay/tools/' + name, no_symlinks(src).read_bytes(), 'renderer_copy')
    put('_replay/tools/primer-blast-results/scripts/verify_site.py', no_symlinks(Path(__file__).with_name('verify_site.py')).read_bytes(), 'renderer_copy')
    put('_replay/tools/primer-blast-results/scripts/history_policy.py', no_symlinks(Path(__file__).with_name('history_policy.py')).read_bytes(), 'renderer_copy')
    put('_replay/tools/primer-blast-results/scripts/gdv_delivery.py', no_symlinks(Path(__file__).with_name('gdv_delivery.py')).read_bytes(), 'renderer_copy')
    from verify_site import validate_files
    structure = validate_files(files, m)
    paths = set(files)
    if any(str(p) in paths for rel in paths for p in Path(rel).parents if str(p) != '.'):
        raise ValueError('文件/目录路径冲突')
    checks = dict(inputs=inputs, outputs={n: dict(sha256=sha256(raw), role=roles[n]) for n, raw in sorted(files.items())},
                  environment=dict(python=sys.version, browser='parent visual owner; not run by builder',
                                   fonts='CSS system-local stack, no download/bundle; actual browser resolution pending parent'),
                  query_count=len(qids), xml_count=len(xml_records), gdv_count=len(gdv_rows),
                  boundary=m['boundary'], hash_policy='checks.json excluded from self-hash; all other outputs listed; no timestamps')
    checks.update(structure=structure, dependencies='Python standard library only; no pip dependencies', platform=platform.platform())
    put('checks.json', dumps(checks))
    # No writes until every input, schema, parser and collision check has passed.
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in sorted(files.items()):
        dest = output / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as stream:
            stream.write(raw)
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--gdv-dir', type=Path, help='GDV delivery_manifest.json 或 render 目录（只读、pending、不代表新导出）')
    a = p.parse_args()
    print(build(a.manifest, a.output, a.gdv_dir))
