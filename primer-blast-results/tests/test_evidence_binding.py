"""Oracle regressions: response binding, display consistency and URL boundaries."""
from html import escape
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_build_panel as fixtures

panel, fetch, evidence = fixtures.panel, fixtures.fetch, fixtures.evidence


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='primer-binding-test-', dir='/tmp/opencode'))

    def root(self, name='input'):
        return fixtures.EvidenceTests.root(self, name)

    def fixture(self, raw=fixtures.PRODUCT, status='completed_results', products=None):
        return fixtures.EvidenceTests.fixture(self, raw, status, products)

    def archived(self, raw=fixtures.PRODUCT, display=None):
        display = raw if display is None else display
        path, data = self.fixture(display)
        q = data['queries'][0]
        q['products'] = evidence.parse_products(raw)[0]
        data['schema_version'] = 2
        for field, rel, content in [('submission', 'T/submission.raw.html', fixtures.SUBMIT),
                                    ('raw_response', 'T/source.raw.html', raw)]:
            (path.parent / rel).write_text(content)
            q[field] = dict(path=rel, sha256=evidence.sha256(content.encode()), received_utc='2026-10-14T00:00:00Z')
        q['display_sha256'] = evidence.sha256(display.encode())
        path.write_text(json.dumps(data))
        return path, data

    def publish(self, path):
        return panel.build(path, self.base / 'output', 'binding regression')

    def test_raw_internal_identity_conflicts_block_publication(self):
        for key, value in [('PRIMER_LEFT_INPUT', 'TTTT'), ('PRIMER_RIGHT_INPUT', 'AAAA'),
                           ('ORGANISM', 'Felis catus'), ('PRIMER_SPECIFICITY_DATABASE', 'refseq_rna'),
                           ('PRIMER_PRODUCT_MIN', '60'), ('PRIMER_PRODUCT_MAX', '4000'),
                           ('TOTAL_PRIMER_SPECIFICITY_MISMATCH', '4'),
                           ('PRIMER_3END_SPECIFICITY_MISMATCH', '3'), ('MISMATCH_REGION_LENGTH', '6')]:
            with self.subTest(key=key):
                root = self.base / key
                root.mkdir()
                old_base = self.base
                self.base = root
                raw = fixtures.PRODUCT.replace(f'name="{key}" value="{fixtures.PARAMS[key]}"', f'name="{key}" value="{value}"')
                path, _ = self.archived(raw=raw)
                with self.assertRaises(evidence.BindingConflict):
                    self.publish(path)
                self.assertFalse((root / 'output').exists())
                self.base = old_base

    def test_query_species_panel_organism_mismatch(self):
        path, data = self.archived()
        data['species_panel'][0]['organism'] = 'Felis catus'
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'species_panel'):
            self.publish(path)
        self.assertFalse((self.base / 'output').exists())

    def test_v2_missing_required_evidence_rejected(self):
        path, original = self.archived()
        for field in ['parameters', 'submission', 'raw_response', 'display_sha256']:
            data = json.loads(json.dumps(original))
            data['queries'][0].pop(field)
            path.write_text(json.dumps(data))
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.publish(path)
            self.assertFalse((self.base / 'output').exists())

    def test_matching_hashes_do_not_hide_display_negative_or_different_lengths(self):
        for i, display in enumerate([fixtures.EMPTY, fixtures.PRODUCT.replace('product length = 82', 'product length = 83')]):
            root = self.base / str(i)
            root.mkdir()
            base = self.base
            self.base = root
            path, _ = self.archived(display=display)
            with self.subTest(i=i), self.assertRaisesRegex(ValueError, 'raw/display'):
                self.publish(path)
            self.assertFalse((root / 'output').exists())
            self.base = base

    def test_matched_raw_is_derivation_source_and_data_remain(self):
        display = fixtures.PRODUCT.replace('</head>', '<title>old display only</title></head>')
        raw = fixtures.PRODUCT.replace('product length = 82', 'product length = 82\nForward primer 1 ACGT 4\nTemplate 10 .... 7')
        path, data = self.archived(raw=raw, display=display)
        output = self.publish(path) / panel.PANEL
        q = json.loads((output / 'status.json').read_text())['queries'][0]
        shown = (output / q['result_page']).read_text()
        self.assertNotIn('old display only', shown)
        self.assertEqual((output / q['archived_input_page']).read_text(), display)
        self.assertEqual(evidence.parse_products(shown), evidence.parse_products(fixtures.PRODUCT))
        self.assertIn('product length = 82', shown)
        self.assertIn('product length = 52', shown)
        self.assertIn('Forward primer 1 ACGT 4\nTemplate 10 .... 7', shown)
        self.assertTrue(q['source_verified'])
        self.assertEqual(q['response_binding']['status'], 'matched')
        self.assertEqual(q['display_sha256'], evidence.sha256(shown.encode()))
        checks = json.loads((output.parent / 'checks.json').read_text())
        self.assertEqual(checks['reports'][q['result_page']]['derivation_sha256'], data['queries'][0]['raw_response']['sha256'])

    def test_response_missing_fields_is_pending_not_verified(self):
        raw = fixtures.html('<div class="prPairDtl">&gt;<a>NC_086024.1</a><pre>product length = 82</pre></div>')
        path, _ = self.archived(raw)
        output = self.publish(path) / panel.PANEL
        q = json.loads((output / 'status.json').read_text())['queries'][0]
        self.assertFalse(q['source_verified'])
        self.assertEqual(q['response_binding']['status'], 'pending')
        text = (output / q['result_page']).read_text()
        self.assertIn('pending', text)
        self.assertNotIn('primertool.cgi', text)

    def test_summary_and_hidden_input_identity_extraction(self):
        rows = ''.join(f'<tr><th>{key}</th><td>{escape(value)}</td></tr>' for key, value in fixtures.PARAMS.items() if key in evidence.IDENTITY_KEYS)
        summary = fixtures.html('<table>' + rows + '</table>')
        self.assertEqual(evidence.response_binding(summary, fixtures.PARAMS)['status'], 'matched')
        native = fixtures.html('<table><tr><th>Forward primer</th><td>ACGT</td></tr>'
                               '<tr><th>Reverse primer</th><td>TGCA</td></tr></table>'
                               'Target templates were found in selected database: RefSeq Reference Genome Database (Organism limited to Rattus norvegicus)')
        binding = evidence.response_binding(native, fixtures.PARAMS)
        self.assertEqual(binding['status'], 'pending')
        self.assertNotIn('PRIMER_LEFT_INPUT', binding['missing_fields'])
        self.assertNotIn('ORGANISM', binding['missing_fields'])
        self.assertNotIn('PRIMER_SPECIFICITY_DATABASE', binding['missing_fields'])
        conflicting = fixtures.PRODUCT.replace('</body>', '<input name="PRIMER_LEFT_INPUT" value="TTTT"></body>')
        self.assertEqual(evidence.response_binding(conflicting, fixtures.PARAMS)['status'], 'conflict')
        human_summary = fixtures.html('<table><tr><th>Product Size Range</th><td>50 - 2000 bp</td></tr>'
                                     '<tr><th>Max Mismatches</th><td>Total: 3 nt; 3\' end (5 nt): &le; 2 nt</td></tr></table>')
        human = evidence.response_binding(human_summary, fixtures.PARAMS)
        self.assertEqual(human['status'], 'pending')
        self.assertNotIn('PRIMER_PRODUCT_MIN', human['missing_fields'])
        self.assertNotIn('TOTAL_PRIMER_SPECIFICITY_MISMATCH', human['missing_fields'])
        self.assertEqual(evidence.response_binding(human_summary.replace('Total: 3', 'Total: 9'), fixtures.PARAMS)['status'], 'conflict')
        self.assertEqual(evidence.response_binding(fixtures.PRODUCT, {'PRIMER_LEFT_INPUT': 'TTTT'})['status'], 'conflict')

    def test_resume_rejects_internal_raw_mismatch_even_with_correct_hash(self):
        path, data = self.archived(raw=fixtures.PRODUCT.replace('value="ACGT"', 'value="TTTT"'))
        q = fetch.resume_query(path.parent, data['queries'][0], fixtures.PARAMS)
        self.assertEqual(q['status'], 'error')
        self.assertFalse(q['source_verified'])
        self.assertEqual(q['products'], [])
        self.assertIn('needs rerun', q['error'])

    def test_resume_missing_returned_fields_stays_unknown_pending(self):
        path, data = self.archived(raw=fixtures.html('No target templates were found'))
        data['queries'][0]['status'] = 'completed_no_target_template'
        q = fetch.resume_query(path.parent, data['queries'][0], fixtures.PARAMS)
        self.assertEqual(q['status'], 'unknown')
        self.assertEqual(q['response_binding']['status'], 'pending')
        self.assertFalse(q['source_verified'])

    def test_legacy_resume_cannot_silently_upgrade_source_verified(self):
        path, data = self.archived()
        old = data['queries'][0]
        old['source_verified'] = True
        q = fetch.resume_query(path.parent, old, fixtures.PARAMS, schema_version=1)
        self.assertEqual(q['status'], 'unknown')
        self.assertFalse(q['source_verified'])
        self.assertIn('legacy', q['error'])

    def test_submission_conflict_blocks_complete_and_fetch(self):
        path, data = self.archived()
        raw = '<input name="ORGANISM" value="Felis catus">'
        record = data['queries'][0]['submission']
        (path.parent / record['path']).write_text(raw)
        record['sha256'] = evidence.sha256(raw.encode())
        path.write_text(json.dumps(data))
        with self.assertRaises(evidence.BindingConflict):
            self.publish(path)
        root = self.root('fetch')
        with patch.object(fetch, 'request_bytes', return_value=(raw + fixtures.PRODUCT).encode()):
            q = fetch.fetch_query(root, 'T', fixtures.SP, fixtures.PARAMS)
        self.assertEqual(q['status'], 'error')

    def test_unsafe_external_urls_without_trusted_parameters(self):
        path, original = self.fixture()
        original['queries'][0].pop('parameters')
        for i, url in enumerate(['javascript:alert(1)', 'data:text/html,unsafe',
                                 'https://example.invalid/tools/primer-blast/primertool.cgi?job_key=x',
                                 evidence.ENDPOINT + '?CMD=Put&job_key=x',
                                 evidence.ENDPOINT + '?job_key=']):
            data = json.loads(json.dumps(original))
            data['queries'][0]['result_url'] = url
            path.write_text(json.dumps(data))
            output = panel.build(path, self.base / f'output-{i}', 'unsafe urls') / panel.PANEL
            text = (output / 'index.html').read_text()
            self.assertNotIn(url, text)
            self.assertIn('data-live=""', text)
            self.assertIn('pending', (output / 'T/report.html').read_text())
        self.assertEqual(evidence.safe_job_url(evidence.ENDPOINT + '?job_key=test-key'), evidence.ENDPOINT + '?job_key=test-key')

    def test_colon_report_paths_rejected_before_any_write(self):
        path, data = self.fixture()
        for rel in ['javascript:alert(1)', 'data:text/html,unsafe', 'T/http:report.html']:
            file = path.parent / rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(fixtures.PRODUCT)
            data['queries'][0]['result_page'] = rel
            path.write_text(json.dumps(data))
            with self.subTest(rel=rel), self.assertRaises(ValueError):
                self.publish(path)
            self.assertFalse((self.base / 'output').exists())

    def test_real_native_echoes_bind_but_summary_is_not_execution_proof(self):
        if not fixtures.REAL.is_file():
            self.skipTest('真实只读 RAT 报告不可用')
        raw = fixtures.REAL.read_text(encoding='utf-8-sig')
        params = evidence.parameters('ATGAGGCTGTCGACGAAGAC', 'TCTTTCTCACTCGCCGCTTC', fixtures.SP['organism'])
        self.assertEqual(evidence.response_binding(raw, params)['status'], 'matched')
        for key in ['PRIMER_LEFT_INPUT', 'PRIMER_RIGHT_INPUT', 'ORGANISM', 'PRIMER_SPECIFICITY_DATABASE']:
            changed = dict(params)
            changed[key] = 'different'
            # Format validity is checked separately; use a valid changed sequence/db.
            if key in evidence.IDENTITY_KEYS[:2]:
                changed[key] = 'TTTT'
            if key == 'PRIMER_SPECIFICITY_DATABASE':
                changed[key] = 'refseq_rna'
            self.assertEqual(evidence.response_binding(raw, changed)['status'], 'conflict')


if __name__ == '__main__':
    unittest.main()
