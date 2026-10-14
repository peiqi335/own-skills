"""Shared conservative evidence, parameter and presentation helpers (stdlib only)."""
import hashlib
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
import urllib.parse

ENDPOINT = 'https://www.ncbi.nlm.nih.gov/tools/primer-blast/primertool.cgi'
STATES = {'completed_results', 'completed_no_target_template', 'timeout', 'error', 'waiting', 'unknown'}
IDENTITY_KEYS = ('PRIMER_LEFT_INPUT', 'PRIMER_RIGHT_INPUT', 'ORGANISM',
                 'PRIMER_SPECIFICITY_DATABASE', 'TOTAL_PRIMER_SPECIFICITY_MISMATCH',
                 'PRIMER_3END_SPECIFICITY_MISMATCH', 'MISMATCH_REGION_LENGTH',
                 'PRIMER_PRODUCT_MIN', 'PRIMER_PRODUCT_MAX')


def parameters(forward, reverse, organism, db='refseq_representative_genomes',
               min_bp=50, max_bp=2000, mismatch=3, mismatch_3end=2, mismatch_region=5):
    return dict(zip(IDENTITY_KEYS, map(str, (forward, reverse, organism, db, mismatch,
                                           mismatch_3end, mismatch_region, min_bp, max_bp))),
                CMD='Put', PAGE_TYPE='Search', USER_TYPE='2', SEARCH_SPECIFIC_PRIMER='on')


def trusted_parameters(p):
    """Compatibility name: format-valid request parameters, NOT response binding."""
    if not isinstance(p, dict) or any(k not in p or not str(p[k]).strip() for k in IDENTITY_KEYS):
        return False
    try:
        return (all(re.fullmatch('[ACGTNacgtn]+', str(p[k])) for k in IDENTITY_KEYS[:2])
                and all(re.fullmatch(r'\d+', str(p[k])) for k in IDENTITY_KEYS[4:])
                and 0 < int(p['PRIMER_PRODUCT_MIN']) <= int(p['PRIMER_PRODUCT_MAX'])
                and p['PRIMER_SPECIFICITY_DATABASE'] in ('refseq_rna', 'refseq_representative_genomes'))
    except (ValueError, TypeError):
        return False


def identity(p):
    return tuple(str(p[k]) for k in IDENTITY_KEYS) if trusted_parameters(p) else None


def live_urls(p):
    if not trusted_parameters(p):
        return '', ''
    p = {k: str(p[k]) for k in IDENTITY_KEYS}
    p.update(CMD='Put', PAGE_TYPE='Search', USER_TYPE='2', SEARCH_SPECIFIC_PRIMER='on')
    live = ENDPOINT + '?' + urllib.parse.urlencode(p)
    p.pop('CMD')
    return live, ENDPOINT + '?' + urllib.parse.urlencode(p)


class BindingConflict(ValueError):
    pass


