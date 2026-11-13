"""Local access evidence, without changing original files or Windows permissions."""
import json,logging,os,sys,time,traceback,getpass
from logging.handlers import RotatingFileHandler
from pathlib import Path


def access_context(root):
    """Shareable evidence only; never changes ACLs or probes client data."""
    elevated=None
    if os.name=='nt':
        try:
            import ctypes
            elevated=bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (OSError,AttributeError):pass
    return {'elevated':elevated,'diagnostic_version':2}

def record(root,operation,path,exc,*,mode='rb',ident=None):
    try:
        directory=Path(root)/'diagnostics';directory.mkdir(exist_ok=True)
        # One open/write/close keeps diagnostics from retaining a sharing lock.
        handler=RotatingFileHandler(directory/'material-access.log',maxBytes=512*1024,backupCount=2,encoding='utf-8')
        event={**access_context(root),'at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'operation':operation,'mode':mode,'pid':os.getpid(),'ppid':os.getppid(),
               'executable':sys.executable,'user':getpass.getuser(),'root':str(Path(root).resolve()),'material_id':ident,
               'path':str(path),'error':type(exc).__name__,'errno':getattr(exc,'errno',None),
               'winerror':getattr(exc,'winerror',None),'detail':str(exc),
               'traceback':''.join(traceback.format_exception(type(exc),exc,exc.__traceback__))}
        try:handler.emit(logging.LogRecord('material-access',logging.ERROR,'',0,json.dumps(event,ensure_ascii=False),(),None))
        finally:handler.close()
    except OSError:pass  # A read-only data volume must retain the original error.
