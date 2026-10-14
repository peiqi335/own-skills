"""Explicit historical request/echo disagreement; never overwrite the registration."""
import re
from evidence import response_binding, BindingConflict


def binding(text, params, allow_conflicts=False):
    original = response_binding(text, params)
    numeric = re.findall(r'<input\b(?=[^>]*\bname=["\']ORGANISM["\'])(?=[^>]*\bvalue=["\'](\d+)["\'])[^>]*>', text, re.I)
    normalized = re.sub(r'<input\b(?=[^>]*\bname=["\']ORGANISM["\'])(?=[^>]*\bvalue=["\']\d+["\'])[^>]*>', '', text, flags=re.I)
    normalized = normalized.replace(' (taxid filter)', '').replace('NCBI Transcript Reference Sequences', 'refseq_rna')
    result = response_binding(normalized, params)
    if result['conflicts'] and not allow_conflicts:
        raise BindingConflict('返回参数与登记冲突：' + ', '.join(result['conflicts']))
    result.update(original_returned_parameters=original['returned_parameters'],
                  display_aliases=['literal (taxid filter) suffix removed for comparison', 'NCBI Transcript Reference Sequences → refseq_rna'],
                  unresolved_numeric_organism_echoes=numeric)
    if numeric and not result['conflicts']:
        result['status'] = 'pending'
    return result


def selected_parameters(old):
    # Identity is supplied by the historical query fields, not the returned page.
    p = dict(old['parameters'])
    for key, field in [('PRIMER_LEFT_INPUT', 'forward'), ('PRIMER_RIGHT_INPUT', 'reverse'),
                       ('ORGANISM', 'organism'), ('PRIMER_SPECIFICITY_DATABASE', 'database')]:
        if key in p and p[key] != old[field]:
            raise ValueError('历史登记自身身份冲突：' + key)
        p[key] = old[field]
    return p


def declaration(old, text, registration):
    b = binding(text, selected_parameters(old), True)
    # No identity conflict is admissible under the historical display policy.
    if set(b['conflicts']) - {'PRIMER_PRODUCT_MIN', 'PRIMER_PRODUCT_MAX',
                              'TOTAL_PRIMER_SPECIFICITY_MISMATCH', 'PRIMER_3END_SPECIFICITY_MISMATCH', 'MISMATCH_REGION_LENGTH'}:
        raise BindingConflict('历史报告身份冲突，不能用参数展示政策豁免')
    return dict(mode='historical_conflict_pending' if b['conflicts'] else 'historical_pending',
                registered_parameters=dict(old['parameters']), returned_parameters=b['returned_parameters'],
                original_returned_parameters=b['original_returned_parameters'], conflicts=b['conflicts'],
                registration_input=dict(registration), registration_key=old['key'],
                display_parameter_source='historical_registered_request',
                live_parameter_source='historical_registered_request_new_query_only',
                status='pending', correction_basis=None)


def validate(q, text, registration_bytes):
    import json
    policy = q['parameter_policy']
    status = json.loads(registration_bytes)
    candidates = [old for old in status['queries'] if old['key'] == policy['registration_key']]
    if len(candidates) != 1:
        raise ValueError('登记 query 缺失或重复')
    old = candidates[0]
    if q['parameters'] != selected_parameters(old):
        raise ValueError('选用参数不是历史登记参数')
    expected = declaration(old, text, policy['registration_input'])
    if expected != policy:
        raise ValueError('显式参数冲突政策与原登记/报告不一致')
    return binding(text, q['parameters'], True)


def warning(q):
    p = q.get('parameter_policy', {})
    if not p.get('conflicts'):
        return ''
    return '参数冲突 pending；无纠正依据：' + '；'.join(
        k + ' 请求登记=' + str(p['registered_parameters'].get(k, '未登记')) +
        '，报告返回=' + '/'.join(p['returned_parameters'][k]) for k in p['conflicts']) + '；展示及新查询参数选自历史请求登记，不保证与归档结果一致'
