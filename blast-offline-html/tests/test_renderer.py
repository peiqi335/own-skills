import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('renderer', ROOT / 'scripts/render_blast_offline.py')
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.tree = ET.parse(ROOT / 'tests/fixtures/tiny_blastn.xml')

    def source(self, name='input.xml'):
        path = self.dir / name
        self.tree.write(path, encoding='utf-8')
        return path

    def test_missing_and_invalid_fields(self):
        for field, value in [('Hsp_query-from', None), ('Hsp_query-to', '21'),
                             ('Hsp_hit-from', '0'), ('Hsp_bit-score', 'nan'),
                             ('Hsp_qseq', 'A'), ('BlastOutput_query-len', '0')]:
            with self.subTest(field=field):
                self.tree = ET.parse(ROOT / 'tests/fixtures/tiny_blastn.xml')
                self.tree.find('.//' + field).text = value
                with self.assertRaises(ValueError):
                    r.parse_xml(self.source())

    def test_union_coverage(self):
        self.assertEqual(r.fmt_cover([{'qfrom': 3, 'qto': 17}, {'qfrom': 1, 'qto': 11}], 20), '85%')
        self.assertEqual(r.fmt_cover([{'qfrom': 20, 'qto': 1}] * 2, 20), '100%')

    def test_reverse_and_gaps(self):
        h = {'qseq': 'AC-GT', 'hseq': 'A-CGT', 'mid': '|  ||',
             'qfrom': 10, 'qto': 7, 'hfrom': 20, 'hto': 17, 'strand': 'Minus/Minus'}
        result = r.aln_pre(h)
        self.assertIn('AC-GT  7', result)
        self.assertIn('A-CGT  17', result)
        h.update(qfrom=1, qto=4, hfrom=1, hto=4, strand='Plus/Plus')
        self.assertIn('AC-GT  4', r.aln_pre(h))

    def test_unsupported(self):
        self.tree.find('BlastOutput_program').text = 'blastp'
        with self.assertRaisesRegex(ValueError, 'program'):
            r.parse_xml(self.source())
        self.tree.find('BlastOutput_program').text = 'blastn'
        it = self.tree.find('BlastOutput_iterations')
        it.append(copy.deepcopy(it[0]))
        with self.assertRaisesRegex(ValueError, 'Iteration'):
            r.parse_xml(self.source())
        path = self.dir / 'xml2.xml'
        path.write_text('<BlastXML2/>')
        with self.assertRaisesRegex(ValueError, 'format'):
            r.parse_xml(path)

    def test_job_title(self):
        rec = r.parse_xml(self.source())
        self.assertEqual(r.job_title(rec['query_def']), 'tiny')
        html = r.page_html(rec)
        self.assertIn('<dt>Job title</dt><dd>tiny</dd>', html)
        self.assertIn('<dt>Query Length</dt><dd>20</dd>', html)
        self.assertNotIn('Job title:', html)
        self.assertEqual(r.job_title('No definition line'), 'Nucleotide Sequence')
        self.assertEqual(r.job_title(''), 'Nucleotide Sequence')
        rec['query_def'] = 'No definition line'
        self.assertIn('<dt>Job title</dt><dd>Nucleotide Sequence</dd>', r.page_html(rec))

    def test_no_hits(self):
        self.tree.find('.//Iteration_hits').clear()
        record = r.parse_xml(self.source())
        self.assertEqual(record['hits'], [])
        self.assertIn('无命中', r.page_html(record))

    def test_batch_and_navigation(self):
        a = self.source('a.xml')
        b = self.dir / 'bad.xml'
        b.write_text('<broken')
        c = self.source('c.xml')
        out = self.dir / 'out'
        written, failed = r.render([a, b, c], out)
        self.assertEqual(len(written), 2)
        self.assertEqual(len(failed), 1)
        self.assertNotIn('bad.html', (out / 'index.html').read_text())
        self.assertIn('href="index.html"', written[0].read_text())
        self.assertTrue((out / 'a.html').exists())
        nested_a = self.source('CAT_1_CAT_F.xml')
        nested_b = self.source('CAT_1_CAT_R.xml')
        nested_out = self.dir / 'nested'
        nested_written, _ = r.render([nested_a, nested_b], nested_out)
        self.assertTrue((nested_out / 'CAT_1' / 'CAT_1_CAT_F.html').exists())
        nested_html = nested_written[0].read_text()
        self.assertIn('href="../viewer.css"', nested_html)
        self.assertIn('href="../index.html"', nested_html)
        self.assertIn('CAT_1/CAT_1_CAT_F.html', (nested_out / 'index.html').read_text())
        one, _ = r.render([a], self.dir / 'one')
        self.assertNotIn('href="index.html"', one[0].read_text())
        run = subprocess.run([sys.executable, str(ROOT / 'scripts/render_blast_offline.py'), str(a), str(b), '-o', str(self.dir / 'cli')], capture_output=True)
        self.assertEqual(run.returncode, 1)
        self.assertTrue((self.dir / 'cli/a.html').exists())

    def test_conflicts_before_writing(self):
        path = self.source()
        for inputs, out in [([path, path], self.dir / 'duplicate'), ([path], self.dir / 'blastn-target')]:
            with self.assertRaises(ValueError):
                r.render(inputs, out)
            self.assertFalse(out.exists())
        out = self.dir / 'existing'
        out.mkdir()
        dest = out / 'input.html'
        dest.write_text('<html>original NCBI page</html>')
        with self.assertRaises(ValueError):
            r.render([path], out)
        self.assertEqual(dest.read_text(), '<html>original NCBI page</html>')

    def test_duplicate_anchor(self):
        hits = self.tree.find('.//Iteration_hits')
        hits.append(copy.deepcopy(hits[0]))
        rec = r.parse_xml(self.source())
        self.assertEqual(len({h['gi'] for h in rec['hits']}), 3)


if __name__ == '__main__':
    unittest.main()
