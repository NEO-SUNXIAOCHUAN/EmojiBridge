"""One bounded heavy-work queue shared by this desktop instance and its children.

Admission estimates are not media size/quality limits. Nested pipeline calls reuse
their lease; UI/thumbnail work never waits on this queue on the message thread.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import os, sqlite3, tempfile, threading, time, uuid

_lease=ContextVar('heavy_work_lease',default=None)
_init_lock=threading.Lock()

@contextmanager
def database(path):
    db=sqlite3.connect(path,timeout=2)
    try:
        with db:yield db
    finally:db.close()

def initialize():
    with _init_lock:
        if not os.environ.get('EMOJI_BRIDGE_TASK_QUEUE'):
            root=Path(tempfile.gettempdir())/'EmojiBridge-tasks'/uuid.uuid4().hex
            root.mkdir(parents=True)
            os.environ['EMOJI_BRIDGE_TASK_QUEUE']=str(root/'queue.sqlite3')
        path=os.environ['EMOJI_BRIDGE_TASK_QUEUE']
        with database(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, pid INTEGER, label TEXT, priority INTEGER, created REAL, running INTEGER, memory INTEGER)')
        return path

def _alive(pid):
    if os.name=='nt':
        import ctypes
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];k.OpenProcess.restype=ctypes.c_void_p
        k.CloseHandle.argtypes=[ctypes.c_void_p]
        k.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        handle=k.OpenProcess(0x1000,False,pid)
        if handle:
            try:
                status=ctypes.c_ulong()
                return not k.GetExitCodeProcess(handle,ctypes.byref(status)) or status.value==259
            finally:k.CloseHandle(handle)
        return ctypes.get_last_error()==5
    try:os.kill(pid,0);return True
    except OSError:return False

def memory_budget():
    if os.name!='nt':return 8192
    import ctypes
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(n,ctypes.c_ulonglong) for n in ('total','available','page','freepage','virtual','freevirtual','extended')]
    value=Memory();value.length=ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):return 8192
    return max(512,int(value.total/1048576*.70))

def child_environment(env=None):
    value=dict(os.environ if env is None else env)
    token=_lease.get()
    if token:value['EMOJI_BRIDGE_HEAVY_LEASE']=token
    return value

def foreground_waiting():
    with database(initialize()) as db:
        return bool(db.execute('SELECT 1 FROM jobs WHERE running=0 AND priority<=0 LIMIT 1').fetchone())

@contextmanager
def admission(label, *, cancel=None, memory=1024, priority=0, waiting=None):
    def check():
        if cancel is not None and cancel.is_set():raise InterruptedError('已取消排队，未开始后续处理')
    check();path=initialize(); inherited=_lease.get() or os.environ.get('EMOJI_BRIDGE_HEAVY_LEASE')
    if inherited:
        with database(path) as db:
            owner=db.execute('SELECT pid,memory FROM jobs WHERE id=? AND running=1',(inherited,)).fetchone()
            if owner and memory>owner[1]:
                if memory>memory_budget():raise RuntimeError('该模型预计内存超过本机任务预算；请换较轻模型，原件与标记保留')
                db.execute('UPDATE jobs SET memory=? WHERE id=?',(memory,inherited))
        if owner and _alive(owner[0]):
            marker=_lease.set(inherited)
            try:yield
            finally:_lease.reset(marker)
            return
    if memory>memory_budget():raise RuntimeError('本次处理预计内存超过本机任务预算；请选择较轻模型或较小处理尺寸，原件保留')
    token=uuid.uuid4().hex;added=False;marker=None;notice=False
    try:
        while True:
            check()
            with database(path) as db:
                db.execute('BEGIN IMMEDIATE')
                for (pid,) in db.execute('SELECT DISTINCT pid FROM jobs').fetchall():
                    if not _alive(pid):db.execute('DELETE FROM jobs WHERE pid=?',(pid,))
                if not added:
                    if db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]>=8:raise RuntimeError('处理队列已满（最多8项），请等当前任务结束或取消后重试')
                    db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,0,?)',(token,os.getpid(),label,priority,time.monotonic(),memory));added=True
                first=db.execute('SELECT id FROM jobs WHERE running=0 ORDER BY priority,created,id LIMIT 1').fetchone()
                if not db.execute('SELECT 1 FROM jobs WHERE running=1 LIMIT 1').fetchone() and first and first[0]==token:
                    db.execute('UPDATE jobs SET running=1 WHERE id=?',(token,));ready=True
                else:ready=False
            if ready:break
            if waiting and not notice:waiting('正在排队，等待当前重处理结束');notice=True
            if cancel is not None:cancel.wait(.05)
            else:time.sleep(.05)
        check();marker=_lease.set(token);yield
    finally:
        if marker is not None:_lease.reset(marker)
        if added:
            with database(path) as db:db.execute('DELETE FROM jobs WHERE id=? AND pid=?',(token,os.getpid()))

def heavy(label, memory=1024):
    def decorate(fn):
        @wraps(fn)
        def call(*args,**kwargs):
            with admission(label,cancel=kwargs.get('cancel'),memory=memory):return fn(*args,**kwargs)
        return call
    return decorate
