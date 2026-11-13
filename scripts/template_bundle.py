"""Copy the reviewed template runtime by distribution records, never a profile."""
from pathlib import Path
import base64
import hashlib
import importlib.metadata as metadata
import json
import shutil

APP=Path(__file__).resolve().parents[1]

def copy_runtime(source,destination):
    source=Path(source).resolve();destination=Path(destination)
    lock=json.loads((APP/'third_party/factory/runtime-lock.json').read_text('utf-8'))
    excluded=set(json.loads((APP/'third_party/factory/excluded-templates.json').read_text('utf-8')))
    normalize=lambda name:name.lower().replace('_','-')
    distributions={normalize(d.metadata['Name']):d for d in metadata.distributions(path=[str(source)])}
    for name,version in lock['packages'].items():
        dist=distributions[name]
        if dist.version!=version:raise ValueError('template_runtime_version_mismatch: '+name)
        for relative in dist.files or ():
            parts=Path(relative).parts
            if len(parts)>2 and parts[:2]==('meme_generator','memes') and parts[2] in excluded:continue
            if '__pycache__' in parts or str(relative).endswith('.pyc'):continue
            original=Path(dist.locate_file(relative)).resolve()
            if not original.is_relative_to(source):
                # msvc-runtime wheels explicitly install their DLLs beside Python.
                # Never copy Scripts entrypoints or arbitrary external files.
                if name!='msvc-runtime' or original.suffix.lower()!='.dll':continue
                if not original.is_relative_to(source.parents[1]):raise ValueError('external_template_runtime_file')
                output=destination/original.name
            else:output=destination/relative
            if not original.is_file():raise ValueError('template_runtime_file_missing: '+str(relative))
            if relative.hash:
                actual=base64.urlsafe_b64encode(hashlib.new(relative.hash.mode,original.read_bytes()).digest()).decode().rstrip('=')
                if actual!=relative.hash.value:raise ValueError('template_runtime_file_changed: '+str(relative))
            output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,output)
    for row in lock['resources']:
        relative=Path(row['path']);original=source/relative
        if not original.resolve().is_relative_to(source):raise ValueError('invalid_template_resource')
        if hashlib.sha256(original.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('template_resource_changed: '+row['path'])
        output=destination/relative;output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,output)
    (destination/'ready.json').write_text(json.dumps({'packages':['meme-generator==0.1.14'],'source':lock['resource_source']}),'utf-8')
    shutil.copyfile(APP/'third_party/factory/runtime-lock.json',destination/'runtime-lock.json')
    return lock['packages']
