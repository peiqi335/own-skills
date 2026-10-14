#!/usr/bin/env python3
"""Offline two-run replay, with whole-batch preflight and unmodified raw comparisons."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import zlib
import render_gdv as gdv


def no_symlink(path):
    return gdv.lexical_path(path)


def repo_path(repo, relative):
    gdv.require(isinstance(relative, str) and relative.strip() and not Path(relative).is_absolute(), '需要 repo 相对路径')
    path = no_symlink(repo / relative)
    gdv.require(path.is_relative_to(repo), '路径逃逸 repo')
    return path


def preflight(repo, config_path, output, profile=None):
    repo = no_symlink(repo)
    config_path = no_symlink(config_path)
    config = gdv.read_json(config_path)
    if profile is not None and not isinstance(profile, dict): profile = no_symlink(profile)
    profile = gdv.load_profile(profile)
    source_manifest = repo_path(repo, config['source_manifest'])
    source = gdv.read_json(source_manifest)
    destination = no_symlink(output)
    gdv.require(destination.is_relative_to(repo), '输出路径逃逸 repo')
    gdv.require(not destination.exists(), 'batch 输出必须为新目录')
    gdv.require(not (gdv.PROTECTED & set(destination.parts)), 'batch 输出受保护')
    ids, aliases, svg_aliases, records, sources = set(), set(), set(), [], {source_manifest, Path(config_path).resolve()}
    for entry in source['loci']:
        for key in ('revised_spec', 'original_spec'):
            gdv.require(isinstance(entry.get(key), str) and entry[key].strip() and not Path(entry[key]).is_absolute(), f'{key} 需要相对路径')
        path = no_symlink(source_manifest.parent / entry['revised_spec'])
        gdv.require(path.is_relative_to(repo), 'spec 逃逸 repo')
        declared = gdv.read_json(path)
        relatives = [declared[k] for k in ('official_svg', 'chromosome_metadata', 'assembly_info', 'product_report') if declared.get(k)]
        if declared.get('primer_evidence'): relatives.append(declared['primer_evidence']['source']['path'])
        if declared.get('titleless_export'): relatives.append(declared['titleless_export']['page_capture'])
        for relative in relatives:
            gdv.require(isinstance(relative, str) and not Path(relative).is_absolute(), '证据需要相对路径')
            evidence = no_symlink(path.parent / relative)
            gdv.require(evidence.is_relative_to(repo), '证据逃逸 repo')
            sources.add(evidence)
        s, raw = gdv.load_spec(path, input_root=repo)
        locus = s['locus_id']
        gdv.require(locus == entry['locus'] and locus not in ids, '重复或不一致 locus ID')
        identity = (path.stat().st_dev, path.stat().st_ino)
        svg_identity = (s['_official_svg'].stat().st_dev, s['_official_svg'].stat().st_ino)
        gdv.require(identity not in aliases and svg_identity not in svg_aliases, '重复源 spec/SVG alias（含 hardlink）')
        ids.add(locus); aliases.add(identity); svg_aliases.add(svg_identity); sources.add(path)
        for key in ('official_svg', 'chromosome_metadata', 'assembly_info', 'product_report'):
            if s.get(key): sources.add(no_symlink(path.parent / s[key]))
        for key in ('_primer_source', '_page_capture'):
            if s.get(key): sources.add(no_symlink(s[key]))
        gdv.compose(s, raw, profile)
        old = no_symlink(source_manifest.parent / entry['original_spec'])
        old = gdv.lexical_path(old, repo, 'file')
        gdv.output_path(destination, s)
        gdv.require(not destination.is_relative_to(path.parent) and not destination.is_relative_to(old.parent), '输出与源目录 alias/嵌套')
        old_spec = gdv.read_json(old)
        gdv.require(isinstance(old_spec, dict), 'original_spec 应为对象')
        tracks = old_spec.get('tracks')
        gdv.require(isinstance(tracks, list) and len(tracks) == 6 and all(isinstance(t, dict) for t in tracks), 'original tracks shape 无效')
        gdv.require({t.get('role') for t in tracks} == gdv.ROLES, 'original tracks roles 无效')
        for track in tracks:
            gdv.require(track.get('status') in {'loaded', 'available_empty', 'unavailable', 'source_unverified_excluded'}, 'original track status 无效')
            gdv.require(isinstance(track.get('title'), str) and isinstance(track.get('evidence'), str) and track['evidence'].strip(), 'original track title/evidence 无效')
        control = copy.deepcopy(s); control['tracks'] = tracks
        control_svg = gdv.compose(control, raw, profile)
        sources.add(old)
        for ext in ('svg', 'png', 'pdf'):
            old_output = old.parent / f'{locus}_enhanced.{ext}'
            gdv.require(old_output.is_file(), f'缺失历史对照：{old_output}')
            sources.add(no_symlink(old_output))
        records.append((locus, path, old, s, old_spec, control_svg))
    for discrepancy in source.get('endpoint_discrepancies', []):
        report = gdv.lexical_path(source_manifest.parent / discrepancy['mRNA_report_path'], repo, 'file')
        sources.add(report)
        discrepancy['mRNA_report_path'] = str(report.relative_to(repo))
        discrepancy['path_base'] = 'repository_root'
        discrepancy['mRNA_report_sha256'] = gdv.sha(report)
        discrepancy['scientific_review'] = 'pending_not_verified'
    gdv.require(records, '空 batch')
    for path in sources:
        gdv.require(path.is_relative_to(repo), '证据逃逸 repo')
        gdv.require(not path.is_relative_to(destination) and not destination.is_relative_to(path), '输出与源 alias/嵌套')
    return repo, destination, profile, source, records, {str(p.relative_to(repo)): gdv.sha(p) for p in sorted(sources)}


def pixels(path):
    from PIL import Image
    with Image.open(path) as image:
        image = image.convert('RGBA')
        return {'size': list(image.size), 'mode': 'RGBA', 'sha256': hashlib.sha256(image.tobytes()).hexdigest()}


def pixel_diff(a, b, difference_output=None):
    from PIL import Image, ImageChops
    with Image.open(a) as ia, Image.open(b) as ib:
        ia, ib = ia.convert('RGBA'), ib.convert('RGBA')
        sizes = (list(ia.size), list(ib.size))
        same_size = ia.size == ib.size
        if not same_size:
            size = (max(ia.width, ib.width), max(ia.height, ib.height))
            padded = []
            for image in (ia, ib):
                canvas = Image.new('RGBA', size, (0, 0, 0, 0)); canvas.paste(image, (0, 0)); padded.append(canvas)
            ia, ib = padded
        diff = ImageChops.difference(ia, ib)
        changed = sum(1 for pixel in zip(*[band.tobytes() for band in diff.split()]) if any(pixel))
        if difference_output: diff.convert('RGB').save(difference_output)
        return {'same_size': same_size, 'before_size': sizes[0], 'after_size': sizes[1],
                'comparison': 'top_left_transparent_padding_no_rescale', 'equal': same_size and changed == 0,
                'changed_pixels': changed, 'total_pixels': ia.width * ia.height}


def pdf_difference(a, b):
    raw_a, raw_b = a.read_bytes(), b.read_bytes()
    dates = lambda raw: [x.decode('ascii', errors='replace') for x in re.findall(rb'/CreationDate\s*\([^)]*\)|/ModDate\s*\([^)]*\)', raw)]
    ranges = []
    if len(raw_a) == len(raw_b):
        for i, (x, y) in enumerate(zip(raw_a, raw_b)):
            if x != y:
                if ranges and ranges[-1][1] == i: ranges[-1][1] = i + 1
                else: ranges.append([i, i + 1])
    def streams(raw):
        result = []
        for match in re.finditer(rb'(?<!end)stream\r?\n(.*?)\r?\nendstream', raw, re.S):
            try: result.append(zlib.decompress(match.group(1)))
            except zlib.error: result.append(match.group(1))
        return result
    sa, sb = streams(raw_a), streams(raw_b)
    date_pattern = rb'/CreationDate\s*\([^)]*\)|/ModDate\s*\([^)]*\)'
    changed_pairs = [(x, y) for x, y in zip(sa, sb) if x != y]
    decoded_date_only = bool(changed_pairs) and len(sa) == len(sb) and all(
        re.sub(date_pattern, b'DATE_DIAGNOSTIC_ONLY', x) == re.sub(date_pattern, b'DATE_DIAGNOSTIC_ONLY', y)
        for x, y in changed_pairs)
    date_spans = [m.span() for m in re.finditer(rb'/CreationDate\s*\([^)]*\)|/ModDate\s*\([^)]*\)', raw_a)]
    only_date_bytes = bool(ranges) and all(any(lo <= start and end <= hi for lo, hi in date_spans) for start, end in ranges)
    changed = [{'stream_index': i, 'before_sha256': hashlib.sha256(x).hexdigest(), 'after_sha256': hashlib.sha256(y).hexdigest(),
                'before_decoded': x.decode('utf-8', errors='replace') if len(x) < 4096 else None,
                'after_decoded': y.decode('utf-8', errors='replace') if len(y) < 4096 else None}
               for i, (x, y) in enumerate(zip(sa, sb)) if x != y]
    return {'cause': 'raw_identical' if raw_a == raw_b else ('only_literal_creation_modification_date_bytes' if only_date_bytes else ('decoded_stream_changes_only_creation_modification_dates_compressed_bytes_differ' if decoded_date_only else 'see_raw_ranges_and_decoded_streams_not_assumed_metadata')),
            'decoded_changed_streams_only_date_values': decoded_date_only,
            'diagnostic_date_substitution_not_original_pdf_equality': True,
            'before_bytes': len(raw_a), 'after_bytes': len(raw_b), 'before_dates': dates(raw_a), 'after_dates': dates(raw_b),
            'differing_byte_ranges': ranges, 'decoded_stream_count': [len(sa), len(sb)], 'changed_decoded_streams': changed,
            'metadata_not_stripped': True, 'raw_equal': raw_a == raw_b}


def run(repo, config_path, output, profile=None):
    repo, out, profile, source, records, before = preflight(repo, config_path, output, profile)
    # Check all real conversion and independent raster dependencies before publishing.
    import cairosvg
    import PIL
    subprocess.run(['pdftoppm', '-v'], check=True, capture_output=True)
    out.mkdir(parents=True, exist_ok=False)
    gdv.write_json(out / 'preflight.json', {'input_sha256': before, 'loci': [r[0] for r in records], 'status': 'passed'})
    gdv.write_json(out / 'render_profile.json', profile)
    for run_id in ('run-01', 'run-02'):
        for locus, spec, old, s, old_spec, control_svg in records:
            gdv.render(spec, out / run_id / locus, profile, input_root=repo)
        if run_id == 'run-01': time.sleep(1.1)  # Expose Cairo's real time-dependent PDF metadata.
    items = []
    for locus, spec, old, s, old_spec, control_svg in records:
        a, b = out / 'run-01' / locus, out / 'run-02' / locus
        hashes, historical = {}, {}
        for ext in ('svg', 'png', 'pdf'):
            name = f'{locus}_enhanced.{ext}'
            hashes[ext] = {'run_01': gdv.sha(a / name), 'run_02': gdv.sha(b / name), 'equal': gdv.sha(a / name) == gdv.sha(b / name)}
            historical[ext] = {'old_sha256': gdv.sha(old.parent / name), 'new_sha256': gdv.sha(a / name), 'equal': gdv.sha(old.parent / name) == gdv.sha(a / name)}
        pdf_checks = []
        for folder in (a, b):
            prefix = folder / f'{locus}_pdftoppm'
            subprocess.run(['pdftoppm', '-scale-to', '1700', '-png', '-singlefile', str(folder / f'{locus}_enhanced.pdf'), str(prefix)], check=True, capture_output=True)
            pdf_checks.append(pixels(prefix.with_suffix('.png')))
        science = {key: {'before': old_spec.get(key), 'after': s.get(key)} for key in ('source_url', 'coordinate_note', 'tracks', 'exons', 'notes', 'boundary_review') if old_spec.get(key) != s.get(key)}
        (a / 'historical_track_declarations_same_environment.svg').write_bytes(control_svg)
        control_png = a / 'historical_track_declarations_same_environment.png'
        control_png.write_bytes(gdv.convert_svg(control_svg, 'png'))
        checks = gdv.read_json(a / 'checks.json')
        pixel_diff(old.parent / f'{locus}_enhanced.png', a / f'{locus}_enhanced.png', a / 'historical_png_difference.png')
        final = gdv.read_json(a / 'spec.json')
        gdv.require(all(final.get(k) == s.get(k) for k in ('source_url', 'exons', 'tracks', 'boundary_review', 'marker_display', 'notes')), '科学字段归档不一致')
        environments = [gdv.read_json(folder / 'environment.json') for folder in (a, b)]
        gdv.require(environments[0] == environments[1], '两次实际环境不一致')
        items.append({'locus': locus, 'title': f'{s["display_name"]} · {locus}',
                      'relative_directory': str(a.relative_to(out)),
                      'relative_output': {ext: str((a / f'{locus}_enhanced.{ext}').relative_to(out)) for ext in ('svg', 'png', 'pdf')},
                      'relative_pdf_preview': str((a / f'{locus}_pdftoppm.png').relative_to(out)),
                      'source': str(spec.relative_to(repo)), 'source_status': 'historical_revised_input_not_new_export',
                      'raw_hashes': hashes, 'png_pixels': [pixels(a / f'{locus}_enhanced.png'), pixels(b / f'{locus}_enhanced.png')],
                      'png_pixel_diff': pixel_diff(a / f'{locus}_enhanced.png', b / f'{locus}_enhanced.png'),
                      'pdf_byte_difference': pdf_difference(a / f'{locus}_enhanced.pdf', b / f'{locus}_enhanced.pdf'),
                      'independent_pdf_pixels': pdf_checks, 'independent_pdf_pixels_equal': pdf_checks[0] == pdf_checks[1],
                      'historical_diff': historical, 'historical_png_pixel_diff': pixel_diff(old.parent / f'{locus}_enhanced.png', a / f'{locus}_enhanced.png'),
                      'scientific_spec_diff': science, 'marker_validation': 'pending', 'visual_review': 'pending_parent'})
        items[-1].update({
            'scientific_check': {'status': 'exact_evidence_contract_passed_not_binding_validation',
                                 'final_scientific_fields_equal_input': True,
                                 'transcript': s['_exons']['transcript'] if s['_exons'] else None,
                                 'exon_intervals': len(s['_exons']['intervals']) if s['_exons'] else 0,
                                 'product_report_sha256': checks.get('product_report_sha256'),
                                 'coordinate_observation': checks['coordinate_observation'], 'markers': s['_markers']},
            'difference_separation': {
                'scientific_track_correction_same_environment': pixel_diff(control_png, a / f'{locus}_enhanced.png'),
                'historical_vs_current_renderer_environment_with_old_track_declarations': pixel_diff(old.parent / f'{locus}_enhanced.png', control_png),
                'boundary': 'Only old track declarations restored; remaining history difference aggregates style/environment, not isolated font attribution. Coordinate audit corrections do not shift geometry.'},
            'run_artifacts_sha256': {folder.parent.name: {p.name: gdv.sha(p) for p in sorted(folder.iterdir()) if p.is_file() and p.name != 'execution.json'} for folder in (a, b)},
            'environment_sha256': gdv.sha(a / 'environment.json'),
            'finalspec_sha256': checks['finalspec_sha256'], 'profile_sha256': checks['profile_sha256']})
    after = {p: gdv.sha(repo / p) for p in before}
    gdv.require(before == after, '源文件回放前后 hash 改变')
    actual = {'schema_version': 1, 'path_base': 'relative outputs to this manifest directory; source to repo root',
              'loci': items, 'original_inputs_unchanged': True, 'input_sha256': after,
              'replay_engine_sha256': gdv.sha(__file__),
              'endpoint_discrepancies': source.get('endpoint_discrepancies'),
              'public_RNA_compatibility': source.get('cross_assembly_public_RNA_compatibility'),
              'visual_review': 'pending_parent_independent_review', 'track_content_review': 'pending',
              'pdftoppm': {'version': subprocess.run(['pdftoppm', '-v'], capture_output=True, text=True).stderr.strip(), 'binary_sha256': gdv.sha('/usr/bin/pdftoppm')},
              'counts': {'loci': len(items), 'real_conversions': 2 * len(items),
                         'svg_raw_equal': sum(x['raw_hashes']['svg']['equal'] for x in items),
                         'png_raw_equal': sum(x['raw_hashes']['png']['equal'] for x in items),
                         'pdf_raw_equal': sum(x['raw_hashes']['pdf']['equal'] for x in items),
                         'png_pixels_equal': sum(x['png_pixel_diff']['equal'] for x in items),
                         'pdftoppm_pixels_equal': sum(x['independent_pdf_pixels_equal'] for x in items)}}
    actual.update({'renderer_sha256': gdv.sha(gdv.__file__), 'profile_sha256': gdv.sha(out / 'render_profile.json'),
                   'input_policy': {'root_base': 'repository_root_explicit_--repo', 'parent_references': 'lexical_symlink_checks_then_root_containment', 'output_in_any_source_directory': 'forbidden'},
                   'endpoint_discrepancy_path_base': 'repository_root',
                   'scientific_review': 'unresolved_requires_actual_evidence_and_user_scientific_review',
                   'technical_component_review': 'does_not_approve_marker_binding',
                   'authenticity': 'real_archived_GDV_evidence_revised_spec_local_CairoSVG_not_new_experiment',
                   'scientific_checks': {'loci': len(items), 'exon_intervals': sum(x['scientific_check']['exon_intervals'] for x in items), 'marker_binding': 'pending', 'synthetic_experiments': 0}})
    gdv.write_json(out / 'actualmanifest.json', actual)
    return out / 'actualmanifest.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    try:
        if args.validate_only:
            result = preflight(args.repo, args.manifest, args.output, args.profile)
            print(f'preflight passed: {len(result[4])} loci')
        else:
            print(run(args.repo, args.manifest, args.output, args.profile))
    except (ValueError, KeyError, TypeError, OSError, ImportError, subprocess.CalledProcessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
