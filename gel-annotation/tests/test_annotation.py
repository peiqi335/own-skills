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
from unittest.mock import patch
from pathlib import Path

from PIL import Image, ImageDraw

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
        self.directory = Path(tempfile.mkdtemp(prefix='gel-regression-', dir='/tmp/opencode'))
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

    def test_sample_identity_is_independent_of_display_and_legacy_name(self):
        spec = copy.deepcopy(self.spec)
        lanes = spec['groups'][0]['lanes']
        lanes[0].update(sample_id='real-rabbit', display_label='兔2')
        lanes[1].update(sample_id='real-rabbit', display_label='兔4', loading_order=1)
        with patch.object(annotator, 'centered', wraps=annotator.centered) as text:
            self.render(spec)
        labels = [call.args[3] for call in text.call_args_list]
        self.assertIn('兔2', labels)
        self.assertIn('兔4', labels)
        self.assertNotIn('real-rabbit', labels)
        payload = json.loads(Path(spec['out']).with_suffix('.annotation-manifest.json').read_text())
        mapping = payload['sample_mapping']
        self.assertEqual([m['physical_index'] for m in mapping], [1, 2, 3, 4])
        self.assertEqual(mapping[1]['labels'][0]['sample_id'], mapping[2]['labels'][0]['sample_id'])
        self.assertEqual(mapping[2]['labels'][0]['loading_order'], 1)

    def test_minimal_hides_parameters_without_moving_geometry(self):
        spec = copy.deepcopy(self.spec)
        spec.update(annotation_profile='report_minimal', date='2026-09-08', primer_name='Rabbit-F/R')
        spec['groups'][0]['bar'] = True
        spec['groups'].append(dict(control='NTC', head='NTC大字', param='浓度',
                                   lanes=[dict(index=3, display_label='NTC')]))
        with patch.object(annotator, 'centered', wraps=annotator.centered) as text:
            image = self.render(spec)
        labels = [call.args[3] for call in text.call_args_list]
        self.assertNotIn('条件', labels)
        self.assertNotIn('浓度', labels)
        self.assertNotIn('NTC大字', labels)
        self.assertEqual(labels.count('NTC'), 1)
        self.assertIn('2026-09-08 Rabbit-F/R', labels)
        self.assertEqual(image.getpixel((600, 600)), annotator.COLORS['purple'])
        self.assertEqual(image.getpixel((600, 258)), (60, 60, 60))
        with self.assertRaises(SystemExit):
            self.render(dict(spec, date=''))

    def test_minimal_pc_uses_only_spec_labels(self):
        for species, label in [('rabbit', 'PC'), ('human', 'PC/9948')]:
            spec = dict(self.spec, annotation_profile='report_minimal', date='9.8', primer_name='引物',
                        out=str(self.directory / f'{species}（标注）.png'),
                        groups=[dict(control='PC', species=species, head='PC大字', param='浓度',
                                     lanes=[dict(index=1, display_label=label), dict(index=2, display_label=label)])])
            with patch.object(annotator, 'centered', wraps=annotator.centered) as text:
                self.render(spec)
            labels = [call.args[3] for call in text.call_args_list]
            self.assertEqual(labels.count(label), 1)
            self.assertNotIn('PC大字', labels)

    def test_manifest_hashes_and_relative_spec_replay(self):
        old = self.directory / 'old.png'
        Image.new('RGB', (10, 10), (1, 2, 3)).save(old)
        old_hash = annotator.sha256(old)
        spec = dict(self.spec, source_annotations=[dict(path=str(old), sha256=old_hash)],
                    date_evidence={'kind': 'specified', 'value': '9.8'},
                    patch_record={'changes': [{'row': 1, 'index': 1, 'field': 'display_label',
                                               'before': '兔2', 'after': '兔2′'}],
                                  'geometry_evidence': 'verified prior spec'})
        dest = self.directory / 'archive' / 'manifest.json'
        out = annotator.annotate(spec, self.directory, None, manifest=dest)
        payload = json.loads(dest.read_text())
        self.assertEqual(payload['sources'][0]['sha256'], self.before)
        self.assertEqual(payload['sources'][1]['sha256'], old_hash)
        self.assertEqual(payload['output']['sha256'], annotator.sha256(out))
        self.assertFalse(Path(payload['spec']['src']).is_absolute())
        self.assertEqual((dest.parent / payload['spec']['src']).resolve(), self.source)
        self.assertEqual(payload['patch_record'], spec['patch_record'])
        replay = payload['spec']
        replay['out'] = '../replay（标注）.png'
        second = annotator.annotate(replay, dest.parent, None)
        self.assertEqual(annotator.sha256(second), annotator.sha256(out))
        self.assertEqual(annotator.sha256(old), old_hash)
        # Move the archive tree to a different root, retaining relative paths.
        moved = self.directory / 'relocated' / 'archive'
        moved.mkdir(parents=True)
        for record in payload['sources']:
            target = moved / record['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((dest.parent / record['path']).read_bytes())
        replay['out'] = '../cli-replay（标注）.png'
        spec_path = moved / 'spec.json'
        spec_path.write_text(json.dumps(replay, ensure_ascii=False), encoding='utf-8')
        result = subprocess.run([sys.executable, str(SCRIPTS / 'annotate_gel.py'), str(spec_path),
                                 '--repo', str(moved), '--manifest', 'cli-manifest.json'],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        archived = json.loads((moved / 'cli-manifest.json').read_text())
        self.assertEqual(archived['output']['sha256'], annotator.sha256(out))
        self.assertEqual(archived['sources'][0]['sha256'], self.before)

    def test_rgb_source_pixels_and_legacy_display_equivalence(self):
        self.source = self.directory / 'rgb.png'
        raw = Image.new('RGB', (1600, 1600), (23, 47, 89))
        raw.save(self.source)
        self.before = annotator.sha256(self.source)
        self.spec['src'] = str(self.source)
        legacy = self.render()
        explicit = copy.deepcopy(self.spec)
        explicit['out'] = str(self.directory / 'explicit（标注）.png')
        for item in explicit['groups'][0]['lanes']:
            item['display_label'] = item['name']
        self.assertEqual(legacy.tobytes(), self.render(explicit).tobytes())
        self.assertEqual(legacy.crop((1100, 700, 1600, 1600)).tobytes(),
                         raw.crop((1100, 700, 1600, 1600)).tobytes())

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

    def _snapshot(self):
        return {str(p.relative_to(self.directory)):
                ('link', str(p.readlink())) if p.is_symlink() else
                ('dir',) if p.is_dir() else ('file', p.read_bytes())
                for p in self.directory.rglob('*')}

    def _reject_without_writes(self, spec=None, **kwargs):
        before = self._snapshot()
        with patch.object(Image.Image, 'save') as save, self.assertRaises(SystemExit):
            annotator.annotate(spec or self.spec, self.directory, None, **kwargs)
        save.assert_not_called()
        self.assertEqual(before, self._snapshot())

    def test_protected_input_paths_reject_output_and_manifest(self):
        path = self._write_spec(self.spec, 'input.json')
        self._reject_without_writes(dict(self.spec, overwrite=True), manifest=path, protected_inputs=[path])
        disguised = self._write_spec(self.spec, 'input（标注）.png')
        self._reject_without_writes(dict(self.spec, out=str(disguised), overwrite=True),
                                    protected_inputs=[disguised])
        before = self._snapshot()
        result = subprocess.run([sys.executable, str(SCRIPTS / 'annotate_gel.py'), str(path),
                                 '--repo', str(self.directory), '--manifest', str(path), '--overwrite'],
                                capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('protected inputs', result.stderr)
        self.assertEqual(before, self._snapshot())

    def test_manifest_rejects_non_json_and_unowned_json(self):
        for filename, content in [('unrelated-original.png', self.source.read_bytes()),
                                  ('unrelated.json', b'{"note":"original record"}')]:
            path = self.directory / filename
            path.write_bytes(content)
            self._reject_without_writes(dict(self.spec, overwrite=True), manifest=path)
        self._reject_without_writes(manifest=self.directory / 'new.png')

    def test_unowned_output_rejected_even_with_annotation_name(self):
        out = Path(self.spec['out'])
        Image.new('RGB', (20, 20), 'red').save(out)
        self._reject_without_writes(dict(self.spec, overwrite=True))

    def test_candidate_overwrite_requires_matching_pair_and_hash(self):
        self.render()
        dest = Path(self.spec['out']).with_suffix('.annotation-manifest.json')
        original = dest.read_bytes()
        payload = json.loads(original)
        for section, field, value in [('output', 'sha256', '0' * 64),
                                      ('output', 'path', 'other（标注）.png'),
                                      ('spec', 'src', 'other.jpg')]:
            changed = copy.deepcopy(payload)
            changed[section][field] = value
            dest.write_text(json.dumps(changed), encoding='utf-8')
            self._reject_without_writes(dict(self.spec, overwrite=True))
        dest.write_bytes(original)
        changed_source = self.directory / 'different.jpg'
        Image.new('RGB', (1600, 1600), (70, 70, 70)).save(changed_source)
        self._reject_without_writes(dict(self.spec, overwrite=True, src=str(changed_source)))
        candidate = copy.deepcopy(self.spec)
        candidate.update(overwrite=True)
        candidate['groups'][0]['head'] = '新标签'
        self.render(candidate)
        refreshed = json.loads(dest.read_text())
        self.assertEqual(refreshed['output']['sha256'], annotator.sha256(Path(self.spec['out'])))
        self.assertNotEqual(refreshed['output']['sha256'], payload['output']['sha256'])
        # Actual image tampering, not just a bad manifest hash.
        Image.new('RGB', (1600, 1600), 'blue').save(Path(self.spec['out']))
        self._reject_without_writes(candidate)

    def test_source_annotation_collisions_and_bad_hash(self):
        old = self.directory / 'old（标注）.png'
        Image.new('RGB', (20, 20), 'green').save(old)
        record = dict(path=str(old), sha256=annotator.sha256(old))
        spec = dict(self.spec, overwrite=True, source_annotations=[record])
        self._reject_without_writes(dict(spec, out=str(old)))
        # A JSON-named source must also stay protected.
        json_source = self.directory / 'annotation.json'
        json_source.write_bytes(old.read_bytes())
        self._reject_without_writes(dict(spec, source_annotations=[dict(path=str(json_source))]),
                                    manifest=json_source)
        self._reject_without_writes(dict(spec, source_annotations=[dict(record, sha256='0' * 64)]))

    def test_write_paths_reject_file_and_ancestor_symlinks(self):
        file_link = self.directory / 'link（标注）.png'
        file_link.symlink_to(self.source)
        self._reject_without_writes(dict(self.spec, out=str(file_link), overwrite=True))
        manifest_link = self.directory / 'link.json'
        manifest_link.symlink_to(self.source)
        self._reject_without_writes(dict(self.spec, overwrite=True), manifest=manifest_link)
        real = self.directory / 'real'
        real.mkdir()
        alias = self.directory / 'alias'
        alias.symlink_to(real, target_is_directory=True)
        self._reject_without_writes(dict(self.spec, out=str(alias / 'new（标注）.png')))
        self._reject_without_writes(manifest=alias / 'new.json')
        self._reject_without_writes(review_dir=alias / 'review')
        self._reject_without_writes(dict(self.spec, out=str(alias / '..' / 'new（标注）.png')))
        dangling = self.directory / 'dangling.json'
        dangling.symlink_to(self.directory / 'missing.json')
        self._reject_without_writes(manifest=dangling)

    def test_review_path_collisions_and_existing_files(self):
        review = self.directory / 'review'
        spec = dict(self.spec, source_sha256=self.before)
        self._reject_without_writes(spec, review_dir=review, manifest=review / 'review.json')
        self._reject_without_writes(dict(spec, out=str(review / 'candidate（标注）.png')), review_dir=review)
        review.mkdir()
        old = review / 'row1_wells_p1.png'
        Image.new('RGB', (10, 10), 'red').save(old)
        self._reject_without_writes(dict(spec, source_annotations=[dict(path=str(old))]), review_dir=review)
        self._reject_without_writes(spec, review_dir=review)
        input_spec = self._write_spec(spec, 'review/input.json')
        self._reject_without_writes(spec, review_dir=review, protected_inputs=[input_spec])

    def test_minimal_control_requires_replacement_labels(self):
        for control, species in [('NTC', 'rabbit'), ('NTC', 'human'), ('PC', 'rabbit'), ('PC', 'human')]:
            for lane in [dict(index=1), dict(index=1, display_label=None),
                         dict(index=1, display_label=''), dict(index=1, display_label='   ')]:
                spec = dict(self.spec, annotation_profile='report_minimal', date='9.8', primer_name='引物',
                            groups=[dict(control=control, species=species, head=control, lanes=[lane])])
                with self.subTest(control=control, species=species, lane=lane):
                    self._reject_without_writes(spec)
        # Default profile keeps the original head-only control presentation.
        spec = dict(self.spec, groups=[dict(control='NTC', head='NTC', lanes=[dict(index=1)])])
        with patch.object(annotator, 'centered', wraps=annotator.centered) as text:
            self.render(spec)
        self.assertIn('NTC', [call.args[3] for call in text.call_args_list])

    def test_display_label_missing_null_and_empty(self):
        for suffix, extra, expected in [('missing', {}, 'PC/9948'),
                                        ('null', {'display_label': None}, 'PC/9948'),
                                        ('empty', {'display_label': ''}, '')]:
            lane = dict(index=1, name='PC/9948', **extra)
            self.assertEqual(annotator.display_label(lane), expected)
            spec = dict(self.spec, out=str(self.directory / f'{suffix}（标注）.png'),
                        groups=[dict(lanes=[lane])])
            with patch.object(annotator, 'centered', wraps=annotator.centered) as text:
                self.render(spec)
            labels = [call.args[3] for call in text.call_args_list]
            self.assertEqual('PC/9948' in labels, bool(expected))

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
        with patch.object(scanner, 'TMP_ROOT', Path('/tmp/opencode')):
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

    def test_detect_wells_outputs_valid_pitch_and_lanes(self):
        dest = self.directory / "detect-wells-test"
        dest.mkdir(parents=True, exist_ok=True)
        # self.source 是 600x400 的测试图，我们在 y=180-220 之间画几个暗坑模拟孔槽
        test_im = Image.new("L", (800, 300), color=150)
        draw = ImageDraw.Draw(test_im)
        # 画 5 个孔槽，间距 100px (x = 150, 250, 350, 450, 550)
        for cx in [150, 250, 350, 450, 550]:
            draw.rectangle((cx - 25, 80, cx + 25, 120), fill=40)
            # 孔壁高光
            draw.rectangle((cx - 30, 80, cx - 26, 120), fill=220)
            draw.rectangle((cx + 26, 80, cx + 30, 120), fill=220)
        test_src = self.directory / "test_gel_wells.png"
        test_im.save(test_src)

        out_buf = io.StringIO()
        with contextlib.redirect_stdout(out_buf):
            scanner.cmd_detect_wells(test_src, dest, "80,120", 100, 600)
        data = json.loads(out_buf.getvalue())
        self.assertEqual(data["stage"], "detect-wells")
        self.assertAlmostEqual(data["pitch"], 100, delta=5)
        self.assertGreaterEqual(len(data["lane_x"]), 4)
        self.assertTrue((dest / "detect_wells.jpg").is_file())

    def test_detect_bp_outputs_peaks_and_guide(self):
        dest = self.directory / "detect-bp-test"
        dest.mkdir(parents=True, exist_ok=True)
        test_im = Image.new("L", (300, 600), color=50)
        draw = ImageDraw.Draw(test_im)
        # 在 x=150 处画 7 条水平亮带 (y = 100, 160, 220, 290, 360, 430, 510)
        band_ys = [100, 160, 220, 290, 360, 430, 510]
        for idx, by in enumerate(band_ys):
            # 290 设为最亮
            brightness = 250 if by == 290 else 180
            draw.rectangle((120, by - 5, 180, by + 5), fill=brightness)
        test_src = self.directory / "test_gel_bp.png"
        test_im.save(test_src)

        out_buf = io.StringIO()
        with contextlib.redirect_stdout(out_buf):
            scanner.cmd_detect_bp(test_src, dest, marker_x=150, y_range="80,550", n_bands=7)
        data = json.loads(out_buf.getvalue())
        self.assertEqual(data["stage"], "detect-bp")
        self.assertEqual(data["n_bands"], 7)
        detected_ys = [b["y"] for b in data["bands"]]
        for target_y in band_ys:
            self.assertTrue(any(abs(dy - target_y) <= 5 for dy in detected_ys))
        # 验证 200bp 最亮标记
        strongest = [b for b in data["bands"] if b["strongest"]]
        self.assertEqual(len(strongest), 1)
        self.assertAlmostEqual(strongest[0]["y"], 290, delta=5)
        self.assertTrue((dest / "detect_bp.jpg").is_file())

    def test_review_quality_audit_detects_offcenter_and_bp_drift(self):
        # 构造一个偏心明显的 row 和歪斜 bp
        row = {
            "well": 100,
            "lane_x": [150, 250, 350],
            "marker_indices": [0],
            "groups": [],
            "bp_guide": [{"label": "200bp", "y": 400}]  # 在空隙黑区
        }
        test_im = Image.new("RGB", (600, 500), color=(40, 40, 40))
        rev_dir = self.directory / "audit-test-rev"
        payload = annotator.annotation_review(
            test_im, test_im, [row], 0, rev_dir, self.directory / "test_out.png", "fakehash", []
        )
        self.assertIn("quality_audit", payload)
        self.assertIn("rows", payload["quality_audit"])
        audit_row = payload["quality_audit"]["rows"][0]
        self.assertEqual(len(audit_row["wells"]), 3)
        self.assertEqual(len(audit_row["bp"]), 1)
        # 验证 review.json 成功落盘
        self.assertTrue((rev_dir / "review.json").is_file())


if __name__ == '__main__':
    unittest.main()
