#!/usr/bin/env python3
"""Build a local paired Primer-BLAST dashboard from archived query status."""
import argparse
from collections import OrderedDict
import hashlib
from html import escape
import json
from pathlib import Path
import sys
import posixpath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import (STATES, classify, decorate, no_symlinks, parse_products,
                      safe_file, trusted_parameters, sha256, check_response_binding,
                      same_result, safe_job_url)

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
PANEL = '01.成对Primer-BLAST'
ZH = {'CAT': '猫', 'CHK': '鸡', 'COW': '牛', 'DOG': '狗', 'DUK': '鸭',
      'GOO': '鹅', 'GUI': '豚鼠', 'HAM': '仓鼠', 'HOR': '马', 'HUM': '人',
      'MUS': '小鼠', 'PIG': '猪', 'RAB': '兔', 'RAT': '大鼠', 'SHE': '羊'}
STYLE_LINK = '<link rel="stylesheet" type="text/css" href="../assets/report.css" />'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_report(source_dir, name):
    return safe_file(source_dir, name)


def status_text(query):
    status = query.get('status', '')
    products = query.get('products') or []
    binding_note = ' · 参数绑定 pending' if query.get('evidence_status') == 'pending' else ''
    if query.get('parse_status') == 'needs_review':
        return '解析待核：请查看原始报告', '解析待核', 'cell-cross-weak'
    if status == 'completed_no_target_template':
        return '报告无产物（未找到目标模板）' + binding_note, '报告无产物' + binding_note, 'cell-specific'
    if status == 'completed_results':
        if products:
            lengths = ', '.join(f'{p["length_bp"]} bp' for p in products)
            return f'报告有产物 {lengths}' + binding_note, lengths + binding_note, 'cell-target' if query.get('is_target') else 'cell-cross-strong'
        return '解析待核', '解析待核', 'cell-cross-weak'
    return f'未完成：{status or "未记录状态"}', '待核查', 'cell-cross-weak'


def decorate_report(raw, params=None, require_binding=False):
    text = raw.decode('utf-8-sig')
    text = decorate(text, params=params or {}, require_binding=require_binding)
    return text.encode('utf-8-sig') if raw.startswith(b'\xef\xbb\xbf') else text.encode('utf-8')


def head(title, css):
    return ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{escape(title)}</title><link rel="stylesheet" href="{css}"></head><body>')


def matrix_html(title, species, assays, queries):
    parts = [head(title + ' · 检索矩阵', 'assets/panel.css'),
             '<header><div class="nav-top"><a href="../index.html">← 返回总入口</a>'
             '<span class="curr">成对 Primer-BLAST 检索矩阵</span></div>',
             f'<h1>{escape(title)}</h1><p class="sub">点击单元格预览展示派生页；原始归档另存，实时 NCBI 作业链接可能过期。</p>',
             '<div class="callout"><strong>判读边界：</strong>“未找到目标模板”仅表示该次限定数据库与参数下的检索返回状态，不等于无交叉扩增或湿实验阴性。</div></header>',
             '<main><div class="table-card"><div class="card-header"><h3 class="card-title">成对产物与检索状态矩阵</h3></div>',
             '<div class="matrix-container"><table class="matrix-table"><thead><tr><th class="sticky-col">引物对 \\ 模板</th>']
    for sp in species:
        code = sp['code']
        organism_name = sp.get('organism') or ''
        parts.append(f'<th>{escape(code)}（{escape(ZH.get(code) or organism_name)}）</th>')
    parts.append('</tr></thead><tbody>')
    for assay in assays:
        parts.append(f'<tr><td class="sticky-col"><strong>{escape(assay)}</strong></td>')
        for sp in species:
            q = queries[(assay, sp['code'])]
            label, shown, cell_class = status_text(q)
            report = q.get('result_page')
            attrs = ''
            if report:
                attrs = (f' role="button" tabindex="0" data-report="{escape(report, quote=True)}"'
                         f' data-title="{escape(assay + " on " + sp["code"] + " · " + label, quote=True)}"'
                         f' data-live="{escape(safe_job_url(q.get("result_url")), quote=True)}"')
            parts.append(f'<td class="{cell_class}"{attrs} title="{escape(label, quote=True)}">{escape(shown)}</td>')
        parts.append('</tr>')
    parts.append('</tbody></table></div></div></main>')
    parts.append('''<div id="previewModal" class="modal" role="dialog" aria-modal="true" aria-label="报告预览">
<div class="modal-content"><div class="modal-header"><h3 class="modal-title" id="modalTitle"></h3>
<a id="modalLiveLink" class="btn btn-ncbi" target="_blank" rel="noopener noreferrer">NCBI 作业链接</a>
<a id="modalNewTabLink" class="btn btn-link" target="_blank">新标签页查看报告</a>
<button class="modal-close" id="closeModal" aria-label="关闭">&times;</button></div>
<div class="modal-body"><iframe id="modalIframe" class="modal-iframe" src="about:blank" title="归档报告展示派生页"></iframe></div></div></div>
<script>
const modal = document.getElementById('previewModal');
function openCell(cell) {
  if (!cell || !cell.dataset.report) return;
  document.getElementById('modalTitle').textContent = cell.dataset.title;
  document.getElementById('modalIframe').src = cell.dataset.report;
  document.getElementById('modalNewTabLink').href = cell.dataset.report;
  const live = document.getElementById('modalLiveLink');
  live.href = cell.dataset.live || '#';
  live.style.display = cell.dataset.live ? 'inline-flex' : 'none';
  modal.classList.add('open');
}
function closeModal() { modal.classList.remove('open'); document.getElementById('modalIframe').src = 'about:blank'; }
document.addEventListener('click', e => { const cell = e.target.closest('td[data-report]'); if (cell) openCell(cell); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('td[data-report]')) { e.preventDefault(); openCell(e.target); } });
document.getElementById('closeModal').addEventListener('click', closeModal);
modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
</script></body></html>''')
    return '\n'.join(parts) + '\n'


