"""Match candidate emoticon file ownership to the one running Weixin process.

No file contents, memory, chat handles, shutdown or restart operations. Windows
Restart Manager queries run in a short-lived worker with a parent-side deadline.
"""
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import json,subprocess,sys
from . import client_sources as sources,windows as win
from .paths import APP_ROOT

LIMIT=32
SAFE_REASONS={'active_emoticon_file_in_use','active_multiple_candidates','active_no_file_owner',
              'active_process_changed','active_candidate_invalid','active_candidate_limit',
              'active_process_unavailable','active_file_query_failed','wechat_process_not_unique_or_not_running',
              'client_family_unadapted','active_query_timeout','active_no_candidates'}


class UniqueProcess(c.Structure):
    _fields_=[('pid',w.DWORD),('started',w.FILETIME)]


class ProcessInfo(c.Structure):
    _fields_=[('process',UniqueProcess),('app',w.WCHAR*256),('service',w.WCHAR*64),
              ('kind',c.c_int),('status',w.ULONG),('session',w.DWORD),('restartable',w.BOOL)]


def started_value(value):return (value.dwHighDateTime<<32)|value.dwLowDateTime


def process_started(pid):
    handle=win.kernel.OpenProcess(0x1000,False,pid)
    if not handle:raise ValueError('active_process_unavailable')
    try:
        fn=win.api(win.kernel,'GetProcessTimes',[w.HANDLE,*([c.POINTER(w.FILETIME)]*4)],w.BOOL)
        times=[w.FILETIME() for _ in range(4)]
        if not fn(handle,*(c.byref(t) for t in times)):raise ValueError('active_process_unavailable')
        return started_value(times[0])
    finally:win.kernel.CloseHandle(handle)


def identity():
    pid,exe=sources.running_wechat()
    version=win.file_version(exe);sources.require_version('wechat',version)
    return (pid,process_started(pid),str(exe.resolve()),version)


def file_users(files):
    """Return only PID/start-time identities using the supplied exact files."""
    dll=c.WinDLL('Rstrtmgr',use_last_error=True)
    start=win.api(dll,'RmStartSession',[c.POINTER(w.DWORD),w.DWORD,w.LPWSTR],w.DWORD)
    register=win.api(dll,'RmRegisterResources',[w.DWORD,w.UINT,c.POINTER(w.LPCWSTR),w.UINT,c.POINTER(UniqueProcess),w.UINT,c.POINTER(w.LPCWSTR)],w.DWORD)
    get=win.api(dll,'RmGetList',[w.DWORD,c.POINTER(w.UINT),c.POINTER(w.UINT),c.POINTER(ProcessInfo),c.POINTER(w.DWORD)],w.DWORD)
    end=win.api(dll,'RmEndSession',[w.DWORD],w.DWORD)
    session=w.DWORD();key=c.create_unicode_buffer(33)
    if start(c.byref(session),0,key):raise ValueError('active_file_query_failed')
    try:
        names=(w.LPCWSTR*len(files))(*(str(p) for p in files))
        if register(session,len(files),names,0,None,0,None):raise ValueError('active_file_query_failed')
        needed=w.UINT();count=w.UINT();reason=w.DWORD()
        result=get(session,c.byref(needed),c.byref(count),None,c.byref(reason))
        if result==0:return set()
        for _ in range(2):
            if result!=234 or not 0<needed.value<=1024:raise ValueError('active_file_query_failed')
            count=w.UINT(needed.value);rows=(ProcessInfo*count.value)()
            result=get(session,c.byref(needed),c.byref(count),rows,c.byref(reason))
            if result==0:return {(r.process.pid,started_value(r.process.started)) for r in rows[:count.value]}
        raise ValueError('active_file_query_failed')
    finally:end(session)


def probe(candidates):
    paths=[Path(p).resolve() for p in candidates]
    if not paths or len(paths)>LIMIT or len(set(paths))!=len(paths):
        return {'state':'unverified','reason':'active_candidate_limit'}
    if any(p.name.lower()!='emoticon.db' or p.parent.name.lower()!='emoticon'
           or p.parent.parent.name.lower()!='db_storage' or not p.is_file() for p in paths):
        return {'state':'unverified','reason':'active_candidate_invalid'}
    before=identity();matched=[]
    for i,path in enumerate(paths):
        files=[path]+[p for p in (Path(str(path)+'-wal'),Path(str(path)+'-shm')) if p.is_file()]
        users=file_users(files)
        if before[:2] in users:matched.append(i)
    if identity()!=before:return {'state':'unverified','reason':'active_process_changed'}
    result={'state':'identified' if len(matched)==1 else 'unverified',
            'reason':'active_emoticon_file_in_use' if len(matched)==1 else
                     'active_multiple_candidates' if matched else 'active_no_file_owner',
            'matched_count':len(matched)}
    if len(matched)==1:result.update(index=matched[0],identity=list(before))
    return result


def detect(candidates):
    """Only a validated candidate index leaves the worker; no paths in diagnostics."""
    if not candidates:return {'state':'unverified','reason':'active_no_candidates'}
    if len(candidates)>LIMIT:return {'state':'unverified','reason':'active_candidate_limit'}
    try:
        worker=subprocess.run([sys.executable,'-X','utf8',str(APP_ROOT/'scripts/probe_wechat_active.py')],
            input=json.dumps([str(p) for p in candidates]),capture_output=True,text=True,encoding='utf8',
            timeout=8,creationflags=subprocess.CREATE_NO_WINDOW)
        if worker.returncode:raise ValueError('active_file_query_failed')
        result=json.loads(worker.stdout)
        if result.get('state')=='identified':
            index=result.get('index')
            if type(index) is not int or not 0<=index<len(candidates):raise ValueError('active_candidate_invalid')
            if tuple(result.get('identity',()))!=identity():raise ValueError('active_process_changed')
            return {'state':'identified','reason':'active_emoticon_file_in_use','index':index,'matched_count':1}
        reason=result.get('reason')
        return {'state':'unverified','reason':reason if reason in SAFE_REASONS else 'active_file_query_failed'}
    except subprocess.TimeoutExpired:return {'state':'unverified','reason':'active_query_timeout'}
    except Exception as exc:
        reason=str(exc)
        return {'state':'unverified','reason':reason if reason in ('active_process_changed','active_candidate_invalid') else 'active_file_query_failed'}
