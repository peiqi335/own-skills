"""Geometry and source-preservation regressions; visual review is still required."""
import contextlib
import copy
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


annotator = module('annotate_gel')
scanner = module('scan_gel')


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        # Retain artifacts for inspection; tests never remove vault files.
        self.directory = Path(tempfile.mkdtemp(prefix='gel-regression-'))
        self.source = self.directory / 'source.jpg'
        Image.new('RGB', (1600, 1600), (60, 60, 60)).save(self.source)
        self.before = annotator.sha256(self.source)
        self.row = dict(well=600, lane_x=[400, 600, 800, 1000], marker_indices=[0],
                        groups=[dict(head='兔', param='条件', lanes=[dict(index=1, name='兔2′'), dict(index=2, name='兔4′')])])
        self.spec = dict(self.row, src=str(self.source), out=str(self.directory / 'test（标注）.png'))

    def render(self, spec=None):
        result = annotator.annotate(spec or self.spec, self.directory, None)
        self.assertEqual(annotator.sha256(self.source), self.before)
        with Image.open(result) as image:
            return image.copy()

    def test_legacy_single_row_and_blank_well(self):
        im = self.render()
        self.assertEqual(im.size, (1600, 1600))
        self.assertEqual(im.mode, 'RGB')
        self.assertEqual(im.getpixel((600, 600)), annotator.COLORS['purple'])
        self.assertEqual(im.getpixel((1000, 600)), (60, 60, 60))
        with self.assertRaises(SystemExit):
            self.render()

    def test_rows_padding_and_individual_endpoints(self):
        row2 = dict(well=1250, lane_x=[400, 600, 800], lane_y=[1240, 1255, 1265],
                    groups=[dict(color='cyan', head='V16S-U', lanes=[dict(index=1, name='样本')])])
        spec = dict(src=str(self.source), out=self.spec['out'], top_padding=100, rows=[self.row, row2])
        im = self.render(spec)
        self.assertEqual(im.size, (1600, 1700))
        self.assertEqual(im.getpixel((600, 1355)), annotator.COLORS['cyan'])
        self.assertEqual(im.getpixel((600, 1365)), (60, 60, 60))
        self.assertEqual(im.getpixel((1200, 20)), (0, 0, 0))
        self.assertEqual(im.getpixel((1200, 1500)), (60, 60, 60))

    def test_invalid_coordinates_and_assignments(self):
        for updates in [dict(lane_x=[600, 400]), dict(lane_y=[600]),
                        dict(marker_indices=[1]), dict(marker_indices=[99]),
                        dict(font_scale=0), dict(lane_y=[-1, 2, 3, 4])]:
            with self.subTest(updates=updates), self.assertRaises(SystemExit):
                self.render(dict(self.spec, **updates))
        self.assertFalse(Path(self.spec['out']).exists())

    def test_clipped_text_rejected(self):
        with self.assertRaises(SystemExit):
            self.render(dict(self.spec, y=dict(head=-100)))
        self.assertFalse(Path(self.spec['out']).exists())

    def test_padding_handles_negative_source_text_position(self):
        im = self.render(dict(self.spec, top_padding=160, y=dict(head=-80)))
        self.assertEqual(im.size, (1600, 1760))

    def test_right_marker_bp(self):
        spec = copy.deepcopy(self.spec)
        spec.update(marker_indices=[0, 3], bp_marker_index=3,
                    bp_guide=[dict(label='已知尺寸', y=900)], bp_source='test fixture',
                    bp_label_x=100, bp_arrow_x=300)
        im = self.render(spec)
        self.assertEqual(im.getpixel((970, 900)), annotator.COLORS['red'])

    def test_scan_unique_directories_and_edge_zoom(self):
        a = scanner.out_dir_for(self.source, None)
        b = scanner.out_dir_for(self.source, None)
        self.assertNotEqual(a, b)
        with contextlib.redirect_stdout(io.StringIO()):
            scanner.cmd_zoom(self.source, a, '10,10', 240)
        with Image.open(a / 'zoom_10_10.jpg') as image:
            im = image.copy()
        # Clipped 130-pixel source box scaled to 640 pixels: x=10 -> ~49.
        red, green, blue = im.getpixel((49, 500))
        self.assertGreater(green, red + 80)
        self.assertGreater(blue, red + 80)
        self.assertEqual(annotator.sha256(self.source), self.before)


if __name__ == '__main__':
    unittest.main()
