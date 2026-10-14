#!/usr/bin/env python3
"""Draw a second-batch-style gel overlay. Geometry comes from this gel's spec."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import stat
import locale
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, __version__ as PILLOW_VERSION, features
from review_gel import annotation_review, check_source, review_directory, row_box, spec_rows

PROFILE_PATH = Path(__file__).resolve().parents[1] / "assets/style_profiles/second_batch_v1.json"
DEFAULT_STYLE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
# Compatibility exports; actual rendering receives a per-call resolved profile.
COLORS = {key: tuple(value) for key, value in DEFAULT_STYLE["colors"].items()}
FONT = Path(DEFAULT_STYLE["fonts"]["regular"])
FONT_BOLD = Path(DEFAULT_STYLE["fonts"]["bold"])
OFFSET = DEFAULT_STYLE["offsets"]


def presentation_rows(spec, rows, fonts):
    """Top-level opt-in; project row facts override top-level facts, not preset policy."""
    selected = spec.get('presentation_profile')
    preset = None
    record = None
    if selected is not None:
        if selected != 'recognized_minimal_v1':
            raise SystemExit('unknown presentation_profile')
        path = input_file(PROFILE_PATH.with_name(selected + '.json'))
        preset = json.loads(path.read_text(encoding='utf-8'))
        if preset.get('schema_version') != 1 or preset.get('name') != selected:
            raise SystemExit('invalid presentation preset')
        if not spec.get('source_sha256'):
            raise SystemExit('presentation preset requires source_sha256')
        record = dict(name=selected, path=path, sha256=sha256(path),
                      effective={key: preset[key] for key in ('annotation_profile', 'primer_separator',
                                 'primer_language', 'primer_layout_engine', 'primer_face_index')},
                      precedence='row date/primer override top-level; preset policy fixed, conflicting policy rejected')
    result = []
    policy_keys = ('annotation_profile', 'primer_separator', 'primer_language', 'primer_layout_engine', 'primer_face_index')
    for supplied in rows:
        row = dict(supplied)
        if 'presentation_profile' in row and row['presentation_profile'] != selected:
            raise SystemExit('presentation_profile must be selected at top-level, not per-row')
        for key in ('date', 'primer_name', *policy_keys):
            if key in spec:
                row.setdefault(key, spec[key])
        if preset:
            for key in policy_keys:
                if key in spec and spec[key] != preset[key] or key in row and row[key] != preset[key]:
                    raise SystemExit(f'presentation preset conflicts with {key}')
                row[key] = preset[key]
        separator = row.get('primer_separator', ' ')
        if not isinstance(separator, str) or not 1 <= len(separator) <= 16 or any(
                unicodedata.category(c).startswith('C') for c in separator):
            raise SystemExit('primer_separator must be 1-16 characters without control/invisible characters')
        language = row.get('primer_language')
        if language is not None and (not isinstance(language, str) or not language):
            raise SystemExit('primer_language must be null or a nonempty string')
        regular = fonts['regular']
        for key, actual in (('primer_layout_engine', regular['layout_engine']), ('primer_face_index', regular['face_index'])):
            if key in row and row[key] != actual:
                raise SystemExit(f'{key} incompatible with actual regular font')
        row.setdefault('primer_separator', separator)
        row.setdefault('primer_language', language)
        row.setdefault('primer_layout_engine', regular['layout_engine'])
        row.setdefault('primer_face_index', regular['face_index'])
        result.append(row)
    return result, record


def primer_text(spec):
    if spec.get('annotation_profile') == 'report_minimal':
        return f"{spec['date']}{spec.get('primer_separator', ' ')}{spec['primer_name']}"
    return spec.get('primer_line')


def resolve_style(spec, repo):
    supplied = spec.get("style_profile")
    path = None
    if isinstance(supplied, dict):
        style = copy.deepcopy(supplied)
    else:
        path = resolve(Path(supplied), repo) if supplied else PROFILE_PATH
        input_file(path)
        style = json.loads(path.read_text(encoding="utf-8"))
    if style.get("schema_version") != 1:
        raise SystemExit("unsupported style profile schema")
    for section in ("colors", "fonts", "offsets", "font_sizes", "drawing"):
        if set(style.get(section, {})) != set(DEFAULT_STYLE[section]):
            raise SystemExit(f"style profile missing/unknown {section} parameters")
    for color in style["colors"].values():
        if len(color) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in color):
            raise SystemExit("invalid profile RGB color")
    for section in ("font_sizes", "drawing"):
        if any(not isinstance(v, (int, float)) or not 0 < v < float('inf') for v in style[section].values()):
            raise SystemExit(f"invalid profile {section}")
    provenance = dict(kind="embedded" if path is None else "file",
                      file_sha256=sha256(path) if path else None,
                      effective_sha256=hashlib.sha256(json.dumps(style, sort_keys=True, separators=(',', ':')).encode()).hexdigest())
    fonts = {}
    for role, value in style["fonts"].items():
        font_path = resolve(Path(spec.get("font_paths", {}).get(role, value)), repo)
        input_file(font_path)
        engine = spec.get('font_layout_engine', {}).get(role)
        if engine not in (None, 'BASIC', 'RAQM') or (engine == 'RAQM' and not features.check('raqm')):
            raise SystemExit('invalid/unavailable explicit font layout engine')
        face = spec.get('font_face_index', {}).get(role, 0)
        loaded = ImageFont.truetype(str(font_path), 12, index=face,
                                    layout_engine=getattr(ImageFont.Layout, engine) if engine else None)
        actual = sha256(font_path)
        expected = spec.get("font_sha256", {}).get(role)
        if expected is not None and expected != actual:
            raise SystemExit(f"font sha256 mismatch: {role}")
        fonts[role] = dict(path=font_path, sha256=actual, name=list(loaded.getname()),
                           layout_engine=loaded.layout_engine.name, face_index=face,
                           resolution="explicit font_paths" if role in spec.get("font_paths", {}) else "style_profile fonts")
    return style, provenance, fonts


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def font(size: int, bold: bool = False, fonts=None) -> ImageFont.FreeTypeFont:
    path = Path(fonts["bold" if bold else "regular"]["path"]) if fonts else (FONT_BOLD if bold else FONT)
    if not path.is_file():
        raise SystemExit(f"missing font: {path}")
    record = fonts['bold' if bold else 'regular'] if fonts else {}
    return ImageFont.truetype(str(path), size, index=record.get('face_index', 0),
                              layout_engine=getattr(ImageFont.Layout, record['layout_engine']) if record.get('layout_engine') else None)


def centered(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, fnt, fill, language=None) -> None:
    box = draw.textbbox((0, 0), text, font=fnt, language=language)
    pos = (x - (box[2] + box[0]) / 2, y - (box[3] + box[1]) / 2)
    checked_text(draw, pos, text, fnt, fill, language=language)


def checked_text(draw, pos, text, fnt, fill, language=None) -> None:
    box = draw.textbbox(pos, text, font=fnt, language=language)
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
    draw.text(pos, text, font=fnt, fill=fill, language=language)


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


def arrow(draw: ImageDraw.ImageDraw, start, end, color, width=4, head=16, head_ratio=0.55) -> None:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    left = (end[0] - ux * head + px * head * head_ratio, end[1] - uy * head + py * head * head_ratio)
    right = (end[0] - ux * head - px * head * head_ratio, end[1] - uy * head - py * head * head_ratio)
    checked_points(draw, [start, end], width, "arrow shaft")
    checked_points(draw, [end, left, right], 1, "arrow head")
    draw.line((*start, *end), fill=color, width=width)
    draw.polygon([end, left, right], fill=color)


def group_bracket(draw: ImageDraw.ImageDraw, x0, x1, y, y1, color, width=4) -> None:
    checked_line(draw, (x0, y, x1, y), color, width, "bracket")
    checked_line(draw, (x0, y, x0, y1), color, width, "bracket")
    checked_line(draw, (x1, y, x1, y1), color, width, "bracket")


def load_spec(path: Path) -> dict:
    input_file(path)
    spec = json.loads(path.read_text(encoding="utf-8"))
    for key in ("src", "out"):
        if key not in spec:
            raise SystemExit(f"spec missing {key}")
    return spec


def resolve(path: Path, repo: Path) -> Path:
    return path if path.is_absolute() else (repo / path)


def geometry(spec: dict, image_height: int, style=None) -> dict:
    style = style or DEFAULT_STYLE
    well = spec.get("well")
    if well is None and spec.get("y"):
        well = spec["y"].get("well")
    if well is None:
        raise SystemExit("missing well; look at the hole row on this gel and put well in the spec")
    well = int(well)
    y = {key: well + delta for key, delta in style["offsets"].items()}
    y["well"] = well
    y["primer"] = image_height - style["drawing"]["primer_bottom_offset"]
    if spec.get("y"):
        y.update(spec["y"])
    return y


def display_label(item: dict) -> str:
    label = item.get("display_label")
    return (item.get("name") if label is None else label) or ""


def check_write_path(path: Path) -> None:
    # Inspect the lexical path BEFORE resolve; even link/../dest is rejected.
    if '3.记录' in path.absolute().parts:
        raise SystemExit('personal records are prohibited')
    for part in (path.absolute(), *path.absolute().parents):
        if part.is_symlink():
            raise SystemExit(f"write path contains symlink: {part}")
    for parent in path.absolute().parents:
        if parent.exists() and not parent.is_dir():
            raise SystemExit(f"write parent is not a directory: {parent}")


def input_file(path):
    path = Path(path).absolute()
    check_write_path(path)
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise SystemExit(f'missing/nonregular input: {path}')
    return path


def destination_plan(files, directories, protected):
    """Reject aliases AND file/directory ancestry conflicts before any mkdir/save."""
    files, directories = list(files), list(directories)
    for path in files + directories:
        check_write_path(path)
        if any(same_path(path, p) for p in protected):
            raise SystemExit('output/input alias: must not overwrite protected inputs')
    for i, path in enumerate(files):
        if any(same_path(path, p) for p in files[:i]):
            raise SystemExit('duplicate file destination')
        for other in files[:i] + directories:
            a, b = path.resolve(), other.resolve()
            if a == b or b.is_relative_to(a) or (other in files[:i] and a.is_relative_to(b)):
                raise SystemExit('file/directory destination conflict')
    for directory in directories:
        if any(p.resolve().is_relative_to(directory.resolve()) for p in protected):
            raise SystemExit('output directory contains a protected input')


def same_path(a: Path, b: Path) -> bool:
    return a.resolve() == b.resolve() or (a.exists() and b.exists() and a.samefile(b))


def check_candidate_overwrite(spec, src, out, before, manifest):
    if not out.exists() and not manifest.exists():
        return
    if not spec.get("overwrite") or not out.is_file() or not manifest.is_file():
        raise SystemExit("existing output/manifest requires a verified candidate pair and overwrite")
    try:
        old = json.loads(manifest.read_text(encoding="utf-8"))
        root = manifest.parent
        original = [r for r in old["sources"] if r["kind"] == "original"]
        valid = (old["schema_version"] == 1 and old["path_base"] == "manifest_directory"
                 and isinstance(old["sample_mapping"], list) and isinstance(old["spec"]["rows"], list)
                 and len(original) == 1 and original[0]["sha256"] == before
                 and same_path(root / original[0]["path"], src)
                 and old["spec"]["source_sha256"] == before
                 and same_path(root / old["spec"]["src"], src)
                 and same_path(root / old["spec"]["out"], out)
                 and same_path(root / old["output"]["path"], out)
                 and old["output"]["sha256"] == sha256(out))
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise SystemExit("overwrite ownership/source/output hash mismatch; use new paths")


def archive_manifest(spec, rows, src, out, before, dest, sources, image_height, style, profile_record, fonts,
                     presentation_record=None, footer_records=None):
    """Paths are relative to the manifest, not the machine's checkout root."""
    def relative(path):
        return os.path.relpath(path.resolve(), dest.parent.resolve())

    normalized = copy.deepcopy(spec)
    normalized.pop("overwrite", None)
    normalized.pop("rows", None)
    for key in rows[0]:
        normalized.pop(key, None)
    normalized.update(src=relative(src), out=relative(out), source_sha256=before,
                      rows=copy.deepcopy(rows))
    # A legacy row includes global fields; keep archived rows geometry-only.
    for row in normalized["rows"]:
        for key in ("src", "out", "source_sha256", "overwrite", "top_padding",
                    "source_annotations", "patch_record", "date_evidence", "style_profile", "font_paths", "font_sha256",
                    "font_layout_engine", "font_face_index", "portable_resources", "presentation_profile"):
            row.pop(key, None)
        row["y"] = geometry(row, image_height, style)
        row["well"] = row["y"]["well"]
        row.setdefault("lane_y", [row["well"]] * len(row["lane_x"]))
        row.setdefault("font_scale", 1)
        row.setdefault("marker_font_scale", row["font_scale"])
        row.setdefault("bp_font_scale", row["font_scale"])
        row.setdefault("annotation_profile", "default")
        row.setdefault('primer_language', None)
        row.setdefault('primer_separator', ' ')
        row.setdefault("marker_indices", [])
        row["drawing"] = drawing_parameters(row, style)
        for group in row.get("groups", []):
            group.setdefault("color", "purple")
            group.setdefault("draw_lines", True)
            group.setdefault("draw_bracket", group["draw_lines"])
            group.setdefault("y_shift", 0)
            group.setdefault("bar", False)
        if row.get("bp_guide"):
            xs = row["lane_x"]
            drawing = row["drawing"]
            marker_x = xs[row.get("bp_marker_index", row["marker_indices"][0])]
            row.setdefault("bp_arrow_x", max(drawing["bp_arrow_x_min"], min(xs) - drawing["bp_arrow_x_offset"]))
            row.setdefault("bp_label_x", max(drawing["bp_label_x_min"], row["bp_arrow_x"] - drawing["bp_label_x_offset"]))
            row.setdefault("bp_target_x", marker_x - drawing["bp_target_x_offset"])
    normalized["style_profile"] = copy.deepcopy(style)
    normalized["font_paths"] = {role: (relative(record["path"]) if spec.get('portable_resources') else str(record["path"].resolve()))
                                for role, record in fonts.items()}
    normalized["font_sha256"] = {role: record["sha256"] for role, record in fonts.items()}
    normalized['font_layout_engine'] = {role: record['layout_engine'] for role, record in fonts.items()}
    normalized['font_face_index'] = {role: record['face_index'] for role, record in fonts.items()}
    if spec.get('portable_resources'):
        normalized['portable_resources'] = True
    normalized.setdefault("top_padding", 0)
    for key in ("top_padding", "date_evidence", "patch_record"):
        if key in spec:
            normalized[key] = copy.deepcopy(spec[key])
    normalized["source_annotations"] = [dict(path=relative(p), sha256=h) for p, h in sources]
    if spec.get('presentation_profile') is not None:
        normalized['presentation_profile'] = spec['presentation_profile']
    mapping = []
    for row_number, row in enumerate(rows, 1):
        for index in range(len(row["lane_x"])):
            labels = [dict(group=g, name=item.get("name"), sample_id=item.get("sample_id"),
                           display_label=display_label(item), loading_order=item.get("loading_order"))
                      for g, group in enumerate(row.get("groups", []), 1)
                      for item in group["lanes"] if item["index"] == index]
            mapping.append(dict(row=row_number, index=index, physical_index=index + 1,
                                marker=index in row.get("marker_indices", []), labels=labels))
    payload = dict(schema_version=1, spec=normalized, path_base="manifest_directory",
                   sources=[dict(kind="original", path=relative(src), sha256=before)] +
                           [dict(kind="existing_annotation", path=relative(p), sha256=h) for p, h in sources],
                   output=dict(path=relative(out), sha256=sha256(out)), sample_mapping=mapping,
                   annotation_profile=[r.get("annotation_profile", "default") for r in rows],
                   visual_status="not_reviewed")
    payload["finalspec"] = copy.deepcopy(normalized)
    payload['footers'] = footer_records or []
    if presentation_record:
        payload['presentation_profile'] = dict(presentation_record, path=relative(presentation_record['path']))
    payload["resolved_y"] = [row["y"] for row in normalized["rows"]]
    payload["style_profile"] = dict(profile_record, name=style.get("name"))
    payload["render_environment"] = dict(python=platform.python_version(), pillow=PILLOW_VERSION,
                                       raqm=features.version('raqm'), harfbuzz=features.version('harfbuzz'),
                                       fribidi=features.version('fribidi'), locale=locale.setlocale(locale.LC_CTYPE),
                                       freetype=features.version("freetype2"),
                                       renderer_sha256=sha256(Path(__file__)),
                                       review_helper_sha256=sha256(Path(__file__).with_name("review_gel.py")),
                                       fonts={role: dict(record, path=relative(record["path"])) for role, record in fonts.items()})
    for key in ("date_evidence", "patch_record"):
        if key in spec:
            payload[key] = spec[key]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def annotate(spec: dict, repo: Path, lane_x: list[int] | None, review_dir: Path | None = None,
             manifest: Path | None = None, protected_inputs: list[Path] | None = None,
             preflight_only: bool = False) -> Path:
    src = resolve(Path(spec["src"]), repo)
    out = resolve(Path(spec["out"]), repo)
    check_write_path(out)
    input_file(src)
    if "（标注）" not in out.name:
        raise SystemExit(f"output name must contain （标注）: {out.name}")
    if out.resolve() == src.resolve():
        raise SystemExit("refusing to overwrite source image")

    if out.suffix.lower() != ".png":
        raise SystemExit("annotation output must be PNG")
    before = sha256(src)
    manifest = resolve(manifest, repo) if manifest is not None else out.with_suffix(".annotation-manifest.json")
    check_write_path(manifest)
    if manifest.suffix.lower() != ".json":
        raise SystemExit("annotation manifest must be JSON (.json)")
    protected = [src] + [resolve(Path(p), repo) for p in (protected_inputs or [])]
    for path in protected:
        input_file(path)
    sources = []
    for record in spec.get("source_annotations", []):
        path = resolve(Path(record["path"]), repo)
        input_file(path)
        actual = sha256(path)
        if record.get("sha256") is not None and record["sha256"] != actual:
            raise SystemExit("existing annotation sha256 mismatch")
        protected.append(path)
        sources.append((path, actual))
    style, profile_record, fonts = resolve_style(spec, repo)
    # Presentation validation is purely additive; existing safety preflight is unchanged.
    rows, presentation_record = presentation_rows(spec, spec_rows(spec), fonts)
    protected.extend(record['path'] for record in fonts.values())
    if presentation_record:
        protected.append(presentation_record['path'])
    if isinstance(spec.get('style_profile'), str):
        protected.append(resolve(Path(spec['style_profile']), repo))
    else:
        protected.append(PROFILE_PATH)
    destination_plan([out, manifest], [review_dir] if review_dir is not None else [], protected)
    if same_path(manifest, out) or any(same_path(dest, p) for dest in (out, manifest) for p in protected):
        raise SystemExit("output/manifest must not overwrite protected inputs or each other")
    check_candidate_overwrite(spec, src, out, before, manifest)
    if review_dir is not None:
        check_write_path(review_dir)
        review_dir = review_directory(review_dir)
        if any(p.resolve().is_relative_to(review_dir) for p in [out, manifest, *protected]):
            raise SystemExit("review directory must not contain outputs, manifest or protected inputs")
        if review_dir.exists() and (not review_dir.is_dir() or any(review_dir.iterdir())):
            raise SystemExit("review directory must be fresh or empty; use a new review path")
    check_source(spec, before, required=review_dir is not None)
    original = Image.open(src).convert("RGB")
    if lane_x is not None:
        rows = [dict(rows[0], lane_x=lane_x)]
    padding = int(spec.get("top_padding", 0))
    if padding < 0:
        raise SystemExit("top_padding must be nonnegative")
    for row in rows:
        validate_row(row, original.size, style)
        if review_dir is not None:
            row_box(dict(row, well=geometry(row, original.height, style)["well"]), original.size)
    im = Image.new("RGB", (original.width, original.height + padding), "black")
    im.paste(original, (0, padding))
    draw = ImageDraw.Draw(im)
    for i, row in enumerate(rows, 1):
        draw._context = f"row {i}"
        draw_row(im, row, original.height, padding, draw, style, fonts)
    if before != sha256(src):
        raise SystemExit("source image changed while annotating")
    if any(sha256(path) != digest for path, digest in sources):
        raise SystemExit("existing annotation changed while annotating")
    if preflight_only:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    archive_manifest(spec, rows, src, out, before, manifest, sources, original.height, style, profile_record, fonts,
                     presentation_record, getattr(draw, '_footer_records', []))
    if review_dir is not None:
        normalized = [dict(r, well=geometry(r, original.height, style)["well"]) for r in rows]
        with Image.open(out) as saved:
            annotation_review(original, saved.convert("RGB"), normalized, padding, review_dir, out, before,
                              getattr(draw, '_text_boxes', []) + getattr(draw, '_shape_boxes', []))
    return out


