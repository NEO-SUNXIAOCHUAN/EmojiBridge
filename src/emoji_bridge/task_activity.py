"""Presentation facts for a user-requested job; never a task scheduler."""
import time
import uuid
from concurrent.futures import CancelledError

def begin(text):
    return {'id':uuid.uuid4().hex,'text':text,'active':True,'state':'running','started':time.monotonic()}

def finish(activity,error=None,cancel=None):
    activity.update(active=False,state='cancelled' if (cancel is not None and cancel.is_set()) or isinstance(error,(CancelledError,InterruptedError)) else 'error' if error else 'success',elapsed=time.monotonic()-activity['started'])

def snapshot(activity):
    result=dict(activity or {})
    if result.get('started'):
        age=time.monotonic()-result['started']
        if result.get('active'):result['elapsed']=round(age,1)
        else:result['end_age']=min(3,round(age-result.get('elapsed',0),1))
    return result
