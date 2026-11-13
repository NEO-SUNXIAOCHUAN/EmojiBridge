"""Task-local timings without filenames, URLs, account IDs or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Lock
import time

_active=ContextVar('stage_timings',default=None)


@contextmanager
def session(path):
    state={'lock':Lock(),'events':[]};token=_active.set(state);start=time.perf_counter()
    try:yield
    finally:
        from .state import save_json
        with state['lock']:events=list(state['events'])
        totals={}
        for e in events:
            t=totals.setdefault(e['stage'],{'calls':0,'seconds':0,'errors':0})
            t['calls']+=1;t['seconds']+=e['seconds'];t['errors']+=not e['ok']
        for t in totals.values():t['seconds']=round(t['seconds'],4)
        _active.reset(token)
        save_json(path,{'wall_seconds':round(time.perf_counter()-start,4),
            'stages':totals,'events':events,'nested_and_parallel_times_not_additive':True})


@contextmanager
def stage(name):
    state=_active.get();start=time.perf_counter();ok=False
    try:yield;ok=True
    finally:
        if state is not None:
            with state['lock']:state['events'].append({'stage':name,'seconds':round(time.perf_counter()-start,4),'ok':ok})


def measured(name):
    def decorate(fn):
        @wraps(fn)
        def call(*args,**kwargs):
            with stage(name):return fn(*args,**kwargs)
        return call
    return decorate


def recorded(fn):
    """Persist each queue run separately, including cancellation/failure."""
    @wraps(fn)
    def call(path,*args,**kwargs):
        from pathlib import Path
        output=Path(path).with_name(Path(path).stem+f'-timing-{time.time_ns()}.json')
        with session(output),stage('transfer_total'):return fn(path,*args,**kwargs)
    return call
