#!/usr/bin/env python3
"""Separate byte, decoded-pixel, signal ROI and geometry results; never infer approval."""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops
from annotate_gel import sha256, check_write_path, same_path


def pixels(image):
    return hashlib.sha256(image.tobytes()).hexdigest()


def geometry_record(manifest):
    if manifest is None:
        return None
    payload = json.loads(manifest.read_text(encoding='utf-8'))
    spec = payload.get('finalspec', payload.get('spec', payload))
    if not spec.get('rows'):
        return None
    return dict(top_padding=spec.get('top_padding', 0),
                rows=[{key: row.get(key) for key in ('well', 'lane_x', 'lane_y', 'marker_indices', 'y')}
                      for row in spec['rows']])


def compare(left, right, roi=None, left_manifest=None, right_manifest=None, diff=None):
    protected = [left, right] + [p for p in (left_manifest, right_manifest) if p is not None]
    if diff is not None:
        check_write_path(diff)
        if diff.exists() or diff.suffix.lower() != '.png' or any(same_path(diff, p) for p in protected):
            raise SystemExit('diff must be a fresh unprotected PNG path')
    with Image.open(left) as source, Image.open(right) as target:
        a, b = source.copy(), target.copy()
    if a.mode not in ('RGB', 'RGBA', 'L') or b.mode not in ('RGB', 'RGBA', 'L'):
        raise SystemExit('decoded comparison supports RGB/RGBA/L only; palette/transparency requires explicit normalization')
    same_canvas = a.size == b.size and a.mode == b.mode
    result = dict(whole_bytes=dict(equal=sha256(left) == sha256(right), left_sha256=sha256(left), right_sha256=sha256(right)),
                  decoded_pixels=dict(equal=same_canvas and a.tobytes() == b.tobytes(),
                                      left_sha256=pixels(a), right_sha256=pixels(b),
                                      left_size=list(a.size), right_size=list(b.size), left_mode=a.mode, right_mode=b.mode),
                  signalROI=dict(status='missing', reason='no explicit registered ROI supplied'),
                  geometry=dict(status='missing', reason='both finalspec/annotation manifests required'))
    if roi is not None:
        if len(roi) != 4 or any(type(v) is not int for v in roi) or not (0 <= roi[0] < roi[2] <= min(a.width, b.width) and 0 <= roi[1] < roi[3] <= min(a.height, b.height)):
            raise SystemExit('signal ROI must be explicit integer coordinates inside both canvases')
        ac, bc = a.crop(roi), b.crop(roi)
        result['signalROI'] = dict(status='compared', roi=list(roi), equal=ac.mode == bc.mode and ac.tobytes() == bc.tobytes(),
                                   left_sha256=pixels(ac), right_sha256=pixels(bc))
    ga, gb = geometry_record(left_manifest), geometry_record(right_manifest)
    if ga is not None and gb is not None:
        result['geometry'] = dict(status='compared', equal=ga == gb, left=ga, right=gb,
                                  boundary='recorded geometry equality, not verified physical well centers')
    if diff is not None:
        width, height = max(a.width, b.width), max(a.height, b.height)
        ca, cb = Image.new('RGB', (width, height)), Image.new('RGB', (width, height))
        ca.paste(a.convert('RGB'), (0, 0))
        cb.paste(b.convert('RGB'), (0, 0))
        difference = ImageChops.difference(ca, cb)
        diff.parent.mkdir(parents=True, exist_ok=True)
        difference.save(diff)
        result['diffPNG'] = dict(path=str(diff), sha256=sha256(diff), bbox=difference.getbbox(),
                                 boundary='RGB visual difference; decoded check separately retains mode/alpha')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    parser.add_argument('--roi', help='explicit x0,y0,x1,y1 in each image canvas')
    parser.add_argument('--left-manifest', type=Path)
    parser.add_argument('--right-manifest', type=Path)
    parser.add_argument('--diff', type=Path)
    args = parser.parse_args()
    roi = [int(v) for v in args.roi.split(',')] if args.roi else None
    print(json.dumps(compare(args.left, args.right, roi, args.left_manifest, args.right_manifest, args.diff), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
