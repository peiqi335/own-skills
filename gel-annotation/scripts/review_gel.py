"""Native-pixel review sheets. A review artifact is not a visual approval."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def review_directory(path):
    dest = Path(path).resolve()
    if any(part in ("1.原始资料", "3.记录") for part in dest.parts):
        raise SystemExit("review panels must be written to a temporary directory, not original records")
    return dest


def split_boxes(box, max_width=1000, max_height=360, overlap=64):
    if not 0 <= overlap < min(max_width, max_height):
        raise ValueError("overlap must be smaller than panel dimensions")
    x0, y0, x1, y1 = map(int, box)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("empty review region")

    def starts(lo, hi, limit):
        points = [lo]
        while points[-1] + limit < hi:
            points.append(points[-1] + limit - overlap)
        return points

    return [(x, y, min(x + max_width, x1), min(y + max_height, y1))
            for y in starts(y0, y1, max_height)
            for x in starts(x0, x1, max_width)]


def clipped(box, size):
    w, h = size
    x0, y0, x1, y1 = box
    result = (max(0, math.floor(x0)), max(0, math.floor(y0)),
              min(w, math.ceil(x1)), min(h, math.ceil(y1)))
    if result[2] <= result[0] or result[3] <= result[1]:
        raise SystemExit(f"empty review region: {box}")
    return result


def row_box(row, size):
    xs = row["lane_x"]
    ys = row.get("lane_y", [row["well"]] * len(xs))
    supplied = row.get("review_box")
    if supplied is not None:
        if len(supplied) != 4 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in supplied):
            raise SystemExit("review_box needs four finite source coordinates")
        x0, y0, x1, y1 = supplied
        if not (0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1]):
            raise SystemExit("review_box outside source image")
        if any(not (x0 <= x < x1 and y0 <= y < y1) for x, y in zip(xs, ys)):
            raise SystemExit("review_box must cover all supplied wells")
        return clipped(supplied, size)
    return clipped((min(xs) - 80, min(ys) - 65, max(xs) + 81, max(ys) + 66), size)


def geometry_hash(rows):
    data = [{"lane_x": r["lane_x"],
             "lane_y": r.get("lane_y", [r["well"]] * len(r["lane_x"])),
             "marker_indices": r.get("marker_indices", [])} for r in rows]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def check_source(spec, actual_hash, required=False):
    expected = spec.get("source_sha256")
    if required and not expected:
        raise SystemExit("source_sha256 required for review workflow; hash the original image")
    if expected is not None and expected != actual_hash:
        raise SystemExit("source_sha256 mismatch: spec belongs to another source or source changed")


def spec_rows(spec):
    if "rows" in spec:
        row_fields = {"well", "lane_x", "lane_y", "groups", "marker_indices", "y", "font_scale",
                      "bp_guide", "bp_source", "bp_marker_index", "bp_label_x", "bp_arrow_x",
                      "bp_target_x", "primer_line", "review_box"}
        mixed = row_fields.intersection(spec)
        if mixed:
            raise SystemExit(f"rows cannot be mixed with top-level row fields: {sorted(mixed)}")
    rows = spec.get("rows", [spec])
    if not isinstance(rows, list) or not rows:
        raise SystemExit("rows must be a nonempty list")
    return rows


def write_panels(original, overlay, dest, stem, box, padding=0, lane_x=None, second_label="OVERLAY"):
    """Pair untouched and overlaid crops; coordinates are in original image space."""
    if original.size != overlay.size:
        raise SystemExit("review images must share canvas dimensions")
    dest = review_directory(dest)
    dest.mkdir(parents=True, exist_ok=True)
    boxes = split_boxes(clipped(box, overlay.size))
    fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    panels = []
    for n, crop_box in enumerate(boxes, 1):
        x0, y0, x1, y1 = crop_box
        cw, ch = x1 - x0, y1 - y0
        left, top, gap = 66, 68, 68
        raw_offset, overlay_offset = (left, top), (left, top + ch + gap)
        sheet = Image.new("RGB", (max(400, cw + left + 12), ch * 2 + top + gap + 12), (24, 24, 24))
        draw = ImageDraw.Draw(sheet)
        for label, source, offset in [("RAW", original, raw_offset), (second_label, overlay, overlay_offset)]:
            ox, oy = offset
            sheet.paste(source.crop(crop_box), offset)
            draw.text((8, oy - 64), f"{label} | x={x0} y={y0-padding} | 1:1", font=fnt, fill="white")
            for x in range(math.ceil(x0 / 50) * 50, x1, 50):
                sx = ox + x - x0
                draw.line((sx, oy - 6, sx, oy - 1), fill="yellow")
                draw.text((sx - 16, oy - 24), str(x), font=fnt, fill="yellow")
            for y in range(math.ceil((y0-padding) / 50) * 50, y1-padding, 50):
                sy = oy + y + padding - y0
                draw.text((2, sy - 7), str(y), font=fnt, fill="yellow")
                draw.line((ox - 6, sy, ox - 1, sy), fill="yellow")
            for idx, x in enumerate(lane_x or [], 1):
                if x0 <= x < x1:
                    draw.text((ox + x - x0 - 10, oy - 44), f"W{idx}", font=fnt, fill="cyan")
        path = dest / f"{stem}_p{n}.png"
        sheet.save(path)
        panels.append({"path": str(path), "source_box": [x0, y0-padding, x1, y1-padding],
                       "canvas_box": list(crop_box), "scale": 1,
                       "raw_offset": list(raw_offset), "overlay_offset": list(overlay_offset)})
    return panels


def annotation_review(original, candidate, rows, padding, dest, out, source_hash, text_boxes):
    dest = review_directory(dest)
    raw = Image.new("RGB", candidate.size, "black")
    raw.paste(original, (0, padding))
    panels = []
    for i, row in enumerate(rows, 1):
        x0, y0, x1, y1 = row_box(row, original.size)
        areas = [("wells", (x0, y0 + padding, x1, y1 + padding))]
        labels = [b for name, b in text_boxes if name.startswith(f"row {i}/") and not name.startswith(f"row {i}/bp/")]
        if labels:
            areas.append(("labels", (min(b[0] for b in labels)-12, min(b[1] for b in labels)-12,
                                      max(b[2] for b in labels)+12, max(b[3] for b in labels)+12)))
        if row.get("bp_guide"):
            marker = row["lane_x"][row.get("bp_marker_index", row["marker_indices"][0])]
            arrow_x = row.get("bp_arrow_x", max(40, min(row["lane_x"])-220))
            label_x = row.get("bp_label_x", max(8, arrow_x-150))
            target_x = row.get("bp_target_x", marker-20)
            bands = [b["y"]+padding for b in row["bp_guide"]]
            areas.append(("bp", (min(label_x, arrow_x, target_x, marker)-12, min(bands)-40,
                                  max(label_x+180, arrow_x, target_x, marker+70), max(bands)+40)))
        for category, area in areas:
            parts = write_panels(raw, candidate, dest, f"row{i}_{category}", area, padding, row["lane_x"] if category == "wells" else None)
            panels.extend(dict(p, row=i, category=category) for p in parts)
    payload = {"out": str(out), "src_sha256": source_hash,
               "geometry_sha256": geometry_hash(rows), "top_padding": padding,
               "panels": panels, "visual_status": "not_reviewed"}
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "review.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
