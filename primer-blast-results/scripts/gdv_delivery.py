"""Read sibling lane delivery metadata and static resources; no coordinate parser."""
import json
import base64
import binascii
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from evidence import safe_file, no_symlinks, sha256


def unique_ids(items, key='id'):
    values = [x[key] for x in items]
    if len(values) != len(set(values)):
        raise ValueError('GDV duplicate IDs：' + repr(values))


def static_svg(raw):
    # Restricted UTF-8 static input, not a general SVG/CSS sanitizer. ET drops
    # processing instructions, so reject them before constructing the tree.
    text = raw.decode('utf-8-sig')
    without_declaration = re.sub(r'^<\?xml\s[^?]*\?>', '', text, count=1)
    if '<?' in without_declaration:
        raise ValueError('GDV SVG 不接收 processing instruction')
    if re.search(rb'<!DOCTYPE|<!ENTITY', raw, re.I):
        raise ValueError('GDV SVG 不接收 DTD/entity')

    def css_resources(value):
        # Attribute values have already had XML entities decoded by ET.
        # Check every attribute, including unknown presentation attributes.
        if '\\' in value or re.search(r'@import', value, re.I):
            raise ValueError('GDV SVG 不接收转义/外部 CSS 资源')
        for match in re.finditer(r'url\s*\(', value, re.I):
            tail = value[match.end():]
            local = re.match(r'\s*(?:#[^\s\"\'()]+|\"#[^\s\"()]+\"|\'#[^\s\'()]+\')\s*\)', tail)
            if local is None:
                raise ValueError('GDV SVG 包含隐式资源')

    def local_reference(value, tag):
        if re.fullmatch(r'#[^\s\"\'()]+', value):
            return True
        # Only raster image data, never nested SVG/HTML or remote resources.
        match = re.fullmatch(r'data:image/(png|jpeg);base64,([A-Za-z0-9+/=]+)', value)
        if tag != 'image' or match is None:
            return False
        try:
            data = base64.b64decode(match[2], validate=True)
        except binascii.Error:
            return False
        return data.startswith(b'\x89PNG\r\n\x1a\n') if match[1] == 'png' else data.startswith(b'\xff\xd8\xff')

    root = ET.fromstring(raw)
    if root.tag.split('}')[-1].lower() != 'svg':
        raise ValueError('GDV SVG 根节点错误')
    for node in root.iter():
        tag = node.tag.split('}')[-1].lower()
        if tag in ('script', 'foreignobject', 'iframe', 'object', 'embed', 'set') or tag.startswith('animate'):
            raise ValueError('GDV SVG 包含主动资源')
        for key, value in node.attrib.items():
            key = key.split('}')[-1].lower()
            if key.startswith('on') or key == 'base' or (key in ('href', 'src') and not local_reference(value, tag)):
                raise ValueError('GDV SVG 包含事件/外部引用')
            css_resources(value)
        if tag == 'style':
            css_resources(''.join(node.itertext()))


def load_delivery(path):
    path = no_symlinks(path).resolve()
    delivery = json.loads(path.read_text())
    actual_path = safe_file(path.parent, delivery['actual_manifest'])
    actual = json.loads(actual_path.read_text())
    unique_ids(actual['loci'], 'locus')
    source_root = actual_path.parent
    if delivery['source_status'] != 'historical_revised_input_not_new_export':
        raise ValueError('GDV delivery source_status 未声明历史修订来源')
    def record(rel, expected=None):
        raw = safe_file(source_root, rel).read_bytes()
        value = sha256(raw)
        if expected is not None and value != expected:
            raise ValueError('GDV delivery hash 不符：' + rel)
        return dict(path=rel, sha256=value)
    gdv = []
    for locus in actual['loci']:
        folder = locus['relative_directory']
        if not folder.startswith('run-01/'):
            raise ValueError('固定 GDV 输入必须为 actualmanifest run-01')
        hashes = locus['run_artifacts_sha256']['run-01']
        def artifact(name):
            return record(folder + '/' + name, hashes[name])
        spec_record = artifact('spec.json')
        spec = json.loads(safe_file(source_root, spec_record['path']).read_text())
        resources = []
        for suffix in ('svg', 'png', 'pdf'):
            rel = locus['relative_output'][suffix]
            if str(Path(rel).parent) != folder:
                raise ValueError('GDV resource 不在声明 locus 目录')
            resources.append(dict(input=record(rel, locus['raw_hashes'][suffix]['run_01']),
                                  output='03.GDV/' + locus['locus'] + '/' + Path(rel).name))
        gdv.append(dict(id=locus['locus'], mode='rendered', spec=spec_record, metadata=spec,
                        product_report=artifact('product_report.json'), resources=resources,
                        evidence_inputs=[artifact(n) for n in ('checks.json', 'environment.json', 'render_profile.json', 'source_notes.md')],
                        source_status=locus['source_status'], marker_validation=locus['marker_validation'],
                        visual_review='pending_parent', scientific_binding_review='pending_Oracle',
                        endpoint_status='pending', public_RNA_status='pending',
                        delivery_metadata=dict(authenticity=delivery['authenticity'], counts=actual['counts'],
                                               endpoint_discrepancies=actual['endpoint_discrepancies'],
                                               public_RNA_compatibility=actual['public_RNA_compatibility'])))
    return source_root, dict(gdv=gdv), dict(path=path.name, sha256=sha256(path.read_bytes())), dict(path=str(actual_path.relative_to(path.parent)), sha256=sha256(actual_path.read_bytes()))