def index_html(title, assays, species, queries):
    total = len(queries)
    finished = sum(q.get('status', '').startswith('completed_') for q in queries.values())
    review = sum(q.get('parse_status') == 'needs_review' for q in queries.values())
    binding_pending = sum(not q.get('source_verified') for q in queries.values())
    target_queries = [q for q in queries.values() if q.get('is_target')]
    cross_queries = [q for q in queries.values() if not q.get('is_target') and q.get('products') and q.get('parse_status') == 'ok']
    specific_queries = [q for q in queries.values() if not q.get('is_target') and not q.get('products') and q.get('status') == 'completed_no_target_template' and q.get('parse_status') == 'ok']
    
    parts = [head(title, PANEL + '/assets/panel.css'), '<header><div class="nav-top"><span class="curr">离线总入口</span>'
             f'<a href="{PANEL}/index.html">成对检索矩阵 →</a></div><h1>{escape(title)}</h1>',
             f'<p class="sub">{len(assays)} 对引物 × {len(species)} 个物种；全量 {finished}/{total} 项检索已有归档状态。</p>',
             f'<p class="sub">未完成：{total - finished}；解析待核：{review}。数据库：' + escape(', '.join(sorted({str(q.get('parameters', {}).get('PRIMER_SPECIFICITY_DATABASE', q.get('database', '未记录'))) for q in queries.values()}))) + '</p>',
             f'<p class="sub">参数/归档绑定 pending：{binding_pending}；source_verified 仅表示归档完整且返回字段与请求一致，不证明传输或来源真实性。</p>',
             '<div class="callout"><strong>结果判读边界：</strong>报告有/无产物仅对应归档数据库及参数，不证明特异性或设计达标；预测长度与湿实验电泳条带分别独立判读。</div></header>',
             '<main>',
             '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-bottom:28px;">',
             f'<div style="background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,0.03);"><div style="font-size:12px;color:#64748b;font-weight:600;">检索矩阵规模</div><div style="font-size:24px;font-weight:800;color:#2563eb;margin-top:4px;">{len(assays)} <span style="font-size:14px;font-weight:normal;color:#64748b;">引物对</span> × {len(species)} <span style="font-size:14px;font-weight:normal;color:#64748b;">物种</span></div><div style="font-size:12px;color:#64748b;margin-top:4px;">共 {total} 组独立成对检索单元</div></div>',
             f'<div style="background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,0.03);"><div style="font-size:12px;color:#64748b;font-weight:600;">目标物种报告有产物</div><div style="font-size:24px;font-weight:800;color:#16a34a;margin-top:4px;">{sum(1 for q in target_queries if q.get("products") and q.get("parse_status") == "ok")} / {len(target_queries)}</div><div style="font-size:12px;color:#64748b;margin-top:4px;">报告列出的产物，不代表设计达标</div></div>',
             f'<div style="background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,0.03);"><div style="font-size:12px;color:#64748b;font-weight:600;">非目标物种报告状态</div><div style="font-size:24px;font-weight:800;color:{"#dc2626" if cross_queries else "#16a34a"};margin-top:4px;">{len(cross_queries)} <span style="font-size:14px;font-weight:normal;color:#64748b;">组报告有产物</span></div><div style="font-size:12px;color:#64748b;margin-top:4px;">{len(specific_queries)} 组报告无产物</div></div>',
             '</div>',
             '<div class="table-card"><div class="card-header"><h3 class="card-title">目标物种成对产物概览</h3></div>',
             '<div class="matrix-container"><table class="matrix-table"><thead><tr><th class="sticky-col">引物对</th><th>目标物种</th><th>物种拉丁名</th><th>报告产物尺寸</th><th>展示派生页直达</th></tr></thead><tbody>']
    for q in target_queries:
        label, shown, cell_class = status_text(q)
        report = q.get('result_page')
        sp_code = str(q.get('species_code', ''))
        sp_name = ZH.get(sp_code, sp_code)
        org = str(q.get('organism', ''))
        assay_str = str(q.get('assay', ''))
        link = f'<a class="btn btn-link" href="{PANEL}/{escape(report, quote=True)}" target="_blank">查看报告 ↗</a>' if report else '待核查'
        parts.append(f'<tr><td class="sticky-col"><strong>{escape(assay_str)}</strong></td>'
                     f'<td><strong>{escape(sp_code)}</strong>（{escape(sp_name)}）</td>'
                     f'<td><em>{escape(org)}</em></td>'
                     f'<td><span class="{cell_class}" style="padding:3px 10px;border-radius:4px;">{escape(shown)}</span></td>'
                     f'<td>{link}</td></tr>')
    parts.append('</tbody></table></div></div>')
    parts.append(f'<div style="margin-top:24px;text-align:center;"><a class="btn btn-ncbi" style="padding:10px 24px;font-size:14px;" href="{PANEL}/index.html">📊 进入成对 Primer-BLAST 检索矩阵看板（支持全量弹窗速览） →</a></div>')
    parts.append('</main></body></html>')
    return '\n'.join(parts) + '\n'


