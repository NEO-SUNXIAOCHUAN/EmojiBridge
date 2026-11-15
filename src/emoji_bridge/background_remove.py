"""Local U2-Net foreground extraction, isolated from the desktop's NumPy runtime.

Model preprocessing/mask normalization follows rembg's MIT U2netSession.
See third_party/cutout/NOTICE.md for the pinned model, code and licenses.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import shutil
import time
import urllib.request
import urllib.error
import socket
import errno
import zipfile

MODEL = 'u2net'
MODEL_URL = 'https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx'
MODEL_MD5 = '60024c5c889badc19c04ad937298a77b'
ORT_VERSION = '1.23.2'
MODELS={
 'u2net':{'file':'u2net.onnx','md5':MODEL_MD5,'edge':320,'std':(.229,.224,.225),'label':'自动 / U²-Net'},
 'isnet-anime':{'file':'isnet-anime.onnx','md5':'6f184e756bb3bd901c8849220a83e38e','edge':1024,'std':(1.,1.,1.),'label':'动漫 / IS-Net'},
 'birefnet-general-lite':{'file':'BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx','md5':'4fab47adc4ff364be1713e97b7e66334','edge':1024,'std':(.229,.224,.225),'sigmoid':True,'label':'精细 / BiRefNet Lite'},
}

def model_digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'md5').hexdigest()


def cache_root():
    return Path(os.environ.get('EMOJI_BRIDGE_CUTOUT_CACHE', Path(os.environ.get('LOCALAPPDATA', Path.home()))/'EmojiBridge'/'cutout'))


def runtime_root():
    bundled=Path(__file__).resolve().parents[2]/'runtime'/'cutout'
    if not os.environ.get('EMOJI_BRIDGE_CUTOUT_RUNTIME') and (bundled/'onnxruntime'/'__init__.py').is_file():return bundled
    return Path(os.environ.get('EMOJI_BRIDGE_CUTOUT_RUNTIME', Path(os.environ.get('LOCALAPPDATA', Path.home()))/'EmojiBridge'/'optional'/f'cutout-ort-{ORT_VERSION}'))


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise InterruptedError('已取消抠图，原图和草稿保留')


def notify(progress, stage, done=0, total=0):
    if progress:progress(stage, done, total)


def _publish(source,destination):
    try:source.replace(destination)
    except OSError as exc:
        if getattr(exc,'winerror',None)!=17:raise
        # Some redirected Windows cache folders span volumes despite the same prefix.
        shutil.copyfile(source,destination);source.unlink()


def _python():
    python=Path(sys.executable)
    console=python.with_name('python.exe')
    return str(console if python.name.lower()=='pythonw.exe' and console.exists() else python)


def _process(command, *, log, cancel, env=None, progress=None, stage='正在处理',timeout=None):
    from .task_budget import admission,child_environment
    estimate=8192 if any('birefnet' in str(v).lower() for v in command) else 1536
    with admission(stage,cancel=cancel,memory=estimate,waiting=lambda text:notify(progress,text)):
        return _admitted_process(command,log=log,cancel=cancel,env=child_environment(env),progress=progress,stage=stage,timeout=timeout)


def _admitted_process(command, *, log, cancel, env=None, progress=None, stage='正在处理',timeout=None):
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    with Path(log).open('wb') as output:
        process=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT,env=env,creationflags=flags)
        started=time.monotonic()
        try:
            while process.poll() is None:
                check_cancel(cancel)
                if timeout is not None and time.monotonic()-started>=timeout:
                    raise TimeoutError('组件准备超时，已停止本次准备；请检查网络后重试，作品保留')
                notify(progress,stage)
                time.sleep(.15)
            check_cancel(cancel)
            return process.returncode
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.wait()


def ensure_runtime(cancel=None, progress=None):
    root=runtime_root();root.mkdir(parents=True,exist_ok=True)
    ready=root/'ready.txt'
    if ready.exists() and (root/'onnxruntime'/'__init__.py').exists():return root
    if (root/'onnxruntime'/'__init__.py').exists():
        # An interrupted first install may have created only some packages.
        env=os.environ.copy();env['PYTHONPATH']=str(root)
        probe=_process([_python(),'-c',f'import sys;sys.path.insert(0,{str(root)!r});import numpy, onnxruntime'],log=root/'prepare.log',cancel=cancel,env=env,
                       progress=progress,stage='检查已下载的抠图组件',timeout=45)
        if not probe:ready.write_text(ORT_VERSION,encoding='ascii');return root
    notify(progress,'首次准备本地抠图组件（仅下载程序，不上传图片）')
    code=_process([_python(),'-m','pip','install','--disable-pip-version-check','--no-warn-script-location',
                   '--timeout','15','--retries','1','--only-binary=:all:','--upgrade','--target',str(root),f'onnxruntime=={ORT_VERSION}','numpy==2.3.5'],
                  log=root/'install.log',cancel=cancel,progress=progress,stage='首次准备本地抠图组件，下载和安装中',timeout=240)
    if code:raise RuntimeError('抠图组件准备失败，请检查网络后点“抠主体”重试；安装日志已保留')
    ready.write_text(ORT_VERSION,encoding='ascii')
    return root


def model_error(exc):
    if isinstance(exc,urllib.error.HTTPError):
        return f'模型下载站返回 HTTP {exc.code}；可稍后重试，或在“模型文件”导入对应 ONNX 文件'
    if isinstance(exc,(urllib.error.URLError,TimeoutError,socket.timeout)):
        return '本地尚无所选模型，连接模型下载站（GitHub）失败或超时；请在“模型文件”导入对应 ONNX 文件，或安装配套模型包'
    if isinstance(exc,PermissionError):return '模型目录不可写或文件被占用；请检查保存目录权限后重试'
    if isinstance(exc,OSError) and (exc.errno==errno.ENOSPC or getattr(exc,'winerror',None)==112):
        return '模型保存磁盘空间不足；请释放空间后重试'
    return '模型文件读写失败；请检查保存目录后重试'


def bundled_models():
    return Path(__file__).resolve().parents[2]/'runtime'/'cutout-models'

def model_url(name):
    return 'https://github.com/danielgatis/rembg/releases/download/v0.0.0/'+MODELS[name]['file']

def model_present(name):
    from .release_components import resolve
    extra=resolve('anime' if name=='isnet-anime' else 'fine',f'runtime/cutout-models/{name}.onnx') if name!=MODEL else None
    return bool(extra and extra.is_file()) or any((folder/f'{name}.onnx').is_file() for folder in (cache_root()/'models',bundled_models()))


def import_model(source,root=None,*,name=MODEL,cancel=None,progress=None):
    """Copy a verified offline model atomically; never move the user's file."""
    root=Path(root) if root is not None else cache_root()/'models'
    if Path(source).suffix.lower()=='.zip':
        check_cancel(cancel);root.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(source) as archive:
            candidates=[i for i in archive.infolist() if not i.is_dir() and Path(i.filename).name in (f'{name}.onnx',MODELS[name]['file'])]
            if len(candidates)!=1 or not 0<candidates[0].file_size<=300*1024*1024:
                raise ValueError('模型包中没有唯一对应的模型，请选择与当前选项一致的配套模型包')
            # Copy one named member only; never extract paths or run archive code.
            with tempfile.TemporaryDirectory(dir=root,prefix='import-') as directory:
                extracted=Path(directory)/f'{name}.onnx'
                with archive.open(candidates[0]) as src,extracted.open('wb') as dst:
                    while block:=src.read(1024*1024):check_cancel(cancel);dst.write(block)
                return import_model(extracted,root,name=name,cancel=cancel,progress=progress)
    part=None
    try:
        check_cancel(cancel);root.mkdir(parents=True,exist_ok=True)
        spec=MODELS[name];model=root/f'{name}.onnx'
        notify(progress,'校验离线模型')
        if model_digest(source)!=spec['md5']:raise RuntimeError('模型文件与所选模型不符或已损坏；请选择对应的原始 ONNX 文件')
        check_cancel(cancel)
        if Path(source).resolve()==model.resolve():return model
        with tempfile.NamedTemporaryFile(dir=root,suffix='.download',delete=False) as output,Path(source).open('rb') as input:
            part=Path(output.name);total=Path(source).stat().st_size;done=0
            while block:=input.read(1024*1024):
                check_cancel(cancel);output.write(block);done+=len(block);notify(progress,'导入离线模型',done,total)
        if model_digest(part)!=spec['md5']:raise RuntimeError('模型文件复制校验失败；原文件保留，请重试')
        check_cancel(cancel);_publish(part,model);return model
    except InterruptedError:raise
    except OSError as exc:raise RuntimeError(model_error(exc)) from exc
    finally:
        if part is not None:part.unlink(missing_ok=True)


