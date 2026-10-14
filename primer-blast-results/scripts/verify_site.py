#!/usr/bin/env python3
"""Offline structural/field/hash verification; never a browser or authenticity oracle."""
import argparse
from collections import Counter
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import posixpath
import re
import sys
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from evidence import parse_products, sha256, safe_file, no_symlinks
from history_policy import validate as validate_history
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'blast-offline-html/scripts'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.links, self.ids, self.cells, self.records = [], set(), [], {}
        self.pending_links = {}
        self.pre, self.pres, self.data_id, self.data = None, [], None, ''
        self.visible, self.script = [], False
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('id'):
            require(a['id'] not in self.ids, 'duplicate HTML id: ' + a['id'])
            self.ids.add(a['id'])
        if tag == 'script':
            require(not a.get('src'), 'implicit script resource')
            self.script = True
            if a.get('type') == 'application/json':
                self.data_id, self.data = a.get('id'), ''
        require(not any(k.startswith('on') for k in a), 'inline event attribute')
        require(tag not in ('base', 'object', 'embed'), 'active/base element')
        if tag == 'meta':
            require(a.get('http-equiv', '').lower() != 'refresh', 'implicit refresh')
        for k in ('href', 'src', 'data-report', 'poster'):
            if a.get(k):
                self.links.append((a[k], tag == 'a' and k == 'href'))
        if 'srcset' in a:
            raise ValueError('unvalidated srcset')
        if tag == 'td' and 'data-query-id' in a:
            self.cells.append(a)
        if tag == 'a' and 'data-pending-query' in a:
            require(a['data-pending-query'] not in self.pending_links, 'duplicate pending link')
            self.pending_links[a['data-pending-query']] = a.get('href')
        if tag == 'pre':
            self.pre = ''

    def handle_data(self, text):
        if self.data_id:
            self.data += text
        if self.pre is not None:
            self.pre += text
        if not self.script:
            self.visible.append(text)

    def handle_endtag(self, tag):
        if tag == 'script':
            if self.data_id:
                self.records[self.data_id] = json.loads(self.data)
            self.data_id, self.script = None, False
        if tag == 'pre' and self.pre is not None:
            self.pres.append(self.pre)
            self.pre = None


def resolve_link(page, url):
    p = urlsplit(url)
    if p.scheme or p.netloc:
        return None, p
    require(not p.path.startswith('/'), 'absolute local URL: ' + url)
    path = posixpath.normpath(posixpath.join(posixpath.dirname(page), unquote(p.path))) if p.path else page
    require(path != '..' and not path.startswith('../'), 'escaping URL: ' + url)
    return path, p


