#!/usr/bin/env python3
"""One-time mechanical adapter for a merged archive (no network, no source writes)."""
import argparse
import json
import re
from pathlib import Path
from evidence import safe_file, no_symlinks, sha256, parse_products, classify
from history_policy import selected_parameters, declaration


def dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def prepare(root, output, assets, reuse_assets=False):
    root = no_symlinks(root).resolve()
    output = no_symlinks(output).resolve()
    assets = no_symlinks(assets).resolve()
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError('需要独立新目录')
    def overlap(a, b):
        return a.is_relative_to(b) or b.is_relative_to(a)
    if overlap(output, assets) or (not reuse_assets and (overlap(assets, root) or overlap(assets, Path(__file__).resolve().parents[1]) or assets.exists())):
        raise ValueError('资产写入须为 source/output 外独立新目录；reuse-assets 仅只读')
    for dest in (output, assets):
        for parent in dest.parents:
            no_symlinks(parent)
            if parent.exists() and not parent.is_dir():
                raise ValueError('写入 parent 不是目录：' + str(parent))
    status = json.loads(safe_file(root, 'status.json').read_text())
    review_path = status['source_review']['unit_manifest']
    review = json.loads(safe_file(root, review_path).read_text())
    provenance = {(q['assay'], q['species_code']): q['evidence_provenance']
                  for q in review['mRNA_no_product_units']}
    datasets = []
    inputs = {}

    def archive(rel):
        raw = safe_file(root, rel).read_bytes()
        inputs[rel] = raw
        return {'path': 'archive_inputs/' + rel, 'sha256': sha256(raw)}

    for name, summary in status['datasets'].items():
        queries = []
        for old in status['queries']:
            if old['dataset'] != name:
                continue
            q = dict(old)
            record = archive(q['report_path'])
            text = inputs[q['report_path']].decode('utf-8-sig')
            products, parse_status, note = parse_products(text)
            if sorted(set(p['length_bp'] for p in products)) != sorted(set(q['product_lengths_bp'])):
                raise ValueError('历史长度与正文冲突：' + q['key'])
            params = selected_parameters(old)
            parameter_policy = declaration(old, text, archive('status.json'))
            prov = provenance.get((q['assay'], q['species_code'])) if name == 'mRNA' else None
            q.update(id=q['key'], display_input=record, parameters=params,
                      parameter_policy=parameter_policy,
                     status=classify(text), products=products, parse_status=parse_status,
                     parse_error=note, provenance=prov or 'historical_decorated_report_not_raw_response',
                     source_verified=False, evidence_status='pending',
                     result_page='01.成对Primer-BLAST/' + name + '/' + q['assay'] + '/' + q['species_code'] + '.html')
            queries.append(q)
        species = [dict(s, organism=next(q['organism'] for q in queries if q['species_code'] == s['code']))
                   for s in status['species_panel']]
        datasets.append(dict(id=name, title=name + ' 成对 Primer-BLAST 检索矩阵',
                             index='01.成对Primer-BLAST/' + name + '/index.html',
                             database=summary['database'], species=species,
                             assays=list(dict.fromkeys(q['assay'] for q in queries)), queries=queries))
    xml = [dict(id=p.stem, input=archive(str(p.relative_to(root))))
           for p in sorted((root / '02.blastn/xml').glob('*.xml'))]
    rids = json.loads(safe_file(root, '02.blastn/done.json').read_text())
    for item in xml:
        item['rid'] = rids.get(item['id'], '')
    gdv = []
    for binding in review['gdv_product_bindings']:
        locus = binding['locus']
        folder = '03.GDV/' + locus + ('增强示例' if locus == 'CAT_1' else '增强')
        spec = json.loads(safe_file(root, folder + '/spec.json').read_text())
        resources = []
        for suffix in ('svg', 'png', 'pdf'):
            rel = folder + '/' + locus + '_enhanced.' + suffix
            resources.append(dict(input=archive(rel), output=rel))
        gdv.append(dict(id=locus, mode='archive_copy', spec=archive(folder + '/spec.json'),
                        product_report=archive(folder + '/product_report.json'),
                        metadata=spec, resources=resources))
    provenance_inputs = [archive('status.json'), archive(review_path), archive('02.blastn/done.json')]
    manifest = dict(schema_version=1, title='BLAST 离线结果总览', synthetic=False,
                    boundary='文件齐全、hash一致不等于来源已核；展示派生页不是原始HTTP或认证NCBI来源。未报告产物不等于实验阴性。',
                    datasets=datasets, blast_xml=xml, gdv=gdv,
                    historical_inputs=[archive('index.html'), archive('01.成对Primer-BLAST/gDNA/index.html'),
                                       archive('01.成对Primer-BLAST/mRNA/index.html'), archive('03.GDV/index.html')])
    # Mechanical CSS and modal extraction: no new palette/layout.
    manifest.update(blast_title='单序列 blastn XML 派生证据', gdv_title='GDV 基因座证据总览',
                    provenance_inputs=provenance_inputs,
                    primer_rows=list(datasets[0]['assays']),
                    notes=['GDV 暂为 archive_copy，不代表本轮新渲染；轨道与坐标说明以审查记录为准。',
                           'SHE／DUK／RAB 的转录本 R 端点及公共 RNA 跨组装兼容性仍待核。'])
    root_html = inputs['index.html'].decode()
    matrix_html = inputs['01.成对Primer-BLAST/gDNA/index.html'].decode()
    css = re.search(r'<style>([\s\S]*?)</style>', root_html)[1]
    matrix_css = re.search(r'<style>([\s\S]*?)</style>', matrix_html)[1]
    gdv_css = re.search(r'<style>([\s\S]*?)</style>', inputs['03.GDV/index.html'].decode())[1]
    modal = matrix_html[matrix_html.index('<div id="previewModal"'):]
    modal = re.sub(r'<p id="modalProvenanceWarning"[\s\S]*?</p>',
                   '<p id="modalProvenanceWarning" class="muted" role="status">$boundary</p>', modal)
    modal = modal.replace("activeCell=cell;", "activeCell=cell;document.getElementById('modalProvenanceWarning').textContent=cell.dataset.provenance;")
    modal = modal.replace('历史归档报告', '证据派生展示页')
    # Capture the accepted shell/hierarchy while replacing all factual body content.
    shell = re.sub(r'<title>[\s\S]*?</title>', '<title>$title</title>', root_html[:root_html.index('<body>') + 6])
    shell = re.sub(r'<style>[\s\S]*?</style>', '<link rel="stylesheet" href="$css">', shell)
    shell += '<header><nav>$navigation</nav><h1>$title</h1><p class="muted">$subtitle</p><div class="callout">$boundary</div></header><main>$content</main></body></html>\n'
    blocks = {
        'templates/card.html': '<div class="card"><span class="badge">$label</span><strong>$count</strong><p class="muted">$description</p><a class="btn" href="$href">查看证据 →</a></div>',
        'templates/section.html': '<section class="box"><h2>$heading</h2><p class="muted">$description</p><div class="scroll">$table</div></section>',
        'templates/table.html': '<table class="$class_name"><thead><tr>$headers</tr></thead><tbody>$rows</tbody></table>',
        'templates/row.html': '<tr>$cells</tr>',
        'templates/cell.html': '<td $attributes>$content</td>',
    }
    for name in ('site.css', 'matrix.css', 'gdv.css', 'templates/page.html', 'templates/modal.html', 'style-config.json', *blocks):
        if (assets / name).exists() and not reuse_assets:
            raise ValueError('提取目标已存在：' + name)
    if reuse_assets:
        expected = {'site.css': css, 'matrix.css': matrix_css, 'gdv.css': gdv_css, **blocks,
                    'templates/page.html': shell, 'templates/modal.html': modal,
                    'style-config.json': dumps(dict(font_policy='system-local-only; no downloads; not bundled',
                                                    extracted_from='accepted archive root/matrix', layout='mechanically preserved'))}
        for rel, text in expected.items():
            if safe_file(assets, rel).read_text() != text:
                raise ValueError('既有模板与机械提取不一致：' + rel)
    for rel in ('site.css', 'matrix.css', 'gdv.css', 'templates/page.html', 'templates/modal.html', 'style-config.json', *blocks):
        no_symlinks(assets / rel)
    ids = [q['id'] for d in datasets for q in d['queries']]
    pages = [q['result_page'] for d in datasets for q in d['queries']]
    if len(ids) != len(set(ids)) or len(pages) != len(set(pages)) or len({x['id'] for x in xml}) != len(xml) or len({g['id'] for g in gdv}) != len(gdv):
        raise ValueError('重复 query/XML/GDV 产物')
    write_paths = [output / 'manifest.json'] + [output / 'archive_inputs' / rel for rel in inputs]
    if not reuse_assets:
        write_paths += [assets / rel for rel in ('site.css', 'matrix.css', 'gdv.css', 'templates/page.html', 'templates/modal.html', 'style-config.json', *blocks)]
    if len(set(write_paths)) != len(write_paths) or any(p in write_paths for dest in write_paths for p in dest.parents):
        raise ValueError('文件/目录写入冲突')
    for dest in write_paths:
        no_symlinks(dest)
        for parent in dest.parents:
            if parent.exists() and not parent.is_dir():
                raise ValueError('写入 parent 不是目录：' + str(parent))
    output.mkdir(parents=True, exist_ok=False)
    for rel, raw in inputs.items():
        dest = output / 'archive_inputs' / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
    (output / 'manifest.json').write_text(dumps(manifest))
    for rel, text in {'site.css': css, 'matrix.css': matrix_css, 'gdv.css': gdv_css, **blocks,
                      'templates/page.html': shell, 'templates/modal.html': modal,
                      'style-config.json': dumps(dict(font_policy='system-local-only; no downloads; not bundled',
                                                      extracted_from='accepted archive root/matrix',
                                                      layout='mechanically preserved'))}.items():
        dest = assets / rel
        if reuse_assets:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--assets', type=Path, default=Path(__file__).resolve().parents[1] / 'assets')
    p.add_argument('--reuse-assets', action='store_true', help='只核对既有模板字节，不改写')
    a = p.parse_args()
    print(prepare(a.archive, a.output, a.assets, a.reuse_assets))
