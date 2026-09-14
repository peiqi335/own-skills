#!/usr/bin/env python3
"""Export a Sequence Viewer SVG from a GDV spec plus a saved disptracks catalog."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fetch_ncbi import fetch
from render_gdv import PROTECTED, parse_url, require, safe_svg


def attr_map(track):
    out = {}
    for item in track.get('attrs', []):
        key, value = item.get('key'), item.get('value')
        if key in out and key == 'id_map':
            continue
        out[key] = value
    return out


def escape_track(value):
    text = str(value)
    return ''.join(('\\' + (format(ord(ch), 'x') if ch in '=&\\;"#%+' else ch))
                   if ch in '][\\|,:=&;"#%+' else ch for ch in text)


def annots(track, attrs):
    if attrs.get('annot_name'):
        return attrs['annot_name']
    parts = []
    for item in track.get('items') or []:
        name = attr_map(item).get('annot_name')
        if name:
            parts.append(name)
    return '|'.join(parts)


def track_role_rank(track):
    attrs = attr_map(track)
    name = track.get('name', '')
    ttype = attrs.get('track_type', '')
    if ttype == 'sequence_track':
        return 99
    if ttype == 'gene_model_track' and ('NCBI' in name or 'RefSeq' in name) and 'Ensembl' not in name:
        return 1
    if ttype == 'gene_model_track' and 'Ensembl' in name:
        return 2
    if 'coverage' in name:
        return 3
    if 'spanning' in name:
        return 4
    if 'features' in name:
        return 5
    if ttype == 'SNP_track' or any(k in name for k in ['EVA', 'dbSNP', 'RefSNP', 'Variations']):
        return 6
    return 10


def selected(track, attrs, want_variants):
    ttype = attrs.get('track_type', '')
    if ttype == 'sequence_track':
        return False
    name = track.get('name', '')
    if ttype == 'SNP_track':
        if not want_variants:
            return False
        if 'dbSNP' in name:
            return 'Cited Variations' in name or 'Live RefSNPs' in name
        return 'EVA' in name
    return attrs.get('show') == 'true'


def track_token(track, order):
    attrs = attr_map(track)
    parts = {
        'key': attrs.get('track_type'),
        'id': track['dtrack_id']['tag']['str'],
        'annots': annots(track, attrs),
        'display_name': track['name'],
        'shown': 'true',
        'order': str(order),
    }
    if attrs.get('track_type') == 'SNP_track' and attrs.get('dbname') == 'EVA':
        parts.update({'rmt_mapped_id': 'X', 'dbname': 'vcfTabix', 'subkey': 'dbSNP'})
    return '[' + ','.join(f'{k}:{escape_track(v)}' for k, v in parts.items() if v) + ']'


def find_track_for_spec(catalog, title, role):
    for t in catalog['tracks']['display_tracks']:
        if t.get('name') == title:
            return t
    for t in catalog['tracks']['display_tracks']:
        name = t.get('name', '')
        attrs = attr_map(t)
        ttype = attrs.get('track_type', '')
        if role == 'refseq' and ttype != 'gene_model_track':
            continue
        if role == 'ensembl' and (ttype != 'gene_model_track' or 'Ensembl' not in name):
            continue
        if title in name or name in title:
            return t
    return None


def build_tracks(catalog, want_variants, spec=None):
    tokens = ['[key:ruler]']
    chosen = []
    spec_tracks = spec.get('tracks') if spec else None
    if spec_tracks:
        for st in spec_tracks:
            status = st.get('status')
            title = st.get('title')
            role = st.get('role')
            if role == 'variants' and not want_variants and status != 'loaded':
                continue
            if status in {'loaded', 'available_empty'} and title:
                t = find_track_for_spec(catalog, title, role)
                if t and t not in chosen:
                    chosen.append(t)
    else:
        for track in catalog['tracks']['display_tracks']:
            attrs = attr_map(track)
            if selected(track, attrs, want_variants):
                chosen.append(track)
    chosen.sort(key=lambda t: (track_role_rank(t), t.get('name', '')))
    for i, track in enumerate(chosen):
        tokens.append(track_token(track, i + 1))
    return ''.join(tokens)


def post(url, data):
    body = urlencode(data).encode()
    with urlopen(Request(url, data=body, headers={'User-Agent': 'gdv-offline-evidence/1.0',
                                                  'Content-Type': 'application/x-www-form-urlencoded'}),
                 timeout=90) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('-o', '--output', type=Path, required=True)
    parser.add_argument('--include-variants', action='store_true')
    parser.add_argument('--width', type=int, default=1094, help='导出 Sequence Viewer 宽度（默认 1094，CAT_1 标准）')
    args = parser.parse_args()
    out = args.output.absolute()
    if out.exists() or out.is_symlink() or any(p.is_symlink() for p in out.parents):
        parser.error('输出已存在或路径含符号链接')
    if PROTECTED & set(out.resolve().parts):
        parser.error('不得写入原始资料、记录或 .git')
    spec = json.loads(args.spec.read_text(encoding='utf-8'))
    assembly, accession, start, end, markers = parse_url(spec['source_url'])
    catalog = json.loads(args.catalog.read_text(encoding='utf-8'))
    tracks = build_tracks(catalog, args.include_variants, spec=spec)
    require('SNP_track' in tracks or not args.include_variants, '目录中没有可导出的变异轨道')
    marker = ','.join(f'{m["start"]-1}:{m["end"]}|{m["label"]}|{m["color"].lstrip("#")}' for m in markers)
    payload = {
        'id': accession,
        'assm_context': assembly,
        'client': 'seqviewer',
        'width': str(args.width),
        'view_width': str(args.width),
        'from': str(start - 1),
        'len': str(end - start + 1),
        'target': 'svg',
        'print_title': 'true',
        'tracks': tracks,
        'markers': marker,
    }
    raw = post('https://www.ncbi.nlm.nih.gov/projects/sviewer/seqgraphic_rmt.cgi', payload)
    info = json.loads(raw)
    file_url = info.get('file_url')
    require(isinstance(file_url, str) and file_url.startswith('?'), 'seqgraphic 未返回 ncfetch 地址')
    svg = fetch('https://www.ncbi.nlm.nih.gov/projects/sviewer/ncfetch.cgi' + file_url)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + '.part')
    tmp.write_bytes(svg)
    try:
        root = safe_svg(tmp)
        texts = [''.join(n.itertext()) for n in root.iter() if n.tag.endswith('}text')]
        require(any(accession in t for t in texts), '导出 SVG 缺少序列号')
        for marker in markers:
            require(marker['label'] in texts, f'导出 SVG 缺少标记 {marker["label"]}')
        if args.include_variants:
            require(any('EVA' in t or 'dbSNP' in t or 'RefSNP' in t for t in texts),
                    '请求了变异轨道，但导出图中没有对应标题')
        tmp.replace(out)
    finally:
        if tmp.exists() and tmp != out:
            tmp.unlink()
    print(f'{out} ({out.stat().st_size} bytes)')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
