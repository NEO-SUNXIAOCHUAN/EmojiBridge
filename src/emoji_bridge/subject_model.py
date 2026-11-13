"""Optional SAM2 CPU capability; basic mask editing has no model dependency."""
from pathlib import Path
import hashlib,json,os,shutil
from .capabilities import root,download,APP
from .background_remove import _python,_process,check_cancel

MODEL_SHA='7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69'
MODEL_URL='https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt'
def folder():return root()/'subject-sam2'
def ready():
    path=folder()/'ready.json'
    if not path.exists():return False
    try:
        data=json.loads(path.read_text('utf8'))
        return (folder()/'sam2.1_hiera_tiny.pt').is_file() and all(Path(p).is_dir() for p in data['paths'])
    except (OSError,ValueError,KeyError):return False

def prepare(cancel=None,progress=None):
    target=folder();target.mkdir(parents=True,exist_ok=True)
    if ready():return target
    # Reuse this project's already prepared optional CPU runtime when present.
    reuse=[root()/'sam2-deps',root()/'depthflow/Lib/site-packages']
    paths=reuse if (reuse[0]/'hydra').is_dir() and (reuse[1]/'torch').is_dir() else [target/'packages']
    if paths!=reuse:
        command=[_python(),'-m','pip','install','--target',str(paths[0]),'torch==2.15.0','torchvision==0.29.2','hydra-core==1.3.2','iopath==0.1.10','numpy==2.2.6','Pillow==11.3.0','tqdm==4.70.1']
        code=_process(command,log=target/'install.log',cancel=cancel,progress=progress,stage='准备可选 SAM2 组件（首次下载较大）')
        if code:raise RuntimeError('SAM2 组件准备失败，可重试；套索和画笔仍可使用')
    source=APP/'third_party/sam2';code=_process([_python(),'-c',f"import sys;sys.path[:0]={[str(source),*[str(p) for p in paths]]!r};import torch,torchvision;from sam2.build_sam import build_sam2;print(torch.__version__)"],log=target/'probe.log',cancel=cancel,progress=progress,stage='检查 SAM2 本地组件')
    if code:raise RuntimeError('SAM2 本地组件检查失败；见组件目录 probe.log')
    model=target/'sam2.1_hiera_tiny.pt';existing=root()/'sam2-trial/checkpoints'/model.name
    if not model.exists():
        if existing.exists():shutil.copyfile(existing,model)
        else:download(MODEL_URL,model,cancel,progress)
    check_cancel(cancel)
    with model.open('rb') as stream:valid=hashlib.file_digest(stream,'sha256').hexdigest()==MODEL_SHA
    if not valid:
        model.replace(model.with_suffix('.invalid'))
        raise ValueError('SAM2 模型校验不符，已隔离损坏文件；再次准备会重新下载')
    (target/'ready.json').write_text(json.dumps({'paths':[str(p) for p in paths],'model_sha256':MODEL_SHA,'device':'cpu'}),'utf8')
    return target

def execute(request,workdir,cancel=None,progress=None):
    if not ready():raise ValueError('请先准备可选 SAM2 组件；基础套索不需要模型')
    workdir=Path(workdir);request['model_root']=str(folder());file=workdir/'sam-request.json';file.write_text(json.dumps(request,ensure_ascii=False),'utf8')
    code=_process([_python(),'-X','utf8',str(APP/'scripts/subject_sam_worker.py'),str(file)],log=workdir/'worker.log',cancel=cancel,progress=progress,stage='SAM2 主体修正')
    if code:
        lines=(workdir/'worker.log').read_text('utf8',errors='replace').splitlines()
        raise RuntimeError(next((s for s in reversed(lines) if s.strip()),'SAM2 未完成'))