def preflight(status_path, output):
    status_path = no_symlinks(status_path).resolve()
    source_dir = status_path.parent
    output = no_symlinks(output).resolve()
    if output == source_dir or output.is_relative_to(source_dir) or source_dir.is_relative_to(output):
        raise ValueError('输出与源目录不得相同或互为祖先/后代')
    if output.exists():
        raise ValueError('输出已存在；--force 不再覆盖，请指定新输出目录')
    data = json.loads(status_path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('queries'), list) or not data['queries'] or not isinstance(data.get('species_panel'), list) or not data['species_panel']:
        raise ValueError('状态 schema 错误：需要非空 queries/species_panel')
    species = data['species_panel']
    if any(not isinstance(s, dict) or not isinstance(s.get('code'), str) or not s['code'] or not isinstance(s.get('organism'), str) for s in species):
        raise ValueError('物种 schema 错误')
    codes = [s['code'] for s in species]
    if len(set(codes)) != len(codes):
        raise ValueError('物种重复')
    prepared = {}
    hashes = {}

    def prepare(rel, display=False, params=None, expected_hash=None, derived_raw=None):
        if not isinstance(rel, str) or not Path(rel).parts or Path(rel).parts[0] in ('assets', 'index.html', 'status.json', '_archived-input'):
            raise ValueError('报告与生成文件路径冲突')
        source = safe_report(source_dir, rel)
        raw = source.read_bytes()
        if expected_hash is not None and sha256(raw) != expected_hash:
            raise ValueError(f'归档 hash 不符：{rel}')
        styled = decorate_report(derived_raw if derived_raw is not None else raw, params,
                                 require_binding=data.get('schema_version') == 2) if display else raw
        if display:
            # Report paths may be nested deeper than the usual assay/file pair.
            parent = str(Path(rel).parent)
            css = posixpath.relpath('assets/report.css', parent)
            back = posixpath.relpath('index.html', parent)
            styled = styled.replace(b'../assets/report.css', css.encode()).replace(
                b'href="../index.html"', ('href="' + back + '"').encode())
        if rel in prepared and prepared[rel] != styled:
            raise ValueError(f'归档路径重复且用途冲突：{rel}')
        prepared[rel] = styled
        hashes[rel] = dict(source_sha256=sha256(raw), output_sha256=sha256(styled),
                           role='derived_display' if display else 'archived_bytes')
        if display and derived_raw is not None:
            hashes[rel]['derivation_sha256'] = sha256(derived_raw)
        if display:
            archived = '_archived-input/' + rel
            prepared[archived] = raw
            hashes[archived] = dict(source_sha256=sha256(raw), output_sha256=sha256(raw), role='unchanged_input')
        return raw

    queries = {}
    ids = set()
    for q in data['queries']:
        if not isinstance(q, dict) or any(not isinstance(q.get(k), str) or not q[k] for k in ('id', 'assay', 'species_code', 'status')):
            raise ValueError('query schema 错误')
        if q['status'] not in STATES or q['species_code'] not in codes or not isinstance(q.get('is_target'), bool):
            raise ValueError('query 状态/物种/is_target 错误')
        key = (q['assay'], q['species_code'])
        if key in queries or q['id'] in ids:
            raise ValueError('查询重复')
        queries[key] = q
        ids.add(q['id'])
        products = q.get('products')
        if not isinstance(products, list) or any(not isinstance(p, dict) or type(p.get('length_bp')) is not int or p['length_bp'] <= 0 or not isinstance(p.get('template_accession'), str) or not p['template_accession'] for p in products):
            raise ValueError('产物 schema 错误：需要 accession 与正整数 length_bp')
        if q.get('parse_status', 'ok') not in ('ok', 'needs_review', 'not_applicable'):
            raise ValueError('parse_status 错误')
        complete = q['status'].startswith('completed_')
        v2 = data.get('schema_version') == 2
        panel_organism = next(s['organism'] for s in species if s['code'] == q['species_code'])
        if q.get('organism') is not None and q['organism'] != panel_organism:
            raise ValueError('query organism 与 species_panel 不符')
        if products and q['status'] != 'completed_results':
            raise ValueError('status/products 矛盾')
        if q['status'] == 'completed_results' and not products and q.get('parse_status') != 'needs_review':
            raise ValueError('completed_results 无产物且未标记解析待核')
        params = q.get('parameters', {})
        if not isinstance(params, dict):
            raise ValueError('parameters 必须是对象')
        if complete and v2 and (not trusted_parameters(params) or not all(q.get(k) for k in ('submission', 'raw_response', 'display_sha256', 'result_page'))):
            raise ValueError('schema_version 2 完成记录缺少请求参数/submission/raw/display hash')
        if trusted_parameters(params):
            if params['ORGANISM'] != panel_organism:
                raise ValueError('请求 ORGANISM 与 species_panel 不符')
            for field, param in [('forward', 'PRIMER_LEFT_INPUT'), ('reverse', 'PRIMER_RIGHT_INPUT'), ('organism', 'ORGANISM')]:
                if q.get(field) is not None and q[field] != params[param]:
                    raise ValueError('参数身份与查询不符')
            if data.get('database') and data['database'] != params['PRIMER_SPECIFICITY_DATABASE']:
                # A non-complete resume retains its OLD request identity for inspection.
                if complete:
                    raise ValueError('批次数据库与查询参数不符')
        binding_params = dict(params)
        for field, param in [('forward', 'PRIMER_LEFT_INPUT'), ('reverse', 'PRIMER_RIGHT_INPUT'), ('organism', 'ORGANISM')]:
            if q.get(field):
                binding_params.setdefault(param, q[field])
        binding_params.setdefault('ORGANISM', panel_organism)
        if data.get('database'):
            binding_params.setdefault('PRIMER_SPECIFICITY_DATABASE', data['database'])
        # New-format raw archives are copied byte-for-byte, never decorated.
        evidence = None
        binding = None
        for field in ('submission', 'raw_response'):
            record = q.get(field)
            if record is not None:
                if not isinstance(record, dict) or not all(isinstance(record.get(k), str) and record[k] for k in ('path', 'sha256', 'received_utc')):
                    raise ValueError('原始响应记录 schema 错误')
                raw = prepare(record['path'], expected_hash=record['sha256'])
                returned = check_response_binding(raw.decode('utf-8-sig', errors='replace'), binding_params)
                if field == 'raw_response':
                    evidence = raw
                    binding = returned
        if q.get('submission_page'):
            prepare(q['submission_page'])
        page = q.get('result_page')
        if complete and not page:
            raise ValueError('已完成查询缺少最终报告')
        if page:
            display_input = safe_report(source_dir, page).read_bytes()
            check_response_binding(display_input.decode('utf-8-sig', errors='replace'), binding_params)
            if evidence is not None and complete:
                same_result(evidence.decode('utf-8-sig', errors='replace'), display_input.decode('utf-8-sig', errors='replace'))
            # Do not turn unverifiable resume parameters into a rerun link.
            nav_params = params if complete else {}
            raw = prepare(page, display=True, params=nav_params, expected_hash=q.get('display_sha256'),
                          derived_raw=evidence if complete else None)
            q['archived_input_page'] = '_archived-input/' + page
            q['display_is_derived'] = True
            q['display_sha256'] = sha256(prepared[page])
            if evidence is None:
                evidence = raw
                binding = check_response_binding(raw.decode('utf-8-sig', errors='replace'), binding_params)
        q['response_binding'] = binding or dict(status='pending', missing_fields=[], conflicts=[])
        q['source_verified'] = bool(complete and v2 and binding and binding['status'] == 'matched')
        q['evidence_status'] = 'content_matched' if q['source_verified'] else 'pending'
        q['result_url'] = safe_job_url(q.get('result_url'))
        if complete:
            if evidence is None:
                raise ValueError('已完成查询缺少可核验报告')
            text = evidence.decode('utf-8-sig', errors='replace')
            if classify(text) != q['status']:
                raise ValueError('报告终态与 status 矛盾')
            parsed, parse_status, note = parse_products(text)
            if q['status'] == 'completed_no_target_template' and (parsed or products):
                raise ValueError('无产物状态包含产物')
            if parsed != products:
                raise ValueError('报告产物与 products 矛盾')
            if parse_status == 'needs_review' or q.get('parse_status') == 'needs_review':
                q.update(parse_status='needs_review', parse_error=note or q.get('parse_error', '人工核查'))
            else:
                q['parse_status'] = 'ok'
        else:
            q.setdefault('parse_status', 'not_applicable')
        q['database'] = q.get('parameters', {}).get('PRIMER_SPECIFICITY_DATABASE', data.get('database', '未记录'))
    assays = list(OrderedDict.fromkeys(q['assay'] for q in data['queries']))
    if set(queries) != {(a, c) for a in assays for c in codes}:
        raise ValueError('查询矩阵缺项')
    # Detect file/directory collisions before creating output.
    paths = set(prepared)
    if any(str(parent) in paths for rel in paths for parent in Path(rel).parents if str(parent) != '.'):
        raise ValueError('归档文件与目录路径冲突')
    return status_path, output, data, species, assays, queries, prepared, hashes


