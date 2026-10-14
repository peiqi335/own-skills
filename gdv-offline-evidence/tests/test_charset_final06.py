"""Finite UTF-8 SVG policy: reject alternate encodings before XML/Cairo/I/O."""
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import render_gdv as gdv

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"><title>猫</title><rect width="10" height="10" fill="red"/></svg>'


class CharsetFinal06Tests(unittest.TestCase):
    def reject_before_parse(self, raw):
        with patch.object(gdv.ET, 'fromstring', side_effect=AssertionError('XML parse forbidden')) as parse, \
             patch('cairosvg.surface.PNGSurface.convert', side_effect=AssertionError('render forbidden')) as render, \
             patch('cairosvg.url.urlopen', side_effect=AssertionError('I/O forbidden')) as network:
            for operation in (gdv.safe_svg_bytes, lambda data: gdv.convert_svg(data, 'png')):
                with self.assertRaisesRegex(ValueError, 'UTF-8'):
                    operation(raw)
            self.assertEqual(parse.call_count, 0)
            self.assertEqual(render.call_count, 0)
            self.assertEqual(network.call_count, 0)

    def test_utf16_utf32_bom_and_explicit_endian_rejected(self):
        for encoding in ('utf-16', 'utf-16-le', 'utf-16-be', 'utf-32', 'utf-32-le', 'utf-32-be'):
            for content in (SVG, '<?xml-stylesheet href="http://invalid.example/style.css"?>' + SVG):
                with self.subTest(encoding=encoding, processing_instruction=content != SVG):
                    self.reject_before_parse(content.encode(encoding))

    def test_nul_and_invalid_utf8_rejected(self):
        for raw in (SVG.encode() + b'\x00', SVG.encode().replace(b'</title>', b'\xff</title>')):
            with self.subTest(raw=raw):
                self.reject_before_parse(raw)

    def test_normal_utf8_and_utf8_bom_accepted_without_byte_rewrite(self):
        from PIL import Image
        raw = ('<?xml version="1.0" encoding="UTF-8"?>' + SVG).encode('utf-8')
        decoded = []
        with patch('cairosvg.url.urlopen', side_effect=AssertionError('I/O forbidden')) as network:
            for data in (raw, b'\xef\xbb\xbf' + raw):
                before = bytes(data)
                root = gdv.safe_svg_bytes(data)
                self.assertEqual(root[0].text, '猫')
                with Image.open(io.BytesIO(gdv.convert_svg(data, 'png'))) as image:
                    decoded.append((image.mode, image.size, image.tobytes()))
                self.assertEqual(data, before)
            self.assertEqual(network.call_count, 0)
        self.assertEqual(decoded[0], decoded[1])


if __name__ == '__main__':
    unittest.main()
