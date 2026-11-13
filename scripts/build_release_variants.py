"""Split a verified full ZIP into a smaller desktop and exact offline templates.

No product is removed from the full artifact. The core's pinned sidecar is
installed by the existing background template task; no network is needed.
"""
from pathlib import Path
import argparse,hashlib,json,shutil,zipfile

def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def member(source,target,name):
    with source.open(name) as input,target.open(name,'w',force_zip64=True) as output:shutil.copyfileobj(input,output,1024*1024)

def build(full,core,templates):
    full,core,templates=map(Path,(full,core,templates))
    if core.exists() or templates.exists():raise ValueError('new_archive_paths_required')
    with zipfile.ZipFile(full) as source:
        manifest=json.loads(source.read('EB/BUILD.json'));rows=manifest['files'];files={row['path']:row for row in rows}
        names=[n for n in source.namelist() if not n.endswith('/')]
        if len(set(names))!=len(names) or set(names)!={'EB/'+p for p in files}|{'EB/BUILD.json'}:raise ValueError('full_manifest_membership_changed')
        # Validate full bytes/CRC before trusting any copied dependency.
        for path,row in files.items():
            sha=hashlib.sha256();size=0
            with source.open('EB/'+path) as input:
                while block:=input.read(1024*1024):sha.update(block);size+=len(block)
            if size!=row['size'] or sha.hexdigest()!=row['sha256']:raise ValueError('full_manifest_digest_changed: '+path)
        excluded={p for p in files if p.startswith('runtime/meme/')}
        if 'runtime/meme/ready.json' not in excluded:raise ValueError('full_template_runtime_required')
        with zipfile.ZipFile(templates,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as target:
            for path in sorted(excluded):member(source,target,'EB/'+path)
        spec=dict(filename=templates.name,sha256=digest(templates),bytes=templates.stat().st_size,
                  file_count=len(excluded),unpacked_bytes=sum(files[p]['size'] for p in excluded))
        manifest.update(distribution='core-with-optional-templates',optional_components={'meme':spec},
                        files=[row for row in rows if row['path'] not in excluded],template_packages={})
        manifest['max_archive_path_chars']=max(len('EB/'+row['path']) for row in manifest['files'])
        with zipfile.ZipFile(core,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as target:
            for path in sorted(set(files)-excluded):member(source,target,'EB/'+path)
            target.writestr('EB/BUILD.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    results=[]
    for path in (core,templates):
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:raise ValueError('archive_crc_failed')
        sha=digest(path);path.with_suffix(path.suffix+'.sha256').write_text(f'{sha}  {path.name}\n','ascii')
        results.append(dict(archive=str(path),bytes=path.stat().st_size,sha256=sha))
    return results

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--full',type=Path,required=True);p.add_argument('--core',type=Path,required=True);p.add_argument('--templates',type=Path,required=True);a=p.parse_args()
    print(json.dumps(build(a.full,a.core,a.templates),ensure_ascii=False,indent=2))
