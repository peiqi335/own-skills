"""Narrow full-site preflight, real subset and failure mechanism regression."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_site as site
import verify_site as verify
from evidence import sha256, parameters

CONFIG = Path('/home/qi/文档/课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14/离线站点/project-config')


def subset(config, dest):
    m = json.loads((config / 'manifest.json').read_text())
    for d in m['datasets']:
        d['assays'] = [a for a in ('SHE_1', 'RAT_1', 'DUK_1') if a in d['assays']]
        d['species'] = [next(s for s in d['species'] if s['code'] == c) for c in ('RAT', 'CHK', 'DUK')]
        d['queries'] = [q for q in d['queries'] if q['assay'] in d['assays'] and q['species_code'] in ('RAT', 'CHK', 'DUK')]
    m['primer_rows'] = ['SHE_1', 'RAT_1', 'DUK_1']
    m['gdv'] = [g for g in m['gdv'] if g['id'] in m['primer_rows']]
    m['blast_xml'] = [x for x in m['blast_xml'] if x['id'] in ('RAT_1_RAT_amp', 'SHE_1_on_CHK_F', 'DUK_1_DUK_R')]
    m['historical_inputs'], m['provenance_inputs'] = [], []
    def archive_records(v):
        if isinstance(v, dict):
            if 'path' in v and 'sha256' in v:
                yield v
            else:
                for value in v.values():
                    yield from archive_records(value)
        elif isinstance(v, list):
            for value in v:
                yield from archive_records(value)
    dest.mkdir()
    for r in archive_records(m):
        p = dest / r['path']
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((config / r['path']).read_bytes())
    path = dest / 'manifest.json'
    path.write_text(json.dumps(m, ensure_ascii=False, indent=2) + '\n')
    return path, m


@unittest.skipUnless((CONFIG / 'manifest.json').is_file(), 'real project archive unavailable')
class SiteTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='full-site-', dir='/tmp/opencode'))
        self.path, self.m = subset(CONFIG, self.base / 'config')

    def test_real_reordered_subset_two_builds(self):
        a = site.build(self.path, self.base / 'a')
        b = site.build(self.path, self.base / 'b')
        result = verify.verify(a, b)
        self.assertTrue(result['byte_comparison']['identical'])
        self.assertEqual(len(result['structure']['primer_mapping']), 15)
        self.assertEqual(len(result['structure']['xml_fields']), 3)
        self.assertTrue(any(len(q['products']) > 1 for d in self.m['datasets'] for q in d['queries']))
        self.assertTrue(any(q['provenance'] == 'reconstructed_display_no_raw_response' for d in self.m['datasets'] for q in d['queries']))

    def test_preflight_failures_zero_writes(self):
        cases = []
        def case(change):
            m = copy.deepcopy(self.m)
            change(m)
            cases.append(m)
        case(lambda m: m['datasets'][0]['queries'].append(copy.deepcopy(m['datasets'][0]['queries'][0])))
        case(lambda m: m['datasets'][0]['queries'][0].update(forward='AAAA'))
        case(lambda m: m['datasets'][0]['queries'][0].update(result_page='../escape.html'))
        case(lambda m: m['datasets'][0]['queries'][0].update(result_page=m['datasets'][0]['index']))
        case(lambda m: m['datasets'][0]['queries'][0]['display_input'].update(sha256='0'*64))
        case(lambda m: m['datasets'][0]['queries'][0].update(products=[{'template_accession': 'NC_000001.1', 'length_bp': 999}]))
        case(lambda m: m['datasets'][0]['species'].append(m['datasets'][0]['species'][0]))
        for i, m in enumerate(cases):
            self.path.write_text(json.dumps(m))
            out = self.base / ('bad-' + str(i))
            with self.subTest(i=i), self.assertRaises(ValueError):
                site.build(self.path, out)
            self.assertFalse(out.exists())
        self.path.write_text(json.dumps(self.m))
        with self.assertRaises(ValueError):
            site.build(self.path, self.path.parent / 'overlap')
        link = self.base / 'link'
        link.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            site.build(link / 'manifest.json', self.base / 'symlink-out')
        out = self.base / 'existing'
        out.mkdir()
        (out / 'keep').write_bytes(b'unchanged')
        with self.assertRaises(ValueError):
            site.build(self.path, out)
        self.assertEqual((out / 'keep').read_bytes(), b'unchanged')

    def test_synthetic_failure_is_not_negative_and_raw_conflict_rejected(self):
        m = copy.deepcopy(self.m)
        q = m['datasets'][0]['queries'][0]
        raw = b'<html><head></head><body>Error: request failed</body></html>'
        p = self.path.parent / 'failure.html'
        p.write_bytes(raw)
        q.update(display_input={'path': 'failure.html', 'sha256': sha256(raw)}, status='error', products=[], parse_status='ok', provenance='synthetic_mechanism_only')
        self.path.write_text(json.dumps(m))
        out = site.build(self.path, self.base / 'failure')
        self.assertIn('待核：error', (out / q['result_page']).read_text())
        q['raw_response'] = self.m['datasets'][0]['queries'][0]['display_input']
        self.path.write_text(json.dumps(m))
        with self.assertRaises(ValueError):
            site.build(self.path, self.base / 'raw-conflict')
        self.assertFalse((self.base / 'raw-conflict').exists())


if __name__ == '__main__':
    unittest.main()
