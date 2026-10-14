#!/usr/bin/env python3
"""Draw per-gel scan overlays. Never writes the final annotation PNG."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont
from review_gel import check_source, geometry_hash, row_box, spec_rows, write_panels

TMP_ROOT = Path("/tmp/codex/gel-annotation")
DEJAVU = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
NOTO = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
RED = (255, 40, 40)
GREEN = (40, 220, 80)
CYAN = (0, 220, 255)
YELLOW = (255, 220, 0)
WHITE = (255, 255, 255)
FORBIDDEN = ("1.原始资料", "3.记录")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def font(size: int) -> ImageFont.FreeTypeFont:
    if DEJAVU.is_file():
        return ImageFont.truetype(str(DEJAVU), size)
    if NOTO.is_file():
        return ImageFont.truetype(str(NOTO), size)
    raise SystemExit(f"missing font: {DEJAVU} or {NOTO}")


def parse_ints(text: str, n: int | None = None, name: str = "values") -> list[int]:
    parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
    if not parts:
        raise SystemExit(f"missing {name}")
    try:
        vals = [int(round(float(p))) for p in parts]
    except ValueError as exc:
        raise SystemExit(f"bad {name}: {text}") from exc
    if n is not None and len(vals) != n:
        raise SystemExit(f"{name} needs {n} integers, got {len(vals)}")
    return vals


def parse_bands(text: str) -> list[tuple[str, int]]:
    bands = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise SystemExit(f"band must be label:y, got {part}")
        label, y = part.rsplit(":", 1)
        bands.append((label.strip(), int(round(float(y)))))
    if not bands:
        raise SystemExit("missing --bands")
    return bands


def resolve_src(path: Path, repo: Path) -> Path:
    src = path if path.is_absolute() else (repo / path)
    if not src.is_file():
        raise SystemExit(f"missing source: {src}")
    if "（标注）" in src.name:
        raise SystemExit("scan the raw gel, not an annotated figure")
    return src


def out_dir_for(src: Path, out_dir: Path | None) -> Path:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    dest = out_dir if out_dir else Path(tempfile.mkdtemp(prefix=src.stem + "-", dir=TMP_ROOT))
    dest = dest.resolve()
    text = str(dest)
    for part in FORBIDDEN:
        if part in text:
            raise SystemExit(f"scan overlays must not be written under {part}")
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def clip_box(size: tuple[int, int], box: list[int]) -> tuple[int, int, int, int]:
    w, h = size
    x0, y0, x1, y1 = box
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    x0 = max(0, min(w - 1, x0))
    x1 = max(x0 + 1, min(w, x1))
    y0 = max(0, min(h - 1, y0))
    y1 = max(y0 + 1, min(h, y1))
    return x0, y0, x1, y1


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def save_jpeg(im: Image.Image, path: Path) -> Path:
    im.save(path, quality=95)
    return path


def cmd_grid(src: Path, dest: Path, region: str | None, x_step: int, y_step: int) -> None:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    box = parse_ints(region, 4, "region") if region else [0, 0, w, h]
    x0, y0, x1, y1 = clip_box((w, h), box)
    draw = ImageDraw.Draw(im)
    fnt = font(22 if min(x1 - x0, y1 - y0) > 400 else 16)
    for x in range(x0, x1 + 1, x_step):
        draw.line((x, y0, x, y1), fill=RED, width=2)
        draw.text((x + 2, y0 + 4), str(x), fill=RED, font=fnt)
    for y in range(y0, y1 + 1, y_step):
        draw.line((x0, y, x1, y), fill=GREEN, width=2)
        draw.text((x0 + 4, y + 2), str(y), fill=GREEN, font=fnt)
    out = save_jpeg(im, dest / "grid.jpg")
    emit(
        {
            "stage": "grid",
            "out": str(out),
            "src": str(src),
            "src_sha256": sha256(src),
            "size": [w, h],
            "region": [x0, y0, x1, y1],
            "x_step": x_step,
            "y_step": y_step,
        }
    )


def draw_x_ticks(im: Image.Image, origin_x: int, tick: int, scale: int) -> None:
    draw = ImageDraw.Draw(im)
    fnt = font(18 if im.size[1] < 200 else 22)
    step = max(tick * scale, 1)
    for x in range(0, im.size[0], step):
        absx = origin_x + x // scale
        draw.line((x, 0, x, im.size[1]), fill=RED, width=1)
        draw.text((x + 2, 4), str(absx), fill=YELLOW, font=fnt)


def cmd_wells(src: Path, dest: Path, row: str, x0: int | None, x1: int | None, tick: int) -> None:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    y0, y1 = parse_ints(row, 2, "row")
    left = 0 if x0 is None else x0
    right = w if x1 is None else x1
    box = clip_box((w, h), [left, y0, right, y1])
    enhanced = im.copy()
    enhanced.paste(ImageEnhance.Contrast(im.crop(box).convert("L")).enhance(2.5).convert("RGB"), box[:2])
    crop = enhanced.crop(box)
    scale = 1
    draw_x_ticks(crop, box[0], tick, scale)
    out = dest / "wells.jpg"
    save_jpeg(crop, out)
    review_panels = write_panels(im, enhanced, dest, "wells", box, second_label="CONTRAST")
    panels = [p["path"] for p in review_panels]
    emit(
        {
            "stage": "wells",
            "out": str(out),
            "panels": panels,
            "review_panels": review_panels,
            "src": str(src),
            "src_sha256": sha256(src),
            "size": [w, h],
            "row": [box[1], box[3]],
            "x": [box[0], box[2]],
            "scale": scale,
            "tick": tick,
            "note": "read every native-pixel RAW/enhanced panel; x/y rulers are source coordinates outside the image",
        }
    )


def cmd_zoom(src: Path, dest: Path, at: str, size: int) -> None:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    x, y = parse_ints(at, 2, "at")
    if not (0 <= x < w and 0 <= y < h):
        raise SystemExit(f"zoom point {x},{y} outside image {w}x{h}")
    half = max(40, size // 2)
    box = clip_box((w, h), [x - half, y - half, x + half, y + half])
    crop = im.crop(box).resize((max(320, box[2] - box[0]) * 2, max(320, box[3] - box[1]) * 2))
    draw = ImageDraw.Draw(crop)
    fnt = font(22)
    cx = round((x - box[0]) * crop.width / (box[2] - box[0]))
    cy = round((y - box[1]) * crop.height / (box[3] - box[1]))
    draw.line((0, cy, crop.size[0], cy), fill=CYAN, width=2)
    draw.line((cx, 0, cx, crop.size[1]), fill=CYAN, width=2)
    draw.text((8, 8), f"x={x} y={y}", fill=YELLOW, font=fnt)
    named = dest / f"zoom_{x}_{y}.jpg"
    latest = dest / "zoom.jpg"
    save_jpeg(crop, named)
    save_jpeg(crop, latest)
    emit(
        {
            "stage": "zoom",
            "out": str(named),
            "latest": str(latest),
            "src": str(src),
            "src_sha256": sha256(src),
            "at": [x, y],
            "box": list(box),
        }
    )


def cmd_lanes(src: Path, dest: Path, xs_text: str, well: int | None, span: str | None, ys_text: str | None = None, review_box=None, geometry_sha256=None) -> None:
    im = Image.open(src).convert("RGB")
    raw = im.copy()
    w, h = im.size
    xs = xs_text if isinstance(xs_text, list) else parse_ints(xs_text, None, "xs")
    ys = ys_text if isinstance(ys_text, list) else (parse_ints(ys_text, len(xs), "ys") if ys_text else None)
    if any(a >= b for a, b in zip(xs, xs[1:])):
        raise SystemExit("xs must be strictly increasing")
    if ys and any(not 0 <= v < h for v in ys):
        raise SystemExit("ys outside image")
    if well is not None and not (0 <= well < h):
        raise SystemExit(f"well y {well} outside image height {h}")
    if span:
        y0, y1 = parse_ints(span, 2, "span")
    elif well is not None:
        y0, y1 = well - 80, well + 360
    else:
        y0, y1 = 0, h
    _, y0, _, y1 = clip_box((w, h), [0, y0, w, y1])
    draw = ImageDraw.Draw(im)
    fnt = font(28 if w > 2000 else 22)
    if well is not None and not ys:
        draw.line((min(xs) - 40, well, max(xs) + 40, well), fill=CYAN, width=3)
        draw.text((8, well - 28), f"well={well}", fill=CYAN, font=fnt)
    for i, x in enumerate(xs, 1):
        if not (0 <= x < w):
            raise SystemExit(f"lane x {x} outside image width {w}")
        draw.line((x, y0, x, y1), fill=RED, width=3)
        if ys:
            cy = ys[i - 1]
            draw.line((x - 15, cy, x + 15, cy), fill=CYAN, width=3)
        draw.text((x - 12, max(0, y0 - 36)), str(i), fill=RED, font=fnt)
    out = save_jpeg(im, dest / "lanes.jpg")
    region = review_box if review_box is not None else [min(xs)-80, min(ys or [well if well is not None else y0])-65,
                                                       max(xs)+81, max(ys or [well if well is not None else y1])+66]
    review_panels = write_panels(raw, im, dest, "lanes", region, lane_x=xs)
    emit(
        {
            "stage": "lanes",
            "out": str(out),
            "src": str(src),
            "src_sha256": sha256(src),
            "size": [w, h],
            "lane_x": xs,
            "lane_y": ys,
            "well": well,
            "span": [y0, y1],
            "n": len(xs),
            "review_panels": review_panels,
            "geometry_sha256": geometry_sha256,
            "visual_status": "not_reviewed",
        }
    )


def cmd_bp(src: Path, dest: Path, bands_text: str, marker_x: int) -> None:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    if not (0 <= marker_x < w):
        raise SystemExit(f"marker x {marker_x} outside image width {w}")
    bands = parse_bands(bands_text)
    draw = ImageDraw.Draw(im)
    fnt = font(28 if w > 2000 else 22)
    label_x = max(8, marker_x - 220)
    tick_x = max(40, marker_x - 80)
    for label, y in bands:
        if not (0 <= y < h):
            raise SystemExit(f"band y {y} outside image height {h}")
        draw.line((tick_x, y, marker_x, y), fill=YELLOW, width=3)
        draw.text((label_x, y - 18), f"{label} y={y}", fill=YELLOW, font=fnt)
    out = save_jpeg(im, dest / "bp.jpg")
    emit(
        {
            "stage": "bp",
            "out": str(out),
            "src": str(src),
            "src_sha256": sha256(src),
            "size": [w, h],
            "marker_x": marker_x,
            "bands": [{"label": label, "y": y} for label, y in bands],
        }
    )


def moving_average(vals: list[float], win: int) -> list[float]:
    if win < 2:
        return vals
    half = win // 2
    out = []
    n = len(vals)
    for i in range(n):
        a = max(0, i - half)
        b = min(n, i + half + 1)
        out.append(sum(vals[a:b]) / (b - a))
    return out


def local_maxima(vals: list[float], min_dist: int, floor: float) -> list[int]:
    found: list[int] = []
    n = len(vals)
    for i in range(1, n - 1):
        if vals[i] < floor or vals[i] < vals[i - 1] or vals[i] < vals[i + 1]:
            continue
        if found and i - found[-1] < min_dist:
            if vals[i] > vals[found[-1]]:
                found[-1] = i
            continue
        found.append(i)
    return found


def cmd_hint(src: Path, dest: Path, row: str, n: int | None, x0: int | None, x1: int | None) -> None:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    y0, y1 = parse_ints(row, 2, "row")
    left = 0 if x0 is None else x0
    right = w if x1 is None else x1
    box = clip_box((w, h), [left, y0, right, y1])
    crop = im.crop(box).convert("L")
    pix = crop.load()
    cw, ch = crop.size
    profile = []
    for x in range(cw):
        total = 0
        for y in range(ch):
            total += pix[x, y]
        profile.append(255.0 - (total / ch))
    smooth = moving_average(profile, 9)
    floor = (min(smooth) + max(smooth)) / 2
    min_dist = max(24, cw // ((n * 3) if n else 40))
    peaks = local_maxima(smooth, min_dist, floor)
    xs = [box[0] + i for i in peaks]
    if n is not None and len(xs) > n:
        # keep the strongest n in left-to-right order
        scored = sorted(((smooth[i], i) for i in peaks), reverse=True)[:n]
        xs = sorted(box[0] + i for _, i in scored)
    overlay = im.copy()
    draw = ImageDraw.Draw(overlay)
    fnt = font(24)
    draw.rectangle(box, outline=CYAN, width=2)
    for i, x in enumerate(xs, 1):
        draw.line((x, box[1] - 30, x, box[3] + 80), fill=CYAN, width=2)
        draw.text((x - 10, max(0, box[1] - 58)), str(i), fill=CYAN, font=fnt)
    out = save_jpeg(overlay, dest / "hint.jpg")
    emit(
        {
            "stage": "hint",
            "out": str(out),
            "src": str(src),
            "src_sha256": sha256(src),
            "size": [w, h],
            "row": [box[1], box[3]],
            "candidates": xs,
            "n_candidates": len(xs),
            "note": "candidates only; draw lanes and inspect before annotating",
        }
    )


def cmd_detect_wells(src: Path, dest: Path, row: str, x0: int | None, x1: int | None, n: int | None = None, well1: int | None = None) -> None:
    im = Image.open(src).convert("L")
    w, h = im.size
    y0, y1 = parse_ints(row, 2, "row")
    left = 0 if x0 is None else max(0, x0)
    right = w if x1 is None else min(w, x1)
    box = clip_box((w, h), [left, y0, right, y1])

    prof = [sum(im.getpixel((x, y)) for y in range(box[1], box[3])) / float(box[3] - box[1]) for x in range(box[0], box[2])]
    contrast = max(prof) - min(prof) if prof else 0.0
    contrast_warning = None
    if contrast < 10.0:
        contrast_warning = f"low contrast in row region ({contrast:.1f} < 10px); verify well-row y coordinates with scan_gel.py grid"
    smooth = moving_average(prof, 7)
    mean_v = sum(smooth) / len(smooth)
    norm = [v - mean_v for v in smooth]

    min_lag = max(25, int(w * 0.015))
    max_lag = min(250, len(norm) // 2)
    corrs = []
    for lag in range(min_lag, max_lag):
        c = sum(norm[i] * norm[i + lag] for i in range(len(norm) - lag))
        corrs.append((lag, c))
    best_lag = max(corrs, key=lambda t: t[1])[0] if corrs else 100

    phase_scores = []
    for phase in range(best_lag):
        score = 0
        cnt = 0
        cur = phase
        while cur < len(smooth):
            score += (mean_v - smooth[cur])
            cnt += 1
            cur += best_lag
        phase_scores.append((phase, score / max(1, cnt)))

    best_phase = max(phase_scores, key=lambda t: t[1])[0]
    first_well = box[0] + best_phase
    if well1 is not None:
        first_well = well1

    cur = first_well
    while cur - best_lag >= box[0] + 10:
        cur -= best_lag

    grid_xs = []
    while cur <= box[2] - 10:
        grid_xs.append(cur)
        cur += best_lag

    if n is not None and len(grid_xs) > n:
        grid_xs = grid_xs[:n]

    wells = []
    for i, gx in enumerate(grid_xs, 1):
        win = max(8, int(best_lag * 0.2))
        dark_x = min(range(max(box[0], gx - win), min(box[2], gx + win + 1)),
                     key=lambda x: prof[x - box[0]])
        l_lo = max(box[0], dark_x - int(best_lag * 0.55))
        l_hi = max(box[0], dark_x - int(best_lag * 0.15))
        left_wall = max(range(l_lo, l_hi), key=lambda x: prof[x - box[0]]) if l_hi > l_lo else (dark_x - int(best_lag * 0.3))

        r_lo = min(box[2], dark_x + int(best_lag * 0.15))
        r_hi = min(box[2], dark_x + int(best_lag * 0.55))
        right_wall = max(range(r_lo, r_hi), key=lambda x: prof[x - box[0]]) if r_hi > r_lo else (dark_x + int(best_lag * 0.3))

        sym_center = int(round((left_wall + right_wall) / 2.0))
        center = sym_center if abs(sym_center - dark_x) <= max(3, int(best_lag * 0.08)) else int(round(dark_x * 0.5 + sym_center * 0.5))

        spacing = (center - wells[-1]["x"]) if wells else None
        wells.append({
            "well": i,
            "x": center,
            "x_dark": dark_x,
            "left_wall": left_wall,
            "right_wall": right_wall,
            "symmetry_diff": abs(center - dark_x),
            "spacing": spacing
        })

    im_rgb = Image.open(src).convert("RGB")
    crop = im_rgb.crop((box[0], max(0, box[1] - 40), box[2], min(h, box[3] + 40)))
    draw = ImageDraw.Draw(crop)
    fnt = font(18 if crop.height < 150 else 22)
    for w_info in wells:
        rx = w_info["x"] - box[0]
        draw.line([(rx, 0), (rx, crop.height)], fill=CYAN, width=2)
        lw = w_info["left_wall"] - box[0]
        rw = w_info["right_wall"] - box[0]
        draw.line([(lw, crop.height - 15), (lw, crop.height)], fill=YELLOW, width=1)
        draw.line([(rw, crop.height - 15), (rw, crop.height)], fill=YELLOW, width=1)
        draw.text((rx - 10, 4), f"W{w_info['well']}", fill=YELLOW, font=fnt)

    out = dest / "detect_wells.jpg"
    save_jpeg(crop, out)
    res = {
        "stage": "detect-wells",
        "out": str(out),
        "src": str(src),
        "src_sha256": sha256(src),
        "pitch": round(float(best_lag), 1),
        "n_wells": len(wells),
        "lane_x": [w_info["x"] for w_info in wells],
        "wells": wells
    }
    if contrast_warning:
        res["warning"] = contrast_warning
    emit(res)


def cmd_detect_bp(src: Path, dest: Path, marker_x: int, y_range: str, n_bands: int = 7, width: int = 40) -> None:
    im = Image.open(src).convert("L")
    w, h = im.size
    y0, y1 = parse_ints(y_range, 2, "y_range")
    x_left = max(0, marker_x - width // 2)
    x_right = min(w, marker_x + width // 2 + 1)

    prof = [sum(im.getpixel((x, y)) for x in range(x_left, x_right)) / float(x_right - x_left) for y in range(y0, y1)]
    win = 5
    smooth = moving_average(prof, win)

    min_dist = max(24, (y1 - y0) // (n_bands + 5))
    candidates = []
    for i in range(5, len(smooth) - 5):
        if smooth[i] >= smooth[i - 1] and smooth[i] >= smooth[i + 1]:
            local_min = min(smooth[max(0, i - 15):min(len(smooth), i + 16)])
            prom = smooth[i] - local_min
            if prom >= 3.0:
                if not candidates or (i - candidates[-1][0]) >= min_dist:
                    candidates.append((i, smooth[i], prom))
                elif prom > candidates[-1][2]:
                    candidates[-1] = (i, smooth[i], prom)

    if len(candidates) > n_bands:
        scored = sorted(candidates, key=lambda t: t[2], reverse=True)[:n_bands]
        sorted_peaks = sorted(scored, key=lambda t: t[0])
    else:
        sorted_peaks = sorted(candidates, key=lambda t: t[0])

    strongest_idx = max(range(len(sorted_peaks)), key=lambda i: sorted_peaks[i][1]) if sorted_peaks else -1

    bands = []
    for i, (pi, b, prom) in enumerate(sorted_peaks, 1):
        bands.append({
            "index": i,
            "y": y0 + pi,
            "brightness": round(float(b), 1),
            "prominence": round(float(prom), 1),
            "strongest": (i - 1 == strongest_idx)
        })

    im_rgb = Image.open(src).convert("RGB")
    crop_box = clip_box((w, h), [max(0, marker_x - 120), y0, min(w, marker_x + 80), y1])
    crop = im_rgb.crop(crop_box)
    draw = ImageDraw.Draw(crop)
    fnt = font(20)
    for b_info in bands:
        rel_y = b_info["y"] - y0
        target_rx = marker_x - crop_box[0]
        draw.line([(target_rx - 60, rel_y), (target_rx - 5, rel_y)], fill=RED, width=2)
        draw.polygon([(target_rx - 5, rel_y), (target_rx - 14, rel_y - 4), (target_rx - 14, rel_y + 4)], fill=RED)
        draw.text((8, rel_y - 10), f"y={b_info['y']}", fill=YELLOW, font=fnt)

    out = dest / "detect_bp.jpg"
    save_jpeg(crop, out)

    ladder_500 = ["500bp", "400bp", "300bp", "200bp", "150bp", "100bp", "50bp"]
    rec_guide = []
    if len(bands) == 7:
        for lbl, b_info in zip(ladder_500, bands):
            rec_guide.append({"label": lbl, "y": b_info["y"]})

    emit({
        "stage": "detect-bp",
        "out": str(out),
        "src": str(src),
        "src_sha256": sha256(src),
        "marker_x": marker_x,
        "n_bands": len(bands),
        "bands": bands,
        "recommended_guide_500bp": rec_guide if rec_guide else None
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Per-gel scan overlays for visual positioning; never writes the annotation PNG")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--out-dir", type=Path, help="default: unique run directory under /tmp/codex/gel-annotation/; reuse explicitly within one run")
    sub = parser.add_subparsers(dest="cmd", required=True)

    grid = sub.add_parser("grid", help="xy ruler over the gel or a region")
    grid.add_argument("src", type=Path)
    grid.add_argument("--region", help="x0,y0,x1,y1")
    grid.add_argument("--x-step", type=int, default=100)
    grid.add_argument("--y-step", type=int, default=50)

    wells = sub.add_parser("wells", help="high-contrast well-row crop with absolute x ticks")
    wells.add_argument("src", type=Path)
    wells.add_argument("--row", required=True, help="y0,y1")
    wells.add_argument("--x0", type=int)
    wells.add_argument("--x1", type=int)
    wells.add_argument("--tick", type=int, default=40, help="absolute x tick spacing on the source")

    lanes = sub.add_parser("lanes", help="numbered verticals at candidate well centers")
    lanes.add_argument("src", type=Path, nargs="?")
    lanes.add_argument("--spec", type=Path, help="read all rows from the rendering spec; requires source_sha256")
    lanes.add_argument("--xs", help="comma-separated well-center x (legacy manual mode)")
    lanes.add_argument("--ys", help="one source y per well")
    lanes.add_argument("--well", type=int, help="well-row y")
    lanes.add_argument("--span", help="y0,y1 for the verticals")

    bp = sub.add_parser("bp", help="candidate marker-band y ticks")
    bp.add_argument("src", type=Path)
    bp.add_argument("--bands", required=True, help="label:y,label:y")
    bp.add_argument("--marker-x", required=True, type=int)

    zoom = sub.add_parser("zoom", help="crosshair crop around one candidate point")
    zoom.add_argument("src", type=Path)
    zoom.add_argument("--at", required=True, help="x,y")
    zoom.add_argument("--size", type=int, default=240)

    hint = sub.add_parser("hint", help="do not use for lane_x; brightness peaks are not wells")
    hint.add_argument("src", type=Path)
    hint.add_argument("--row", required=True, help="y0,y1")
    hint.add_argument("--n", type=int)
    hint.add_argument("--x0", type=int)
    hint.add_argument("--x1", type=int)

    dw = sub.add_parser("detect-wells", help="auto-detect physical well centers, comb pitch, and well walls via autocorrelation")
    dw.add_argument("src", type=Path)
    dw.add_argument("--row", required=True, help="y0,y1")
    dw.add_argument("--x0", type=int)
    dw.add_argument("--x1", type=int)
    dw.add_argument("--n", type=int, help="expected well count")
    dw.add_argument("--well1", type=int, help="optional anchor x for the first well")

    dbp = sub.add_parser("detect-bp", help="auto-detect marker band y peaks along the marker lane")
    dbp.add_argument("src", type=Path)
    dbp.add_argument("--marker-x", required=True, type=int)
    dbp.add_argument("--y-range", required=True, help="y0,y1 vertical range containing bands")
    dbp.add_argument("--n-bands", type=int, default=7, help="expected band count, default 7")
    dbp.add_argument("--width", type=int, default=40, help="sampling slice width, default 40")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    for name in ("x_step", "y_step", "tick", "size"):
        if hasattr(args, name) and getattr(args, name) <= 0:
            raise SystemExit(f"{name} must be positive")
    if args.cmd == "lanes" and args.spec:
        if any(v is not None for v in (args.src, args.xs, args.ys, args.well, args.span)):
            raise SystemExit("--spec cannot be mixed with manual source/geometry arguments")
        from annotate_gel import geometry, validate_row
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        src = resolve_src(Path(spec["src"]), args.repo)
        check_source(spec, sha256(src), required=True)
        rows = spec_rows(spec)
        with Image.open(src) as source:
            size = source.size
        rows = [dict(r, well=geometry(r, size[1])["well"]) for r in rows]
        for row in rows:
            validate_row(row, size)
            row_box(row, size)
        dest = out_dir_for(src, args.out_dir)
        for i, row in enumerate(rows, 1):
            row_dest = dest / f"row{i}"
            row_dest.mkdir(parents=True, exist_ok=True)
            region = row_box(row, size)
            # Use the exact spec values; do not round float coordinates differently from rendering.
            cmd_lanes(src, row_dest, row["lane_x"], row["well"], f"{region[1]},{region[3]}",
                      row.get("lane_y"), region, geometry_hash(rows))
        return
    if args.cmd == "lanes" and (args.src is None or not args.xs):
        raise SystemExit("lanes requires --spec SPEC or SRC --xs ...")
    src = resolve_src(args.src, args.repo)
    dest = out_dir_for(src, args.out_dir)
    if args.cmd == "grid":
        cmd_grid(src, dest, args.region, args.x_step, args.y_step)
    elif args.cmd == "wells":
        cmd_wells(src, dest, args.row, args.x0, args.x1, args.tick)
    elif args.cmd == "lanes":
        cmd_lanes(src, dest, args.xs, args.well, args.span, args.ys)
    elif args.cmd == "bp":
        cmd_bp(src, dest, args.bands, args.marker_x)
    elif args.cmd == "zoom":
        cmd_zoom(src, dest, args.at, args.size)
    elif args.cmd == "hint":
        cmd_hint(src, dest, args.row, args.n, args.x0, args.x1)
    elif args.cmd == "detect-wells":
        cmd_detect_wells(src, dest, args.row, args.x0, args.x1, args.n, args.well1)
    elif args.cmd == "detect-bp":
        cmd_detect_bp(src, dest, args.marker_x, args.y_range, args.n_bands, args.width)
    else:
        raise SystemExit(f"unknown command {args.cmd}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