def validate_files(files, manifest):
    docs = {n: Document(raw.decode('utf-8')) for n, raw in files.items()
            if n.endswith('.html') and not n.startswith(('_archive/', '_replay/'))}
    edges, links = {}, 0
    for name, doc in docs.items():
        edges[name] = set()
        for url, manual in doc.links:
            target, parsed = resolve_link(name, url)
            if target is None:
                require((manual and parsed.scheme == 'https') or url == 'about:blank', 'implicit/unsafe remote URL: ' + url)
                continue
            require(target in files, 'broken relative resource: ' + name + ' → ' + url)
            if parsed.fragment and target in docs:
                require(unquote(parsed.fragment) in docs[target].ids, 'broken anchor: ' + name + ' → ' + url)
            links += 1
            edges[name].add(target)
    reachable, todo = set(), ['index.html']
    while todo:
        n = todo.pop()
        if n not in reachable:
            reachable.add(n)
            todo.extend(edges.get(n, ()))
    require(set(docs) <= reachable, 'HTML unreachable from root: ' + repr(sorted(set(docs) - reachable)))
    mapping, conflicts = [], []
    for d in manifest['datasets']:
        cells = docs[d['index']].cells
        expected = [next(q for q in d['queries'] if q['assay'] == a and q['species_code'] == s['code'])
                    for a in d['assays'] for s in d['species']]
        require([c['data-query-id'] for c in cells] == [q['id'] for q in expected], 'matrix row/column/order mismatch')
        for c, q in zip(cells, expected):
            target, _ = resolve_link(d['index'], c['data-report'])
            require(target == q['result_page'], 'matrix report mapping mismatch')
            require('pending' in c['title'] and 'pending' in c['data-provenance'], 'missing external warning/tooltip')
            page = docs[target]
            embedded = page.records.get('query-record', {})
            for k, value in q.items():
                if k != 'display_sha256':
                    require(embedded.get(k) == value, 'query/page field mismatch: ' + q['id'] + ' ' + k)
            require(parse_products(files[target].decode())[:2] == (q['products'], q['parse_status']), 'display products mismatch')
            source = files[q['archived_input']].decode('utf-8-sig')
            require(parse_products(source)[:2] == (q['products'], q['parse_status']), 'real source product facts differ')
            if q.get('parameter_policy'):
                hp = q['parameter_policy']
                raw_registration = files[hp['registration_input']['path']]
                require(sha256(raw_registration) == hp['registration_input']['sha256'], 'registration hash mismatch')
                b = validate_history(q, source, raw_registration)
                require(q['response_binding'] == b, 'source echo binding mismatch')
                if hp['conflicts']:
                    visible_text = ' '.join(page.visible)
                    require('参数冲突 pending' in visible_text and '请求登记' in visible_text and '报告返回' in visible_text, 'conflict hidden from visible report')
                    require('参数冲突 pending' in c['title'], 'conflict tooltip missing')
                    conflicts.append(dict(id=q['id'], registration=hp['registration_input'], registered=hp['registered_parameters'],
                                          returned=hp['returned_parameters'], conflicts=hp['conflicts'], page=target))
            if q['provenance'] != 'reconstructed_display_no_raw_response':
                # Every scientific pre block (coordinates, alignments, mismatch annotations)
                # must survive sanitization in the same order, not just product lengths.
                pres = re.findall(r'<pre\b[^>]*>([\s\S]*?)</pre>', source, re.I)
                normalized = [unescape(re.sub(r'<[^>]+>', '', p)) for p in pres]
                require(normalized == page.pres, 'scientific pre blocks changed: ' + q['id'])
                clean = re.sub(r'<(?:script|head|style)\b[^>]*>[\s\S]*?</(?:script|head|style)>', '', source, flags=re.I)
                text_rows = lambda text: [' '.join(unescape(re.sub(r'<[^>]+>', ' ', r)).split())
                                         for r in re.findall(r'<tr\b[^>]*>([\s\S]*?)</tr>', text, re.I)]
                shown_rows = text_rows(files[target].decode())
                require(all(r in shown_rows for r in text_rows(clean)), 'scientific table fields changed: ' + q['id'])
            else:
                require(not page.pres and q['evidence_status'] == 'pending', 'reconstruction not marked pending')
            visible = ' '.join(page.visible)
            require('复现归档结果' not in visible and '自动出结果' not in visible, 'obsolete live guarantee remains')
            require(all(str(v) in visible for v in q['parameters'].values()), 'parameter missing from visible page')
            mapping.append(dict(id=q['id'], dataset=d['id'], assay=q['assay'], species=q['species_code'],
                                source=q['archived_input'], page=target, products=q['products'],
                                status=q['status'], provenance=q['provenance'], pre_blocks=len(page.pres)))
    root = docs['index.html']
    pending = {q['id']: q for d in manifest['datasets'] for q in d['queries'] if q['provenance'] == 'reconstructed_display_no_raw_response'}
    require(set(root.pending_links) == set(pending), 'root pending evidence links missing/extra')
    for key, q in pending.items():
        require(root.pending_links[key] == q['result_page'], 'root pending link incorrect')
    root_text = ' '.join(root.visible)
    require('历史无产物登记但来源 pending：' + str(len(pending)) in root_text, 'root pending count not visible')
    require('请求登记与报告返回参数冲突 pending：' + str(len(conflicts)) in root_text, 'root conflict count not visible')
    xml_checks, hsps = [], 0
    parsed_records = json.loads(files['02.blastn/parsed-records.json'])
    for item in parsed_records:
        rec = item['record']
        page = docs[item['output']]
        require(page.records.get('scientific-record') == rec, 'XML scientific payload/page mismatch')
        raw = files[item['input_archive']].decode('utf-8')
        tree = ET.fromstring(re.sub(r'<!DOCTYPE[^>]*>', '', raw, count=1))
        leaves = lambda node: {n.tag: n.text or '' for n in node if len(n) == 0}
        require(rec['xml_fields'] == leaves(tree), 'XML top-level fields mismatch')
        for key, path in [('parameters', 'BlastOutput_param/Parameters'),
                          ('statistics', 'BlastOutput_iterations/Iteration/Iteration_stat/Statistics')]:
            node = tree.find(path)
            require(rec[key] == (leaves(node) if node is not None else {}), 'XML ' + key + ' mismatch')
        hits = tree.findall('BlastOutput_iterations/Iteration/Iteration_hits/Hit')
        require(len(hits) == len(rec['hits']), 'XML hit count mismatch')
        visible = ' '.join(page.visible)
        for index, (hit, h) in enumerate(zip(hits, rec['hits'])):
            require(h['xml_fields'] == leaves(hit), 'XML accession/description/length mismatch')
            xml_hsps = hit.findall('Hit_hsps/Hsp')
            require(len(xml_hsps) == len(h['hsps']), 'XML HSP count mismatch')
            covered = set()
            require(h['acc'] in visible and h['def'] in visible, 'accession/description missing from page')
            for x, s in zip(xml_hsps, h['hsps']):
                require(s['xml_fields'] == leaves(x), 'XML HSP exact scientific fields mismatch')
                for field, xml_field, cast in [('bits', 'Hsp_bit-score', float), ('score', 'Hsp_score', float),
                        ('evalue', 'Hsp_evalue', float), ('qfrom', 'Hsp_query-from', int), ('qto', 'Hsp_query-to', int),
                        ('hfrom', 'Hsp_hit-from', int), ('hto', 'Hsp_hit-to', int), ('ident', 'Hsp_identity', int),
                        ('alen', 'Hsp_align-len', int), ('gaps', 'Hsp_gaps', int)]:
                    require(s[field] == cast(x.findtext(xml_field)), 'XML typed HSP mismatch: ' + field)
                covered.update(range(min(s['qfrom'], s['qto']), max(s['qfrom'], s['qto']) + 1))
                from render_blast_offline import aln_pre, fmt_e
                # Full rendered HSP alignment and score/identity/gap/strand fields,
                # not merely a hidden JSON record or an accession substring.
                require(aln_pre(s) in page.pres, 'HSP alignment absent/changed in visible page')
                for value in (f"Score = {s['bits']:.1f} bits ({s['score']:.0f})",
                              'Expect = ' + fmt_e(s['evalue']),
                              f"Identities = {s['ident']}/{s['alen']} ({100*s['ident']/s['alen']:.0f}%)",
                              f"Gaps = {s['gaps']}/{s['alen']} ({100*s['gaps']/s['alen']:.0f}%)",
                              'Strand=' + s['strand']):
                    require(value in visible, 'visible HSP scientific metric missing: ' + value)
                hsps += 1
            coverage = f"{100 * len(covered) / rec['qlen']:.0f}%"
            require(coverage == item['coverage'][index] and coverage in visible, 'union coverage/page mismatch')
        xml_checks.append(dict(id=item['id'], page=item['output'], hits=len(hits),
                               hsps=sum(len(h['hsps']) for h in rec['hits']), coverage=item['coverage']))
    return dict(html_pages=len(docs), relative_links=links, root_reachable=True,
                primer_mapping=mapping, xml_fields=xml_checks, hsp_count=hsps,
                parameter_conflicts=conflicts, root_visible_pending_count=len(pending),
                gdv_modes={g['id']: g['mode'] for g in manifest['gdv']},
                scope='structural/scientific field consistency only; browser/NCBI authenticity not verified')


