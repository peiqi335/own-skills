#!/usr/bin/env python3
"""Archive paired Primer-BLAST requests without converting failures into negatives."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import (ENDPOINT, classify, decorate, identity, live_urls, no_symlinks,
                      parameters, parse_products, safe_file, sha256, BindingConflict,
                      check_response_binding, same_result)

DEFAULT_SPECIES_PANEL = [dict(code=c, organism=o, cn=n) for c, o, n in [
    ('CAT', 'Felis catus', '猫'), ('CHK', 'Gallus gallus', '鸡'),
    ('COW', 'Bos taurus', '牛'), ('DOG', 'Canis lupus familiaris', '狗'),
    ('DUK', 'Anas platyrhynchos', '鸭'), ('GOO', 'Anser cygnoides', '鹅'),
    ('GUI', 'Cavia porcellus', '豚鼠'), ('HAM', 'Mesocricetus auratus', '仓鼠'),
    ('HOR', 'Equus caballus', '马'), ('HUM', 'Homo sapiens', '人'),
    ('MUS', 'Mus musculus', '小鼠'), ('PIG', 'Sus scrofa', '猪'),
    ('RAB', 'Oryctolagus cuniculus', '兔'), ('RAT', 'Rattus norvegicus', '大鼠'),
    ('SHE', 'Ovis aries', '羊')]]


def now():
    return datetime.now(timezone.utc).isoformat()


def build_live_urls(primer_f, primer_r, organism, db='refseq_representative_genomes',
                    min_bp=50, max_bp=2000, mismatch=3, mismatch_3end=2, mismatch_region=5):
    return live_urls(parameters(primer_f, primer_r, organism, db, min_bp, max_bp,
                                mismatch, mismatch_3end, mismatch_region))


def decorate_report_html(raw_html, live_url='', form_url='', is_rna=False):
    # Legacy URL interface: only complete, matching NCBI parameters are trusted.
    parsed = [urllib.parse.urlsplit(url) for url in (live_url, form_url)]
    params = [dict(urllib.parse.parse_qsl(url.query)) for url in parsed]
    valid = (all(url.scheme == 'https' and url.netloc == 'www.ncbi.nlm.nih.gov' and
                 url.path == '/tools/primer-blast/primertool.cgi' for url in parsed)
             and identity(params[0]) is not None and identity(params[0]) == identity(params[1]))
    return decorate(raw_html, params[0] if valid else {})


def parse_products_from_html(html):
    return parse_products(html)[0]


class RequestFailure(Exception):
    def __init__(self, message, raw):
        super().__init__(message)
        self.raw = raw


def request_bytes(request, request_timeout=30.0):
    try:
        with urllib.request.urlopen(request, timeout=request_timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        finally:
            exc.close()
        raise RequestFailure(str(exc), raw) from exc


def job_key(raw):
    html = raw.decode('utf-8', errors='replace')
    # Attribute order does not matter.
    for tag in re.findall(r'<input\b[^>]*>', html, re.I):
        if re.search(r'name=["\']job_key["\']', tag, re.I):
            match = re.search(r'value=["\']([^"\']+)', tag, re.I)
            if match:
                return match[1]
    match = re.search(r'job_key=([A-Za-z0-9_-]+)', html)
    return match[1] if match else None


def poll_job(key, timeout_sec=300, request_timeout=30, on_response=None):
    deadline = time.monotonic() + timeout_sec
    last = b''
    while time.monotonic() < deadline:
        request = urllib.request.Request(ENDPOINT + '?' + urllib.parse.urlencode({'job_key': key}),
                                         headers={'User-Agent': 'Mozilla/5.0'})
        try:
            last = request_bytes(request, min(request_timeout, max(0.001, deadline - time.monotonic())))
        except Exception as exc:
            if isinstance(exc, RequestFailure) and on_response:
                last = exc.raw
                on_response(last)
            return 'error', last, str(exc)
        if on_response:
            on_response(last)
        state = classify(last.decode('utf-8', errors='replace'))
        if state != 'waiting':
            return state, last, ''
        time.sleep(min(10, max(0, deadline - time.monotonic())))
    return 'timeout', last, '轮询期限已到；最后响应不代表终态'


def archive(root, relative, raw):
    dest = no_symlinks(root / relative)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open('xb') as stream:
        stream.write(raw)
    return {'path': relative, 'sha256': sha256(raw), 'received_utc': now()}


def verified_raw(root, record):
    if not isinstance(record, dict) or not all(isinstance(record.get(k), str) and record[k] for k in ('path', 'sha256', 'received_utc')):
        raise ValueError('原始响应 path/hash/time 记录不足')
    path = safe_file(root, record['path'])
    raw = path.read_bytes()
    if sha256(raw) != record['sha256']:
        raise ValueError('原始响应 hash 不符')
    return raw


def resume_query(root, old, params, schema_version: object = 2):
    """Never relabel old artifacts with the newly requested parameters."""
    result = dict(old)
    result['requested_parameters'] = params
    result['products'] = []
    result['parse_status'] = 'needs_review'
    result['source_verified'] = False
    result['evidence_status'] = 'pending'
    if identity(old.get('parameters')) is None:
        result.update(status='unknown', error='旧参数信息不足，需人工核查；新目录重跑')
        return result
    if identity(old['parameters']) != identity(params):
        result.update(status='error', error='needs rerun：旧归档参数与本次请求不符')
        return result
    if schema_version != 2:
        result.update(status='unknown', error='pending：legacy 归档不能自动升级为 v2 可信完成')
        return result
    try:
        raw = verified_raw(root, old['raw_response'])
        # A submission archive is required for trusted new-format resumes.
        submission = verified_raw(root, old['submission'])
        check_response_binding(submission.decode('utf-8', errors='replace'), params)
        binding = check_response_binding(raw.decode('utf-8', errors='replace'), params)
        result['response_binding'] = binding
        result['source_verified'] = binding['status'] == 'matched'
        state = classify(raw.decode('utf-8', errors='replace'))
        if state not in ('completed_results', 'completed_no_target_template'):
            result.update(status=state, error='非可复用终态；请在新目录重跑')
            return result
        if old.get('status') != state:
            raise ValueError('归档状态与原始终态不符')
        display = safe_file(root, old['result_page']).read_bytes()
        if sha256(display) != old.get('display_sha256'):
            raise ValueError('展示页 hash 缺失或不符')
        display_text = display.decode('utf-8', errors='replace')
        check_response_binding(display_text, params)
        same_result(raw.decode('utf-8', errors='replace'), display_text)
        if binding['status'] != 'matched':
            result.update(status='unknown', source_verified=False, error='pending：返回参数字段证据不足，不能安全复用')
            return result
        prods, parsed, note = parse_products(raw.decode('utf-8', errors='replace'))
        result.update(status=state, products=prods, parse_status=parsed, parse_error=note)
        result['evidence_status'] = 'content_matched'
    except BindingConflict as exc:
        result.update(status='error', source_verified=False, error=f'needs rerun：{exc}')
    except (KeyError, ValueError, OSError, TypeError) as exc:
        result['source_verified'] = False
        result.update(status='unknown', error=f'归档证据不足：{exc}')
    return result


def fetch_query(root, assay, sp, params, timeout_sec=300, request_timeout=30):
    qid = f'{assay}_on_{sp["code"]}'
    prefix = f'{assay}/{qid}'
    result: dict = dict(id=qid, assay=assay, species_code=sp['code'], organism=sp['organism'],
                  forward=params['PRIMER_LEFT_INPUT'], reverse=params['PRIMER_RIGHT_INPUT'],
                  parameters=params, requested_utc=now(), job_key=None, status='unknown',
                  products=[], parse_status='not_applicable', result_page=None)
    try:
        request = urllib.request.Request(ENDPOINT, data=urllib.parse.urlencode(params).encode(),
                                         headers={'User-Agent': 'Mozilla/5.0'})
        submission = request_bytes(request, request_timeout)
        result['submission'] = archive(root, prefix + '.submission.raw.html', submission)
        result['submission_page'] = result['submission']['path']
        result['raw_response'] = result['submission']
        check_response_binding(submission.decode('utf-8', errors='replace'), params)
        key = job_key(submission)
        result['job_key'] = key
        raw = submission
        state = classify(raw.decode('utf-8', errors='replace'))
        if key:
            # Persist every response before classification. No overwrite of an archive.
            counter = [0]
            def save_response(content):
                counter[0] += 1
                result['raw_response'] = archive(root, f'{prefix}.poll-{counter[0]}.raw.html', content)
            state, polled, error = poll_job(key, timeout_sec, request_timeout, save_response)
            if polled:
                raw = polled
            if error:
                result['error'] = error
        elif state not in ('completed_results', 'completed_no_target_template', 'error'):
            state = 'error'
            result['error'] = '提交未获得 job_key，不能确认完成'
        result['status'] = state
        if state in ('completed_results', 'completed_no_target_template'):
            text = raw.decode('utf-8', errors='replace')
            binding = check_response_binding(text, params)
            result.update(response_binding=binding, source_verified=binding['status'] == 'matched')
            prods, parsed, note = parse_products(text)
            if state == 'completed_results' and not prods:
                parsed = 'needs_review'
            if state == 'completed_no_target_template' and prods:
                parsed = 'needs_review'
            result.update(products=prods, parse_status=parsed, parse_error=note)
            display = decorate(text, params, require_binding=True).encode()
            rel = prefix + '.display.html'
            record = archive(root, rel, display)
            result.update(result_page=rel, display_sha256=record['sha256'], display_is_derived=True)
    except Exception as exc:
        if isinstance(exc, RequestFailure):
            record = archive(root, prefix + '.submission.raw.html', exc.raw)
            result.update(submission=record, submission_page=record['path'], raw_response=record)
        result.update(status='error', products=[], parse_status='not_applicable', source_verified=False, error=str(exc))
    result['finished_utc'] = now()
    return result


def run(assays_path, out_dir, db, timeout_sec=300, request_timeout=30):
    assays = json.loads(assays_path.read_text(encoding='utf-8'))
    if not isinstance(assays, dict) or not assays:
        raise ValueError('assays 必须是非空对象')
    for name, info in assays.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or not isinstance(info, dict):
            raise ValueError('无效 assay 名称或定义')
        p = parameters(info.get('forward', ''), info.get('reverse', ''), 'validation', db)
        if identity(p) is None or info.get('target_species', '') not in ['', *[s['code'] for s in DEFAULT_SPECIES_PANEL]]:
            raise ValueError(f'无效引物或物种：{name}')
    if timeout_sec <= 0 or request_timeout <= 0:
        raise ValueError('timeout 必须大于 0')
    root = no_symlinks(out_dir).resolve()
    old = {}
    previous_schema = None
    if root.exists():
        status = safe_file(root, 'status.json')
        previous = json.loads(status.read_text())
        previous_schema = previous.get('schema_version')
        for q in previous['queries']:
            if q['id'] in old:
                raise ValueError('旧状态 query id 重复')
            old[q['id']] = q
    else:
        root.mkdir(parents=True)
    # Existing batches are read-only. A resume assessment is a new unique status file.
    queries = []
    for assay, info in assays.items():
        for sp in DEFAULT_SPECIES_PANEL:
            params = parameters(info['forward'], info['reverse'], sp['organism'], db)
            qid = f'{assay}_on_{sp["code"]}'
            if root.joinpath('status.json').exists():
                prior = old.get(qid, dict(id=qid, assay=assay, species_code=sp['code'], organism=sp['organism']))
                query = resume_query(root, prior, params, schema_version=previous_schema)
            else:
                query = fetch_query(root, assay, sp, params, timeout_sec, request_timeout)
            query['is_target'] = sp['code'] == info.get('target_species')
            queries.append(query)
    data = dict(schema_version=2, created_utc=now(), database=db,
                species_panel=DEFAULT_SPECIES_PANEL, queries=queries)
    dest = root / ('status.resume-' + uuid.uuid4().hex + '.json' if old or (root / 'status.json').exists() else 'status.json')
    with dest.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    return dest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assays', type=Path, required=True)
    parser.add_argument('--db', choices=['refseq_representative_genomes', 'refseq_rna'], default='refseq_representative_genomes')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--request-timeout', type=float, default=30)
    parser.add_argument('--build-panel', action='store_true')
    parser.add_argument('--panel-output', type=Path)
    parser.add_argument('--title', default='成对 Primer-BLAST 离线成果')
    args = parser.parse_args()
    status = run(args.assays, args.output, args.db, args.timeout, args.request_timeout)
    print(status)
    if args.build_panel:
        import build_panel
        print(build_panel.build(status, args.panel_output or args.output.with_name(args.output.name + '_panel'), args.title))


if __name__ == '__main__':
    main()
