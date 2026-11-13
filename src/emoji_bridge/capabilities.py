"""Optional, pinned Python capabilities, isolated from the desktop interpreter."""
from pathlib import Path
import json,os,sys,zipfile,urllib.request,shutil
from .background_remove import _python,_process,check_cancel

APP=Path(__file__).resolve().parents[2]
PACKAGES={
 'meme':('meme-generator==0.1.14',),
 'vision':('rapidocr==3.4.2','onnxruntime==1.23.2','opencv-python==4.11.0.86','opencv-contrib-python-headless==4.11.0.86','numpy==2.2.6'),
 'speech':('faster-whisper==1.2.1','av==14.2.0'),
}

def settings_path():return Path(os.environ.get('LOCALAPPDATA',Path.home()))/'EmojiBridge/capability-settings.json'

def root():
    if os.environ.get('EMOJI_BRIDGE_CAPABILITIES'):return Path(os.environ['EMOJI_BRIDGE_CAPABILITIES'])
    settings=settings_path()
    if settings.is_file():return Path(json.loads(settings.read_text('utf-8'))['root'])
    return Path(os.environ.get('LOCALAPPDATA',Path.home()))/'EmojiBridge/optional/factory'

def configure_root(path):
    path=Path(path).resolve();path.mkdir(parents=True,exist_ok=True)
    settings=settings_path();settings.parent.mkdir(parents=True,exist_ok=True)
    from .state import save_json
    if settings.is_file() and json.loads(settings.read_text('utf-8')).get('root')==str(path):
        os.environ['EMOJI_BRIDGE_CAPABILITIES']=str(path);return
    try:save_json(settings,{'root':str(path)})
    except OSError as exc:
        # Redirected Windows profile volumes may reject a same-folder rename.
        # Keep the prior preference before the explicit user-requested change.
        if getattr(exc,'winerror',None)!=17:raise
        if settings.exists():shutil.copyfile(settings,settings.with_suffix('.json.bak'))
        with settings.open('w',encoding='utf-8') as stream:
            json.dump({'root':str(path)},stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        settings.with_suffix('.json.tmp').unlink(missing_ok=True)
    os.environ['EMOJI_BRIDGE_CAPABILITIES']=str(path)

def dependencies(name):
    override=os.environ.get('EMOJI_BRIDGE_'+name.upper()+'_DEPENDENCIES')
    if override:return Path(override)
    bundled=APP/'runtime'/name
    if name in ('meme','vision') and bundled.is_dir():return bundled
    target=root()/name/'packages'
    # Reuse the already prepared standalone runtimes used by earlier pilots.
    # New installations still use one predictable directory per capability.
    legacy={'meme':'meme-python'}.get(name)
    candidate=root()/legacy/'Lib/site-packages' if legacy else target
    return candidate if not target.exists() and candidate.is_dir() else target

def models(name):
    default=root()/name/'models'
    return Path(os.environ.get('EMOJI_BRIDGE_'+name.upper()+'_MODELS',default))

def ensure(name,cancel=None,progress=None):
    check_cancel(cancel)
    target=dependencies(name)
    if name=='meme' and not os.environ.get('EMOJI_BRIDGE_MEME_DEPENDENCIES') and not (APP/'runtime/meme').is_dir():
        from .offline_components import specification,install
        spec=specification(APP,name)
        if spec:return install(APP,root(),name,spec,cancel,progress)
    if name in ('meme','vision') and target==APP/'runtime'/name:
        ready=target/'ready.json'
        complete=(ready.is_file() and json.loads(ready.read_text('utf-8')).get('packages')==list(PACKAGES[name])
                and (target/('meme_generator/__init__.py' if name=='meme' else 'rapidocr/__init__.py')).is_file())
        if complete and name=='vision':
            import hashlib
            try:
                models=json.loads((target/'runtime-lock.json').read_text('utf-8'))['models']
                complete=len(models)==3
                for model in models:
                    check_cancel(cancel);path=(target/model['path']).resolve()
                    if not path.is_relative_to(target.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=model['sha256']:complete=False;break
            except (OSError,ValueError,KeyError):complete=False
        if complete:
            if progress:progress('使用随包模板组件' if name=='meme' else '使用随包识字 / 跟随组件',0,0)
            return target
        raise RuntimeError(('随包模板组件' if name=='meme' else '随包识字 / 跟随组件')+'不完整，请重新完整解压新版；原图和作品保留')
    folder=target.parent;folder.mkdir(parents=True,exist_ok=True)
    ready=folder/'ready.json'
    if ready.is_file() and json.loads(ready.read_text('utf-8')).get('packages')==list(PACKAGES[name]):return target
    if progress:progress('准备 '+name+' 本地组件',0,0)
    code=_process([_python(),'-m','pip','install','--disable-pip-version-check','--no-warn-script-location','--retries','2','--timeout','15','--target',str(target),*PACKAGES[name]],log=folder/'install.log',cancel=cancel,progress=progress,stage='首次下载并安装模板组件' if name=='meme' else '首次准备识字 / 跟随组件' if name=='vision' else '准备 '+name+' 本地组件',timeout=300 if name in ('meme','vision') else None)
    if code:raise RuntimeError('本地组件下载或安装失败，请检查网络后重试；诊断日志已保留，作品未改变')
    if name=='meme':
        commit='f5ee44f6a3e134b9ac54032f97eab788d6454e3c';archive=folder/'resources.zip'
        download('https://codeload.github.com/MemeCrafters/meme-generator/zip/'+commit,archive,cancel,progress)
        with zipfile.ZipFile(archive) as z:
            for entry in z.infolist():
                check_cancel(cancel);parts=Path(entry.filename).parts
                if len(parts)<3 or parts[1]!='meme_generator' or entry.is_dir() or entry.filename.endswith('.py'):continue
                destination=target.joinpath(*parts[1:])
                if not destination.resolve().is_relative_to(target.resolve()):raise ValueError('资源路径无效')
                destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(z.read(entry))
        archive.unlink()
    ready.write_text(json.dumps({'packages':PACKAGES[name]}),'utf-8');return target

def download(url,path,cancel=None,progress=None):
    import time
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    for attempt in range(3):
        check_cancel(cancel)
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'EmojiBridge'}),timeout=40) as response,path.with_suffix('.part').open('wb') as out:
                total=int(response.headers.get('Content-Length',0));done=0
                while block:=response.read(256*1024):
                    check_cancel(cancel);out.write(block);done+=len(block)
                    if progress:progress('下载组件资源',done,total)
            path.with_suffix('.part').replace(path);return path
        except InterruptedError:raise
        except Exception:
            if attempt==2:raise
            time.sleep(1)

def worker(name,script,request,folder,cancel=None,progress=None,prepare=True,timeout=None):
    target=ensure(name,cancel,progress) if prepare else dependencies(name)
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    file=folder/'request.json';file.write_text(json.dumps(request,ensure_ascii=False),'utf-8')
    def report(stage,*args):
        if progress:
            try:
                state=json.loads(Path(request['result']).with_suffix('.progress.json').read_text('utf-8'))
                progress(state.get('stage',stage),state.get('completed',0),state.get('total',0));return
            except (OSError,ValueError):pass
            progress(stage,*args)
    code=_process([_python(),'-X','utf8',str(APP/'scripts'/script),str(file),'--dependencies',str(target)],log=folder/'worker.log',cancel=cancel,progress=report,stage='载入模板并生成' if name=='meme' else '正在识别文字' if name=='vision' and request.get('action')=='ocr' else '正在计算跟随位置' if name=='vision' else '本地处理',timeout=timeout)
    if code:
        lines=(folder/'worker.log').read_text('utf-8',errors='replace').splitlines()
        raise RuntimeError(next((s for s in reversed(lines) if s.strip()),'本地处理失败'))
    return Path(request['result'])