def snapshot(root):
    root = no_symlinks(root).resolve()
    return {str(p.relative_to(root)): no_symlinks(p).read_bytes() for p in root.rglob('*') if p.is_file()}


def verify(root, other=None, old=None):
    files = snapshot(root)
    checks = json.loads(files['checks.json'])
    require(set(files) == set(checks['outputs']) | {'checks.json'}, 'unlisted/missing outputs')
    for n, record in checks['outputs'].items():
        require(sha256(files[n]) == record['sha256'], 'output hash mismatch: ' + n)
    for n, record in checks['inputs'].items():
        require(sha256(files[record['archive']]) == record['sha256'], 'archive hash mismatch: ' + n)
    m = json.loads(files['finalspec.json'])
    require(json.loads(files['projectspec.json']) == m, 'finalspec mismatch')
    result = dict(structure=validate_files(files, m), output_hashes=checks['outputs'], input_hashes=checks['inputs'])
    if other:
        second = snapshot(other)
        names = set(files) | set(second)
        differences = [n for n in sorted(names) if files.get(n) != second.get(n)]
        result['byte_comparison'] = dict(files=len(names), differences=differences, identical=not differences)
        require(not differences, 'two-build bytes differ: ' + repr(differences))
    if old:
        prior = snapshot(old)
        rows = []
        for d in m['datasets']:
            for q in d['queries']:
                source = q['report_path']
                previous = prior.get(source)
                archive = files[q['archived_input']]
                role = 'unknown' if previous is None else 'corrected' if q['provenance'] == 'reconstructed_display_no_raw_response' else 'rebuilt'
                rows.append(dict(old=source, new=q['result_page'], category=role,
                                 archive_equal=previous == archive, display_equal=previous == files[q['result_page']]))
        for n, record in checks['inputs'].items():
            source = n.removeprefix('archive_inputs/')
            previous = prior.get(source)
            rows.append(dict(old=source, new=record['archive'], category='archive_copy' if previous == files[record['archive']] else 'unknown',
                             equal=previous == files[record['archive']]))
        for item in json.loads(files['02.blastn/parsed-records.json']):
            n = item['output']
            rows.append(dict(old=n, new=n, category='rebuilt' if n in prior else 'unknown', equal=prior.get(n) == files[n]))
        for n in ('index.html', '01.成对Primer-BLAST/gDNA/index.html', '01.成对Primer-BLAST/mRNA/index.html', '02.blastn/index.html', '03.GDV/index.html'):
            rows.append(dict(old=n, new=n, category='rebuilt' if n in prior else 'unknown', equal=prior.get(n) == files[n]))
        for g in m['gdv']:
            for r in g['resources']:
                n = r['output']
                historical = next((p for p in g.get('historical_outputs', []) if Path(p).suffix == Path(n).suffix), n)
                equal = prior.get(historical) == files[n]
                category = 'archive_copy' if equal else 'rebuilt' if g['mode'] == 'rendered' and historical in prior else 'unknown'
                rows.append(dict(old=historical, new=n, category=category, equal=equal))
        result['old_site_comparison'] = dict(counts=dict(Counter(r['category'] for r in rows)), files=rows,
                                            note='corrected means source qualification corrected, not scientifically re-searched; unknown is not asserted equal')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    p.add_argument('--compare', type=Path)
    p.add_argument('--old-site', type=Path)
    p.add_argument('--report', required=True, type=Path)
    a = p.parse_args()
    require(not a.report.exists(), 'report must not exist')
    result = verify(a.run, a.compare, a.old_site)
    with a.report.open('x', encoding='utf-8') as f:
        f.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k == 'byte_comparison'}, ensure_ascii=False))