def validate_row(spec: dict, size: tuple[int, int], style=None) -> None:
    style = style or DEFAULT_STYLE
    profile = spec.get("annotation_profile", "default")
    if profile not in ("default", "report_minimal"):
        raise SystemExit("unknown annotation_profile")
    if profile == "report_minimal" and not all(spec.get(k) for k in ("date", "primer_name")):
        raise SystemExit("report_minimal requires explicit date and primer_name")
    w, h = size
    xs = spec.get("lane_x", [])
    if not xs or any(not isinstance(x, (int, float)) or not 0 <= x < w for x in xs):
        raise SystemExit("lane_x must contain source-image x coordinates")
    if any(a >= b for a, b in zip(xs, xs[1:])):
        raise SystemExit("lane_x must be strictly increasing")
    y = geometry(spec, h, style)
    ys = spec.get("lane_y", [y["well"]] * len(xs))
    if len(ys) != len(xs) or any(not isinstance(v, (int, float)) or not 0 <= v < h for v in ys):
        raise SystemExit("lane_y must contain one source-image y per well")
    used = set()
    markers = spec.get("marker_indices", [])
    for group in spec.get("groups", []):
        if profile == "report_minimal" and group.get("control") in ("PC", "NTC"):
            if not any(display_label(item).strip() for item in group["lanes"]):
                raise SystemExit("minimal PC/NTC requires an explicit nonempty replacement lane label")
        if profile == "report_minimal" and group.get("control") == "PC" and group.get("species") != "human":
            labels = [display_label(item) for item in group["lanes"]]
            if len(set(label for label in labels if label)) > 1 or not any(labels):
                raise SystemExit("non-human minimal PC requires one supplied shared label (or one labeled lane)")
        for item in group["lanes"]:
            for key in ("name", "sample_id", "display_label"):
                if key in item and item[key] is not None and not isinstance(item[key], str):
                    raise SystemExit(f"lane {key} must be a string")
        indices = [item["index"] for item in group["lanes"]]
        if not indices or any(type(i) is not int or not 0 <= i < len(xs) for i in indices):
            raise SystemExit("group indices must refer to existing wells")
        if indices != sorted(set(indices)):
            raise SystemExit("group indices must be unique and increasing")
        if group.get("draw_lines", True):
            if used.intersection(indices):
                raise SystemExit("well assigned to multiple drawing groups")
            used.update(indices)
        if group.get("color", "purple") not in style["colors"]:
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


