#!/usr/bin/env python3
"""Draw a second-batch-style gel overlay. Geometry comes from this gel's spec."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from review_gel import annotation_review, check_source, review_directory, row_box, spec_rows

COLORS = {
    "purple": (211, 61, 243),
    "yellow": (245, 217, 0),
    "red": (255, 66, 66),
    "white": (255, 255, 255),
    "cyan": (0, 200, 230),
    "green": (30, 180, 95),
    "orange": (245, 150, 35),
    "pink": (230, 75, 180),
}
FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
FONT_BOLD = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")

# Offsets relative to well (hole-center y). Negative is above the gel.
OFFSET = {
    "head": -450,
    "param": -370,
    "lane": -280,
    "bracket": -220,
    "bracket_end": -100,
    "marker": -250,
    "marker_arrow": -210,
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT
    if not path.is_file():
        raise SystemExit(f"missing font: {path}")
    return ImageFont.truetype(str(path), size)


def centered(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, fnt, fill) -> None:
    box = draw.textbbox((0, 0), text, font=fnt)
    pos = (x - (box[2] + box[0]) / 2, y - (box[3] + box[1]) / 2)
    checked_text(draw, pos, text, fnt, fill)


def checked_text(draw, pos, text, fnt, fill) -> None:
    box = draw.textbbox(pos, text, font=fnt)
    width, height = draw._image.size
    if box[0] < 0 or box[1] < 0 or box[2] > width or box[3] > height:
        raise SystemExit(f"label outside canvas: {text!r}; adjust y/font_scale/top_padding")
    name = f"{getattr(draw, '_context', '')}/{text}"
    boxes = getattr(draw, '_text_boxes', [])
    for other, previous in boxes:
        if max(box[0], previous[0]) < min(box[2], previous[2]) and max(box[1], previous[1]) < min(box[3], previous[3]):
            raise SystemExit(f"label collision: {name!r} {box} overlaps {other!r} {previous}; adjust layout")
    boxes.append((name, box))
    draw._text_boxes = boxes
    draw.text(pos, text, font=fnt, fill=fill)


def checked_points(draw, points, width, name):
    w, h = draw._image.size
    margin = (width - 1) / 2
    if any(not (margin <= x <= w-1-margin and margin <= y <= h-1-margin) for x, y in points):
        raise SystemExit(f"{getattr(draw, '_context', '')}/{name} outside canvas: {points}")
    if name in ("bracket", "bar"):
        boxes = getattr(draw, '_shape_boxes', [])
        boxes.append((getattr(draw, '_context', '') + '/' + name,
                      (min(p[0] for p in points)-margin, min(p[1] for p in points)-margin,
                       max(p[0] for p in points)+margin, max(p[1] for p in points)+margin)))
        draw._shape_boxes = boxes


def checked_line(draw, coords, fill, width=3, name="line"):
    checked_points(draw, [(coords[0], coords[1]), (coords[2], coords[3])], width, name)
    draw.line(coords, fill=fill, width=width)


def arrow(draw: ImageDraw.ImageDraw, start, end, color, width=4, head=16) -> None:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    left = (end[0] - ux * head + px * head * 0.55, end[1] - uy * head + py * head * 0.55)
    right = (end[0] - ux * head - px * head * 0.55, end[1] - uy * head - py * head * 0.55)
    checked_points(draw, [start, end], width, "arrow shaft")
    checked_points(draw, [end, left, right], 1, "arrow head")
    draw.line((*start, *end), fill=color, width=width)
    draw.polygon([end, left, right], fill=color)


def group_bracket(draw: ImageDraw.ImageDraw, x0, x1, y, y1, color, width=4) -> None:
    checked_line(draw, (x0, y, x1, y), color, width, "bracket")
    checked_line(draw, (x0, y, x0, y1), color, width, "bracket")
    checked_line(draw, (x1, y, x1, y1), color, width, "bracket")


def load_spec(path: Path) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    for key in ("src", "out"):
        if key not in spec:
            raise SystemExit(f"spec missing {key}")
    return spec


def resolve(path: Path, repo: Path) -> Path:
    return path if path.is_absolute() else (repo / path)


def geometry(spec: dict, image_height: int) -> dict:
    well = spec.get("well")
    if well is None and spec.get("y"):
        well = spec["y"].get("well")
    if well is None:
        raise SystemExit("missing well; look at the hole row on this gel and put well in the spec")
    well = int(well)
    y = {key: well + delta for key, delta in OFFSET.items()}
    y["well"] = well
    y["primer"] = image_height - 122
    if spec.get("y"):
        y.update(spec["y"])
    return y


def annotate(spec: dict, repo: Path, lane_x: list[int] | None, review_dir: Path | None = None) -> Path:
    src = resolve(Path(spec["src"]), repo)
    out = resolve(Path(spec["out"]), repo)
    if not src.is_file():
        raise SystemExit(f"missing source: {src}")
    if "（标注）" not in out.name:
        raise SystemExit(f"output name must contain （标注）: {out.name}")
    if out.resolve() == src.resolve():
        raise SystemExit("refusing to overwrite source image")
    if out.exists() and not spec.get("overwrite"):
        raise SystemExit(f"refusing to overwrite existing annotation: {out}")

    if out.suffix.lower() != ".png":
        raise SystemExit("annotation output must be PNG")
    before = sha256(src)
    if review_dir is not None:
        review_dir = review_directory(review_dir)
    check_source(spec, before, required=review_dir is not None)
    original = Image.open(src).convert("RGB")
    rows = spec_rows(spec)
    if lane_x is not None:
        rows = [dict(rows[0], lane_x=lane_x)]
    padding = int(spec.get("top_padding", 0))
    if padding < 0:
        raise SystemExit("top_padding must be nonnegative")
    for row in rows:
        validate_row(row, original.size)
        if review_dir is not None:
            row_box(dict(row, well=geometry(row, original.height)["well"]), original.size)
    im = Image.new("RGB", (original.width, original.height + padding), "black")
    im.paste(original, (0, padding))
    draw = ImageDraw.Draw(im)
    for i, row in enumerate(rows, 1):
        draw._context = f"row {i}"
        draw_row(im, row, original.height, padding, draw)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    if before != sha256(src):
        raise SystemExit("source image changed while annotating")
    if review_dir is not None:
        normalized = [dict(r, well=geometry(r, original.height)["well"]) for r in rows]
        with Image.open(out) as saved:
            annotation_review(original, saved.convert("RGB"), normalized, padding, review_dir, out, before,
                              getattr(draw, '_text_boxes', []) + getattr(draw, '_shape_boxes', []))
    return out


def validate_row(spec: dict, size: tuple[int, int]) -> None:
    w, h = size
    xs = spec.get("lane_x", [])
    if not xs or any(not isinstance(x, (int, float)) or not 0 <= x < w for x in xs):
        raise SystemExit("lane_x must contain source-image x coordinates")
    if any(a >= b for a, b in zip(xs, xs[1:])):
        raise SystemExit("lane_x must be strictly increasing")
    y = geometry(spec, h)
    ys = spec.get("lane_y", [y["well"]] * len(xs))
    if len(ys) != len(xs) or any(not isinstance(v, (int, float)) or not 0 <= v < h for v in ys):
        raise SystemExit("lane_y must contain one source-image y per well")
    used = set()
    markers = spec.get("marker_indices", [])
    for group in spec.get("groups", []):
        indices = [item["index"] for item in group["lanes"]]
        if not indices or any(type(i) is not int or not 0 <= i < len(xs) for i in indices):
            raise SystemExit("group indices must refer to existing wells")
        if indices != sorted(set(indices)):
            raise SystemExit("group indices must be unique and increasing")
        if group.get("draw_lines", True):
            if used.intersection(indices):
                raise SystemExit("well assigned to multiple drawing groups")
            used.update(indices)
        if group.get("color", "purple") not in COLORS:
            raise SystemExit("unknown group color")
    if len(set(markers)) != len(markers) or any(type(i) is not int or not 0 <= i < len(xs) for i in markers):
        raise SystemExit("invalid marker_indices")
    if used.intersection(markers):
        raise SystemExit("Marker also assigned to a sample group")
    if spec.get("bp_guide"):
        if not spec.get("bp_source"):
            raise SystemExit("bp_guide requires bp_source (ladder specification evidence)")
        if not markers:
            raise SystemExit("bp_guide requires a Marker")
        if spec.get("bp_marker_index", markers[0]) not in markers:
            raise SystemExit("bp_marker_index must refer to a Marker")
        if any(not 0 <= band["y"] < h for band in spec["bp_guide"]):
            raise SystemExit("bp band outside source image")
    for key in ("bp_target_x", "bp_arrow_x", "bp_label_x"):
        if key in spec and (not isinstance(spec[key], (int, float)) or not 0 <= spec[key] < w):
            raise SystemExit(f"{key} outside source image")
    scale = spec.get("font_scale", 1)
    if not isinstance(scale, (int, float)) or not 0 < scale <= 2:
        raise SystemExit("font_scale must be greater than 0 and at most 2")


def draw_row(im: Image.Image, spec: dict, image_height: int, padding: int, draw=None) -> None:
    xs = spec["lane_x"]
    y = {key: value + padding for key, value in geometry(spec, image_height).items()}
    ys = [v + padding for v in spec.get("lane_y", [y["well"] - padding] * len(xs))]
    draw = draw if draw is not None else ImageDraw.Draw(im)
    row_context = getattr(draw, '_context', 'row')
    scale = spec.get("font_scale", 1)
    head_f = font(max(1, round(46 * scale)), True)
    param_f = font(max(1, round(38 * scale)), True)
    lane_f = font(max(1, round(31 * scale)))
    marker_f = font(max(1, round(36 * scale)))
    bp_f = font(max(1, round(32 * scale)))
    primer_f = font(max(1, round(38 * scale)))

    for group_index, group in enumerate(spec.get("groups", []), 1):
        draw._context = f"{row_context}/group {group_index}"
        color = COLORS[group.get("color", "purple")]
        lanes = group["lanes"]
        indices = [item["index"] for item in lanes]
        x_first, x_last = xs[indices[0]], xs[indices[-1]]
        mid = (x_first + x_last) / 2
        shift = int(group.get("y_shift") or 0)
        draw_lines = group.get("draw_lines", True)
        if len(indices) >= 2 and group.get("draw_bracket", draw_lines):
            group_bracket(draw, x_first - 42 * scale, x_last + 42 * scale, y["bracket"], y["bracket_end"], color)
        if group.get("head"):
            centered(draw, mid, y["head"] + shift, group["head"], head_f, color)
        if group.get("param"):
            centered(draw, mid, y["param"] + shift, group["param"], param_f, color)
        if group.get("bar") and len(indices) >= 2:
            bar_y = y["param"] + shift + 28
            checked_line(draw, (x_first - 20, bar_y, x_last + 20, bar_y), color, name="bar")
        names = [item.get("name") or "" for item in lanes]
        labeled = [name for name in names if name]
        same_name = len(set(labeled)) == 1 and len(labeled) == len(names)
        if labeled and same_name:
            centered(draw, mid, y["lane"], names[0], lane_f, color)
        for item in lanes:
            x = xs[item["index"]]
            name = item.get("name") or ""
            if name and not same_name:
                centered(draw, x, y["lane"], name, lane_f, color)
            if draw_lines:
                checked_line(draw, (x, y["bracket"], x, ys[item["index"]]), color, name=f"well {item['index']+1} leader")

    for idx in spec.get("marker_indices", []):
        draw._context = f"{row_context}/Marker well {idx+1}"
        x = xs[idx]
        centered(draw, x, y["marker"], "Marker", marker_f, COLORS["white"])
        arrow(draw, (x, y["marker_arrow"]), (x, ys[idx]), COLORS["white"], 4, 18)

    bp_guide = spec.get("bp_guide") or []
    marker_indices = spec.get("marker_indices") or []
    marker_x = xs[spec.get("bp_marker_index", marker_indices[0])] if marker_indices else xs[0]
    gel_left = min(xs)
    bp_arrow_x = spec.get("bp_arrow_x", max(40, gel_left - 220))
    bp_label_x = spec.get("bp_label_x", max(8, bp_arrow_x - 150))
    bp_target_x = spec.get("bp_target_x", marker_x - 20)
    for item in bp_guide:
        draw._context = f"{row_context}/bp"
        band_y = item["y"] + padding
        checked_text(draw, (bp_label_x, band_y - 20), item["label"], bp_f, COLORS["red"])
        arrow(draw, (bp_arrow_x, band_y), (bp_target_x, band_y), COLORS["red"], 3, 16)

    if spec.get("primer_line"):
        draw._context = f"{row_context}/primer"
        primer_x = (min(xs) + max(xs)) / 2
        centered(draw, primer_x, y["primer"], spec["primer_line"], primer_f, COLORS["red"])



def main() -> None:
    parser = argparse.ArgumentParser(description="Annotate a gel from a per-image spec")
    parser.add_argument("spec", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--review-dir", type=Path, help="write native-pixel review panels and review.json; requires source_sha256")
    args = parser.parse_args()
    spec = load_spec(args.spec)
    if args.overwrite:
        spec["overwrite"] = True
    out = annotate(spec, args.repo, None, args.review_dir)
    if args.review_dir:
        print((args.review_dir / "review.json").read_text(encoding="utf-8"))
    else:
        print(out)


if __name__ == "__main__":
    main()
