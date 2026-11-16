"""Standalone stdlib updater, launched explicitly outside the desktop Job.

No switch on crash/timeout: the parent's saved-ready token is mandatory.
Old program files remain available until the new host acknowledges its version.
"""
from pathlib import Path
import ctypes,json,os,shutil,subprocess,sys,time,uuid

def save(path,value):
    path=Path(path);temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False),'utf8');os.replace(temp,path)

def read(path):
    try:return json.loads(Path(path).read_text('utf8'))
    except (OSError,ValueError):return {}

def wait_process(pid):
    if os.name=='nt':
        from ctypes import wintypes as w
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
        k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD]
        k.CloseHandle.argtypes=[w.HANDLE]
        handle=k.OpenProcess(0x100000,False,pid)
        return (lambda: not handle or k.WaitForSingleObject(handle,0)==0), (lambda:k.CloseHandle(handle) if handle else None)
    def gone():
        try:os.kill(pid,0);return False
        except ProcessLookupError:return True
    return gone,lambda:None

def move(source,target):
    for attempt in range(60):
        try:os.replace(source,target);return
        except PermissionError:
            if attempt==59:raise
            time.sleep(.1)

def launch(app,plan,ack=True):
    command=[str(app/'runtime/python.exe'),'-X','utf8',str(app/'scripts/desktop_modern.py'),
             '--data-dir',str(Path(plan['library']).parent)]
    if ack:command+=['--update-session',str(Path(plan['session'])/'plan.json')]
    return subprocess.Popen(command,cwd=app,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

def preserve_library(source,target,app,library):
    if library.is_relative_to(app):
        relative=library.relative_to(app)
        if not relative.parts:raise ValueError('素材目录不能等于程序目录')
        old=source/relative
        if old.is_dir():shutil.copytree(old,target/relative,dirs_exist_ok=True)

def run(plan_path):
    plan=read(plan_path);session=Path(plan['session']).resolve();app=Path(plan['app']).resolve()
    if Path(plan_path).resolve()!=session/'plan.json' or session.is_relative_to(app):raise ValueError('更新暂存目录无效')
    token=plan['token'];state=session/'state.json';previous=session/'previous';staged=session/'staged'
    library=Path(plan['library']).resolve();gone,close=wait_process(plan['parent'])
    save(session/'listening.json',{'token':token,'pid':os.getpid()})
    try:
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            if read(session/'abort.json').get('token')==token:return
            ready=read(session/'saved-ready.json').get('token')==token
            if gone():
                if not ready:save(state,{'state':'cancelled','text':'原程序未确认保存完成，未更新'});return
                break
            time.sleep(.1)
        else:save(state,{'state':'cancelled','text':'等待保存退出超时，未更新'});return
    finally:close()
    switched=False;new=None
    try:
        if plan['mode']=='update':
            actual=read(staged/'BUILD.json')
            if actual.get('build')!=plan['build'] or actual.get('source_commit')!=plan['source_commit']:raise ValueError('暂存程序身份不符')
            preserve_library(app,staged,app,library)
            move(app,previous)
            try:move(staged,app)
            except Exception:move(previous,app);raise
            switched=True
        save(state,{'state':'starting','text':'新程序启动确认中'})
        new=launch(app,plan)
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            ack=read(session/'started.json')
            if ack.get('token')==token and ack.get('pid')==new.pid and ack.get('build')==plan['build'] and ack.get('source_commit')==plan['source_commit'] and ack.get('library')==str(library) and ack.get('services_ready'):
                save(state,{'state':'complete','text':'新版启动与素材库已确认；旧程序保留在更新目录'});return
            if new.poll() is not None:break
            time.sleep(.2)
        raise RuntimeError('新版未确认启动完成')
    except Exception as exc:
        if new and new.poll() is None:
            new.terminate()
            try:new.wait(10)
            except subprocess.TimeoutExpired:raise RuntimeError('新程序无法结束，请使用更新目录的 previous 恢复；数据未删除') from exc
        if switched:
            # Roll back only code. Preserve any library writes made by the new
            # host, including when --data-dir lives inside the portable app.
            preserve_library(app,previous,app,library)
            move(app,session/'failed-version');move(previous,app)
        save(state,{'state':'rolled_back' if switched else 'failed','text':str(exc),'previous':str(previous)})
        fallback=dict(plan)
        if plan.get('previous_library'):fallback['library']=plan['previous_library']
        launch(app,fallback,ack=False)

if __name__=='__main__':
    try:run(Path(sys.argv[1]))
    except Exception as exc:
        try:save(Path(sys.argv[1]).parent/'state.json',{'state':'failed','text':str(exc)})
        except Exception:pass
        raise
