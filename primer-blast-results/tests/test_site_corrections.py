"""Narrow Oracle M1/M2/M3 and GDV boundary regressions against real archive facts."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_site as site
import prepare_site_archive as adapter
import history_policy as history
import gdv_delivery as gdv
from evidence import sha256, safe_file
from test_build_site import subset

REAL = Path('/home/qi/文档/课题实验/4.知识库/01.检测体系准备/PCR与凝胶初筛/结果汇总/primer-blast')
NEW = Path('/home/qi/文档/课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14/离线站点/project-config-A-v2')
ASSETS = Path(__file__).resolve().parents[1] / 'assets'


@unittest.skipUnless(REAL.is_dir() and NEW.is_dir(), 'real corrected config unavailable')
class Corrections(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='site-corrections-', dir='/tmp/opencode'))

    def test_M1_real_registered_4000_echo_2000_preserved_and_policy_required(self):
        status_raw = (REAL / 'status.json').read_bytes()
        old = next(q for q in json.loads(status_raw)['queries'] if q['assay']=='RAT_1' and q['species_code']=='SHE' and q['dataset']=='gDNA')
        text = (REAL / old['report_path']).read_text('utf-8-sig')
        registration = dict(path='status.json', sha256=sha256(status_raw))
        hp = history.declaration(old, text, registration)
        self.assertEqual(hp['registered_parameters']['PRIMER_PRODUCT_MAX'], '4000')
        self.assertEqual(hp['returned_parameters']['PRIMER_PRODUCT_MAX'], ['2000'])
        self.assertEqual(hp['conflicts'], ['PRIMER_PRODUCT_MAX'])
        q = dict(old, parameters=history.selected_parameters(old), parameter_policy=hp)
        self.assertEqual(history.validate(q, text, status_raw)['status'], 'conflict')
        with self.assertRaises(ValueError):
            site.site_binding(text, q['parameters'])
        q['parameters']['PRIMER_PRODUCT_MAX'] = '2000'
        with self.assertRaises(ValueError):
            history.validate(q, text, status_raw)

    def test_M2_real_mixed_all_pending_absent_target_visible_text(self):
        path, m = subset(NEW, self.base / 'mixed')
        out = site.build(path, self.base / 'mixed-run')
        text = (out / 'index.html').read_text()
        pending = [q for d in m['datasets'] for q in d['queries'] if q['provenance']=='reconstructed_display_no_raw_response']
        self.assertIn('历史无产物登记但来源 pending：'+str(len(pending)), text)
        self.assertIn('未包含该目标查询', text)
        self.assertIn('82、52 bp', text)
        self.assertIn('96 bp', text)
        self.assertNotIn('已完成检索未报告产物', text)
        for q in pending:
            self.assertIn('data-pending-query="'+q['id']+'"', text)
            self.assertIn('href="'+q['result_page']+'"', text)
        # All-pending real B slice (no invented scientific result).
        mrna = m['datasets'][1]
        mrna['assays'] = ['DUK_1']
        mrna['species'] = [s for s in mrna['species'] if s['code']=='RAT']
        mrna['queries'] = [q for q in mrna['queries'] if q['assay']=='DUK_1' and q['species_code']=='RAT']
        m['datasets'], m['primer_rows'] = [mrna], ['DUK_1']
        m['gdv'] = [g for g in m['gdv'] if g['id']=='DUK_1']
        path.write_text(json.dumps(m))
        out = site.build(path, self.base / 'all-pending-run')
        text = (out / 'index.html').read_text()
        self.assertIn('历史无产物登记但来源 pending：1', text)
        self.assertIn('未包含该目标查询', text)
        self.assertIn('历史登记无产物 · pending', text)
        self.assertNotIn('已完成检索未报告产物', text)

    def test_M3_adapter_write_roots_parent_file_overlap_symlink_zero_writes(self):
        f = self.base / 'parent-file'
        f.write_bytes(b'keep')
        link = self.base / 'link'
        link.symlink_to(REAL, target_is_directory=True)
        cases = [(REAL/'new-assets', self.base/'o1', False),
                 (self.base/'a2', self.base/'a2'/'nested', False),
                 (f/'assets', self.base/'o3', False),
                 (self.base/'a4', f/'out', False),
                 (link/'assets', self.base/'o5', False),
                 (ASSETS, self.base/'o6', False)]
        for assets, out, reuse in cases:
            with self.subTest(assets=str(assets)), self.assertRaises(ValueError):
                adapter.prepare(REAL, out, assets, reuse)
            self.assertFalse(out.exists())
            if not str(assets).startswith(str(REAL)) and assets != ASSETS and not assets.is_relative_to(link):
                self.assertFalse(assets.exists())
        self.assertEqual(f.read_bytes(), b'keep')

    def test_M3_adapter_duplicate_and_reuse_mismatch_zero_writes(self):
        raw_status = json.loads((REAL/'status.json').read_text())
        raw_status['queries'].append(copy.deepcopy(raw_status['queries'][0]))
        duplicate = self.base/'duplicate.json'
        duplicate.write_text(json.dumps(raw_status))
        def source(root, rel):
            return duplicate if rel=='status.json' else safe_file(root, rel)
        with patch.object(adapter, 'safe_file', side_effect=source), self.assertRaises(ValueError):
            adapter.prepare(REAL, self.base/'duplicate-out', self.base/'duplicate-assets')
        self.assertFalse((self.base/'duplicate-out').exists())
        self.assertFalse((self.base/'duplicate-assets').exists())
        # A different declared key must not hide duplicate matrix/output identity.
        raw_status['queries'][-1]['key'] += '|different-key'
        duplicate.write_text(json.dumps(raw_status))
        with patch.object(adapter, 'safe_file', side_effect=source), self.assertRaises(ValueError):
            adapter.prepare(REAL, self.base/'duplicate-page-out', self.base/'duplicate-page-assets')
        self.assertFalse((self.base/'duplicate-page-out').exists())
        self.assertFalse((self.base/'duplicate-page-assets').exists())
        bad = self.base/'bad-assets'
        bad.mkdir()
        (bad/'site.css').write_text('mismatch')
        with self.assertRaises(ValueError):
            adapter.prepare(REAL, self.base/'reuse-out', bad, True)
        self.assertFalse((self.base/'reuse-out').exists())
        self.assertEqual((bad/'site.css').read_text(), 'mismatch')

    def test_QA_only_old_navigation_removed_scientific_fields_kept(self):
        for rel in ('01.成对Primer-BLAST/gDNA/RAT_1/RAT_1_target.html', '01.成对Primer-BLAST/mRNA/SHE_1/SHE_1_on_CHK.html'):
            text = (REAL/rel).read_text('utf-8-sig')
            before = sha256((REAL/rel).read_bytes())
            stripped = site.strip_legacy_navigation(text)
            self.assertNotIn('复现归档结果', stripped)
            self.assertNotIn('自动出结果', stripped)
            from evidence import parse_products
            self.assertEqual(parse_products(text), parse_products(stripped))
            import re
            self.assertEqual(re.findall(r'<pre\b[^>]*>[\s\S]*?</pre>', text), re.findall(r'<pre\b[^>]*>[\s\S]*?</pre>', stripped))
            self.assertEqual(sha256((REAL/rel).read_bytes()), before)

    def test_GDV_duplicate_ID_and_active_external_SVG_rejected(self):
        with self.assertRaises(ValueError):
            gdv.unique_ids([{'id':'T'}, {'id':'T'}])
        for raw in (b'<svg><script/></svg>', b'<svg onload="x()"/>', b'<svg><image href="https://example.invalid/a.png"/></svg>', b'<svg><image href="relative.png"/></svg>', b'<svg><style>@import "x.css"</style></svg>', b'<svg><style>&#64;import "x.css"</style></svg>', b'<svg><style>rect{fill:u\\72l(http://example.invalid/a)}</style></svg>', b'<svg xml:base="http://example.invalid/"><use href="#p"/></svg>'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                gdv.static_svg(raw)
        gdv.static_svg(b'<svg><defs><path id="p"/></defs><use href="#p"/></svg>')

    def test_GDV_builder_full_ID_mode_hash_metadata_and_pending_contract(self):
        path, m = subset(NEW, self.base/'gdv-config')
        sr = self.base/'gdv-input'
        sr.mkdir()
        gm = {'gdv': copy.deepcopy(m['gdv'])}
        for g in gm['gdv']:
            g['mode'] = 'rendered'
            for record in [g['spec'], g['product_report']] + [r['input'] for r in g['resources']]:
                dest = sr / record['path']
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((path.parent/record['path']).read_bytes())
        cases = []
        def case(change):
            value=copy.deepcopy(gm)
            change(value)
            cases.append(value)
        case(lambda v: v['gdv'].append(copy.deepcopy(v['gdv'][0])))
        case(lambda v: v['gdv'].pop())
        case(lambda v: v['gdv'][0].update(mode='archive_copy'))
        case(lambda v: v['gdv'][0]['resources'][0]['input'].update(sha256='0'*64))
        case(lambda v: v['gdv'][0]['metadata'].update(organism='conflict'))
        case(lambda v: v['gdv'][0].update(marker_validation='passed'))
        for i, value in enumerate(cases):
            (sr/'site-resources.json').write_text(json.dumps(value))
            out=self.base/('gdv-bad-'+str(i))
            with self.subTest(i=i), self.assertRaises(ValueError):
                site.build(path,out,sr)
            self.assertFalse(out.exists())
        (sr/'site-resources.json').write_text(json.dumps(gm))
        out=site.build(path,self.base/'gdv-good',sr)
        final=json.loads((out/'finalspec.json').read_text())
        self.assertTrue(all(g['marker_validation']=='pending' and g['scientific_binding_review']=='pending_Oracle' for g in final['gdv']))


if __name__ == '__main__':
    unittest.main()
