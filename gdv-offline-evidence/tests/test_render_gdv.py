import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import render_gdv as gdv
STANDARD = ROOT / 'assets/cat1-standard'


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gdv-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.spec = gdv.read_json(STANDARD / 'spec.json')
        self.original_url = self.spec['source_url']
        for key in ['official_svg', 'chromosome_metadata']:
            self.spec[key] = str(STANDARD / self.spec[key])

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
            title='RNA-seq intron features, aggregate (filtered), NCBI Mus musculus Annotation Release 109',
            evidence='目录有该轨道；本次导出 SVG 未画出独立特征。')
        self.load()

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
        s, root = self.load()
        self.assertIsNone(s['_exons'])
        out = ET.fromstring(gdv.compose(s, root))
        self.assertFalse([n for n in out.iter() if (n.get('id') or '').startswith('exon-')])
        self.spec['exons'] = self.cat_exons()
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

    def test_inverted_track_order_rejected(self):
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
        with self.assertRaises(ValueError) as ctx:
            self.load()
        self.assertIn('官方 SVG 轨道顺序倒挂', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
