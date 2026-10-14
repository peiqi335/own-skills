"""Real Cairo security counterexamples; mutated copies are not new experiments."""
import base64
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import render_gdv as gdv
import batch_replay as batch
STANDARD = ROOT / 'assets/cat1-standard'
PROJECT = Path('/home/qi/文档/课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14/GDV')


class Oracle5Tests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir='/tmp/opencode', prefix='gdv-oracle5-'))
        self.evidence = self.base / 'evidence'; self.evidence.mkdir()
        for p in STANDARD.iterdir():
            if p.is_file(): (self.evidence / p.name).write_bytes(p.read_bytes())
        self.spec = self.evidence / 'spec.json'
        self.out = self.base / 'new'
        gdv.write_json(self.evidence / 'source.json', {'loci': [{'locus': 'CAT_1', 'revised_spec': 'spec.json', 'original_spec': 'old.json'}]})
        (self.evidence / 'old.json').write_bytes(self.spec.read_bytes())
        self.config = self.base / 'config.json'
        gdv.write_json(self.config, {'source_manifest': 'evidence/source.json'})

    def cli(self, path, *extra):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/render_gdv.py'), str(path), '--input-root', str(self.base), '-o', str(self.out), *extra], capture_output=True, text=True)

    def test_M1_real_cairo_escaped_import_fetch_denied_before_io(self):
        from cairosvg.parser import Tree
        from cairosvg.surface import PNGSurface
        raw = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><style>@\\69mport "https://invalid.example/escape.css";</style><rect width="10" height="10"/></svg>'
        calls = []
        def spy(url, kind):
            calls.append((url, kind)); return gdv.offline_fetch(url, kind)
        with patch('cairosvg.url.urlopen', side_effect=AssertionError('I/O forbidden')) as io_spy:
            with self.assertRaises(ValueError): Tree(bytestring=raw, url_fetcher=spy)
            self.assertEqual(len(calls), 1)
            self.assertIn('https://invalid.example/', calls[0][0])
            self.assertEqual(io_spy.call_count, 0)
            with self.assertRaises(ValueError): PNGSurface.convert(bytestring=raw, url_fetcher=spy)
            with self.assertRaises(ValueError): gdv.convert_svg(raw, 'png')
            self.assertEqual(io_spy.call_count, 0)
        for value in (b'@\\69mport "file:///etc/passwd";', b'@font-face { src:url("https://invalid/font"); }', b'rect {fill:u\\72l("file:///etc/passwd")}'):
            with self.subTest(css=value), self.assertRaises(ValueError):
                gdv.safe_svg_bytes(raw.replace(b'@\\69mport "https://invalid.example/escape.css";', value))
        svg = self.evidence / 'CAT_1_official_tracks.svg'
        svg.write_bytes(svg.read_bytes().replace(b'</svg>', b'<style>@\\69mport "https://invalid.example/escape.css";</style></svg>'))
        with self.assertRaises(ValueError): gdv.render(self.spec, self.out)
        self.assertFalse(self.out.exists())

    def test_M1_fragments_and_known_raster_data_not_active_svg(self):
        from PIL import Image
        png = io.BytesIO(); Image.new('RGB', (2, 2), 'red').save(png, format='PNG')
        uri = 'data:image/png;base64,' + base64.b64encode(png.getvalue()).decode()
        raw = f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><defs><linearGradient id="g"><stop offset="0" stop-color="red"/></linearGradient></defs><rect width="10" height="10" fill="url(#g)"/><image href="{uri}" width="2" height="2"/></svg>'.encode()
        self.assertTrue(gdv.convert_svg(raw, 'png').startswith(b'\x89PNG'))
        evil = 'data:image/svg+xml;base64,' + base64.b64encode(b'<svg><script/></svg>').decode()
        with self.assertRaises(ValueError): gdv.convert_svg(raw.replace(uri.encode(), evil.encode()), 'png')
        for url in ('https://invalid/resource', 'file:///etc/passwd', '/etc/passwd', evil):
            with self.assertRaises(ValueError): gdv.offline_fetch(url, 'image/svg+xml')

    def test_M2_CAT_exact_version_rejects_40_copy(self):
        svg = self.evidence / 'CAT_1_official_tracks.svg'
        raw = svg.read_bytes(); self.assertIn(b'XM_011281731.4', raw)
        svg.write_bytes(raw.replace(b'XM_011281731.4', b'XM_011281731.40'))
        with self.assertRaisesRegex(ValueError, '精确版本'): gdv.load_spec(self.spec)
        self.assertEqual(self.cli(self.spec, '--validate-only').returncode, 1)
        self.assertFalse(self.out.exists())

    def test_M3_direct_API_CLI_lexical_symlink_and_nested_output(self):
        link = self.base / 'link'; link.symlink_to(self.evidence, target_is_directory=True)
        disguised = link / '../evidence/spec.json'
        with self.assertRaisesRegex(ValueError, 'symlink'): gdv.load_spec(disguised, input_root=self.base)
        for path in (link / 'spec.json', disguised):
            with self.assertRaises(ValueError): gdv.render(path, self.out, input_root=self.base)
            for mode in ((), ('--validate-only',)):
                self.assertEqual(self.cli(path, *mode).returncode, 1)
        nested = self.evidence / 'nested/new'
        with self.assertRaisesRegex(ValueError, 'alias'): gdv.render(self.spec, nested)
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/render_gdv.py'), str(self.spec), '-o', str(nested), '--validate-only'], capture_output=True)
        self.assertEqual(process.returncode, 1); self.assertFalse(nested.exists())

    def test_M3_evidence_link_escape_and_explicit_input_root(self):
        spec = gdv.read_json(self.spec)
        (self.evidence / 'linked.svg').symlink_to(self.evidence / spec['official_svg'])
        spec['official_svg'] = 'linked.svg'; gdv.write_json(self.spec, spec)
        with self.assertRaisesRegex(ValueError, 'symlink'): gdv.load_spec(self.spec)
        with self.assertRaises(ValueError): batch.preflight(self.base, self.config, self.out)
        spec['official_svg'] = '../outside.svg'
        (self.base / 'outside.svg').write_bytes((STANDARD / 'CAT_1_official_tracks.svg').read_bytes())
        gdv.write_json(self.spec, spec)
        with self.assertRaisesRegex(ValueError, '逃逸'): gdv.load_spec(self.spec)
        gdv.load_spec(self.spec, input_root=self.base)
        with self.assertRaisesRegex(ValueError, 'input-root'): gdv.load_spec(self.spec, input_root=self.evidence / 'not-existing')
        self.assertFalse(self.out.exists())

    def test_M4_bad_originals_fail_whole_batch_before_mkdir(self):
        for value in (b'{invalid', b'{}', b'{"tracks":[1]}', json.dumps({'tracks': [dict(t, evidence=[]) for t in gdv.read_json(self.spec)['tracks']]}).encode()):
            (self.evidence / 'old.json').write_bytes(value)
            before = sorted(str(p.relative_to(self.base)) for p in self.base.rglob('*'))
            with self.assertRaises(ValueError): batch.run(self.base, self.config, self.out)
            self.assertEqual(before, sorted(str(p.relative_to(self.base)) for p in self.base.rglob('*')))
            process = subprocess.run([sys.executable, str(ROOT / 'scripts/batch_replay.py'), '--repo', str(self.base), '--manifest', str(self.config), '--output', str(self.out), '--validate-only'], capture_output=True)
            self.assertEqual(process.returncode, 1); self.assertFalse(self.out.exists())

    def test_M5_endpoint_links_use_checked_repo_base_keep_values(self):
        report = self.base / 'report.html'; report.write_text('archived evidence')
        manifest = gdv.read_json(self.evidence / 'source.json')
        original = {'locus': 'CAT_1', 'gdv_R_tx_interval': [1, 2], 'mRNA_report_R_tx_interval': [3, 4], 'mRNA_report_path': '../report.html'}
        manifest['endpoint_discrepancies'] = [original]
        gdv.write_json(self.evidence / 'source.json', manifest)
        result = batch.preflight(self.base, self.config, self.out)
        endpoint = result[3]['endpoint_discrepancies'][0]
        self.assertEqual(endpoint['mRNA_report_path'], 'report.html')
        self.assertEqual(endpoint['path_base'], 'repository_root')
        self.assertEqual(endpoint['mRNA_report_sha256'], gdv.sha(report))
        self.assertEqual(endpoint['gdv_R_tx_interval'], original['gdv_R_tx_interval'])
        self.assertEqual(endpoint['scientific_review'], 'pending_not_verified')
        self.assertFalse(self.out.exists())

    def test_recognized_1700_and_default_no_visual_change(self):
        from PIL import Image
        legacy = PROJECT / 'replay-final-03/run-01/CAT_1'
        s, raw = gdv.load_spec(legacy / 'spec.json')
        svg = gdv.compose(s, raw)
        self.assertEqual(svg, (legacy / 'CAT_1_enhanced.svg').read_bytes())
        with Image.open(io.BytesIO(gdv.convert_svg(svg, 'png'))) as current, Image.open(legacy / 'CAT_1_enhanced.png') as old:
            self.assertEqual(current.convert('RGBA').tobytes(), old.convert('RGBA').tobytes())
        profile = gdv.load_profile(ROOT / 'assets/recognized-standard-profile.json')
        recognized = ET.fromstring(gdv.compose(s, raw, profile))
        self.assertEqual(recognized.get('width'), '1700')
        self.assertEqual(raw.get('viewBox'), gdv.load_spec(legacy / 'spec.json')[1].get('viewBox'))
        for value in (True, 999, 10001, float('nan'), 1700.5):
            bad = copy.deepcopy(profile); bad['width']['canvas_width'] = value
            with self.assertRaises(ValueError): gdv.validate_profile(bad)


if __name__ == '__main__': unittest.main()