def ensure_model(root, cancel=None, progress=None, name=MODEL):
    spec=MODELS[name];root=Path(root);model=root/f'{name}.onnx';part=None
    try:
        check_cancel(cancel);root.mkdir(parents=True,exist_ok=True)
        if model.exists() and model_digest(model)==spec['md5']:return model
        offline=bundled_models()/f'{name}.onnx'
        from .release_components import resolve,require,catalog
        if name!=MODEL and not offline.is_file():
            component='anime' if name=='isnet-anime' else 'fine'
            offline=resolve(component,f'runtime/cutout-models/{name}.onnx') or offline
        if offline.is_file():
            if model_digest(offline)!=spec['md5']:raise RuntimeError('随包模型校验失败，请重新解压完整包或导入完整模型文件')
            check_cancel(cancel)
            return offline
        if catalog():
            if name!=MODEL:require(component)
            raise RuntimeError('默认抠图模型缺失，请重新完整解压轻量版或完整版；无需另外下载模型')
        notify(progress,'首次下载 '+spec['label']+' 模型；仅下载到本机')
        request=urllib.request.Request('https://github.com/danielgatis/rembg/releases/download/v0.0.0/'+spec['file'],headers={'User-Agent':'EmojiBridge-local-cutout'})
        for attempt in range(2):
            check_cancel(cancel)
            try:
                with urllib.request.urlopen(request,timeout=8) as response,tempfile.NamedTemporaryFile(dir=root,suffix='.download',delete=False) as output:
                    part=Path(output.name);total=int(response.headers.get('Content-Length',0));done=0;started=time.monotonic()
                    while True:
                        check_cancel(cancel)
                        if time.monotonic()-started>600:raise TimeoutError('download_timeout')
                        block=response.read(256*1024)
                        if not block:break
                        output.write(block);done+=len(block);notify(progress,'下载主体模型',done,total)
                break
            except (urllib.error.URLError,TimeoutError) as exc:
                if part is not None:part.unlink(missing_ok=True);part=None
                if attempt or (isinstance(exc,urllib.error.HTTPError) and exc.code not in (408,429,500,502,503,504)):raise
                notify(progress,'连接中断，正在重试模型下载（1/1）')
        if model_digest(part)!=spec['md5']:raise RuntimeError('模型下载不完整，请重试')
        check_cancel(cancel)
        _publish(part,model);return model
    except InterruptedError:raise
    except RuntimeError:raise
    except OSError as exc:raise RuntimeError(model_error(exc)) from exc
    finally:
        if part is not None:part.unlink(missing_ok=True)


