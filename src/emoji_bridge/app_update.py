"""Official release checks are metadata-only; downloads require an explicit call."""
from pathlib import Path
import json,os,re,shutil,stat,subprocess,tempfile,threading,uuid,urllib.request,zipfile
from .release_components import digest,check,safe_name
from .state import save_json

REPO='https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge'
API='https://api.github.com/repos/NEO-SUNXIAOCHUAN/EmojiBridge/releases/latest'

def version(text):
    match=re.fullmatch(r'S(\d+)(?:[- ]?R(\d+))?',str(text),re.I)
    if not match:raise ValueError('无法识别发行版本：'+str(text))
    return int(match[1]),int(match[2] or 0)

def current(app):
    file=Path(app)/'BUILD.json'
    if not file.exists() or (Path(app)/'.git').exists():return {'build':'源码工作区','manual':True}
    data=json.loads(file.read_text('utf8'))
    return {k:data.get(k) for k in ('build','distribution','source_commit','database_schema')}

def read_json(url,limit=16*1024*1024):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'EmojiBridge','Accept':'application/json'}),timeout=15) as response:
        raw=response.read(limit+1)
    if len(raw)>limit:raise ValueError('发行信息过大')
    return json.loads(raw)

def latest(app):
    installed=current(app)
    if installed.get('manual'):return {'current':installed,'available':False,'text':'源码工作区请通过 Git 更新','url':REPO}
    release=read_json(API);tag=release['tag_name']
    if release.get('draft') or release.get('prerelease'):raise ValueError('未找到稳定发行')
    available=version(tag)>version(installed['build'])
    result={'current':installed,'available':available,'build':tag,'notes':release.get('body',''),'url':REPO+'/releases/tag/'+tag}
    if not available:return dict(result,text='当前已是最新版本')
    entries=read_json(REPO+'/releases/download/'+tag+'/release-assets.json')
    filename=f'EmojiBridge-{tag}-Windows-x64-{installed["distribution"]}.zip'
    asset=next((e for e in entries if e['name']==filename),None)
    if not asset or not re.fullmatch('[a-f0-9]{64}',asset.get('sha256','')):return dict(result,manual=True,text='此发行没有匹配的安装包，请手动下载')
    expected=REPO+'/releases/download/'+tag+'/'+filename
    if asset.get('url')!=expected:raise ValueError('发行包地址不符')
    if type(asset.get('bytes')) is not int or asset['bytes']<=0:raise ValueError('发行包大小无效')
    return dict(result,asset=asset,text='发现新版本 '+tag+'，点击更新后下载安装')

def unpack(archive,stage,expected_build,distribution,cancel=None,progress=None):
    stage=Path(stage);stage.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        if z.getinfo('EB/BUILD.json').file_size>32*1024*1024:raise ValueError('应用清单过大')
        build=json.loads(z.read('EB/BUILD.json'))
        if build.get('build')!=expected_build or build.get('distribution')!=distribution:raise ValueError('下载包版本或形态不符')
        if build.get('database_schema')!=3:raise ValueError('此版本需要手动迁移素材库，请按发行说明升级；当前程序保留')
        expected={safe_name(e['path']):e for e in build['files']}
        if len(expected)!=len(build['files']):raise ValueError('应用清单重复')
        names=set();entries=z.infolist()
        for info in entries:
            name=safe_name(info.filename)
            if name.casefold() in names or info.is_dir() or stat.S_ISLNK(info.external_attr>>16) or info.flag_bits&1:raise ValueError('应用包存在重复文件或链接')
            names.add(name.casefold())
            if name=='EB/BUILD.json':continue
            if not name.startswith('EB/') or name[3:] not in expected or expected[name[3:]]['size']!=info.file_size:raise ValueError('应用包清单不符')
        if len(entries)!=len(expected)+1:raise ValueError('应用包缺少成员')
        if shutil.disk_usage(stage).free<sum(e['size'] for e in expected.values())+64*1024*1024:raise OSError('磁盘空间不足')
        for n,info in enumerate(entries):
            check(cancel);relative=info.filename[3:];file=stage/relative;file.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as src,file.open('xb') as dst:
                while block:=src.read(1024*1024):check(cancel);dst.write(block)
            if relative!='BUILD.json' and digest(file,cancel)!=expected[relative]['sha256']:raise ValueError('应用文件校验失败：'+relative)
            if progress:progress('校验应用',n+1,len(entries))
    return build

def prepare(app,info,cancel=None,progress=None):
    app=Path(app).resolve();installed=current(app)
    if installed.get('manual') or not info.get('asset'):raise ValueError('此发行需要手动更新')
    asset=info['asset'];session=app.parent/('.emojibridge-update-'+uuid.uuid4().hex);session.mkdir()
    archive=session/'application.zip'
    try:
        request=urllib.request.Request(asset['url'],headers={'User-Agent':'EmojiBridge'})
        with urllib.request.urlopen(request,timeout=20) as src,archive.open('xb') as dst:
            size=0
            while block:=src.read(1024*1024):
                check(cancel);size+=len(block)
                if size>asset['bytes']:raise ValueError('更新包大小超过清单')
                dst.write(block)
                if progress:progress('下载应用更新',size,asset['bytes'])
        if size!=asset['bytes'] or digest(archive,cancel)!=asset['sha256']:raise ValueError('更新包校验失败；当前版本保留')
        build=unpack(archive,session/'staged',info['build'],installed['distribution'],cancel,progress)
        return session,build
    finally:archive.unlink(missing_ok=True)

def copy_bootstrap(source,runtime):
    """Support both zip-based embedded Python and our unpacked stdlib layout."""
    source=Path(source);runtime=Path(runtime);runtime.mkdir(parents=True,exist_ok=True)
    for file in source.iterdir():
        if file.is_file() and file.suffix.lower() in ('.exe','.dll','.zip','._pth','.pyd'):shutil.copy2(file,runtime/file.name)
    if (source/'Lib').is_dir():
        shutil.copytree(source/'Lib',runtime/'Lib',ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests'),dirs_exist_ok=True)
    if (source/'DLLs').is_dir():shutil.copytree(source/'DLLs',runtime/'DLLs',dirs_exist_ok=True)
    for pth in runtime.glob('*._pth'):
        pth.write_text('\n'.join([p.name for p in runtime.glob('python*.zip')])+ '\nLib\nDLLs\n.\n','utf8')

def launch_helper(app,session,library,build,mode='update',previous_library=None):
    """Copy a minimal stdlib runtime outside the app before any rename."""
    app=Path(app).resolve();session=Path(session).resolve();runtime=session/'runtime';runtime.mkdir()
    source=app/'runtime'
    if not (source/'python.exe').is_file():
        import sys
        source=Path(sys.executable).parent
    copy_bootstrap(source,runtime)
    helper=Path(__file__).resolve().parents[2]/'scripts/update_helper.py'
    shutil.copy2(helper,session/'helper.py')
    plan={'token':uuid.uuid4().hex,'app':str(app),'session':str(session),'library':str(Path(library).resolve()),
          'parent':os.getpid(),'build':build['build'],'source_commit':build.get('source_commit'),'mode':mode}
    if previous_library:plan['previous_library']=str(Path(previous_library).resolve())
    save_json(session/'plan.json',plan)
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'CREATE_BREAKAWAY_FROM_JOB',0)
    from .instance_job import updater_breakaway
    with (session/'helper.log').open('ab') as log, updater_breakaway():
        process=subprocess.Popen([str(runtime/'python.exe'),'-X','utf8',str(session/'helper.py'),str(session/'plan.json')],
            cwd=session,creationflags=flags,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
    return plan,process
