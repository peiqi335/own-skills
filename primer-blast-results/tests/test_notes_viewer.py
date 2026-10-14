"""Mechanical plain-text notes safety and atomic preflight regressions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_site as site
from evidence import sha256
from test_build_site import subset

CONFIG = Path('/home/qi/文档/课题实验/5.知识结论/02.PCR与凝胶初筛/标准样板_2026-10-14/离线站点/project-config-A-v2')


class NotesText(unittest.TestCase):
    def test_nonascii_and_injection_are_literal(self):
        raw = '来源待核 pending\n<script>alert(1)</script><img src="https://evil.invalid" onerror="x"> &'.encode()
        text = site.notes_text(raw)
        self.assertIn('来源待核 pending', text)
        self.assertNotIn('<script', text)
        self.assertNotIn('<img', text)
        self.assertIn('&lt;script&gt;', text)
        self.assertIn('&amp;', text)

    def test_invalid_encoding_rejected(self):
        with self.assertRaises(UnicodeDecodeError):
            site.notes_text(b'\xff')


@unittest.skipUnless(CONFIG.is_dir(), 'real config unavailable')
class NotesBuilder(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='notes-viewer-', dir='/tmp/opencode'))
        self.path, self.m = subset(CONFIG, self.base / 'config')
        self.raw = '不是新的 GDV 导出；来源待核 pending\n<script>alert(1)</script> &'.encode()
        for g in self.m['gdv']:
            name = 'notes/' + g['id'] + '/source_notes.md'
            p = self.path.parent / name
            p.parent.mkdir(parents=True)
            p.write_bytes(self.raw)
            g['evidence_inputs'] = [dict(path=name, sha256=sha256(self.raw))]
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.m, ensure_ascii=False))

    def test_viewer_raw_hash_navigation_and_manifest(self):
        out = site.build(self.path, self.base / 'run')
        final = json.loads((out / 'finalspec.json').read_text())
        for g in final['gdv']:
            meta = g['notes_viewers'][0]
            self.assertEqual((out / meta['raw_archive']).read_bytes(), self.raw)
            self.assertEqual(meta['raw_sha256'], sha256(self.raw))
            text = (out / meta['viewer']).read_text()
            self.assertIn('<meta charset="utf-8">', text)
            self.assertIn('white-space:pre-wrap', text)
            self.assertIn('不是新的 GDV 导出', text)
            self.assertIn('&lt;script&gt;', text)
            self.assertNotIn('<script>', text)
            self.assertIn('<a download href=', text)
            self.assertIn('source_notes.html', (out / '03.GDV/index.html').read_text())
            self.assertEqual(meta['viewer_sha256'], sha256((out / meta['viewer']).read_bytes()))

    def test_bad_hash_or_utf8_produces_zero_outputs(self):
        record = self.m['gdv'][0]['evidence_inputs'][0]
        record['sha256'] = '0' * 64
        self.save()
        with self.assertRaises(ValueError):
            site.build(self.path, self.base / 'bad-hash')
        self.assertFalse((self.base / 'bad-hash').exists())
        p = self.path.parent / record['path']
        p.write_bytes(b'\xff')
        record['sha256'] = sha256(b'\xff')
        self.save()
        with self.assertRaises(UnicodeDecodeError):
            site.build(self.path, self.base / 'bad-encoding')
        self.assertFalse((self.base / 'bad-encoding').exists())


if __name__ == '__main__':
    unittest.main()