class ReturnedParameters(HTMLParser):
    """Explicit echoed inputs and unambiguous summary labels, never navigation URLs."""
    LABELS = {
        'forward primer': 'PRIMER_LEFT_INPUT', 'primer left (forward)': 'PRIMER_LEFT_INPUT',
        'reverse primer': 'PRIMER_RIGHT_INPUT', 'primer right (reverse)': 'PRIMER_RIGHT_INPUT',
        'organism': 'ORGANISM', 'database': 'PRIMER_SPECIFICITY_DATABASE',
        'product min': 'PRIMER_PRODUCT_MIN', 'product max': 'PRIMER_PRODUCT_MAX',
        'total primer specificity mismatch': 'TOTAL_PRIMER_SPECIFICITY_MISMATCH',
        "primer 3end specificity mismatch": 'PRIMER_3END_SPECIFICITY_MISMATCH',
        'mismatch region length': 'MISMATCH_REGION_LENGTH',
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = {}
        self.row = None
        self.cell = None
        self.text = []

    def add(self, key, value):
        value = ' '.join(str(value).split())
        if not value:
            return
        if key in IDENTITY_KEYS[:2]:
            match = re.match(r'^([ACGTNacgtn]+)(?:\s|$)', value)
            value = match[1].upper() if match else value
        elif key == 'PRIMER_SPECIFICITY_DATABASE':
            aliases = {'refseq representative genomes': 'refseq_representative_genomes',
                       'refseq reference genome database': 'refseq_representative_genomes',
                       'refseq representative rna (refseq_rna)': 'refseq_rna',
                       'refseq rna database': 'refseq_rna'}
            value = aliases.get(value.lower(), value)
        self.values.setdefault(key, set()).add(value)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        name = attrs.get('name') or ''
        if tag == 'input' and name.upper() in IDENTITY_KEYS:
            self.add(name.upper(), attrs.get('value') or '')
        if tag == 'input' and attrs.get('name') in ('FW_PRIMER_SEQ_0', 'RV_PRIMER_SEQ_0'):
            self.add('PRIMER_LEFT_INPUT' if name.startswith('FW') else 'PRIMER_RIGHT_INPUT', attrs.get('value') or '')
        if tag == 'meta' and attrs.get('name') == 'ncbi_db':
            self.add('PRIMER_SPECIFICITY_DATABASE', attrs.get('content') or '')
        if tag == 'tr':
            self.row = []
        if tag in ('td', 'th') and self.row is not None:
            self.cell = ''

    def handle_data(self, data):
        self.text.append(data)
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None and self.row is not None:
            self.row.append(' '.join(self.cell.split()))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            if len(self.row) >= 2:
                label, value = self.row[:2]
                key = self.LABELS.get(label.lower()) or (label if label in IDENTITY_KEYS else None)
                if key:
                    self.add(key, value)
                if label.lower() == 'product size range':
                    match = re.fullmatch(r'(\d+)\s*[-–]\s*(\d+)\s*bp', value, re.I)
                    if match:
                        self.add('PRIMER_PRODUCT_MIN', match[1])
                        self.add('PRIMER_PRODUCT_MAX', match[2])
                if label.lower() == 'max mismatches':
                    total = re.search(r'Total:\s*(\d+)\s*nt', value, re.I)
                    end = re.search(r"3['’]\s*end\s*\((\d+)\s*nt\)\s*:\s*(?:≤|<=)?\s*(\d+)\s*nt", value, re.I)
                    if total:
                        self.add('TOTAL_PRIMER_SPECIFICITY_MISMATCH', total[1])
                    if end:
                        self.add('MISMATCH_REGION_LENGTH', end[1])
                        self.add('PRIMER_3END_SPECIFICITY_MISMATCH', end[2])
            self.row = None


def response_binding(html, params):
    """Content consistency only: cannot authenticate NCBI origin or execution."""
    parser = ReturnedParameters()
    parser.feed(html)
    text = ' '.join(parser.text)
    for organism in re.findall(r'Organism limited to\s+([^()]+)\)', text, re.I):
        parser.add('ORGANISM', organism)
    for database in re.findall(r'selected database:\s*([^()]+)\s*\(Organism limited to', text, re.I):
        parser.add('PRIMER_SPECIFICITY_DATABASE', database)
    valid = trusted_parameters(params)
    conflicts = []
    for key, values in parser.values.items():
        supplied = isinstance(params, dict) and key in params
        expected = str(params[key]).upper() if supplied and key in IDENTITY_KEYS[:2] else str(params[key]) if supplied else None
        if len(values) > 1 or (expected is not None and values != {expected}):
            conflicts.append(key)
    missing = [key for key in IDENTITY_KEYS if key not in parser.values]
    return dict(status='conflict' if conflicts else 'matched' if valid and not missing else 'pending',
                returned_parameters={key: sorted(values) for key, values in parser.values.items()},
                missing_fields=missing, conflicts=conflicts)


def check_response_binding(html, params):
    result = response_binding(html, params)
    if result['status'] == 'conflict':
        raise BindingConflict('返回参数与请求或页面内字段冲突：' + ', '.join(result['conflicts']))
    return result


def same_result(raw, display):
    """Compare the facts, not merely the independent file hashes."""
    if classify(raw) != classify(display) or parse_products(raw)[:2] != parse_products(display)[:2]:
        raise ValueError('raw/display 终态或产物冲突')


def safe_job_url(url):
    if not isinstance(url, str) or any(ord(c) < 32 for c in url):
        return ''
    try:
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        keys = query.get('job_key', [])
        if (parsed.scheme != 'https' or parsed.netloc not in ('www.ncbi.nlm.nih.gov', 'ncbi.nlm.nih.gov')
                or parsed.path != '/tools/primer-blast/primertool.cgi' or parsed.fragment
                or len(keys) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]+', keys[0])
                or any(v.lower() == 'put' for v in query.get('CMD', []))
                or any(key in query for key in IDENTITY_KEYS)):
            return ''
        return ENDPOINT + '?' + urllib.parse.urlencode({'job_key': keys[0]})
    except ValueError:
        return ''


