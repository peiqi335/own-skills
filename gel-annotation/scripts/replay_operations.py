#!/usr/bin/env python3
"""Hash-bound, bounds-checked operation replay; no experiment-specific defaults."""
import argparse
import copy
import json
import locale
import math
import os
import platform
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, __version__ as PILLOW_VERSION, features
from annotate_gel import check_write_path, sha256, input_file, destination_plan


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def environment():
    return dict(python=platform.python_version(), pillow=PILLOW_VERSION,
                **{name: features.version(name) for name in ('freetype2', 'raqm', 'harfbuzz', 'fribidi')},
                raqm_available=features.check('raqm'), locale=locale.setlocale(locale.LC_CTYPE),
                locale_environment={key: os.environ.get(key) for key in ('LANG', 'LC_ALL', 'LC_CTYPE')},
                renderer_sha256=sha256(Path(__file__)))


def resources(spec):
    return [*spec['inputs'].values(), spec['font']] + ([spec['profile']] if spec.get('profile') else []) + ([spec['footer_style']] if spec.get('footer_style') else []) + spec.get('bindings', [])


def checked_resource(record, base):
    path = input_file(base / record['path'])
    if sha256(path) != record['sha256']:
        raise SystemExit(f'resource hash mismatch: {record["path"]}')
    return path


def coords(value, count, integer=False):
    if not isinstance(value, (list, tuple)) or len(value) != count or any(
            type(v) not in (int, float) or not math.isfinite(v) or (integer and type(v) is not int) for v in value):
        raise SystemExit('coordinates must be finite (integer pixel coordinates for crop/paste/rectangle)')
    return list(value)


def rgb(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in value):
        raise SystemExit('fill must be RGB integers in [0,255]')
    return tuple(value)


def box_inside(box, size, inclusive=False):
    box = coords(box, 4, True)
    w, h = size
    x0, y0, x1, y1 = box
    if not (0 <= x0 <= x1 < w and 0 <= y0 <= y1 < h) if inclusive else not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise SystemExit(f'box outside canvas/source: {box} / {size}')
    return box


def render(spec, base, effective=False):
    base = Path(base).absolute()
    normalized = copy.deepcopy(spec)
    for record in resources(spec):
        checked_resource(record, base)
    for binding in spec.get('bindings', []):
        if binding.get('role') == 'identity':
            payload = json.loads(checked_resource(binding, base).read_text())
            entry = next((item for item in payload['items'] if item['primer'] == spec['id']), None)
            if entry is None or entry['date'] != spec['date'] or entry['mapping'] != spec.get('sample_mapping'):
                raise SystemExit('identity/date mapping binding mismatch')
        if binding.get('executor'):
            active = input_file(Path(__file__).with_name(binding['executor']))
            if sha256(active) != binding['sha256']:
                raise SystemExit('active executor/helper hash mismatch')
    inputs = {}
    for role, record in spec['inputs'].items():
        with Image.open(base / record['path']) as source:
            inputs[role] = source.convert('RGB')
    font = checked_resource(spec['font'], base)
    footer_style = json.loads(checked_resource(spec['footer_style'], base).read_text()) if spec.get('footer_style') else {}
    if spec['start'] == 'canonical':
        raise SystemExit('canonical reference cannot be used as a render source')
    im = inputs[spec['start']].copy()
    original = im.copy()
    for index, op in enumerate(spec['operations']):
        if op.get('role') == 'date_primer_footer':
            op = dict(op)
            for key in ('language', 'layout_engine', 'face_index'):
                op.setdefault(key, footer_style.get(key))
        final = normalized['operations'][index]
        kind = op['op']
        if kind == 'rectangle':
            box = coords(op['box'], 4, True)
            # Pillow's inclusive W/H endpoint was historically clipped. Only this
            # exact one-past-edge case is normalized, explicitly in the finalspec.
            fixed = [box[0], box[1], min(box[2], im.width - 1), min(box[3], im.height - 1)]
            if box[2] > im.width or box[3] > im.height:
                raise SystemExit('rectangle outside canvas')
            box_inside(fixed, im.size, True)
            final['original_box'] = op.get('original_box', box)
            final['box'] = fixed
            final['effective_bounds'] = fixed
            ImageDraw.Draw(im).rectangle(fixed, fill=rgb(op['fill']))
        elif kind == 'text':
            xy = coords(op['xy'], 2)
            if type(op['size']) is not int or op['size'] <= 0:
                raise SystemExit('text size must be a positive integer')
            face = op.get('face_index', spec['font'].get('face_index', 0))
            if type(face) is not int or face < 0:
                raise SystemExit('font face_index must be a nonnegative integer')
            engine = op.get('layout_engine')
            if engine not in (None, 'RAQM', 'BASIC'):
                raise SystemExit('unknown layout_engine')
            if engine == 'RAQM' and not features.check('raqm'):
                raise SystemExit('explicit RAQM requires available RAQM')
            fnt = ImageFont.truetype(str(font), op['size'], index=face,
                                    layout_engine=getattr(ImageFont.Layout, engine) if engine else None)
            language = op.get('language')
            if language is not None and (not isinstance(language, str) or not language):
                raise SystemExit('language must be null or a nonempty string')
            options = dict(font=fnt, anchor=op['anchor'], language=language,
                           direction=op.get('direction'), features=op.get('features'))
            draw = ImageDraw.Draw(im)
            bbox = draw.textbbox(tuple(xy), op['text'], **options)
            if not (0 <= bbox[0] <= bbox[2] <= im.width and 0 <= bbox[1] <= bbox[3] <= im.height):
                raise SystemExit(f'text outside canvas: {bbox}')
            draw.text(tuple(xy), op['text'], fill=rgb(op['fill']), **options)
            final.update(language=language, layout_engine=fnt.layout_engine.name, face_index=face,
                         direction=op.get('direction'), features=op.get('features'), effective_bbox=list(bbox))
        elif kind == 'paste':
            if op['source'] == 'canonical':
                raise SystemExit('canonical reference pixels may not be pasted')
            source = inputs[op['source']]
            crop = box_inside(op['crop'], source.size)
            xy = coords(op['xy'], 2, True)
            box_inside([xy[0], xy[1], xy[0]+crop[2]-crop[0], xy[1]+crop[3]-crop[1]], im.size)
            im.paste(source.crop(crop), tuple(xy))
        elif kind == 'expand_bottom':
            if type(op['pixels']) is not int or op['pixels'] <= 0:
                raise SystemExit('expand_bottom pixels must be a positive integer')
            expanded = Image.new('RGB', (im.width, im.height + op['pixels']), rgb(op['fill']))
            expanded.paste(im, (0, 0))
            im = expanded
        elif kind == 'restore_gray':
            for box in op['boxes']:
                box_inside(box, original.size, True)
                box_inside(box, im.size, True)
                for y in range(box[1], box[3] + 1):
                    for x in range(box[0], box[2] + 1):
                        pixel = original.getpixel((x, y))
                        if pixel[0] == pixel[1] == pixel[2] and pixel[0] > 0:
                            im.putpixel((x, y), pixel)
        else:
            raise SystemExit(f'unknown operation: {kind}')
    preservation = spec.get('signal_preservation')
    if preservation is None and spec.get('signal_roi') is not None:
        preservation = dict(source=spec['start'], source_roi=spec['signal_roi'], offset=[0, 0])
    if preservation:
        source = inputs[preservation['source']]
        roi = box_inside(preservation['source_roi'], source.size)
        dx, dy = coords(preservation.get('offset', [0, 0]), 2, True)
        target = box_inside([roi[0]+dx, roi[1]+dy, roi[2]+dx, roi[3]+dy], im.size)
        if source.crop(roi).tobytes() != im.crop(target).tobytes():
            raise SystemExit('registered source/destination signal ROI changed')
        normalized['signal_preservation'] = dict(preservation, destination_roi=target, equal=True)
    normalized['environment'] = environment()
    return (im, normalized) if effective else im


