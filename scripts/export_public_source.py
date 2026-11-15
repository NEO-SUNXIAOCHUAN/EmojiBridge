"""Export an exact source allowlist without development history or user data."""
from pathlib import Path
import argparse,hashlib,json,re,shutil,subprocess,zipfile
ROOT=Path(__file__).resolve().parents[1]
TOP={'LICENSE','COPYRIGHT.md','README.md','THIRD_PARTY_NOTICES.md','RELEASE_RIGHTS.md',
     'RELEASE_NOTES.md','FEATURES.md','BUILDING.md','TEMPLATE_CATALOG.json','RELEASE_COMPONENTS.json','requirements-release.txt','requirements-cutout.txt'}
BUILD_SCRIPTS={'build_pilot.py','build_release_variants.py','export_public_source.py',
               'portable_launcher.cs','portable_launcher.manifest'}
DOCS={'portable-使用说明.txt','pilot-使用说明.txt','demo-使用说明.txt','S0146-候选包使用说明.txt'}
def selected(name):
    p=Path(name)
    if name in TOP:return True
    if p.parts[0] in ('src','assets','third_party','desktop-ui'):
        return not any(part in ('node_modules','__pycache__','.cache') for part in p.parts)
    if p.parts[0]=='scripts':
        return p.name in BUILD_SCRIPTS or (not p.name.startswith(('check_','drop_','build_'))
            and (p.suffix in ('.py','.ps1') or p.name=='qq_accessible.cs'))
    return (p.parts[0]=='tests' and p.name in ('test_builtin_upgrade_S0162.py','test_download_startup_S0168.py','test_release_paths_S0174.py')) or (p.parts[0]=='docs' and p.name in DOCS)
def digest(data):return hashlib.sha256(data).hexdigest()
def export(destination):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('new_output_required')
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf8').split('\0')
    names=sorted(n for n in tracked if n and selected(n));destination.mkdir(parents=True)
    for n in names:
        p=destination/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/n,p)
    (destination/'run-desktop.cmd').write_bytes(b'@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\nif exist "runtime\\pythonw.exe" (\r\n start "" "runtime\\pythonw.exe" -X utf8 "scripts\\desktop_modern.py" %*\r\n) else if exist ".venv\\Scripts\\pythonw.exe" (\r\n start "" ".venv\\Scripts\\pythonw.exe" -X utf8 "scripts\\desktop_modern.py" %*\r\n) else (\r\n pyw -3.12 -X utf8 "scripts\\desktop_modern.py" %*\r\n)\r\n')
    (destination/'.gitignore').write_text('exports/\nprivate/\nruntime/\nruntime-data/\n.venv/\n__pycache__/\n*.pyc\nnode_modules/\n*.db\n*.db-wal\n*.db-shm\n','utf8')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip()
    report={'source_commit':commit,'history_included':False,'publication_ready':False,
            'rights_review':'RELEASE_RIGHTS.md','files':[],'scan_findings':[]}
    patterns={'private_profile':r'(?i)[A-Z]:[\\/]+Users[\\/]+(?!Public\b|Default\b)[^\s"\x27<>]+',
              'session_path':r'/workspace/(?:scratch|upload)/',
              'credential':r'(?i)(?:gh[pousr]_[a-z0-9]{25,}|github_pat_[a-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)'}
    for p in sorted(destination.rglob('*')):
        if not p.is_file():continue
        data=p.read_bytes();relative=p.relative_to(destination).as_posix()
        report['files'].append({'path':relative,'sha256':digest(data),'bytes':len(data)})
        try:text=data.decode('utf8')
        except UnicodeDecodeError:continue
        for label,pattern in patterns.items():
            for m in re.finditer(pattern,text):
                report['scan_findings'].append({'path':relative,'line':text.count('\n',0,m.start())+1,'kind':label})
    (destination/'SOURCE_BUILD.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    archive=destination.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(destination.rglob('*')):
            if p.is_file():z.write(p,Path(destination.name)/p.relative_to(destination))
    archive.with_suffix('.zip.sha256').write_text(digest(archive.read_bytes())+'  '+archive.name+'\n','ascii')
    print(json.dumps({'directory':str(destination),'archive':str(archive),'files':len(report['files']),
                      'scan_findings':report['scan_findings']},ensure_ascii=False))
    return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();export(a.output)
