"""Durable local journal. A submitted attempt is never automatically re-submitted."""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
import hashlib
import json
import os
import time
import threading
import uuid
from pathlib import Path


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(1024*1024):digest.update(chunk)
    return digest.hexdigest()


def save_json(path, value, *, compact=False):
    path=Path(path).resolve()
    library=next((p for p in path.parents if (p/'materials.db').is_file()),None)
    if library:
        from .library_gate import hold
        with hold(library):return _save_json(path,value,compact=compact)
    return _save_json(path,value,compact=compact)


def _save_json(path, value, *, compact=False):
    path = Path(path).resolve()
    # The unique staging suffix can cross MAX_PATH even when the final record
    # is readable. Use extended paths for this atomic I/O only; stored paths
    # and caller-facing identities remain ordinary absolute paths.
    if os.name == 'nt' and not str(path).startswith('\\\\?\\'):
        text=str(path)
        path=Path('\\\\?\\UNC\\'+text[2:] if text.startswith('\\\\') else '\\\\?\\'+text)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Concurrent saves must never share or replace another writer's staging
    # file. Keep it on the destination volume for atomic replacement.
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    # Windows readers (including our GUI) may briefly hold a handle without
    # FILE_SHARE_DELETE. Preserve the old complete record until an atomic
    # replacement succeeds; do not truncate it or abandon preparation after
    # a single sharing violation. A permanent denial still fails boundedly.
    try:
        with temp.open('x',encoding='utf-8') as f:
            if compact:f.write(json.dumps(value,ensure_ascii=False,separators=(',',':')))
            else:json.dump(value,f,ensure_ascii=False,indent=2)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(10):
            try:
                temp.replace(path)
                break
            except PermissionError:
                if attempt==9:raise
                time.sleep(.01*(attempt+1))
    finally:
        temp.unlink(missing_ok=True)


class ResourceBusy(RuntimeError):
    def __init__(self,path,owner):
        super().__init__('another_client_run_is_active')
        self.path=Path(path);self.owner=owner


class WaitingCancelled(InterruptedError):
    """Cancelled before ownership; the caller must not rewrite another journal."""


_operation=ContextVar('client_operation',default=None)


@contextmanager
def task_scope(task_id,kind,*,cancel=None,on_wait=None):
    """Annotate the existing locks and allow cancellable waiting at their boundary."""
    value={'task_id':str(task_id),'kind':kind,'stage':kind,'started_at':time.time(),
           'last_progress_at':time.time(),'cancel':cancel,'on_wait':on_wait,'held':{}}
    token=_operation.set(value)
    try:yield value
    finally:_operation.reset(token)


def owner_path(path):
    path=Path(path)
    # Keep diagnostics out of task/catalog *.json discovery.
    return path.parent/'.resource-owners'/(path.name+'.json')


def resource_owner(path):
    try:return json.loads(owner_path(path).read_text('utf-8'))
    except (OSError,ValueError):return {}


def task_progress(stage):
    operation=_operation.get()
    if not operation:return
    now=time.time();changed=stage!=operation['stage'];operation.update(stage=str(stage),last_progress_at=now)
    for held in operation['held'].values():
        if changed or now-held.get('written',0)>=.5:
            held['value'].update(stage=str(stage),last_progress_at=now,
                                 cancel_requested=bool(operation['cancel'] and operation['cancel']()))
            save_json(held['metadata'],held['value']);held['written']=now


def waiting_text(owner):
    kind=owner.get('kind') or '另一项客户端操作'
    return f'正在执行{kind}，本任务已排队；当前步骤结束后继续，可取消等待。'


@contextmanager
def single_instance(path):
    path=Path(path).resolve()
    if path.name=='client-ui.lock':
        # Foreground input is one desktop resource even across data directories.
        # Keep the per-profile lock as well for older running executors.
        shared=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'EmojiBridgePilot/foreground.lock'
        with _resource_lock(shared),_resource_lock(path):yield
    else:
        with _resource_lock(path):yield


@contextmanager
def _resource_lock(path):
    import msvcrt
    path = Path(path).resolve()
    operation=_operation.get();key=str(path).casefold();thread=threading.get_ident()
    # Reuse ownership only in the same explicit operation and execution thread.
    # Outside that context, nested/parallel callers still cannot enter.
    held=operation['held'].get(key) if operation else None
    if held and held['thread']==thread:
        yield
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as f:
        if f.tell()==0:
            f.write(b'0');f.flush()
        f.seek(0)
        waiting=False;last_notice=0
        while True:
            if operation and operation['cancel'] and operation['cancel']():raise WaitingCancelled('已取消资源等待；未取得占用，不改写正在执行任务的结果。')
            try:
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1);break
            except OSError as exc:
                owner=resource_owner(path)
                if not operation or not operation['on_wait']:raise ResourceBusy(path,owner) from exc
                waiting=True
                if time.monotonic()-last_notice>=.5:
                    operation['on_wait'](dict(owner,resource=path.name));last_notice=time.monotonic()
                time.sleep(.05)
        metadata=owner_path(path);token=uuid.uuid4().hex
        value={k:operation[k] for k in ('task_id','kind','stage','started_at','last_progress_at')} if operation else {}
        value.update(token=token,pid=os.getpid(),thread=thread,state='running',cancel_requested=False,
                     acquired_at=time.time(),resource=path.name)
        try:
            save_json(metadata,value)
            if operation:operation['held'][key]={'thread':thread,'value':value,'metadata':metadata,'written':time.time()}
            if waiting:operation['on_wait'](None)
            # Hide our topmost visual windows before any client input/screenshot.
            # Only the global foreground lease owns this; nested profile locks
            # and nested calls within one task do not independently restore it.
            from .overlay_guard import hidden_overlays
            with hidden_overlays(token) if path.name=='foreground.lock' else nullcontext():
                yield
        finally:
            # The OS lock is the authority. No file deletion/timeout-based force
            # release; a dead process automatically loses its byte-range lock.
            if operation:operation['held'].pop(key,None)
            try:
                if resource_owner(path).get('token')==token:
                    value.update(state='released',released_at=time.time());save_json(metadata,value)
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)


def validate_sample(file, manifest_path):
    file = Path(file)
    if not file.is_absolute() or not file.is_file():
        raise ValueError('absolute_existing_file_required')
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if Path(manifest['sample']).resolve()!=file.resolve() or sha(file)!=manifest['sha256']:
        raise ValueError('sample_manifest_mismatch')
    extension={'PNG':'.png','GIF':'.gif'}.get(manifest.get('format','PNG'))
    if not extension or file.name != 'T003-'+manifest['nonce']+extension or len(manifest['nonce'])!=16:
        raise ValueError('fresh_test_card_required')
    return manifest


def may_submit(prior):
    # Conservative at-most-once policy, including a crash immediately before submission.
    return prior is None or prior.get('status')=='not_submitted'
