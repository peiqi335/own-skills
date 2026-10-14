"""N1 restricted static SVG boundary; no GDV renderer or visual validation."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_site as site
import gdv_delivery as gdv
from evidence import sha256
from test_build_site import subset
from test_site_corrections import NEW

BAD = (
    b"<svg><rect fill='u\\72l(https://example.invalid/p.svg#paint)'/></svg>",
    b"<svg><rect fill='&#117;rl(https://example.invalid/p.svg#paint)'/></svg>",
    b'<?xml-stylesheet type="text/css" href="https://example.invalid/p.css"?><svg/>',
)
ATTRS = ('fill', 'stroke', 'filter', 'clip-path', 'mask', 'marker',
         'marker-start', 'marker-mid', 'marker-end', 'cursor', 'unknown-resource')


class StaticN1(unittest.TestCase):
    def test_three_oracle_counterexamples(self):
        for raw in BAD:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                gdv.static_svg(raw)

    def test_all_resource_attributes_entities_escapes_and_unknown_urls(self):
        for attr in ATTRS:
            for value in ('url(https://example.invalid/p.svg#paint)',
                          '&#117;rl(https://example.invalid/p.svg#paint)',
                          'u\\72l(https://example.invalid/p.svg#paint)',
                          'URL (https://example.invalid/p.svg#paint)', 'url(#p'):
                raw = f'<svg><rect {attr}="{value}"/></svg>'.encode()
                with self.subTest(attr=attr, value=value), self.assertRaises(ValueError):
                    gdv.static_svg(raw)

    def test_local_urls_and_normal_xml_declaration(self):
        for attr in ATTRS:
            for value in ('url(#paint)', "url( '#paint' )", 'URL ( #paint )'):
                raw = f'<?xml version="1.0" encoding="UTF-8"?><svg><defs><pattern id="paint"/></defs><rect {attr}="{value}"/></svg>'.encode()
                with self.subTest(attr=attr, value=value):
                    gdv.static_svg(raw)
        gdv.static_svg(b'<svg><style>rect{fill:url(#paint)}</style><use href="#paint"/></svg>')
        for raw in (b'<svg><?other value?></svg>', b'<svg><?xml-stylesheet href="x"?></svg>',
                    b'<svg><image href="#"/></svg>'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                gdv.static_svg(raw)

    def test_embedded_raster_contract_not_nested_svg_or_other_elements(self):
        png = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()
        jpeg = 'data:image/jpeg;base64,' + base64.b64encode(b'\xff\xd8\xff').decode()
        for value in (png, jpeg):
            gdv.static_svg(f'<svg><image href="{value}"/></svg>'.encode())
        for tag, value in (('use', png), ('image', 'data:image/svg+xml;base64,PHN2Zy8+'),
                           ('image', 'data:image/png;base64,YmFk'), ('image', 'relative.png'),
                           ('image', 'https://example.invalid/p.png')):
            with self.subTest(tag=tag, value=value), self.assertRaises(ValueError):
                gdv.static_svg(f'<svg><{tag} href="{value}"/></svg>'.encode())

    @unittest.skipUnless(NEW.is_dir(), 'real corrected config unavailable')
    def test_builder_rejects_before_first_write_even_with_rendered_and_valid_hash(self):
        base = Path(tempfile.mkdtemp(prefix='site-n1-', dir='/tmp/opencode'))
        path, manifest = subset(NEW, base / 'config')
        g = manifest['gdv'][0]
        g['mode'] = 'rendered'
        record = next(r['input'] for r in g['resources'] if r['output'].endswith('.svg'))
        for i, raw in enumerate(BAD):
            (path.parent / record['path']).write_bytes(raw)
            record['sha256'] = sha256(raw)
            path.write_text(json.dumps(manifest))
            output = base / ('rejected-' + str(i))
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                site.build(path, output)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
