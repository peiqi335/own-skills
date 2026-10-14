import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import render_gdv as gdv
import batch_replay as batch


class ProfileTests(unittest.TestCase):
    def test_complete_finite_contract_all_api_paths(self):
        s, raw = gdv.load_spec(ROOT / 'assets/cat1-standard/spec.json')
        good = gdv.load_profile()
        bad_profiles = [None, [], {}, dict(good, extra=1), dict(good, schema_version=True)]
        for key in ('width', 'font_sizes', 'colors'):
            p = copy.deepcopy(good); p[key] = []; bad_profiles.append(p)
            p = copy.deepcopy(good); p[key].pop(next(iter(p[key]))); bad_profiles.append(p)
        for value in (True, float('nan'), float('inf'), -1, 0, 125, 127):
            p = copy.deepcopy(good); p['width']['padding'] = value; bad_profiles.append(p)
        for value in (True, float('nan'), float('inf'), 0, 129):
            p = copy.deepcopy(good); p['font_sizes']['13'] = value; bad_profiles.append(p)
        p = copy.deepcopy(good); p['colors']['white'] = 'url(https://example.com)'; bad_profiles.append(p)
        p = copy.deepcopy(good); p['font_family'] = '@import'; bad_profiles.append(p)
        for p in bad_profiles:
            with self.subTest(profile=p), self.assertRaises(ValueError): gdv.validate_profile(p)
            if p is not None and isinstance(p, dict):
                with self.assertRaises(ValueError): gdv.compose(s, raw, p)
                with self.assertRaises(ValueError): gdv.render('not-existing.json', '/tmp/opencode/not-created', p)
        self.assertEqual(gdv.compose(s, raw), gdv.compose(s, raw, good))

    def test_cli_validate_only_checks_profile(self):
        base = Path(tempfile.mkdtemp(dir='/tmp/opencode', prefix='gdv-profile-test-'))
        path = base / 'bad.json'
        profile = gdv.load_profile(); profile['width']['padding'] = 127
        gdv.write_json(path, profile)
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/render_gdv.py'), str(ROOT / 'assets/cat1-standard/spec.json'), '--validate-only', '--profile', str(path)], capture_output=True, text=True)
        self.assertEqual(process.returncode, 1)
        self.assertIn('width.padding', process.stderr)

    def test_real_finalspec_and_no_source_mutation(self):
        # No converters mocked: a real PDF, PNG, and finalspec recompose.
        try: import cairosvg
        except ImportError: self.skipTest('CairoSVG required for real integration')
        base = Path(tempfile.mkdtemp(dir='/tmp/opencode', prefix='gdv-finalspec-test-'))
        out = gdv.render(ROOT / 'assets/cat1-standard/spec.json', base / 'out')
        s, raw = gdv.load_spec(out / 'spec.json')
        self.assertEqual(gdv.compose(s, raw, out / 'render_profile.json'), (out / 'CAT_1_enhanced.svg').read_bytes())
        self.assertTrue((out / 'CAT_1_enhanced.pdf').read_bytes().startswith(b'%PDF'))
        self.assertTrue((out / 'CAT_1_enhanced.png').read_bytes().startswith(b'\x89PNG'))
        checks = gdv.read_json(out / 'checks.json')
        self.assertEqual(checks['finalspec_sha256'], gdv.sha(out / 'spec.json'))
        self.assertEqual(checks['profile_sha256'], gdv.sha(out / 'render_profile.json'))
        env = gdv.read_json(out / 'environment.json')
        self.assertNotEqual(env['dependencies']['CairoSVG'], 'unavailable')
        self.assertTrue(env['libraries']['cairo']['loaded_files'])
        self.assertTrue(env['font_resolution'])


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir='/tmp/opencode', prefix='gdv-batch-test-'))
        evidence = self.base / 'evidence'; evidence.mkdir()
        for path in (ROOT / 'assets/cat1-standard').iterdir():
            if path.is_file(): (evidence / path.name).write_bytes(path.read_bytes())
        (evidence / 'revised.json').write_bytes((evidence / 'spec.json').read_bytes())
        self.manifest = evidence / 'manifest.json'
        gdv.write_json(self.manifest, {'loci': [{'locus': 'CAT_1', 'revised_spec': 'revised.json', 'original_spec': 'spec.json'}]})
        self.config = self.base / 'config.json'
        gdv.write_json(self.config, {'source_manifest': 'evidence/manifest.json'})

    def test_preflight_no_writes_and_duplicate_id(self):
        output = self.base / 'new'
        self.assertEqual(len(batch.preflight(self.base, self.config, output)[4]), 1)
        self.assertFalse(output.exists())
        manifest = gdv.read_json(self.manifest); manifest['loci'] *= 2; gdv.write_json(self.manifest, manifest)
        with self.assertRaisesRegex(ValueError, '重复'): batch.preflight(self.base, self.config, output)
        self.assertFalse(output.exists())

    def test_existing_symlink_escape_and_source_alias(self):
        with self.assertRaisesRegex(ValueError, '新目录'): batch.preflight(self.base, self.config, self.base / 'evidence')
        link = self.base / 'link'; link.symlink_to(self.base / 'evidence', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'): batch.preflight(self.base, self.config, link / 'new')
        gdv.write_json(self.config, {'source_manifest': '../escape/manifest.json'})
        with self.assertRaisesRegex(ValueError, '逃逸'): batch.preflight(self.base, self.config, self.base / 'new')

    def test_unique_id_cannot_reuse_same_official_source(self):
        # Synthetic alias fixture, not a DOG scientific configuration.
        second = gdv.read_json(self.base / 'evidence/revised.json')
        second['locus_id'] = 'DOG_SYNTHETIC'
        gdv.write_json(self.base / 'evidence/second.json', second)
        manifest = gdv.read_json(self.manifest)
        manifest['loci'].append({'locus': 'DOG_SYNTHETIC', 'revised_spec': 'second.json', 'original_spec': 'spec.json'})
        gdv.write_json(self.manifest, manifest)
        with self.assertRaisesRegex(ValueError, 'alias'): batch.preflight(self.base, self.config, self.base / 'new')
        self.assertFalse((self.base / 'new').exists())

    def test_late_input_failure_run_adds_zero_files(self):
        manifest = gdv.read_json(self.manifest)
        manifest['loci'].append({'locus': 'MISSING', 'revised_spec': 'missing.json', 'original_spec': 'spec.json'})
        gdv.write_json(self.manifest, manifest)
        before = sorted(str(p.relative_to(self.base)) for p in self.base.rglob('*'))
        with self.assertRaises(OSError): batch.run(self.base, self.config, self.base / 'new')
        self.assertEqual(before, sorted(str(p.relative_to(self.base)) for p in self.base.rglob('*')))

    def test_source_directory_destination_alias_and_output_escape(self):
        with self.assertRaisesRegex(ValueError, 'alias'):
            batch.preflight(self.base, self.config, self.base / 'evidence/new')
        with self.assertRaisesRegex(ValueError, '逃逸'):
            batch.preflight(self.base, self.config, self.base.parent / 'outside')

    def test_declared_evidence_symlink_not_hidden_by_resolve(self):
        evidence = self.base / 'evidence'
        (evidence / 'linked.svg').symlink_to(evidence / 'CAT_1_official_tracks.svg')
        spec = gdv.read_json(evidence / 'revised.json'); spec['official_svg'] = 'linked.svg'
        gdv.write_json(evidence / 'revised.json', spec)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            batch.preflight(self.base, self.config, self.base / 'new')
        self.assertFalse((self.base / 'new').exists())

    def test_new_input_drives_output_not_locus_template(self):
        # Synthetic contract exercise, explicitly not an experimental locus.
        path = self.base / 'evidence/revised.json'
        s, raw = gdv.load_spec(path)
        first = gdv.compose(s, raw)
        changed = gdv.read_json(path)
        changed['display_name'] = 'SYNTHETIC_INPUT_CONTRACT'
        gdv.write_json(path, changed)
        s, raw = gdv.load_spec(path)
        second = gdv.compose(s, raw)
        self.assertNotEqual(first, second)
        self.assertIn(b'SYNTHETIC_INPUT_CONTRACT', second)

    def test_profile_symlink_and_absolute_entry_rejected(self):
        link = self.base / 'profile.json'; link.symlink_to(ROOT / 'assets/render_profile.json')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            batch.preflight(self.base, self.config, self.base / 'new', link)
        manifest = gdv.read_json(self.manifest)
        manifest['loci'][0]['revised_spec'] = str(self.base / 'evidence/revised.json')
        gdv.write_json(self.manifest, manifest)
        with self.assertRaisesRegex(ValueError, '相对路径'):
            batch.preflight(self.base, self.config, self.base / 'new')
        self.assertFalse((self.base / 'new').exists())

    def test_pdf_stream_diagnostic_preserves_raw(self):
        import zlib
        a, b = self.base / 'a.pdf', self.base / 'b.pdf'
        for path, date in ((a, b'20260101'), (b, b'20260102')):
            path.write_bytes(b'%PDF\nstream\n' + zlib.compress(b'/CreationDate (D:' + date + b')') + b'\nendstream')
        before = (gdv.sha(a), gdv.sha(b))
        diff = batch.pdf_difference(a, b)
        self.assertFalse(diff['raw_equal'])
        self.assertIn('/CreationDate', diff['changed_decoded_streams'][0]['before_decoded'])
        self.assertEqual(before, (gdv.sha(a), gdv.sha(b)))


if __name__ == '__main__':
    unittest.main()