def remove_background(image, *, root=None, cancel=None, progress=None, model_name=MODEL):
    """Return original, independent mask and composed RGBA; model never edits input."""
    from PIL import Image
    started=time.perf_counter();check_cancel(cancel)
    rgba=image.convert('RGBA');root=Path(root or cache_root());root.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(b'mask-v2'+str(rgba.size).encode()+rgba.tobytes()+MODELS[model_name]['md5'].encode()).hexdigest()
    results=root/'results';results.mkdir(exist_ok=True);output=results/(digest+'.png')
    mask_path=output.with_suffix('.mask.png')
    if output.exists() and mask_path.exists():
        with Image.open(output) as cached:
            cached.load()
            if cached.size==rgba.size:
                notify(progress,'已复用本张图片的透明结果',1,1)
                with Image.open(mask_path) as mask:mask_value=mask.convert('L')
                return {'image':cached.convert('RGBA'),'original':rgba,'mask':mask_value,'model':model_name,'cache_hit':True,'seconds':time.perf_counter()-started,'source_pixels_sha256':digest}
    runtime=ensure_runtime(cancel,progress);model=ensure_model(root/'models',cancel,progress,name=model_name)
    check_cancel(cancel)
    with tempfile.TemporaryDirectory(prefix='cutout-',dir=root) as directory:
        directory=Path(directory);source=directory/'source.png';result=directory/'result.png';metrics=directory/'metrics.json';events=directory/'progress.json'
        rgba.save(source,'PNG');env=os.environ.copy();env['PYTHONPATH']=str(runtime)
        notify(progress,'载入本地主体模型')
        # The worker never receives network credentials or a remote image endpoint.
        command=[_python(),'-X','utf8',str(Path(__file__).resolve()),'--worker',str(model),str(source),str(result),str(metrics),str(events)]
        last=''
        def updates(stage,done,total):
            nonlocal last
            try:
                message=json.loads(events.read_text(encoding='utf-8'))
                current=message['stage']
                if current!=last:notify(progress,current,message.get('done',0),message.get('total',0));last=current
            except (OSError,ValueError):pass
        code=_process(command,log=root/'last-worker.log',cancel=cancel,env=env,progress=updates)
        if code:raise RuntimeError('本地抠图未完成，请点“抠主体”重试；原图未修改')
        check_cancel(cancel)
        with Image.open(result) as processed:
            processed.load()
            if processed.size!=rgba.size or processed.mode!='RGBA':raise RuntimeError('抠图结果不完整，未替换原图')
            value=processed.copy()
        _publish(result,output)
        with Image.open(result.with_suffix('.mask.png')) as mask:mask_value=mask.convert('L')
        _publish(result.with_suffix('.mask.png'),mask_path)
        info=json.loads(metrics.read_text(encoding='utf-8'))
    notify(progress,'主体提取完成',1,1)
    return dict(image=value,original=rgba,mask=mask_value,model=model_name,cache_hit=False,seconds=time.perf_counter()-started,source_pixels_sha256=digest,**info)