def replay(batch, output):
    batch, output = input_file(Path(batch).absolute()), Path(output).absolute()
    check_write_path(output)
    if output.exists() or '1.原始资料' in output.parts:
        raise SystemExit('output must be new and outside originals/records')
    payload = json.loads(batch.read_text())
    if payload.get('schema_version') != 1 or not isinstance(payload.get('items'), list) or not payload['items']:
        raise SystemExit('unsupported/empty operation batch schema')
    jobs, protected, ids = [], {batch: sha256(batch)}, set()
    files, directories = [output / 'replay-manifest.json'], [output]
    for record in payload['items']:
        identity = record['id']
        if not isinstance(identity, str) or identity in ids or identity in ('', '.', '..') or '/' in identity or '\\' in identity:
            raise SystemExit('invalid/duplicate identity')
        ids.add(identity)
        spec_path = input_file(batch.parent / record['spec'])
        if sha256(spec_path) != record['sha256']:
            raise SystemExit('spec hash mismatch')
        spec = json.loads(spec_path.read_text())
        for item in resources(spec):
            path = checked_resource(item, spec_path.parent)
            protected[path] = sha256(path)
        protected[spec_path] = sha256(spec_path)
        directory = output / identity
        directories.append(directory)
        files.extend([directory / 'final（标注）.png', directory / 'finalspec.json'])
        jobs.append((identity, spec, spec_path.parent))
    destination_plan(files, directories, list(protected))
    for _, spec, base in jobs:
        render(spec, base)  # evolving in-memory state, no writes
    if any(sha256(p) != h for p, h in protected.items()):
        raise SystemExit('protected input changed during preflight')
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for identity, spec, base in jobs:
        if any(sha256(p) != h for p, h in protected.items()):
            raise SystemExit('protected input changed; partial run retained')
        directory = output / identity
        image, normalized = render(spec, base, effective=True)
        directory.mkdir()
        path = directory / 'final（标注）.png'
        image.save(path)
        for item in resources(normalized):
            item['path'] = os.path.relpath((base / item['path']).resolve(), directory)
        normalized.update(output=dict(path=path.name, sha256=sha256(path)),
                          path_base='manifest_directory', visual_status='not_reviewed')
        write_json(directory / 'finalspec.json', normalized)
        records.append(dict(id=identity, output=f'{identity}/{path.name}', sha256=sha256(path),
                            finalspec=f'{identity}/finalspec.json'))
    if any(sha256(p) != h for p, h in protected.items()):
        raise SystemExit('protected input changed during replay')
    write_json(output / 'replay-manifest.json', dict(schema_version=1, items=records, protected_inputs_unchanged=True,
               batch_sha256=sha256(batch), environment=environment(), visual_status='not_reviewed'))
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(replay(args.batch, args.output), ensure_ascii=False))
