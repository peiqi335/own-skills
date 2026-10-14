"""Offline regression suite. Temporary artifacts intentionally remain under /tmp/opencode."""
import copy
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_panel as panel
import fetch_and_prepare as fetch
import evidence


def html(body):
    return '<html><head></head><body>' + body + '</body></html>'


def echoed(raw, params=None):
    params = params or evidence.parameters('ACGT', 'TGCA', 'Rattus norvegicus')
    fields = ''.join(f'<input name="{key}" value="{value}">' for key, value in params.items())
    return raw.replace('</body>', fields + '</body>')


PRODUCT = echoed(html('<nav><a>NM_999.9</a></nav><div class="prPairDtl">'
               '&gt;<a>NC_086024.1</a> Rat chromosome 6'
               '<pre>product length = 82</pre><pre>product length = 52</pre></div>'))
EMPTY = html('No target templates were found')
WAIT = html('This job is still running. Please wait')
SUBMIT = html('<input value="test-key" name="job_key">Please wait')
SP = {'code': 'RAT', 'organism': 'Rattus norvegicus'}
PARAMS = evidence.parameters('ACGT', 'TGCA', SP['organism'])
REAL = Path('/home/qi/文档/课题实验/4.知识库/01.检测体系准备/PCR与凝胶初筛/结果汇总/primer-blast/01.成对Primer-BLAST/gDNA/RAT_1/RAT_1_target.html')


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='primer-blast-test-', dir='/tmp/opencode'))

    def root(self, name='input'):
        path = self.base / name
        path.mkdir()
        return path

    def fixture(self, raw=PRODUCT, status='completed_results', products=None):
        root = self.root()
        (root / 'T').mkdir()
        (root / 'T/report.html').write_text(raw)
        data: dict = dict(database='refseq_representative_genomes', species_panel=[dict(SP)], queries=[
            dict(id='T_on_RAT', assay='T', species_code='RAT', organism=SP['organism'],
                 is_target=True, parameters=PARAMS, forward='ACGT', reverse='TGCA',
                 status=status, products=evidence.parse_products(raw)[0] if products is None else products,
                 result_page='T/report.html')])
        path = root / 'status.json'
        path.write_text(json.dumps(data))
        return path, data

    def test_template_blocks_multi_products_and_navigation_noise(self):
        products, status, _ = evidence.parse_products(PRODUCT)
        self.assertEqual(status, 'ok')
        self.assertEqual(products, [{'template_accession': 'NC_086024.1', 'length_bp': 82},
                                    {'template_accession': 'NC_086024.1', 'length_bp': 52}])
        other = PRODUCT.replace('</body>', '<div class="prPairDtl">&gt;<a>XM_123.4</a><pre>product length = 120</pre></div></body>')
        self.assertEqual(evidence.parse_products(other)[0][-1]['template_accession'], 'XM_123.4')

    def test_parse_anomaly_never_becomes_negative(self):
        bad = html('<pre>product length = 99</pre>')
        self.assertEqual(evidence.classify(bad), 'completed_results')
        self.assertEqual(evidence.parse_products(bad)[1], 'needs_review')
        root = self.root()
        with patch.object(fetch, 'request_bytes', return_value=bad.encode()):
            q = fetch.fetch_query(root, 'T', SP, PARAMS)
        self.assertEqual(q['status'], 'completed_results')
        self.assertEqual(q['parse_status'], 'needs_review')
        self.assertEqual(fetch.verified_raw(root, q['raw_response']), bad.encode())

    def test_states_wait_error_unknown_and_negative(self):
        for raw, expected in [(EMPTY, 'completed_no_target_template'), (WAIT, 'waiting'),
                              (html('Error: job expired'), 'error'), (html('hello'), 'unknown'),
                              (WAIT + PRODUCT, 'waiting'), (html('Products on target templates'), 'unknown')]:
            with self.subTest(expected=expected):
                self.assertEqual(evidence.classify(raw), expected)

    def test_submission_without_key_is_not_negative(self):
        for i, raw in enumerate([html('hello'), WAIT, html('Error: bad request')]):
            with patch.object(fetch, 'request_bytes', return_value=raw.encode()):
                q = fetch.fetch_query(self.root(str(i)), 'T', SP, PARAMS)
            self.assertEqual(q['status'], 'error')
            self.assertEqual(q['products'], [])
            self.assertIsNone(q['result_page'])
            self.assertIn('raw_response', q)

    def test_network_timeout_is_per_query_and_request_is_bounded(self):
        root = self.root()
        with patch.object(fetch.urllib.request, 'urlopen', side_effect=TimeoutError('network')) as mock:
            q = fetch.fetch_query(root, 'T', SP, PARAMS, request_timeout=7)
        self.assertEqual(q['status'], 'error')
        self.assertEqual(mock.call_args.kwargs['timeout'], 7)
        assays = self.base / 'assays.json'
        assays.write_text(json.dumps({'T': {'forward': 'ACGT', 'reverse': 'TGCA'}}))
        with patch.object(fetch, 'DEFAULT_SPECIES_PANEL', [SP, {'code': 'CAT', 'organism': 'Felis catus'}]), patch.object(fetch, 'request_bytes', side_effect=[OSError('offline'), EMPTY.encode()]):
            status = fetch.run(assays, self.base / 'batch', 'refseq_rna')
        data = json.loads(status.read_text())
        self.assertEqual([q['status'] for q in data['queries']], ['error', 'completed_no_target_template'])

    def test_http_error_body_preserved(self):
        err = urllib.error.HTTPError('https://example.invalid', 503, 'unavailable', Message(), BytesIO(b'<html>service unavailable</html>'))
        root = self.root()
        with patch.object(fetch.urllib.request, 'urlopen', side_effect=err):
            q = fetch.fetch_query(root, 'T', SP, PARAMS)
        self.assertEqual(q['status'], 'error')
        self.assertEqual(fetch.verified_raw(root, q['raw_response']), b'<html>service unavailable</html>')

    def test_poll_timeout_keeps_last_waiting_and_error_never_negative(self):
        root = self.root()
        with patch.object(fetch, 'request_bytes', side_effect=[SUBMIT.encode(), WAIT.encode()]), patch.object(fetch.time, 'monotonic', side_effect=[0, 0, 0, 301, 301]), patch.object(fetch.time, 'sleep'):
            q = fetch.fetch_query(root, 'T', SP, PARAMS)
        self.assertEqual(q['status'], 'timeout')
        self.assertEqual(fetch.verified_raw(root, q['raw_response']), WAIT.encode())
        self.assertEqual(fetch.verified_raw(root, q['submission']), SUBMIT.encode())
        self.assertIsNone(q['result_page'])
        for i, response in enumerate([html('Error: invalid job'), html('unknown response')]):
            with patch.object(fetch, 'request_bytes', side_effect=[SUBMIT.encode(), response.encode()]):
                q = fetch.fetch_query(self.root(str(i)), 'T', SP, PARAMS)
            self.assertEqual(q['status'], ['error', 'unknown'][i])

    def test_poll_network_failure_keeps_submission(self):
        root = self.root()
        with patch.object(fetch, 'request_bytes', side_effect=[SUBMIT.encode(), OSError('offline')]):
            q = fetch.fetch_query(root, 'T', SP, PARAMS)
        self.assertEqual(q['status'], 'error')
        self.assertEqual(fetch.verified_raw(root, q['raw_response']), SUBMIT.encode())

    def test_resume_identity_terminal_and_hash_checks(self):
        root = self.root()
        with patch.object(fetch, 'request_bytes', return_value=PRODUCT.encode()):
            old = fetch.fetch_query(root, 'T', SP, PARAMS)
        before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
        self.assertEqual(fetch.resume_query(root, old, PARAMS)['status'], 'completed_results')
        for key in evidence.IDENTITY_KEYS:
            params = dict(PARAMS)
            params[key] = '99' if key not in evidence.IDENTITY_KEYS[:4] else ('TGCA' if key == 'PRIMER_LEFT_INPUT' else 'different')
            if key == 'PRIMER_RIGHT_INPUT':
                params[key] = 'ACGT'
            if key == 'PRIMER_SPECIFICITY_DATABASE':
                params[key] = 'refseq_rna'
            q = fetch.resume_query(root, old, params)
            self.assertEqual(q['status'], 'error', key)
            self.assertEqual(q['parameters'], old['parameters'])
        missing = dict(old)
        missing.pop('parameters')
        self.assertEqual(fetch.resume_query(root, missing, PARAMS)['status'], 'unknown')
        no_raw = dict(old)
        no_raw.pop('raw_response')
        self.assertEqual(fetch.resume_query(root, no_raw, PARAMS)['status'], 'unknown')
        for p, raw in before.items():
            self.assertEqual(p.read_bytes(), raw)
        (root / old['raw_response']['path']).write_text(WAIT)
        old['raw_response']['sha256'] = evidence.sha256(WAIT.encode())
        self.assertEqual(fetch.resume_query(root, old, PARAMS)['status'], 'waiting')

    def test_existing_batch_read_only_resume_uses_unique_status(self):
        assays = self.base / 'assays.json'
        assays.write_text(json.dumps({'T': {'forward': 'ACGT', 'reverse': 'TGCA'}}))
        with patch.object(fetch, 'DEFAULT_SPECIES_PANEL', [SP]), patch.object(fetch, 'request_bytes', return_value=PRODUCT.encode()):
            first = fetch.run(assays, self.base / 'batch', 'refseq_representative_genomes')
        original = first.read_bytes()
        with patch.object(fetch, 'DEFAULT_SPECIES_PANEL', [SP]), patch.object(fetch, 'request_bytes', side_effect=AssertionError('must not submit')):
            second = fetch.run(assays, self.base / 'batch', 'refseq_rna')
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(json.loads(second.read_text())['queries'][0]['status'], 'error')

    def test_decorate_idempotent_livebar_both_modes_and_pending(self):
        for db in ['refseq_rna', 'refseq_representative_genomes']:
            params = dict(PARAMS, PRIMER_SPECIFICITY_DATABASE=db)
            raw = PRODUCT.replace('value="refseq_representative_genomes"', f'value="{db}"')
            once = panel.decorate_report(raw.encode(), params)
            twice = panel.decorate_report(once, params)
            self.assertEqual(once, twice)
            text = once.decode()
            self.assertEqual(text.count('class="ncbi-live-bar"'), 1)
            self.assertEqual(text.count('../assets/report.css'), 1)
            self.assertIn('按归档参数重新检索', text)
            self.assertIn(db, text)
            self.assertNotIn('自动出结果', text)
            self.assertIn('不保证复现旧结果', text)
        pending = panel.decorate_report(PRODUCT.encode()).decode()
        self.assertIn('pending', pending)
        self.assertNotIn('primertool.cgi', pending)
        self.assertIn('pending', fetch.decorate_report_html(PRODUCT, 'https://example.invalid', 'https://example.invalid'))
        live, form = fetch.build_live_urls('ACGT', 'TGCA', SP['organism'], db='refseq_rna')
        self.assertIn('转录组 mRNA 模式', fetch.decorate_report_html(PRODUCT.replace('value="refseq_representative_genomes"', 'value="refseq_rna"'), live, form))

    def test_build_preserves_input_and_homepage_wording(self):
        path, _ = self.fixture()
        original = path.read_bytes()
        output = panel.build(path, self.base / 'output', '测试')
        home = (output / 'index.html').read_text()
        self.assertIn('报告有产物', home)
        self.assertIn('未完成：0', home)
        self.assertIn('解析待核：0', home)
        self.assertIn('refseq_representative_genomes', home)
        self.assertNotIn('符合设计预期', home)
        self.assertNotIn('完全特异阴性', home)
        self.assertEqual(path.read_bytes(), original)
        dest = output / panel.PANEL
        self.assertEqual((dest / '_archived-input/T/report.html').read_text(), PRODUCT)
        self.assertIn('ncbi-live-bar', (dest / 'T/report.html').read_text())
        checks = json.loads((output / 'checks.json').read_text())
        self.assertEqual(checks['query_count'], 1)
        for rel, record in checks['reports'].items():
            self.assertEqual(panel.digest(dest / rel), record['output_sha256'])

    def test_empty_report_is_not_specificity_claim(self):
        path, _ = self.fixture(EMPTY, 'completed_no_target_template')
        output = panel.build(path, self.base / 'output', '测试')
        self.assertIn('报告无产物', (output / panel.PANEL / 'index.html').read_text())

    def test_fetch_to_build_preserves_raw_submission_and_last_response(self):
        root = self.root()
        with patch.object(fetch, 'request_bytes', side_effect=[SUBMIT.encode(), PRODUCT.encode()]):
            q = fetch.fetch_query(root, 'T', SP, PARAMS)
        q['is_target'] = True
        data = dict(schema_version=2, database='refseq_representative_genomes', species_panel=[SP], queries=[q])
        status = root / 'status.json'
        status.write_text(json.dumps(data))
        output = panel.build(status, self.base / 'output', '测试')
        dest = output / panel.PANEL
        self.assertEqual((dest / q['submission']['path']).read_bytes(), SUBMIT.encode())
        self.assertEqual((dest / q['raw_response']['path']).read_bytes(), PRODUCT.encode())
        self.assertNotEqual(q['raw_response']['path'], q['result_page'])
        shown = (dest / q['result_page']).read_text()
        self.assertIn('展示派生页，非原始响应', shown)
        self.assertEqual(shown.count('class="ncbi-live-bar"'), 1)
        self.assertIn('按归档参数重新检索', shown)
        output_status = json.loads((dest / 'status.json').read_text())
        self.assertEqual(output_status['queries'][0]['display_sha256'], panel.digest(dest / q['result_page']))

    def test_parse_pending_is_visible_without_fabricating_negative(self):
        raw = html('<pre>product length = 99</pre>')
        path, data = self.fixture(raw)
        data['queries'][0]['parse_status'] = 'needs_review'
        path.write_text(json.dumps(data))
        output = panel.build(path, self.base / 'output', '测试')
        home = (output / 'index.html').read_text()
        matrix = (output / panel.PANEL / 'index.html').read_text()
        self.assertIn('解析待核：1', home)
        self.assertIn('解析待核', matrix)
        self.assertNotIn('报告无产物', matrix)

    def test_unfinished_counts_do_not_become_no_products(self):
        source = self.root()
        data = dict(database='refseq_rna', species_panel=[SP], queries=[dict(
            id='T_on_RAT', assay='T', species_code='RAT', is_target=True,
            status='timeout', products=[], result_page=None, parse_status='not_applicable')])
        status = source / 'status.json'
        status.write_text(json.dumps(data))
        output = panel.build(status, self.base / 'output', '测试')
        self.assertIn('未完成：1', (output / 'index.html').read_text())
        self.assertIn('未完成：timeout', (output / panel.PANEL / 'index.html').read_text())

    def test_nested_report_assets_and_back_link(self):
        path, data = self.fixture()
        rel = 'T/deep/report.html'
        dest = path.parent / rel
        dest.parent.mkdir()
        dest.write_text(PRODUCT)
        data['queries'][0]['result_page'] = rel
        path.write_text(json.dumps(data))
        output = panel.build(path, self.base / 'output', '测试')
        shown = (output / panel.PANEL / rel).read_text()
        self.assertIn('href="../../assets/report.css"', shown)
        self.assertIn('href="../../index.html"', shown)

    def test_force_rejected_existing_intact_even_invalid_json(self):
        source = self.root()
        status = source / 'status.json'
        status.write_text('invalid json')
        output = self.root('output')
        sentinel = output / 'user.txt'
        sentinel.write_bytes(b'keep me')
        for force in [False, True]:
            with self.assertRaises(ValueError):
                panel.build(status, output, '测试', force=force)
            self.assertEqual(sentinel.read_bytes(), b'keep me')
            self.assertEqual(list(output.iterdir()), [sentinel])

    def test_invalid_matrix_schema_products_page_path_leave_no_output(self):
        path, original = self.fixture()
        cases = []
        data = copy.deepcopy(original); data['queries'].append(data['queries'][0]); cases.append(data)
        data = copy.deepcopy(original); data['species_panel'].append(dict(code='CAT', organism='Felis catus')); cases.append(data)
        data = copy.deepcopy(original); data['queries'][0]['products'] = []; cases.append(data)
        data = copy.deepcopy(original); data['queries'][0]['products'][0]['length_bp'] = 100; cases.append(data)
        data = copy.deepcopy(original); data['queries'][0]['status'] = 'completed_no_target_template'; cases.append(data)
        data = copy.deepcopy(original); data['queries'][0]['result_page'] = '../outside.html'; cases.append(data)
        data = copy.deepcopy(original); data['queries'][0]['result_page'] = 'missing.html'; cases.append(data)
        data = copy.deepcopy(original); data['queries'][0]['result_page'] = 'assets/report.css'; cases.append(data)
        data = copy.deepcopy(original); data['queries'][0]['forward'] = 'TTTT'; cases.append(data)
        data = copy.deepcopy(original); data['queries'][0]['result_page'] = 'T//report.html'; cases.append(data)
        for i, data in enumerate(cases):
            path.write_text(json.dumps(data))
            output = self.base / f'out-{i}'
            with self.subTest(i=i), self.assertRaises(ValueError):
                panel.build(path, output, '测试', force=True)
            self.assertFalse(output.exists())

    def test_waiting_page_must_not_be_published_as_negative(self):
        path, _ = self.fixture(WAIT, 'completed_no_target_template')
        with self.assertRaises(ValueError):
            panel.build(path, self.base / 'output', '测试')
        self.assertFalse((self.base / 'output').exists())

    def test_source_overlap_and_symlink_rejected(self):
        path, _ = self.fixture()
        for output in [path.parent, path.parent / 'nested', self.base]:
            with self.assertRaises(ValueError):
                panel.build(path, output, '测试', force=True)
        link = self.base / 'link'
        link.symlink_to(path.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            panel.build(link / 'status.json', self.base / 'output', '测试')
        destlink = self.base / 'destlink'
        destlink.symlink_to(self.base / 'new')
        with self.assertRaises(ValueError):
            panel.build(path, destlink / 'child', '测试')
        (path.parent / 'T/link.html').symlink_to(path.parent / 'T/report.html')
        data = json.loads(path.read_text()); data['queries'][0]['result_page'] = 'T/link.html'
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            panel.build(path, self.base / 'output', '测试')

    @unittest.skipUnless(REAL.is_file(), '只读真实 RAT 报告不可用')
    def test_real_rat_82_52_fixture_output(self):
        before = evidence.sha256(REAL.read_bytes())
        raw = REAL.read_text(encoding='utf-8-sig')
        products, parsed, _ = evidence.parse_products(raw)
        self.assertEqual(parsed, 'ok')
        self.assertEqual(products, [{'template_accession': 'NC_086024.1', 'length_bp': 82},
                                    {'template_accession': 'NC_086024.1', 'length_bp': 52}])
        path, data = self.fixture(raw)
        data['queries'][0].pop('parameters')
        data['queries'][0].update(forward='ATGAGGCTGTCGACGAAGAC', reverse='TCTTTCTCACTCGCCGCTTC')
        path.write_text(json.dumps(data))
        output = panel.build(path, self.base / 'fixture-output', 'RAT fixture')
        report = (output / panel.PANEL / 'T/report.html').read_text()
        self.assertIn('product length = 82', report)
        self.assertIn('product length = 52', report)
        self.assertIn('pending', report)
        matrix = (output / panel.PANEL / 'index.html').read_text()
        self.assertIn('82 bp, 52 bp', matrix)
        self.assertEqual(evidence.sha256(REAL.read_bytes()), before)


if __name__ == '__main__':
    unittest.main()
