#!/usr/bin/env python3
"""Preflight the entire batch without writes, then render into a NEW directory."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import stat

import annotate_gel as renderer
from review_gel import check_source, geometry_hash


def input_file(path):
    renderer.check_write_path(path)  # lexical ancestor link checks also apply to reads
    if '3.记录' in path.absolute().parts:
        raise SystemExit('personal records are prohibited')
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise SystemExit(f'missing/nonregular input: {path}')
    return path


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def preflight(batch_path, output, repo=None):
    batch_path, output = Path(batch_path).absolute(), Path(output).absolute()
    repo = Path(repo).absolute() if repo is not None else None
    input_file(batch_path)
    renderer.check_write_path(output)
    if output.exists():
        raise SystemExit('batch output directory must be new (not even an empty existing directory)')
    if any(part in ('1.原始资料', '3.记录') for part in output.absolute().parts):
        raise SystemExit('batch outputs must not be inside original/personal records')
    batch = json.loads(batch_path.read_text(encoding='utf-8'))
    items = batch.get('items')
    if batch.get('schema_version') != 1 or not isinstance(items, list) or not items:
        raise SystemExit('batch requires schema_version=1 and nonempty items')
    ids, jobs, protected, destinations = set(), [], [batch_path], [output / 'replay-manifest.json']
    directories = [output]
    for item in items:
        identity = item.get('id')
        if not isinstance(identity, str) or identity in ('', '.', '..') or '/' in identity or '\\' in identity or identity in ids:
            raise SystemExit('batch ids must be unique path-free names')
        ids.add(identity)
        spec_path = input_file(renderer.resolve(Path(item['spec']), batch_path.parent))
        if item.get('spec_sha256') and renderer.sha256(spec_path) != item['spec_sha256']:
            raise SystemExit('batch spec sha256 mismatch')
        spec = copy.deepcopy(renderer.load_spec(spec_path))
        base = repo if repo is not None else spec_path.parent
        if item.get('repo') is not None:
            base = renderer.resolve(Path(item['repo']), batch_path.parent)
        name = item.get('name', Path(spec['out']).name)
        if not isinstance(name, str) or name != Path(name).name or '/' in name or '\\' in name:
            raise SystemExit('batch output name must be path-free')
        if not name.endswith('.png') or '（标注）' not in name:
            raise SystemExit('batch output names require （标注） and .png')
        directory = output / identity
        directories.extend([directory, directory / 'review'])
        spec['out'] = str(directory / name)
        spec.pop('overwrite', None)  # no batch overwrite, even if the supplied spec requested it
        source = input_file(renderer.resolve(Path(spec['src']), base))
        check_source(spec, renderer.sha256(source), required=True)
        protected.extend([spec_path, source])
        for record in spec.get('source_annotations', []):
            protected.append(input_file(renderer.resolve(Path(record['path']), base)))
        if isinstance(spec.get('style_profile'), str):
            protected.append(input_file(renderer.resolve(Path(spec['style_profile']), base)))
        else:
            protected.append(input_file(renderer.PROFILE_PATH))
        _, _, fonts = renderer.resolve_style(spec, base)
        protected.extend(input_file(record['path']) for record in fonts.values())
        archive = directory / 'annotation-manifest.json'
        finalspec = directory / 'finalspec.json'
        destinations.extend([Path(spec['out']), archive, finalspec])
        jobs.append(dict(id=identity, spec=spec, repo=base, input_spec=spec_path,
                         archive=archive, finalspec=finalspec, review=directory / 'review'))
    renderer.destination_plan(destinations, directories, protected)
    for path in protected:
        if path.resolve().is_relative_to(output.resolve()):
            raise SystemExit('batch output directory contains a protected input')
    for index, destination in enumerate(destinations):
        renderer.check_write_path(destination)
        if any(renderer.same_path(destination, path) for path in protected + destinations[:index]):
            raise SystemExit('batch output/input alias or duplicate destination')
    before = {path: renderer.sha256(path) for path in protected}
    for job in jobs:
        renderer.annotate(job['spec'], job['repo'], None, job['review'], job['archive'], protected,
                          preflight_only=True)  # actual fonts, validation and in-memory drawing
    if any(renderer.sha256(path) != value for path, value in before.items()):
        raise SystemExit('protected input changed during whole-batch preflight')
    return jobs, before


def replay(batch_path, output, repo=None):
    batch_path, output = Path(batch_path).absolute(), Path(output).absolute()
    repo = Path(repo).absolute() if repo is not None else None
    jobs, before = preflight(batch_path, output, repo)
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for job in jobs:
        if any(renderer.sha256(path) != value for path, value in before.items()):
            raise SystemExit('protected input changed; partial batch retained, no rollback/deletion')
        out = renderer.annotate(job['spec'], job['repo'], None, job['review'], job['archive'], list(before))
        archive = json.loads(job['archive'].read_text(encoding='utf-8'))
        write_json(job['finalspec'], archive['finalspec'])
        records.append(dict(id=job['id'], input_spec_sha256=renderer.sha256(job['input_spec']),
                            output=dict(path=os.path.relpath(out, output), sha256=renderer.sha256(out)),
                            finalspec=dict(path=os.path.relpath(job['finalspec'], output), sha256=renderer.sha256(job['finalspec'])),
                            annotation_manifest=os.path.relpath(job['archive'], output),
                            review=os.path.relpath(job['review'] / 'review.json', output),
                            geometry_sha256=geometry_hash(archive['spec']['rows']),
                            render_environment=archive['render_environment']))
    if any(renderer.sha256(path) != value for path, value in before.items()):
        raise SystemExit('protected input changed during replay')
    payload = dict(schema_version=1, path_base='manifest_directory', batch_sha256=renderer.sha256(batch_path),
                   renderer_sha256=renderer.sha256(Path(renderer.__file__)),
                   executor_sha256=renderer.sha256(Path(__file__)),
                   preflight='all_items_passed_before_any_output_write', protected_inputs_unchanged=True,
                   visual_status='not_reviewed', items=records)
    write_json(output / 'replay-manifest.json', payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repo', type=Path)
    args = parser.parse_args()
    result = replay(args.batch.absolute(), args.output.absolute(), args.repo)
    print(json.dumps({'items': len(result['items']), 'output': str(args.output), 'visual_status': 'not_reviewed'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
