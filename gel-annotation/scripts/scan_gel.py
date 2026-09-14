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
    crop = im.crop(box).convert("L")
    crop = ImageEnhance.Contrast(crop).enhance(2.5).convert("RGB")
    scale = 2 if crop.size[1] < 220 else 1
    if scale > 1:
        crop = crop.resize((crop.size[0] * scale, crop.size[1] * scale))
    draw_x_ticks(crop, box[0], tick, scale)
    out = dest / "wells.jpg"
    save_jpeg(crop, out)
    panels = []
    if crop.size[0] > 1400:
        n = 3
        pw = crop.size[0] // n
        for i in range(n):
            a = i * pw
            b = crop.size[0] if i == n - 1 else (i + 1) * pw
            panel = crop.crop((a, 0, b, crop.size[1]))
            path = dest / f"wells_p{i + 1}.jpg"
            save_jpeg(panel, path)
            panels.append(str(path))
    emit(
        {
            "stage": "wells",
            "out": str(out),
            "panels": panels,
            "src": str(src),
            "src_sha256": sha256(src),
            "size": [w, h],
            "row": [box[1], box[3]],
            "x": [box[0], box[2]],
            "scale": scale,
            "tick": tick,
            "note": "read absolute x from the yellow ticks; view each panel",
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


def cmd_lanes(src: Path, dest: Path, xs_text: str, well: int | None, span: str | None, ys_text: str | None = None) -> None:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    xs = parse_ints(xs_text, None, "xs")
    ys = parse_ints(ys_text, len(xs), "ys") if ys_text else None
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
    if well is not None:
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
    lanes.add_argument("src", type=Path)
    lanes.add_argument("--xs", required=True, help="comma-separated well-center x")
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
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    for name in ("x_step", "y_step", "tick", "size"):
        if hasattr(args, name) and getattr(args, name) <= 0:
            raise SystemExit(f"{name} must be positive")
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
    else:
        raise SystemExit(f"unknown command {args.cmd}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
