"""Cross-process, reentrant boundary for persistent saves and local backups."""
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import os,threading,time

_guard=threading.Lock();_locks={};_local=threading.local()

@contextmanager
def hold(root,cancel=None):
    root=Path(root).resolve();key=str(root).casefold()
    held=getattr(_local,'held',set())
    if key in held:
        yield;return
    with _guard:lock=_locks.setdefault(key,threading.RLock())
    with lock:
        root.mkdir(parents=True,exist_ok=True)
        with (root/'.persistent-write.lock').open('a+b') as file:
            if file.tell()==0:file.write(b'0');file.flush()
            while True:
                if cancel and cancel.is_set():raise InterruptedError('已取消等待素材保存')
                try:
                    file.seek(0)
                    if os.name=='nt':
                        import msvcrt
                        msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except (BlockingIOError,OSError):time.sleep(.05)
            _local.held=held|{key}
            try:yield
            finally:
                _local.held=held;file.seek(0)
                if os.name=='nt':msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(file,fcntl.LOCK_UN)

def store_write(function):
    @wraps(function)
    def wrapped(store,*args,**kwargs):
        with hold(store.root,kwargs.get('cancel')):return function(store,*args,**kwargs)
    return wrapped
