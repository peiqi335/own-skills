"""Archived CAT evidence tests; mutated coordinates/models are synthetic mechanics,
not additional loci, source observations, or scientific binding facts.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import render_gdv as gdv
STANDARD = ROOT / 'assets/cat1-standard'


class RendererTests(unittest.TestCase):
    def setUp(self):
        # Intentionally retained: no recursive cleanup of real directories.
        self.base = Path(tempfile.mkdtemp(prefix='gdv-test-', dir='/tmp/opencode'))
        self.spec = gdv.read_json(STANDARD / 'spec.json')
        self.original_url = self.spec['source_url']
        for key in ['official_svg', 'chromosome_metadata']:
            (self.base / self.spec[key]).write_bytes((STANDARD / self.spec[key]).read_bytes())
        (self.base / 'product_report.json').write_bytes((STANDARD / 'product_report.json').read_bytes())

    def load(self):
        p = self.base / 'spec.json'
        p.write_text(json.dumps(self.spec, ensure_ascii=False))
        return gdv.load_spec(p)

    def test_real_source_and_true_geometry(self):
        before = gdv.sha(STANDARD / 'CAT_1_official_tracks.svg')
        s, root = self.load()
        self.assertEqual(s['_end'] - s['_start'] + 1, 4083)
        self.assertEqual(s['_length'], 205367284)
        generated = gdv.compose(s, root)
        self.assertNotIn(b'@import', generated)
        self.assertNotIn(b'<!DOCTYPE', generated)
        self.assertIn(b'@import', (STANDARD / 'CAT_1_official_tracks.svg').read_bytes())
        out = ET.fromstring(generated)
        segments = [n for n in out.iter() if n.get('id', '').startswith('primer-segment-')]
        self.assertEqual(len(segments), 2)
        self.assertAlmostEqual(float(segments[0].get('width')), float(segments[1].get('width')))
        self.assertLess(float(segments[0].get('x')), float(segments[1].get('x')))
        nested = out.find(f'{{{gdv.NS}}}svg')
        # Track path data must be byte-for-byte identical after composition.
        self.assertEqual([n.attrib for n in root.iter() if n.tag.endswith('}path')],
                         [n.attrib for n in nested.iter() if n.tag.endswith('}path')])
        self.assertEqual(before, gdv.sha(STANDARD / 'CAT_1_official_tracks.svg'))

    def test_out_of_window_and_reversed(self):
        for bad in ['from=142727266', 'to=142725200']:
            self.spec['source_url'] = gdv.read_json(STANDARD / 'spec.json')['source_url']
            key = bad.split('=')[0]
            import re
            self.spec['source_url'] = re.sub(key + r'=\d+', bad, self.spec['source_url'])
            with self.assertRaises(ValueError):
                self.load()

    def test_wrong_accession_or_length(self):
        original = gdv.read_json(STANDARD / 'chromosome_metadata.json')
        for kind in ['accession', 'length']:
            data = copy.deepcopy(original)
            for v in data['result'].values():
                if isinstance(v, dict):
                    if kind == 'accession': v['accessionversion'] = 'NC_000001.1'
                    else: v['slen'] = 100
            meta = self.base / 'metadata.json'
            meta.write_text(json.dumps(data))
            self.spec['chromosome_metadata'] = str(meta)
            with self.assertRaises(ValueError): self.load()

    def test_missing_track_and_explicit_unavailable(self):
        self.spec['tracks'][1]['title'] = 'Not a real track'
        with self.assertRaises(ValueError): self.load()
        self.spec['tracks'][1].update(status='unavailable', title='', evidence='Test fixture: no compatible annotation')
        s, root = self.load()
        self.assertIn(b'ensembl', gdv.compose(s, root))
        self.assertIn(b'unavailable', gdv.compose(s, root))
        self.spec['tracks'][1]['status'] = 'not_checked'
        with self.assertRaises(ValueError): self.load()

    def test_multipart_intervals_stay_separate(self):
        s, root = self.load()
        s['_markers'] = [
            {'start': 142725183, 'end': 142725192, 'label': 'F_ex1', 'color': '#ff0000'},
            {'start': 142725213, 'end': 142725222, 'label': 'F_ex2', 'color': '#ff0000'},
            {'start': 142725246, 'end': 142725265, 'label': 'R', 'color': '#2563eb'}]
        out = ET.fromstring(gdv.compose(s, root))
        seg = [n for n in out.iter() if n.get('id', '').startswith('primer-segment-')]
        self.assertEqual(len(seg), 3)
        self.assertAlmostEqual(float(seg[0].get('width')) * 2, float(seg[2].get('width')))
        self.assertLess(float(seg[0].get('x')) + float(seg[0].get('width')), float(seg[1].get('x')))
        self.assertNotEqual(seg[0].get('y'), seg[1].get('y'))

    def test_distant_segments_get_cluster_windows(self):
        s, root = self.load()
        s['_markers'] = [
            {'start': 142723183, 'end': 142723202, 'label': 'F_ex5', 'color': '#ff0000'},
            {'start': 142727246, 'end': 142727265, 'label': 'R_ex6', 'color': '#2563eb'}]
        out = ET.fromstring(gdv.compose(s, root))
        overview = [n for n in out.iter() if n.get('id', '').startswith('primer-segment-')]
        clusters = [n for n in out.iter() if n.get('id', '').startswith('cluster-')]
        self.assertEqual(len(overview), 2)
        self.assertEqual(len(clusters), 2)
        self.assertGreaterEqual(float(clusters[0].get('width')), 8)
        self.assertGreaterEqual(float(clusters[1].get('width')), 8)
        self.assertIn('分段局部窗', ''.join(n.text or '' for n in out.iter() if n.tag.endswith('}text')))

    def test_wrong_assembly_rejected(self):
        info = self.base / 'assembly_info.json'
        self.spec['assembly_info'] = str(info)
        info.write_text(json.dumps({'assemblies': [{'acc': 'GCF_000003025.6', 'units': [{'seq': [{'acc': 'NC_058371.1'}]}]}]}))
        with self.assertRaises(ValueError):
            self.load()
        info.write_text(json.dumps({'assemblies': [{'acc': 'GCF_018350175.1', 'units': [{'seq': [{'acc': 'NC_000001.1'}]}]}]}))
        self.spec['assembly_name'] = 'WrongAssemblyName'
        with self.assertRaises(ValueError):
            self.load()
        self.spec['assembly_name'] = gdv.read_json(STANDARD / 'spec.json')['assembly_name']
        info.write_text(json.dumps({'assemblies': [{'acc': 'GCF_018350175.1', 'units': [{'seq': []}]}]}))
        self.load()
        info.write_text(json.dumps({'assemblies': [{'acc': 'GCF_018350175.1', 'units': [{'seq': [{'acc': 'NC_058371.1'}]}]}]}))
        self.load()

    def test_banned_unavailable_and_wetlab_notes(self):
        self.spec['tracks'][5].update(status='unavailable', title='', evidence='该物种当前组装区间在 NCBI 数据库中未收录密集公共变异数据。')
        with self.assertRaises(ValueError):
            self.load()
        self.spec['tracks'][5].update(status='unavailable', title='', evidence='2026-09-12 NCBI disptracks 目录无 EVA/dbSNP 轨道。')
        self.spec['notes'] = ['在 58°C 下被酶促阻断']
        with self.assertRaises(ValueError):
            self.load()
        self.spec['notes'] = ['单外显子在位扩增 83 bp。']
        self.load()

    def test_available_empty_allows_missing_svg_title(self):
        self.spec['tracks'][4].update(
            status='available_empty',
            content_state='empty', content_evidence='本次导出未显示独立特征；空窗口声明待视觉复核。',
            title='RNA-seq intron features, aggregate (filtered), NCBI Mus musculus Annotation Release 109',
            evidence='目录有该轨道；本次导出 SVG 未画出独立特征。')
        self.load()

    def test_source_unverified_track_must_be_excluded_from_svg(self):
        track = self.spec['tracks'][2]
        track['status'] = 'source_unverified_excluded'
        track['evidence'] = '页面轨道来源组装未经核实，本次官方导出中已隐藏。'
        with self.assertRaisesRegex(ValueError, '必须从官方导出中排除'):
            self.load()
        root = ET.parse(STANDARD / 'CAT_1_official_tracks.svg').getroot()
        for parent in root.iter():
            for child in list(parent):
                if child.tag == f'{{{gdv.NS}}}text' and track['title'] in ''.join(child.itertext()):
                    parent.remove(child)
        svg = self.base / 'excluded.svg'
        ET.ElementTree(root).write(svg, encoding='utf-8', xml_declaration=True)
        self.spec['official_svg'] = str(svg)
        s, _ = self.load()
        self.assertEqual(s['tracks'][2]['status'], 'source_unverified_excluded')

    def test_html_remote_image_script_rejected(self):
        for content in ['<html>500 error</html>',
                        '<svg xmlns="http://www.w3.org/2000/svg"><image href="x.png"/></svg>',
                        '<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>',
                        '<svg xmlns="http://www.w3.org/2000/svg"><style>@import "https://x";</style></svg>']:
            f = self.base / 'bad.svg'; f.write_text(content)
            with self.assertRaises(ValueError): gdv.safe_svg(f)

    def test_title_replacement_must_be_exact(self):
        self.spec['export_title_to_remove'] = 'NC_058371.1:wrong'
        with self.assertRaises(ValueError): self.load()

    def test_titleless_export_requires_independent_matching_evidence(self):
        root = gdv.safe_svg(STANDARD / 'CAT_1_official_tracks.svg')
        for parent in root.iter():
            for child in list(parent):
                if child.tag == f'{{{gdv.NS}}}text' and ''.join(child.itertext()).startswith('NC_058371.1:'):
                    parent.remove(child)
        svg = self.base / 'titleless.svg'
        svg.write_bytes(ET.tostring(root, encoding='utf-8'))
        self.spec['official_svg'] = str(svg)
        self.spec.pop('export_title_to_remove', None)
        with self.assertRaisesRegex(ValueError, 'titleless_export'):
            self.load()
        capture = self.base / 'page-capture.md'
        capture.write_text('同次 GDV 页面与导出记录；测试夹具。')
        self.spec['titleless_export'] = {
            'page_url': self.original_url,
            'exported_at': '2026-09-24T10:00:00+08:00',
            'page_capture': capture.name,
            'official_svg_sha256': gdv.sha(svg),
            'ruler_labels': ['142,723,500', '142,724 K'],
            'identity_review': '页面核对组装、序列、窗口和 F/R。',
        }
        self.load()
        self.spec['titleless_export']['ruler_labels'][0] = '142,999,999'
        with self.assertRaises(ValueError): self.load()
        self.spec['titleless_export']['ruler_labels'][0] = '142,723,500'
        self.spec['titleless_export']['official_svg_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, '哈希'):
            self.load()

    def test_wrong_svg_title_rejected_even_with_titleless_evidence(self):
        root = gdv.safe_svg(STANDARD / 'CAT_1_official_tracks.svg')
        for node in root.iter():
            if node.tag == f'{{{gdv.NS}}}text' and ''.join(node.itertext()).startswith('NC_058371.1:'):
                node.text = node.text.replace('NC_058371.1:', 'NC_000001.1:')
        svg = self.base / 'wrong-title.svg'
        svg.write_bytes(ET.tostring(root, encoding='utf-8'))
        self.spec['official_svg'] = str(svg)
        (self.base / 'capture.md').write_text('Synthetic titleless mechanics fixture')
        self.spec['titleless_export'] = {'page_url': self.original_url, 'page_capture': 'capture.md'}
        with self.assertRaisesRegex(ValueError, '标题与目标序列'):
            self.load()

    def test_wrong_svg_title_window_rejected(self):
        root = gdv.safe_svg(STANDARD / 'CAT_1_official_tracks.svg')
        for node in root.iter():
            if node.tag == f'{{{gdv.NS}}}text' and ''.join(node.itertext()).startswith('NC_058371.1:'):
                node.text = node.text.replace('142723182..142727265', '142700000..142727265')
        svg = self.base / 'wrong-window.svg'
        svg.write_bytes(ET.tostring(root, encoding='utf-8'))
        self.spec['official_svg'] = str(svg)
        with self.assertRaisesRegex(ValueError, '标题窗口'):
            self.load()

    def test_output_protection_before_rendering(self):
        self.load(); p = self.base / 'spec.json'
        sentinel = self.base / 'keep.txt'; sentinel.write_text('keep')
        with self.assertRaises(ValueError): gdv.render(p, self.base)
        with self.assertRaises(ValueError): gdv.render(p, self.base / '1.原始资料' / 'new')
        link = self.base / 'linked'; link.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(ValueError): gdv.render(p, link / 'new')
        self.assertEqual(sentinel.read_text(), 'keep')
        self.assertFalse((self.base / 'new').exists())

    def test_standard_assets_unchanged(self):
        for filename, expected in gdv.read_json(STANDARD / 'sha256.json').items():
            self.assertEqual(gdv.sha(STANDARD / filename), expected)

    def test_frozen_refseq_has_gene_bar(self):
        root = ET.parse(STANDARD / 'CAT_1_official_tracks.svg').getroot()
        self.assertEqual(root.get('width'), '1094px')
        self.assertEqual(root.get('viewBox'), '0 0 1094 274')
        labels = [n for n in root.iter() if n.tag.endswith('}text') and (n.text or '').strip() == 'SOWAHB']
        self.assertTrue(any(n.get('fill') == '#ffffff' for n in labels))
        texts = [(n.get('y'), (n.text or '').strip()) for n in root.iter() if n.tag.endswith('}text')]
        xm = [y for y, t in texts if t == 'XM_011281731.4']
        xp = [y for y, t in texts if t == 'XP_011280033.1']
        self.assertTrue(xm and xp and xm[0] == xp[0])
        self.assertIn('exons', gdv.read_json(STANDARD / 'spec.json'))

    def cat_exons(self, **changes):
        data = {
            'transcript': 'XM_011281731.4',
            'gene': 'SOWAHB',
            'strand': '+',
            'source': 'NCBI Datasets product_report 2026-09-12',
            'intervals': [{'order': 1, 'start': 142723522, 'end': 142727185}],
        }
        data.update(changes)
        return data

    def test_exons_optional_and_single_overlap(self):
        self.spec.pop('exons', None)
        self.spec.pop('product_report', None)
        s, root = self.load()
        self.assertIsNone(s['_exons'])
        out = ET.fromstring(gdv.compose(s, root))
        self.assertFalse([n for n in out.iter() if (n.get('id') or '').startswith('exon-')])
        self.spec['exons'] = self.cat_exons()
        self.spec['product_report'] = 'product_report.json'
        s, root = self.load()
        out = ET.fromstring(gdv.compose(s, root))
        self.assertEqual(len([n for n in out.iter() if (n.get('id') or '') == 'exon-overview-1']), 1)
        self.assertIn('XM_011281731.4', ''.join(n.text or '' for n in out.iter() if n.tag.endswith('}text')))

    def test_exons_reject_zero_or_two_overlaps(self):
        self.spec['exons'] = self.cat_exons(intervals=[{'order': 1, 'start': 1, 'end': 20}])
        with self.assertRaises(ValueError):
            self.load()
        self.spec['exons'] = self.cat_exons(intervals=[
            {'order': 1, 'start': 142723522, 'end': 142727185},
            {'order': 2, 'start': 142725180, 'end': 142725270},
        ])
        with self.assertRaises(ValueError):
            self.load()

    def test_exons_split_intron_and_cluster(self):
        s, root = self.load()
        s['_markers'] = [
            {'start': 142723183, 'end': 142723202, 'label': 'F_ex5', 'color': '#ff0000'},
            {'start': 142727246, 'end': 142727265, 'label': 'R_ex6', 'color': '#2563eb'}]
        s['_exons'] = {
            'transcript': 'XM_011281731.4', 'gene': 'SOWAHB', 'strand': '+',
            'source': 'test',
            'intervals': [
                {'order': 5, 'start': 142723183, 'end': 142723220},
                {'order': 6, 'start': 142727230, 'end': 142727265},
            ],
        }
        out = ET.fromstring(gdv.compose(s, root))
        self.assertEqual(sorted(n.get('id') for n in out.iter() if (n.get('id') or '').startswith('exon-overview-')),
                         ['exon-overview-5', 'exon-overview-6'])
        self.assertTrue([n for n in out.iter() if (n.get('id') or '').startswith('exon-cluster-0-')])
        self.assertTrue([n for n in out.iter() if (n.get('id') or '').startswith('exon-cluster-1-')])
        titles = [n for n in out.iter() if n.tag.endswith('}text') and (n.text or '').startswith('局部 1')]
        exon_bar = next(n for n in out.iter() if n.get('id') == 'exon-cluster-0-5')
        self.assertGreater(float(exon_bar.get('y')), float(titles[0].get('y')) + 12)

    def relabel_markers(self, forward, reverse):
        url = self.original_url.replace('%7CF%7C', f'%7C{forward}%7C').replace('%7CR%7C', f'%7C{reverse}%7C')
        self.spec['source_url'] = url
        svg = (STANDARD / 'CAT_1_official_tracks.svg').read_bytes()
        svg = svg.replace(b'>F<', f'>{forward}<'.encode('utf-8')).replace(b'>R<', f'>{reverse}<'.encode('utf-8'))
        path = self.base / f'{forward}_{reverse}.svg'
        path.write_bytes(svg)
        self.spec['official_svg'] = str(path)

    def test_marker_display_only_changes_overview_text(self):
        self.spec['marker_display'] = {'F': 'F_ex1', 'R': 'R_ex1'}
        s, root = self.load()
        self.assertEqual([m['label'] for m in s['_markers']], ['F', 'R'])
        self.assertEqual([m['display'] for m in s['_markers']], ['F_ex1', 'R_ex1'])
        texts = ''.join(n.text or '' for n in ET.fromstring(gdv.compose(s, root)).iter() if n.tag.endswith('}text'))
        self.assertIn('F_ex1', texts)
        self.assertIn('R_ex1', texts)
        self.spec['marker_display'] = {'F_missing': 'F_ex1'}
        with self.assertRaises(ValueError):
            self.load()
        self.spec['marker_display'] = {'R_ex13': 'R_ex11'}
        self.spec['source_url'] = self.spec['source_url'].replace('%7CR%7C', '%7CR_ex13%7C')
        with self.assertRaisesRegex(ValueError, '不得把'):
            self.load()

    def test_exn_label_must_match_refseq_order(self):
        self.relabel_markers('F_ex1', 'R_ex1')
        s, _ = self.load()
        self.assertEqual([m['label'] for m in s['_markers']], ['F_ex1', 'R_ex1'])
        self.relabel_markers('F_ex11', 'R_ex13')
        with self.assertRaisesRegex(ValueError, '外显子号须等于落入外显子'):
            self.load()
        self.spec.pop('exons', None)
        self.relabel_markers('F_ex1', 'R_ex1')
        with self.assertRaisesRegex(ValueError, 'mk 或显示名含 exN 时必须填写 exons'):
            self.load()

    def test_inverted_track_order_reported_without_changing_official_svg(self):
        # Create a modified SVG where RNA-seq is placed above RefSeq
        svg_bytes = (STANDARD / 'CAT_1_official_tracks.svg').read_bytes()
        # In CAT_1, RefSeq y=41, RNA-seq coverage y=138.
        # Swap their y values: RefSeq -> y=300, RNA-seq -> y=41
        root = ET.fromstring(svg_bytes.replace(b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">', b''))
        for n in root.iter():
            if n.tag.endswith('}text'):
                txt = ''.join(n.itertext())
                if 'Genes, NCBI' in txt:
                    n.set('y', '300.0')
        bad_svg = self.base / 'bad_order.svg'
        bad_svg.write_bytes(ET.tostring(root, encoding='utf-8'))
        self.spec['official_svg'] = str(bad_svg)
        s, _ = self.load()
        self.assertTrue(s['_track_order_warnings'])
        self.assertIn('原件保持不变', s['_track_order_warnings'][0])

    def test_report_missing_wrong_version_accession_strand_and_one_bp(self):
        original = gdv.read_json(STANDARD / 'product_report.json')
        self.spec.pop('product_report')
        with self.assertRaisesRegex(ValueError, '必须提供 product_report'):
            self.load()
        self.spec['product_report'] = 'missing.json'
        with self.assertRaisesRegex(ValueError, '不存在'):
            self.load()
        self.spec['product_report'] = 'product_report.json'
        for kind in ('version', 'accession', 'strand', 'start', 'end', 'order', 'missing_exon', 'ambiguous'):
            with self.subTest(kind=kind):
                data = copy.deepcopy(original)
                transcript = data['reports'][0]['product']['transcripts'][0]
                loc = transcript['genomic_locations'][0]
                if kind == 'version': transcript['accession_version'] = 'XM_011281731.3'
                elif kind == 'accession': loc['genomic_accession_version'] = 'NC_058371.2'
                elif kind == 'strand': loc['genomic_range']['orientation'] = 'minus'
                elif kind == 'start': loc['exons'][0]['begin'] = '142723523'
                elif kind == 'end': loc['exons'][0]['end'] = '142727184'
                elif kind == 'order': loc['exons'][0]['order'] = 2
                elif kind == 'missing_exon': loc['exons'] = []
                else: transcript['genomic_locations'].append(copy.deepcopy(loc))
                # Query strings still contain the correct version; they must not select a record.
                (self.base / 'product_report.json').write_text(json.dumps(data))
                with self.assertRaises(ValueError): self.load()

    def test_report_multi_transcript_selects_exact_record(self):
        data = gdv.read_json(STANDARD / 'product_report.json')
        records = data['reports'][0]['product']['transcripts']
        other = copy.deepcopy(records[0])
        other['accession_version'] = 'XM_011281731.3'
        other['genomic_locations'][0]['exons'][0]['begin'] = '1'
        records.insert(0, other)
        (self.base / 'product_report.json').write_text(json.dumps(data))
        self.load()
        records.append(copy.deepcopy(records[1]))
        (self.base / 'product_report.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, '唯一匹配'): self.load()

    def test_track_content_contradiction_and_title_only(self):
        self.spec['tracks'][2]['content_state'] = 'empty'
        with self.assertRaisesRegex(ValueError, '矛盾'): self.load()
        self.spec['tracks'][2]['content_state'] = 'data'
        self.spec['tracks'][2]['content_evidence'] = self.spec['tracks'][2]['title']
        with self.assertRaisesRegex(ValueError, '内容证据'): self.load()

    def test_coordinate_observation_uses_actual_title(self):
        s, _ = self.load()
        self.assertEqual(s['_coordinate_observation']['delta_start_end'], [-1, 0])
        root = gdv.safe_svg(STANDARD / 'CAT_1_official_tracks.svg')
        for n in root.iter():
            if n.tag.endswith('}text') and (n.text or '').startswith('NC_058371.1:'):
                n.text = n.text.replace('142723182..142727265', '142723183..142727266')
        svg = self.base / 'end-plus-one.svg'
        svg.write_bytes(ET.tostring(root))
        self.spec['official_svg'] = str(svg)
        with self.assertRaisesRegex(ValueError, '标题窗口'): self.load()
        self.spec['export_title_to_remove'] = next(n.text for n in root.iter() if (n.text or '').startswith('NC_058371.1:'))
        self.spec['boundary_review'] = {'observed_range': [142723183, 142727266],
                                        'url_range': [142723183, 142727265], 'review': 'fixture: reviewed, no translation'}
        s, _ = self.load()
        self.assertEqual(s['_coordinate_observation']['delta_start_end'], [0, 1])
        self.assertEqual(s['_coordinate_observation']['coordinate_convention'], 'unknown')

    def test_primer_evidence_structure_hash_and_pending(self):
        s, _ = self.load()
        self.assertEqual(s['_marker_validation']['status'], 'pending')
        source = self.base / 'alignment.txt'
        source.write_text('Synthetic alignment provenance fixture; not a verified binding.')
        self.spec['primer_evidence'] = {
            'transcript': 'XM_011281731.4', 'genomic_accession': 'NC_058371.1',
            'source': {'kind': 'alignment', 'path': source.name, 'sha256': gdv.sha(source)},
            'primers': {'F': {'sequence': 'ACGT' * 5, 'segments': [{'label': 'F', 'start': 142725183, 'end': 142725202}]},
                        'R': {'sequence': 'TGCA' * 5, 'segments': [{'label': 'R', 'start': 142725246, 'end': 142725265}]}}}
        s, _ = self.load()
        self.assertEqual(s['_marker_validation']['status'], 'pending')
        self.assertEqual(s['_marker_validation']['provenance_structure'], 'matched')
        good = copy.deepcopy(self.spec['primer_evidence'])
        for kind in ('hash', 'version', 'endpoint', 'sequence', 'missing_R'):
            self.spec['primer_evidence'] = copy.deepcopy(good)
            evidence = self.spec['primer_evidence']
            if kind == 'hash': evidence['source']['sha256'] = '0' * 64
            elif kind == 'version': evidence['transcript'] = 'XM_011281731.3'
            elif kind == 'endpoint': evidence['primers']['F']['segments'][0]['end'] += 1
            elif kind == 'sequence': evidence['primers']['F']['sequence'] = ''
            else: evidence['primers'].pop('R')
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.load()

    def test_export_audit_and_notes_without_real_raster_rendering(self):
        self.load()
        # Stub converters: this tests provenance publishing, not PDF/PNG validity or vision.
        converter = SimpleNamespace(svg2pdf=lambda **kwargs: b'fixture-pdf',
                                    svg2png=lambda **kwargs: b'fixture-png')
        with patch.object(gdv, 'convert_svg', side_effect=lambda svg, format: b'fixture-' + format.encode()):
            out = gdv.render(self.base / 'spec.json', self.base.with_name(self.base.name + '-output'))
        audit = gdv.read_json(out / 'checks.json')
        self.assertEqual(audit['coordinate_observation']['delta_start_end'], [-1, 0])
        self.assertEqual(audit['marker_validation']['status'], 'pending')
        self.assertEqual(audit['track_content_review'], 'pending')
        self.assertEqual(audit['visual_review'], 'pending')
        self.assertEqual(audit['product_report_sha256'], gdv.sha(STANDARD / 'product_report.json'))
        notes = (out / 'source_notes.md').read_text()
        self.assertIn('142723182–142727265', notes)
        self.assertIn('142723183–142727265', notes)
        self.assertIn('不推断官方内部坐标约定', notes)
        self.assertEqual(gdv.sha(out / 'product_report.json'), gdv.sha(STANDARD / 'product_report.json'))

    def test_frozen_eva_manually_reviewed_empty_window(self):
        # Independent human review supplied this fact; no automatic feature detection.
        track = next(t for t in self.spec['tracks'] if t['role'] == 'variants')
        self.assertEqual(track['status'], 'available_empty')
        self.assertEqual(track['content_state'], 'empty')
        self.assertEqual(track['title'], 'EVA RefSNP Release 8')
        self.assertIn('未见', track['content_evidence'])
        self.assertIn('不是数据库无变异', track['content_evidence'])
        self.assertIn('不代表数据库或样本无变异', track['evidence'])
        self.load()

    def test_product_report_named_spec_json_roundtrips(self):
        evidence = self.base / 'evidence'
        evidence.mkdir()
        report = evidence / 'spec.json'
        report.write_bytes((STANDARD / 'product_report.json').read_bytes())
        self.spec['product_report'] = 'evidence/spec.json'
        self.load()
        converter = SimpleNamespace(svg2pdf=lambda **kwargs: b'fixture-pdf',
                                    svg2png=lambda **kwargs: b'fixture-png')
        with patch.object(gdv, 'convert_svg', side_effect=lambda svg, format: b'fixture-' + format.encode()):
            out = gdv.render(self.base / 'spec.json', self.base.with_name(self.base.name + '-roundtrip-output'))
        s, _ = gdv.load_spec(out / 'spec.json')
        self.assertEqual(s['product_report'], 'product_report.json')
        self.assertEqual(gdv.sha(out / s['product_report']), gdv.sha(report))

    def test_same_basename_evidence_files_roundtrip_without_collision(self):
        for folder in ('assembly', 'product', 'primer'):
            (self.base / folder).mkdir()
        assembly = self.base / 'assembly' / 'spec.json'
        assembly.write_text(json.dumps({'assemblies': [{'acc': 'GCF_018350175.1',
                            'units': [{'seq': [{'acc': 'NC_058371.1'}]}]}]}))
        report = self.base / 'product' / 'spec.json'
        report.write_bytes((STANDARD / 'product_report.json').read_bytes())
        primer = self.base / 'primer' / 'spec.json'
        primer.write_text(json.dumps({'fixture': 'Unverified primer provenance, not a binding result'}))
        self.spec['assembly_info'] = 'assembly/spec.json'
        self.spec['product_report'] = 'product/spec.json'
        self.spec['primer_evidence'] = {
            'transcript': 'XM_011281731.4', 'genomic_accession': 'NC_058371.1',
            'source': {'kind': 'report', 'path': 'primer/spec.json', 'sha256': gdv.sha(primer)},
            'primers': {'F': {'sequence': 'ACGT' * 5, 'segments': [{'label': 'F', 'start': 142725183, 'end': 142725202}]},
                        'R': {'sequence': 'TGCA' * 5, 'segments': [{'label': 'R', 'start': 142725246, 'end': 142725265}]}}}
        self.load()
        converter = SimpleNamespace(svg2pdf=lambda **kwargs: b'fixture-pdf',
                                    svg2png=lambda **kwargs: b'fixture-png')
        with patch.object(gdv, 'convert_svg', side_effect=lambda svg, format: b'fixture-' + format.encode()):
            out = gdv.render(self.base / 'spec.json', self.base.with_name(self.base.name + '-same-basename-output'))
        s, _ = gdv.load_spec(out / 'spec.json')
        self.assertEqual(s['assembly_info'], 'assembly_info.json')
        self.assertEqual(s['product_report'], 'product_report.json')
        self.assertEqual(s['primer_evidence']['source']['path'], 'primer_evidence_source.json')
        for source, name in ((assembly, 'assembly_info.json'), (report, 'product_report.json'),
                             (primer, 'primer_evidence_source.json')):
            self.assertEqual(gdv.sha(out / name), gdv.sha(source))
        self.assertEqual(s['_marker_validation']['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
