"""Verified handoff allowlist; no private library or development folder copying."""
import hashlib
import json
from pathlib import Path
import shutil

def digest(file):
    value=hashlib.sha256()
    with file.open('rb') as stream:
        while chunk:=stream.read(1024*1024):value.update(chunk)
    return value.hexdigest()

def verify_bundle(source):
    source=Path(source).resolve()
    checks={}
    for line in (source/'checksums.sha256').read_text('utf-8-sig').splitlines():
        expected,name=line.split('  ',1)
        file=(source/name).resolve()
        if not file.is_relative_to(source) or not file.is_file():raise ValueError('promo_path_invalid: '+name)
        if digest(file)!=expected:raise ValueError('promo_hash_mismatch: '+name)
        checks[name]=expected
    manifest=json.loads((source/'manifest.json').read_text('utf-8'))
    if manifest['schema']!='emojibridge.promo-assets.v1':raise ValueError('promo_schema_unknown')
    for row in manifest['assets']:
        if checks.get(row['path'])!=row['sha256']:raise ValueError('promo_media_not_verified')
    for row in manifest['editable']:
        if row['path'] not in checks:raise ValueError('promo_project_not_verified')
    return checks,manifest

def copy_bundle(source,destination):
    source=Path(source).resolve();destination=Path(destination)
    checks,manifest=verify_bundle(source)
    for name in checks:
        # Provenance documents are allowed, but development instructions are not runtime data.
        if name.startswith('给开发'):continue
        output=destination/name;output.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/name,output)
    (destination/'checksums.sha256').write_text(''.join(value+'  '+name+'\n' for name,value in checks.items() if not name.startswith('给开发')),'utf-8')
    info={'version':manifest['version'],'manifest_sha256':checks['manifest.json'],
          'main_materials':sum(bool(r['seed_default']) for r in manifest['assets']),
          'preview_files':sum(not r['seed_default'] for r in manifest['assets']),
          'editable_entries':len(manifest['editable']),'verified_source_files':len(checks)}
    (destination/'bundle-index.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),'utf-8')
    return info
