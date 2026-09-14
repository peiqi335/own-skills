#!/usr/bin/env python3
"""Download a freshly observed NCBI export URL, sequence metadata, or transcript product report; no guessing export keys."""
import argparse
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from render_gdv import PROTECTED, safe_svg


def fetch(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'gdv-offline-evidence/1.0'}), timeout=45) as r:
                return r.read()
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
            if exc.headers.get('Retry-After'):
                from email.utils import parsedate_to_datetime
                import datetime
                hint = exc.headers['Retry-After']
                try:
                    delay = float(hint)
                except ValueError:
                    delay = (parsedate_to_datetime(hint) - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
                if delay > 60:
                    raise ValueError(f'服务器要求等待 {delay:.0f} 秒；停止本次自动重试，请按 Retry-After 稍后重试') from exc
                time.sleep(max(0, delay))
                continue
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep((2, 5)[attempt])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode', required=True)
    for mode, argument in [('metadata', 'accession'), ('export', 'url'), ('product_report', 'accession')]:
        child = sub.add_parser(mode)
        child.add_argument(argument)
        child.add_argument('-o', '--output', required=True, type=Path)
    a = p.parse_args()
    out = a.output.absolute()
    if out.exists() or out.is_symlink() or any(x.is_symlink() for x in out.parents):
        p.error('输出已存在或路径含符号链接；选择新的明确路径')
    if PROTECTED & set(out.resolve().parts):
        p.error('不得写入原始资料、记录或 .git')
    if a.mode == 'metadata':
        if not re.fullmatch(r'[A-Z]+_?\d+\.\d+', a.accession):
            p.error('需要带版本的序列 accession')
        url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?' + urlencode(
            {'db': 'nuccore', 'id': a.accession, 'retmode': 'json'})
    elif a.mode == 'product_report':
        if not re.fullmatch(r'(?:XM|NM)_\d+\.\d+', a.accession):
            p.error('需要带版本的 XM_/NM_ 转录本 accession')
        url = 'https://api.ncbi.nlm.nih.gov/datasets/v2/gene/accession/' + a.accession + '/product_report'
    else:
        u = urlparse(a.url)
        if u.scheme != 'https' or u.hostname != 'www.ncbi.nlm.nih.gov' or u.path != '/projects/sviewer/ncfetch.cgi':
            p.error('仅接受本次官方页面实际返回的 HTTPS ncfetch.cgi 导出链接')
        url = a.url
    data = fetch(url)
    if a.mode == 'metadata':
        d = json.loads(data)
        if not any(isinstance(v, dict) and v.get('accessionversion') == a.accession
                   for v in d.get('result', {}).values()):
            p.error('返回数据不含目标序列')
    elif a.mode == 'product_report':
        d = json.loads(data)
        blob = json.dumps(d, ensure_ascii=False)
        if a.accession not in blob:
            p.error('返回数据不含目标转录本')
    else:
        # Validate in a temporary directory, not at the requested final destination.
        import tempfile
        with tempfile.TemporaryDirectory(prefix='gdv-download-') as temp:
            test = Path(temp) / 'download.svg'
            test.write_bytes(data)
            safe_svg(test)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('xb') as stream:
        stream.write(data)
    print(f'{out} ({len(data)} bytes)')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