def _session(model):
    import onnxruntime as ort
    # S0102 fixed-frame trial: 8 threads helped on the 32-logical-core host;
    # cap at half available CPUs, leaving capacity for the desktop/decoder.
    options=ort.SessionOptions();options.intra_op_num_threads=max(1,min(8,(os.cpu_count() or 4)//2));options.inter_op_num_threads=1
    session=ort.InferenceSession(str(model),sess_options=options,providers=['CPUExecutionProvider']);session._eb_model=Path(model).stem;return session


def _predict_mask(session, image, timings=None):
    import numpy as np
    from PIL import Image,ImageChops
    # Adapted from rembg BaseSession.normalize / U2netSession.predict (MIT).
    started=time.perf_counter()
    spec=MODELS[getattr(session,'_eb_model',MODEL)]
    rgb=image.convert('RGB').resize((spec['edge'],spec['edge']),Image.Resampling.LANCZOS)
    pixels=np.asarray(rgb,dtype=np.float32);pixels/=max(float(pixels.max()),1e-6)
    pixels=(pixels-np.asarray((.485,.456,.406),dtype=np.float32))/np.asarray(spec['std'],dtype=np.float32)
    tensor=np.expand_dims(pixels.transpose(2,0,1),0).astype(np.float32)
    prepared=time.perf_counter()
    prediction=session.run(None,{session.get_inputs()[0].name:tensor})[0][0,0]
    if spec.get('sigmoid'):prediction=1/(1+np.exp(-np.clip(prediction,-80,80)))
    inferred=time.perf_counter()
    low=float(prediction.min());high=float(prediction.max())
    if high-low<1e-8:raise ValueError('model returned an empty foreground mask')
    mask=Image.fromarray(((prediction-low)/(high-low)*255).astype('uint8')).resize(image.size,Image.Resampling.LANCZOS)
    if timings is not None:
        for key,seconds in [('preprocess',prepared-started),('inference',inferred-prepared),('mask',time.perf_counter()-inferred)]:
            timings[key]=timings.get(key,0)+seconds
    return mask


def _predict(session,image,timings=None):
    from PIL import ImageChops
    value=image.copy();value.putalpha(ImageChops.multiply(image.getchannel('A'),_predict_mask(session,image,timings)));return value


def _worker(model, source, output, metrics, events):
    """One session per request; sequence requests share it across every frame."""
    from PIL import Image,ImageChops
    def report(stage,done,total):
        Path(events).write_text(json.dumps(dict(stage=stage,done=done,total=total)),encoding='utf-8')
    started=time.perf_counter();report('载入本地模型',0,0)
    session=_session(model);timings={'load':time.perf_counter()-started};io=0
    if Path(source).is_dir():
        files=sorted(Path(source).glob('*.png'));Path(output).mkdir(exist_ok=True)
        masks=Path(output)/'masks';masks.mkdir();originals=Path(output)/'originals';originals.mkdir()
        for index,file in enumerate(files):
            before=time.perf_counter()
            with Image.open(file) as opened:image=opened.convert('RGBA')
            io+=time.perf_counter()-before
            mask=_predict_mask(session,image,timings);mask.save(masks/file.name,'PNG');shutil.copyfile(file,originals/file.name)
            image.putalpha(ImageChops.multiply(image.getchannel('A'),mask))
            before=time.perf_counter();image.save(Path(output)/file.name,'PNG');io+=time.perf_counter()-before
            report('逐帧抠主体',index+1,len(files))
    else:
        with Image.open(source) as opened:image=opened.convert('RGBA')
        report('识别图片主体',1,2)
        mask=_predict_mask(session,image,timings);mask.save(Path(output).with_suffix('.mask.png'),'PNG')
        image.putalpha(ImageChops.multiply(image.getchannel('A'),mask));image.save(output,'PNG')
    timings['frame_io']=io
    Path(metrics).write_text(json.dumps(dict(inference_seconds=time.perf_counter()-started,stages=timings,provider=session.get_providers()[0],dimensions=list(image.size))),encoding='utf-8')
    report('主体推理完成，正在校验并整理帧',1,1)


if __name__=='__main__':
    if len(sys.argv)!=7 or sys.argv[1]!='--worker':raise SystemExit('internal cutout worker')
    # Bundled CPython deliberately ignores PYTHONPATH. Add only our explicit
    # isolated inference runtime, keeping the normal desktop import path intact.
    sys.path.insert(0,str(runtime_root()))
    _worker(*sys.argv[2:])