def build(status_path, output, title, force=False):
    # force is accepted for CLI compatibility only; no deletion or overwrite.
    status_path, output, data, species, assays, queries, prepared, hashes = preflight(status_path, output)
    matrix = matrix_html(title, species, assays, queries).encode()
    index = index_html(title, assays, species, queries).encode()
    assets = {name: (ASSETS / name).read_bytes() for name in ('panel.css', 'report.css')}
    archived_status = '_archived-input/status.json'
    prepared[archived_status] = status_path.read_bytes()
    hashes[archived_status] = dict(source_sha256=sha256(prepared[archived_status]),
                                  output_sha256=sha256(prepared[archived_status]), role='unchanged_source_status')
    checks = dict(source_status_sha256=digest(status_path), query_count=len(queries), reports=hashes)
    # All input/path/schema/report validations above precede the first write.
    output.mkdir(parents=True, exist_ok=False)
    panel = output / PANEL
    (panel / 'assets').mkdir(parents=True)
    for name, raw in assets.items():
        (panel / 'assets' / name).write_bytes(raw)
    for rel, raw in prepared.items():
        dest = panel / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as stream:
            stream.write(raw)
    (panel / 'status.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    (panel / 'index.html').write_bytes(matrix)
    (output / 'index.html').write_bytes(index)
    (output / 'checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('status_json', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--title', default='成对 Primer-BLAST 离线结果')
    parser.add_argument('--force', action='store_true', help='兼容旧接口；不覆盖已有输出，仍须指定新目录')
    args = parser.parse_args()
    print(build(args.status_json, args.output, args.title, force=args.force))


if __name__ == '__main__':
    main()
