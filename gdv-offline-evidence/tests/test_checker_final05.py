"""Narrow real-Cairo tests for marker resource attributes and XML PI rejection."""
import base64
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import render_gdv as gdv

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12">{}</svg>'


class CheckerFinal05Tests(unittest.TestCase):
    def reject_without_io(self, raw, message):
        with patch('cairosvg.url.urlopen', side_effect=AssertionError('external I/O forbidden')) as cairo_io, \
             patch('urllib.request.urlopen', side_effect=AssertionError('external I/O forbidden')) as urllib_io:
            for operation in (gdv.safe_svg_bytes, lambda value: gdv.convert_svg(value, 'png'),
                              lambda value: gdv.convert_svg(value, 'pdf')):
                with self.assertRaisesRegex(ValueError, message):
                    operation(raw)
            self.assertEqual(cairo_io.call_count, 0)
            self.assertEqual(urllib_io.call_count, 0)

    def test_three_marker_positions_http_and_file_rejected(self):
        for attr in ('marker-start', 'marker-mid', 'marker-end'):
            for url in ('http://invalid.example/marker.svg#m', 'file:///etc/passwd#m'):
                with self.subTest(attr=attr, url=url):
                    raw = SVG.format(f'<path d="M1 1L10 10" {attr}="url({url})"/>').encode()
                    self.reject_without_io(raw, 'CSS 含外部 URL')

    def test_shorthand_color_profile_cursor_rejected(self):
        for attr in ('marker', 'color-profile', 'cursor'):
            with self.subTest(attr=attr):
                self.reject_without_io(SVG.format(f'<rect width="10" height="10" {attr}="url(http://invalid.example/resource)"/>').encode(), 'CSS 含外部 URL')

    def test_css_escape_and_xml_character_entity_values_rejected(self):
        for value in (r'u\72l(http://invalid.example/marker)',
                      r'url(\66ile:///etc/passwd)',
                      '&#117;rl(http://invalid.example/marker)',
                      'url(&#34;file:///etc/passwd&#34;)'):
            with self.subTest(value=value):
                self.reject_without_io(SVG.format(f'<path d="M1 1L10 10" marker-end="{value}"/>').encode(), 'CSS 含外部 URL')

    def test_stylesheet_processing_instruction_rejected_before_xml_parse(self):
        for declaration in ('<?xml-stylesheet type="text/css" href="http://invalid.example/style.css"?>',
                            '<?xml-stylesheet href="file:///etc/passwd"?>', '<?other target="x"?>'):
            raw = (declaration + SVG.format('<rect width="10" height="10"/>')).encode()
            with self.subTest(declaration=declaration):
                with patch.object(gdv.ET, 'fromstring', side_effect=AssertionError('must reject before XML parse')) as parse:
                    self.reject_without_io(raw, 'processing instruction')
                    self.assertEqual(parse.call_count, 0)

    def test_local_fragments_and_normal_xml_declaration_real_cairo(self):
        attrs = ' '.join(f'{attr}="url(#missing)"' for attr in ('marker', 'marker-start', 'marker-mid', 'marker-end', 'color-profile', 'cursor'))
        raw = ('<?xml version="1.0" encoding="utf-8"?>' + SVG.format(f'<rect width="10" height="10" {attrs} fill="red"/>')).encode()
        with patch('cairosvg.url.urlopen', side_effect=AssertionError('external I/O forbidden')) as external:
            root = gdv.safe_svg_bytes(raw)
            self.assertEqual(root[0].get('marker-start'), 'url(#missing)')
            self.assertTrue(gdv.convert_svg(raw, 'png').startswith(b'\x89PNG'))
            self.assertTrue(gdv.convert_svg(raw, 'pdf').startswith(b'%PDF'))
            self.assertEqual(external.call_count, 0)
        # This does not introduce support for SVG marker elements.
        self.reject_without_io(SVG.format('<defs><marker id="m"/></defs>').encode(), '不支持的 active/外部元素')

    def test_embedded_png_jpeg_positive_and_official_font_import_policy(self):
        from PIL import Image
        for kind, format in (('png', 'PNG'), ('jpeg', 'JPEG')):
            data = io.BytesIO()
            Image.new('RGB', (2, 2), 'red').save(data, format=format)
            uri = f'data:image/{kind};base64,' + base64.b64encode(data.getvalue()).decode()
            raw = SVG.format(f'<style>@import url("https://www.ncbi.nlm.nih.gov/projects/sviewer/css/svg_fonts.css");</style><image href="{uri}" width="2" height="2"/>').encode()
            before = bytes(raw)
            with patch('cairosvg.url.urlopen', side_effect=AssertionError('external I/O forbidden')) as external:
                self.assertTrue(gdv.convert_svg(raw, 'png').startswith(b'\x89PNG'))
                self.assertEqual(external.call_count, 0)
            self.assertEqual(raw, before)


if __name__ == '__main__':
    unittest.main()
