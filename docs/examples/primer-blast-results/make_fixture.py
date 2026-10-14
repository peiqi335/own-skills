"""Public synthetic test-state archive. No network and no real primer design."""
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'primer-blast-results/scripts'))
from evidence import parameters, classify, parse_products

STAMP = '2026-01-01T00:00:00Z'  # Fixed synthetic timestamp, not a request time.


def main():
    source = HERE / 'input'
    source.mkdir(exist_ok=True)
    species = [{'code': 'RAT', 'organism': 'Rattus norvegicus'},
               {'code': 'CAT', 'organism': 'Felis catus'},
               {'code': 'DOG', 'organism': 'Canis lupus familiaris'}]
    # Adapted only from PRODUCT / anomaly / ERROR in tests/test_build_panel.py.
    bodies = ['<div class="prPairDtl">&gt;<a>NC_086024.1</a> Synthetic template'
              '<pre>product length = 82</pre><pre>product length = 52</pre></div>',
              '<pre>product length = 99</pre>', 'Error: synthetic offline failure']
    queries = []
    for sp, body in zip(species, bodies):
        # Four-base test strings intentionally unsuitable as experimental primers.
        params = parameters('ACGT', 'TGCA', sp['organism'])
        raw = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
               '<title>合成测试夹具 · 非 NCBI 响应</title></head><body>'
               '<h1>合成测试夹具 · 非 NCBI 响应</h1>'
               '<p>未提交 NCBI；不代表检索结论。ACGT / TGCA 仅为测试字符串。</p>'
               + body + '</body></html>')
        name = sp['code']
        raw_path = f'{name}-raw.html'
        display_path = f'{name}-display.html'
        payload = raw.encode('utf-8')
        (source / raw_path).write_bytes(payload)
        (source / display_path).write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        products, parse_status, note = parse_products(raw)
        state = classify(raw)
        record = dict(path=raw_path, sha256=digest, received_utc=STAMP)
        queries.append(dict(id=f'DEMO_on_{name}', assay='DEMO_fixture', species_code=name,
                            organism=sp['organism'], is_target=name == 'RAT',
                            forward='ACGT', reverse='TGCA', parameters=params,
                            requested_utc=STAMP, finished_utc=STAMP, job_key=None,
                            status=state, products=products if state == 'completed_results' else [],
                            parse_status=parse_status if state.startswith('completed_') else 'not_applicable',
                            parse_error=note, error='Synthetic failure' if state == 'error' else None,
                            submission=record, raw_response=record, result_page=display_path,
                            display_sha256=digest, display_is_derived=True))
    data = dict(schema_version=2, created_utc=STAMP, database='refseq_representative_genomes',
                provenance='Synthetic public test fixture; NOT NCBI responses; no requests submitted',
                species_panel=species, queries=queries)
    (source / 'status.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
