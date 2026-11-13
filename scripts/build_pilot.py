"""Build a private portable pilot from explicit code/runtime allowlists.

Never copies developer profiles, reports, caches, databases or historical jobs.
No network access and no global Python installation changes.
"""
from pathlib import Path
import argparse,ast,hashlib,importlib.metadata as metadata,json,os,shutil,subprocess,sys,zipfile
ROOT=Path(__file__).resolve().parents[1]
PACKAGES=('Pillow','numpy','cryptography','cffi','pycparser','pip')
OPTIONAL_PACKAGES=('onnxruntime','coloredlogs','flatbuffers','humanfriendly','packaging','protobuf','pyreadline3','sympy','mpmath')
DESKTOP_PACKAGES=('pywebview','pythonnet','clr_loader','bottle','proxy_tools','typing_extensions')
ARCHIVE_ROOT='EB'


def file_sha(file):
    value=hashlib.sha256()
    with Path(file).open('rb') as stream:
        while chunk:=stream.read(1024*1024):value.update(chunk)
    return value.hexdigest()


def copy_tree(source,target):
    shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc','test','tests'),dirs_exist_ok=True)


def build(destination,runtime,cutout_runtime=None,desktop_runtime=None,*,demo=False,template_runtime=None,promo_assets=None,vision_runtime=None):
    destination=Path(destination).resolve();runtime=Path(runtime).resolve()
    if destination.exists():raise ValueError('new_output_directory_required')
    if not destination.is_relative_to(ROOT/'exports'):raise ValueError('build_output_must_be_in_exports')
    def git(*args):
        return subprocess.check_output(['git',*args],cwd=ROOT).decode('utf-8')
    if git('status','--porcelain','--untracked-files=no').strip():
        raise ValueError('commit_tracked_changes_before_build')
    commit=git('rev-parse','HEAD').strip()
    tree=ast.parse((ROOT/'src/emoji_bridge/pilot.py').read_text(encoding='utf-8'))
    version=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                 and any(isinstance(t,ast.Name) and t.id=='BUILD' for t in n.targets))
    destination.mkdir(parents=True)
    # Tracked code/resources only: never include local diagnostic or cached files.
    for name in git('ls-files','-z','--','src','assets','third_party','scripts').split('\0'):
        if not name:continue
        relative=Path(name)
        if relative.parts[0]=='scripts' and (relative.name.startswith(('check_','drop_','build_'))
                                           or (relative.suffix not in ('.py','.ps1') and relative.name != 'qq_accessible.cs')):continue
        source=ROOT/relative;output=destination/relative
        output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,output)
    shutil.copyfile(ROOT/'THIRD_PARTY_NOTICES.md',destination/'THIRD_PARTY_NOTICES.md')
    for name in ('LICENSE','COPYRIGHT.md','RELEASE_RIGHTS.md','RELEASE_NOTES.md','FEATURES.md','TEMPLATE_CATALOG.json'):
        if (ROOT/name).is_file():shutil.copyfile(ROOT/name,destination/name)
    shutil.copyfile(ROOT/'docs/pilot-使用说明.txt',destination/'使用说明.txt')
    (destination/'版本信息.txt').write_text(f'EmojiBridge {version}\n源码提交：{commit}\nWindows x64 预览候选；许可与待验事项见随包说明\n',encoding='utf-8-sig')
    target=destination/'runtime';target.mkdir()
    for name in ('python.exe','pythonw.exe','python3.dll','python312.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt'):
        shutil.copyfile(runtime/name,target/name)
    copy_tree(runtime/'DLLs',target/'DLLs');copy_tree(runtime/'tcl',target/'tcl')
    lib=target/'Lib';lib.mkdir()
    for source in (runtime/'Lib').iterdir():
        if source.name in ('site-packages','__pycache__','test','ensurepip','venv','idlelib'):continue
        if source.is_dir():copy_tree(source,lib/source.name)
        elif source.suffix=='.py' and source.name not in ('sitecustomize.py','usercustomize.py'):
            shutil.copyfile(source,lib/source.name)
    # This selected Python runtime's SSL module references its public rejection
    # certificate bundle. Preserve that runtime asset and its verification policy.
    ssl_source=(lib/'ssl.py').read_text('utf-8')
    if 'codex-rejected-cas.pem' in ssl_source:
        shutil.copyfile(runtime/'Lib/codex-rejected-cas.pem',lib/'codex-rejected-cas.pem')
    # Explorer's ZIP extraction still rejects long destination paths. Keep the
    # dependency root short without renaming any third-party package internals.
    site=target/'p';site.mkdir()
    versions={}
    for package in PACKAGES:
        dist=metadata.distribution(package);versions[package]=dist.version
        for relative in dist.files or ():
            parts=Path(relative).parts
            if '..' in parts or '__pycache__' in parts or str(relative).endswith('.pyc'):continue
            source=Path(dist.locate_file(relative)).resolve()
            if not source.is_relative_to(runtime/'Lib/site-packages'):
                raise ValueError('dependency_outside_selected_runtime')
            if source.is_file():
                output=site/relative;output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,output)
    # Isolated CPython search paths: no registry Python, global site or user .pth.
    (target/'python312._pth').write_text('Lib\nDLLs\np\n.\n',encoding='ascii')
    optional_versions={}
    if cutout_runtime:
        optional=Path(cutout_runtime).resolve();output_root=target/'cutout';output_root.mkdir()
        distributions={d.metadata['Name'].lower():d for d in metadata.distributions(path=[str(optional)])}
        for name in OPTIONAL_PACKAGES:
            dist=distributions[name];optional_versions[name]=dist.version
            for relative in dist.files or ():
                parts=Path(relative).parts
                if '..' in parts or any(p in ('__pycache__','tests','test','benchmarks') for p in parts) or str(relative).endswith('.pyc'):continue
                source=Path(dist.locate_file(relative)).resolve()
                if not source.is_relative_to(optional):raise ValueError('optional_dependency_outside_runtime')
                if source.is_file():
                    output=output_root/relative;output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,output)
        (output_root/'ready.txt').write_text(optional_versions['onnxruntime'],encoding='ascii')
    desktop_versions={}
    if desktop_runtime:
        optional=Path(desktop_runtime).resolve();output_root=target/'desktop';output_root.mkdir()
        distributions={d.metadata['Name'].lower().replace('-','_'):d for d in metadata.distributions(path=[str(optional)])}
        for name in DESKTOP_PACKAGES:
            dist=distributions[name];desktop_versions[name]=dist.version
            for relative in dist.files or ():
                parts=Path(relative).parts
                if '..' in parts or '__pycache__' in parts or str(relative).endswith('.pyc'):continue
                source=Path(dist.locate_file(relative)).resolve()
                if not source.is_relative_to(optional):raise ValueError('desktop_dependency_outside_runtime')
                if source.is_file():
                    output=output_root/relative;output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,output)
    template_versions={}
    if template_runtime:
        from template_bundle import copy_runtime
        template_versions=copy_runtime(template_runtime,target/'meme')
    vision_versions={}
    if vision_runtime:
        from vision_bundle import copy_runtime
        vision_versions=copy_runtime(vision_runtime,target/'vision')
    promo=None
    if promo_assets:
        from promo_bundle import copy_bundle
        promo=copy_bundle(promo_assets,destination/'宣传片同款表情')
    if desktop_runtime:
        compiler=Path(os.environ['SystemRoot'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not compiler.is_file():raise ValueError('Windows .NET Framework C# compiler is required to build the GUI launcher')
        subprocess.run([str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+',
                        '/reference:System.Windows.Forms.dll',
                        '/win32icon:'+str(ROOT/'assets/branding/EmojiBridge.ico'),
                        '/win32manifest:'+str(ROOT/'scripts/portable_launcher.manifest'),
                        '/out:'+str(destination/'EmojiBridge.exe'),str(ROOT/'scripts/portable_launcher.cs')],check=True)
    launcher='@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\nstart "" "%~dp0runtime\\pythonw.exe" -X utf8 "%~dp0scripts\\pilot_launcher.py"\r\n'
    if demo:
        # Every entry uses the same package-local profile. Never clear or copy
        # the user's normal library; the existing initializer seeds examples.
        launcher=launcher.replace('pilot_launcher.py"','pilot_launcher.py" --data-dir "%~dp0demo-data"')
    (destination/'启动表情互通.cmd').write_bytes(launcher.encode('ascii'))
    (destination/'启动EmojiBridge.cmd').write_bytes(launcher.encode('ascii'))
    (destination/'启动原版编辑器.cmd').write_bytes(launcher.encode('ascii'))
    if desktop_runtime:
        (destination/'启动EmojiBridge.cmd').write_bytes(launcher.replace('pilot_launcher.py','desktop_modern.py').encode('ascii'))
        # EXE and fallback forward the same supported arguments, with no data-root override.
        for name in ('启动EmojiBridge.cmd','启动表情互通.cmd','启动原版编辑器.cmd'):
            file=destination/name;file.write_bytes(file.read_bytes().replace(b'.py"\r\n',b'.py" %*\r\n'))
    if desktop_runtime and not demo:
        independent=launcher.replace('pilot_launcher.py"','desktop_modern.py" --data-dir "%~dp0independent-data"')
        (destination/'启动独立初始库（不动旧库）.cmd').write_bytes(independent.encode('ascii'))
        (destination/'预览失败处理说明.txt').write_text(
            '完整功能保留，两个入口仅数据位置不同。\n'
            '1. 启动EmojiBridge.cmd：继续原来的素材、账号和草稿。设置 → 本地保存 → 检查并修复素材。完成后返回素材库。\n'
            '2. 启动独立初始库（不动旧库）.cmd：本文件夹/independent-data 中的独立初始素材库，第一次启动准备随包素材。完整功能保留，不读取旧库及旧账号任务；需要互通时选择自己的账号。以后仍用同一入口，新增作品会保留。\n'
            '请先完整解压到普通可写文件夹，不要直接在ZIP内运行，也不要覆盖或删除旧库。\n'
            '独立库正常不代表旧库已经修复。修复不能凭空恢复个人文件，也不会修改权限或删除素材。原库仍失败时，点“复制检查结果”发给开发者；没有账号和完整路径。详细访问记录留在本机素材库 diagnostics 中。\n',encoding='utf-8-sig')
    shutil.copyfile(ROOT/'docs/portable-使用说明.txt',destination/'使用说明.txt')
    if promo_assets:
        shutil.copyfile(ROOT/'docs/S0146-候选包使用说明.txt',destination/'使用说明.txt')
    if demo:
        shutil.copyfile(ROOT/'docs/demo-使用说明.txt',destination/'演示版说明.txt')
        (destination/'版本信息.txt').write_text(f'EmojiBridge {version} · 初始素材演示版\n源码提交：{commit}\n独立数据：程序目录/demo-data\n',encoding='utf-8-sig')
    # Reuse the tested, bounded read-only probe without activating accessibility.
    probe='@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\\diagnose_wechat_controls.ps1" -OutputDirectory "%~dp0."\r\npause\r\n'
    if not version.startswith('preview-'):(destination/'检查微信控件.cmd').write_bytes(probe.encode('ascii'))
    forbidden={'private','reports','runtime-data','logs','backups','.git','exports'}
    files=[]
    for file in destination.rglob('*'):
        if not file.is_file():continue
        relative=file.relative_to(destination)
        if any(p in forbidden for p in relative.parts) or file.suffix.lower() in ('.db','.db-wal','.db-shm'):
            raise ValueError('private_file_in_distribution')
        files.append({'path':relative.as_posix(),'size':file.stat().st_size,'sha256':file_sha(file)})
    manifest={'build':version,'source_commit':commit,'source_tree_clean':True,
              'data_profile':'package-local-demo' if demo else 'user-local',
              'runtime':sys.version.split()[0],'packages':versions,'optional_packages':optional_versions,'desktop_packages':desktop_versions,'template_packages':template_versions,'archive_root':ARCHIVE_ROOT,
              'vision_packages':vision_versions,'max_archive_path_chars':max(len(ARCHIVE_ROOT+'/'+f['path']) for f in files),
              'files':files,'promo_assets':promo,'launcher':'EmojiBridge.exe' if desktop_runtime else None,
              'private_files_included':False,'external_machine_verified':False}
    (destination/'BUILD.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=destination.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as out:
        for file in destination.rglob('*'):
            if file.is_file():out.write(file,Path(ARCHIVE_ROOT)/file.relative_to(destination))
    return {'directory':str(destination),'archive':str(archive),'zip_bytes':archive.stat().st_size,
            'sha256':file_sha(archive),'files':len(files)+1,'packages':versions}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--runtime',type=Path,default=Path(sys.base_prefix));p.add_argument('--cutout-runtime',type=Path);p.add_argument('--desktop-runtime',type=Path);p.add_argument('--template-runtime',type=Path);p.add_argument('--vision-runtime',type=Path);p.add_argument('--promo-assets',type=Path);p.add_argument('--demo',action='store_true',help='Use an isolated package-local library seeded only with the built-in examples');a=p.parse_args()
    print(json.dumps(build(a.output,a.runtime,a.cutout_runtime,a.desktop_runtime,demo=a.demo,template_runtime=a.template_runtime,promo_assets=a.promo_assets,vision_runtime=a.vision_runtime),ensure_ascii=False,indent=2))
