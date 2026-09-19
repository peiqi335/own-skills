"""Geometry and source-preservation regressions; visual review is still required."""
import contextlib
import copy
import importlib.util
import io
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


annotator = module('annotate_gel')
scanner = module('scan_gel')
reviewer = module('review_gel')


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

    def test_equal_spacing_is_not_rejected_as_provenance(self):
        # Equal spacing is a valid input; visual/source checks decide whether
        # these coordinates are correct for a particular gel.
        im = self.render(dict(self.spec, lane_x=[300, 500, 700, 900]))
        self.assertEqual(im.size, (1600, 1600))

    def test_split_boxes_cover_edges_without_gaps_or_enlargement(self):
        bound = (3, 5, 253, 117)
        boxes = reviewer.split_boxes(bound, max_width=100, max_height=50, overlap=16)
        self.assertGreater(len(boxes), 1)
        for x0, y0, x1, y1 in boxes:
            self.assertGreaterEqual(x0, bound[0])
            self.assertGreaterEqual(y0, bound[1])
            self.assertLessEqual(x1, bound[2])
            self.assertLessEqual(y1, bound[3])
            self.assertLessEqual(x1 - x0, 100)
            self.assertLessEqual(y1 - y0, 50)
        # Pixel-cell coverage catches both outer-edge omissions and gaps
        # between adjacent panels while allowing intentional overlap.
        for y in range(bound[1], bound[3]):
            for x in range(bound[0], bound[2]):
                self.assertTrue(
                    any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in boxes),
                    (x, y, boxes),
                )
        # Every internal panel boundary must be crossed by overlapping panels
        # in the other dimension, so a read cannot lose an edge between pages.
        x_edges = sorted({edge for box in boxes for edge in (box[0], box[2])})
        for cut in x_edges[1:-1]:
            self.assertTrue(
                any(
                    a[0] < cut < a[2]
                    and b[0] < cut < b[2]
                    and max(a[1], b[1]) < min(a[3], b[3])
                    for i, a in enumerate(boxes)
                    for b in boxes[i + 1:]
                ),
                ("x boundary", cut, boxes),
            )
        y_edges = sorted({edge for box in boxes for edge in (box[1], box[3])})
        for cut in y_edges[1:-1]:
            self.assertTrue(
                any(
                    a[1] < cut < a[3]
                    and b[1] < cut < b[3]
                    and max(a[0], b[0]) < min(a[2], b[2])
                    for i, a in enumerate(boxes)
                    for b in boxes[i + 1:]
                ),
                ("y boundary", cut, boxes),
            )
        self.assertIn(bound[0], [box[0] for box in boxes])
        self.assertIn(bound[2], [box[2] for box in boxes])
        self.assertIn(bound[1], [box[1] for box in boxes])
        self.assertIn(bound[3], [box[3] for box in boxes])

    def test_write_panels_preserves_raw_pixels_and_padding_coordinates(self):
        width, height = 96, 72
        original = Image.new('RGB', (width, height))
        for y in range(height):
            for x in range(width):
                original.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
        padding = 12
        raw = Image.new('RGB', (width, height + padding), (0, 0, 0))
        raw.paste(original, (0, padding))
        overlay = raw.copy()
        overlay.putpixel((35, 28 + padding), (255, 0, 0))
        box = (20, 18 + padding, 56, 50 + padding)
        dest = self.directory / 'review-panels'
        panels = reviewer.write_panels(
            raw, overlay, dest, 'candidate', box, padding=padding, lane_x=[35]
        )
        self.assertTrue(panels)
        record = panels[0]
        self.assertEqual(tuple(record['source_box']), (20, 18, 56, 50))
        self.assertEqual(tuple(record['canvas_box']), box)
        self.assertEqual(record['scale'], 1)
        with Image.open(record['path']) as image:
            # The panel is a vertical raw-source/annotated comparison at 1:1.
            raw_offset = tuple(record.get('raw_offset', (0, 0)))
            overlay_offset = tuple(record.get('overlay_offset', (0, 32)))
            self.assertGreaterEqual(image.width, raw_offset[0] + 36)
            self.assertGreaterEqual(image.height, overlay_offset[1] + 32)
            self.assertEqual(image.getpixel((raw_offset[0] + 15, raw_offset[1] + 10)), original.getpixel((35, 28)))
            self.assertEqual(image.getpixel((overlay_offset[0] + 15, overlay_offset[1] + 10)), (255, 0, 0))

    def _review_spec(self, **updates):
        spec = copy.deepcopy(self.spec)
        spec['source_sha256'] = self.before
        spec.update(
            bp_guide=[dict(label='已知尺寸', y=900)],
            bp_source='test fixture',
            bp_label_x=100,
            bp_arrow_x=300,
        )
        spec.update(updates)
        return spec

    def test_review_manifest_contains_panel_metadata_and_hashes(self):
        spec = self._review_spec(out=str(self.directory / 'review（标注）.png'))
        review_dir = self.directory / 'review'
        out = annotator.annotate(spec, self.directory, None, review_dir)
        manifest_path = review_dir / 'review.json'
        self.assertEqual(Path(out).resolve(), Path(spec['out']).resolve())
        self.assertTrue(manifest_path.is_file())
        payload = json.loads(manifest_path.read_text(encoding='utf-8'))
        self.assertEqual(payload['out'], str(Path(out)))
        self.assertEqual(payload['src_sha256'], self.before)
        self.assertTrue(payload['geometry_sha256'])
        categories = {panel['category'] for panel in payload['panels']}
        self.assertTrue({'wells', 'labels', 'bp'} <= categories)
        for panel in payload['panels']:
            self.assertTrue(Path(panel['path']).is_file())
            self.assertIn('source_box', panel)
            self.assertIn('canvas_box', panel)
            self.assertEqual(panel['scale'], 1)

    def test_review_source_hash_mismatch_is_rejected(self):
        spec = self._review_spec(
            out=str(self.directory / 'mismatch（标注）.png'),
            source_sha256='0' * 64,
        )
        with self.assertRaises(SystemExit):
            annotator.annotate(spec, self.directory, None, self.directory / 'review-mismatch')

    def test_labels_review_panels_cover_bracket_shape_and_padding(self):
        spec = dict(
            src=str(self.source),
            out=str(self.directory / 'bracket-review（标注）.png'),
            top_padding=80,
            well=600,
            lane_x=[400, 800],
            groups=[dict(head='组', lanes=[dict(index=0, name='样本1'), dict(index=1, name='样本2')])],
            source_sha256=self.before,
        )
        review_dir = self.directory / 'bracket-review'
        annotator.annotate(spec, self.directory, None, review_dir)
        payload = json.loads((review_dir / 'review.json').read_text(encoding='utf-8'))
        labels = [panel for panel in payload['panels'] if panel['category'] == 'labels']
        self.assertTrue(labels)

        # The default bracket spans x_first-42 .. x_last+42 and
        # well-220 .. well-100 in source coordinates.
        source_bracket = (358, 380, 842, 500)
        canvas_bracket = (source_bracket[0], source_bracket[1] + 80,
                          source_bracket[2], source_bracket[3] + 80)
        self.assertLessEqual(min(panel['source_box'][0] for panel in labels), source_bracket[0])
        self.assertLessEqual(min(panel['source_box'][1] for panel in labels), source_bracket[1])
        self.assertGreaterEqual(max(panel['source_box'][2] for panel in labels), source_bracket[2])
        self.assertGreaterEqual(max(panel['source_box'][3] for panel in labels), source_bracket[3])
        self.assertLessEqual(min(panel['canvas_box'][0] for panel in labels), canvas_bracket[0])
        self.assertLessEqual(min(panel['canvas_box'][1] for panel in labels), canvas_bracket[1])
        self.assertGreaterEqual(max(panel['canvas_box'][2] for panel in labels), canvas_bracket[2])
        self.assertGreaterEqual(max(panel['canvas_box'][3] for panel in labels), canvas_bracket[3])

    def test_review_directory_rejects_original_record_paths_before_save(self):
        spec = self._review_spec(out=str(self.directory / 'blocked-review（标注）.png'))
        for record_dir in ('1.原始资料', '3.记录'):
            with self.subTest(record_dir=record_dir), self.assertRaises(SystemExit):
                annotator.annotate(
                    spec,
                    self.directory,
                    None,
                    self.directory / record_dir / 'review',
                )
            self.assertFalse(Path(spec['out']).exists())

    def test_repeated_label_collision_is_rejected(self):
        spec = dict(
            src=str(self.source),
            out=str(self.directory / 'collision（标注）.png'),
            well=600,
            lane_x=[600, 601],
            groups=[
                dict(lanes=[dict(index=0, name='重复标签很长')]),
                dict(lanes=[dict(index=1, name='重复标签很长')]),
            ],
        )
        with self.assertRaises(SystemExit):
            annotator.annotate(spec, self.directory, None)

    def test_out_of_bounds_primitives_are_rejected(self):
        bracket = dict(
            src=str(self.source),
            out=str(self.directory / 'bracket（标注）.png'),
            well=600,
            lane_x=[10, 20],
            groups=[dict(lanes=[dict(index=0), dict(index=1)])],
        )
        with self.subTest(primitive='bracket'), self.assertRaises(SystemExit):
            annotator.annotate(bracket, self.directory, None)

        arrow = self._review_spec(
            out=str(self.directory / 'arrow（标注）.png'),
            bp_arrow_x=-1,
        )
        with self.subTest(primitive='arrow'), self.assertRaises(SystemExit):
            annotator.annotate(arrow, self.directory, None)

    def test_bp_target_x_must_be_inside_canvas(self):
        spec = self._review_spec(
            out=str(self.directory / 'bp-target（标注）.png'),
            bp_target_x=-1,
        )
        with self.assertRaises(SystemExit):
            annotator.annotate(spec, self.directory, None)

    def test_rows_cannot_mix_top_level_geometry(self):
        spec = dict(
            src=str(self.source),
            out=str(self.directory / 'mixed（标注）.png'),
            well=600,
            lane_x=[400, 600, 800, 1000],
            rows=[copy.deepcopy(self.row)],
        )
        with self.assertRaises(SystemExit):
            annotator.annotate(spec, self.directory, None)

    def _write_spec(self, spec, name='scan-spec.json'):
        path = self.directory / name
        path.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
        return path

    def _scan_lanes(self, spec_path, out_dir, extra=None):
        command = [
            sys.executable,
            str(SCRIPTS / 'scan_gel.py'),
            '--repo', str(self.directory),
            '--out-dir', str(out_dir),
            'lanes',
            '--spec', str(spec_path),
        ]
        command.extend(extra or [])
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def test_scan_spec_lanes_preserves_float_geometry_and_matches_review_hash(self):
        rows = [
            dict(well=240, lane_x=[101.25, 201.5, 301.75],
                 lane_y=[239.5, 241.25, 240.75], groups=[]),
            dict(well=640, lane_x=[102.5, 202.75, 303.25],
                 lane_y=[639.25, 640.5, 641.75], groups=[]),
        ]
        spec = dict(
            src=str(self.source),
            out=str(self.directory / 'scan-review（标注）.png'),
            source_sha256=self.before,
            rows=rows,
        )
        spec_path = self._write_spec(spec)
        result = self._scan_lanes(spec_path, self.directory / 'scan-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(records), 2)
        self.assertEqual([record['lane_x'] for record in records], [row['lane_x'] for row in rows])
        self.assertEqual([record['lane_y'] for record in records], [row['lane_y'] for row in rows])
        self.assertTrue(all(record['src_sha256'] == self.before for record in records))
        self.assertTrue(all(record['geometry_sha256'] for record in records))
        self.assertTrue(all(Path(panel['path']).is_file()
                            for record in records for panel in record['review_panels']))

        annotator.annotate(spec, self.directory, None, self.directory / 'annotate-review')
        manifest = json.loads(
            (self.directory / 'annotate-review' / 'review.json').read_text(encoding='utf-8')
        )
        self.assertTrue(all(record['geometry_sha256'] == manifest['geometry_sha256'] for record in records))

    def test_scan_spec_lanes_requires_hash_and_rejects_manual_geometry(self):
        rows = [dict(well=240, lane_x=[101.25, 201.5], lane_y=[239.5, 240.75], groups=[])]
        valid = dict(src=str(self.source), out=str(self.directory / 'unused（标注）.png'), rows=rows)
        missing_hash = self._write_spec(valid, 'missing-hash.json')
        result = self._scan_lanes(missing_hash, self.directory / 'missing-hash-run')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('source_sha256', result.stderr)

        valid['source_sha256'] = self.before
        mixed = self._write_spec(valid, 'mixed-manual.json')
        result = self._scan_lanes(
            mixed,
            self.directory / 'mixed-manual-run',
            ['--xs', '101.25,201.5'],
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--spec cannot be mixed', result.stderr)

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