def drawing_parameters(spec, style):
    drawing = dict(style["drawing"])
    overrides = spec.get("drawing", {})
    if set(overrides) - set(drawing):
        raise SystemExit("unknown drawing parameter")
    drawing.update(overrides)
    if any(not isinstance(v, (int, float)) or not 0 < v < float('inf') for v in drawing.values()):
        raise SystemExit("invalid drawing parameter")
    for key in ("line_width", "bracket_width", "marker_arrow_width", "bp_arrow_width"):
        if type(drawing[key]) is not int:
            raise SystemExit(f"{key} must be an integer")
    return drawing


def draw_row(im: Image.Image, spec: dict, image_height: int, padding: int, draw=None, style=None, fonts=None) -> None:
    style = style or DEFAULT_STYLE
    colors = {key: tuple(value) for key, value in style["colors"].items()}
    drawing = drawing_parameters(spec, style)
    sizes = style["font_sizes"]
    xs = spec["lane_x"]
    y = {key: value + padding for key, value in geometry(spec, image_height, style).items()}
    ys = [v + padding for v in spec.get("lane_y", [y["well"] - padding] * len(xs))]
    draw = draw if draw is not None else ImageDraw.Draw(im)
    row_context = getattr(draw, '_context', 'row')
    scale = spec.get("font_scale", 1)
    head_f = font(max(1, round(sizes["head"] * scale)), True, fonts)
    param_f = font(max(1, round(sizes["param"] * scale)), True, fonts)
    lane_f = font(max(1, round(sizes["lane"] * scale)), fonts=fonts)
    marker_scale = float(spec.get("marker_font_scale", 1.0 if "marker_font_scale" in spec else scale))
    marker_f = font(max(1, round(sizes["marker"] * marker_scale)), fonts=fonts)
    bp_scale = float(spec.get("bp_font_scale", 1.0 if "bp_font_scale" in spec else scale))
    bp_f = font(max(1, round(sizes["bp"] * bp_scale)), fonts=fonts)
    primer_f = font(max(1, round(sizes["primer"] * scale)), fonts=fonts)
    minimal = spec.get("annotation_profile") == "report_minimal"

    for group_index, group in enumerate(spec.get("groups", []), 1):
        draw._context = f"{row_context}/group {group_index}"
        color = colors[group.get("color", "purple")]
        lanes = group["lanes"]
        indices = [item["index"] for item in lanes]
        x_first, x_last = xs[indices[0]], xs[indices[-1]]
        mid = (x_first + x_last) / 2
        shift = int(group.get("y_shift") or 0)
        draw_lines = group.get("draw_lines", True)
        if len(indices) >= 2 and group.get("draw_bracket", draw_lines):
            group_bracket(draw, x_first - drawing["bracket_x_pad"] * scale, x_last + drawing["bracket_x_pad"] * scale,
                          y["bracket"], y["bracket_end"], color, drawing["bracket_width"])
        control = group.get("control") in ("NTC", "PC")
        if group.get("head") and not (minimal and control):
            centered(draw, mid, y["head"] + shift, group["head"], head_f, color)
        if group.get("param") and not minimal:
            centered(draw, mid, y["param"] + shift, group["param"], param_f, color)
        if group.get("bar") and len(indices) >= 2 and not minimal:
            bar_y = y["param"] + shift + drawing["bar_y_offset"]
            checked_line(draw, (x_first - drawing["bar_x_pad"], bar_y, x_last + drawing["bar_x_pad"], bar_y),
                         color, drawing["line_width"], name="bar")
        names = [display_label(item) for item in lanes]
        labeled = [name for name in names if name]
        same_name = len(set(labeled)) == 1 and len(labeled) == len(names)
        if labeled and same_name:
            centered(draw, mid, y["lane"], names[0], lane_f, color)
        for item in lanes:
            x = xs[item["index"]]
            name = display_label(item)
            if name and not same_name:
                centered(draw, x, y["lane"], name, lane_f, color)
            if draw_lines:
                checked_line(draw, (x, y["bracket"], x, ys[item["index"]]), color,
                             drawing["line_width"], name=f"well {item['index']+1} leader")

    for idx in spec.get("marker_indices", []):
        draw._context = f"{row_context}/Marker well {idx+1}"
        x = xs[idx]
        centered(draw, x, y["marker"], "Marker", marker_f, colors["white"])
        arrow(draw, (x, y["marker_arrow"]), (x, ys[idx]), colors["white"],
              drawing["marker_arrow_width"], drawing["marker_arrow_head"], drawing["arrow_head_ratio"])

    bp_guide = spec.get("bp_guide") or []
    marker_indices = spec.get("marker_indices") or []
    marker_x = xs[spec.get("bp_marker_index", marker_indices[0])] if marker_indices else xs[0]
    gel_left = min(xs)
    bp_arrow_x = spec.get("bp_arrow_x", max(drawing["bp_arrow_x_min"], gel_left - drawing["bp_arrow_x_offset"]))
    bp_label_x = spec.get("bp_label_x", max(drawing["bp_label_x_min"], bp_arrow_x - drawing["bp_label_x_offset"]))
    bp_target_x = spec.get("bp_target_x", marker_x - drawing["bp_target_x_offset"])
    for item in bp_guide:
        draw._context = f"{row_context}/bp"
        band_y = item["y"] + padding
        checked_text(draw, (bp_label_x, band_y - drawing["bp_text_y_offset"]), item["label"], bp_f, colors["red"])
        arrow(draw, (bp_arrow_x, band_y), (bp_target_x, band_y), colors["red"],
              drawing["bp_arrow_width"], drawing["bp_arrow_head"], drawing["arrow_head_ratio"])

    primer_line = primer_text(spec)
    if primer_line:
        draw._context = f"{row_context}/primer"
        primer_x = (min(xs) + max(xs)) / 2
        centered(draw, primer_x, y["primer"], primer_line, primer_f, colors["red"], language=spec.get('primer_language'))
        records = getattr(draw, '_footer_records', [])
        records.append(dict(row=row_context, text=primer_line, language=spec.get('primer_language'),
                            separator=spec.get('primer_separator', ' ') if minimal else None,
                            center=[primer_x, y['primer']], bbox=list(draw._text_boxes[-1][1]),
                            font_size=primer_f.size, font_sha256=fonts['regular']['sha256'] if fonts else sha256(FONT),
                            layout_engine=primer_f.layout_engine.name, face_index=spec.get('primer_face_index', 0)))
        draw._footer_records = records



def main() -> None:
    parser = argparse.ArgumentParser(description="Annotate a gel from a per-image spec")
    parser.add_argument("spec", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--review-dir", type=Path, help="write native-pixel review panels and review.json; requires source_sha256")
    parser.add_argument("--manifest", type=Path, help="archive normalized spec and provenance; default: OUTPUT.annotation-manifest.json")
    args = parser.parse_args()
    spec = load_spec(args.spec)
    if args.overwrite:
        spec["overwrite"] = True
    out = annotate(spec, args.repo, None, args.review_dir, args.manifest,
                   protected_inputs=[args.spec.absolute()])
    if args.review_dir:
        print((args.review_dir / "review.json").read_text(encoding="utf-8"))
    else:
        print(out)


if __name__ == "__main__":
    main()