class ProductParser(HTMLParser):
    """Only template headers and pre blocks inside prPairDtl are evidence."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.block = None
        self.accession = None
        self.heading = False
        self.pre = None
        self.products = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div':
            self.depth += 1
            if 'prPairDtl' in (attrs.get('class') or '').split():
                self.block = self.depth
                self.accession = None
                self.heading = False
        if self.block is not None and tag == 'pre':
            self.pre = ''

    def handle_endtag(self, tag):
        if tag == 'pre' and self.pre is not None:
            lengths = re.findall(r'product length\s*=\s*(\d+)', self.pre, re.I)
            for length in lengths:
                if not self.accession or int(length) <= 0:
                    self.errors.append('产物缺少可信模板 accession 或长度')
                else:
                    self.products.append({'template_accession': self.accession, 'length_bp': int(length)})
            self.pre = None
        if tag == 'div':
            if self.block == self.depth:
                self.block = None
                self.accession = None
            self.depth -= 1

    def handle_data(self, data):
        if self.block is None:
            return
        if self.pre is not None:
            self.pre += data
            return
        if data.strip().startswith('>'):
            self.heading = True
            self.accession = None
        if self.heading:
            match = re.match(r'\s*>?\s*([A-Z]{1,6}_?\d+(?:\.\d+)?)(?:\s|$)', data)
            if match:
                self.accession = match.group(1)
                self.heading = False


def parse_products(html):
    parser = ProductParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        parser.errors.append(str(exc))
    expected = len(re.findall(r'product length\s*=\s*\d+', re.sub(r'<(?:script|nav)\b[^>]*>[\s\S]*?</(?:script|nav)>', '', html, flags=re.I), re.I))
    if expected != len(parser.products) or parser.pre is not None or parser.block is not None:
        parser.errors.append('产物数或模板块结构待核')
    return parser.products, ('needs_review' if parser.errors else 'ok'), '; '.join(parser.errors)


def classify(html):
    # Waiting/error always take precedence over stale result fragments.
    text = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', html, flags=re.I)
    text = re.sub('<[^>]+>', ' ', text)
    if re.search(r'job (?:has )?expired|invalid job|job not found|\berror\b|service unavailable|request failed', text, re.I):
        return 'error'
    if re.search(r'still running|status:\s*WAITING|please wait|refreshed automatically|queued', text, re.I):
        return 'waiting'
    if re.search(r'No target templates were found|No primers were found|There are no targets', text, re.I):
        return 'completed_no_target_template'
    if re.search(r'product length\s*=\s*\d+', text, re.I):
        return 'completed_results'
    return 'unknown'


def no_symlinks(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError(f'拒绝符号链接路径：{path}')
    return path


def safe_file(root, name):
    if not isinstance(name, str) or not name or ':' in name or '\\' in name or Path(name).is_absolute() or '..' in Path(name).parts or str(Path(name)) != name or any(ord(c) < 32 for c in name):
        raise ValueError(f'无效归档相对路径：{name}')
    root = no_symlinks(root).resolve()
    path = no_symlinks(root / name)
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError(f'归档不存在或越界：{name}')
    return path


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def decorate(html, params=None, require_binding=False):
    binding = check_response_binding(html, params)
    # Marked injection is replaceable; also remove the previous tool's exact bar.
    html = re.sub(r'<!-- pbr-navigation -->[\s\S]*?<!-- /pbr-navigation -->\s*', '', html)
    html = re.sub(r'<div class="ncbi-live-bar">[\s\S]*?</div>\s*</div>\s*', '', html)
    html = re.sub(r'<link\b[^>]*href=["\'][^"\']*(?:report|ncbi_style|results|nwds)\.css["\'][^>]*>\s*', '', html, flags=re.I)
    css = '<link rel="stylesheet" type="text/css" href="../assets/report.css" />'
    if not re.search('</head>', html, re.I):
        raise ValueError('报告缺少 HTML head；不能安全生成展示页')
    html = re.sub('</head>', css + '\n</head>', html, count=1, flags=re.I)
    live_url, form_url = live_urls(params)
    if require_binding and binding['status'] != 'matched':
        live_url, form_url = '', ''
    is_rna = params.get('PRIMER_SPECIFICITY_DATABASE') == 'refseq_rna' if isinstance(params, dict) and trusted_parameters(params) else False
    mode = '转录组 mRNA 模式' if is_rna else '预设计引物模式'
    if live_url and form_url:
        qualification = '仅按归档请求参数；不证明来源或传输真实性' if binding['status'] == 'matched' else 'pending：仅按归档请求参数，返回字段证据不足'
        content = (f'<strong>按归档参数重新检索（{mode}；{qualification}；不保证复现旧结果）</strong> '
                   f'<a href="{escape(live_url, quote=True)}" target="_blank" rel="noopener noreferrer">按归档参数重新检索</a> '
                   f'<a href="{escape(form_url, quote=True)}" target="_blank" rel="noopener noreferrer">打开参数表单（可修改）</a>')
    else:
        content = '<strong>pending：归档参数不完整或未核验，未生成检索链接</strong>'
    bar = ('<!-- pbr-navigation --><div class="ncbi-live-bar"><div>' + content +
           '</div><div><a href="../index.html">← 返回检索矩阵</a> · 展示派生页，非原始响应</div></div><!-- /pbr-navigation -->')
    if not re.search(r'<body\b', html, re.I):
        raise ValueError('报告缺少 HTML body')
    return re.sub(r'(<body\b[^>]*>)\s*', lambda m: m[1] + '\n' + bar + '\n', html, count=1, flags=re.I)
