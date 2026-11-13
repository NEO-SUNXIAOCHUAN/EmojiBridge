"""First-use readers with isolated working catalogs and one shared writer.

Only the QQ worker operates a client window. WeChat uses its authenticated
index/download path. No sends/additions or transfer queues are started here.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import queue,time
from emoji_bridge import catalog
from emoji_bridge.state import single_instance,save_json
from emoji_bridge.windows import StopAutomation


def prepare_qq(library_path,cancel,changed,observed,index_only=False):
    if not index_only:
        from qq_startup_pipeline import prepare
        return prepare(library_path,cancel,changed,observed)
    from qq_catalog import scan,MAX_SCAN_VIEWS
    library=catalog.read(library_path)
    library['clients']['qq']['initial_index_attempted']=True;catalog.save(library,library_path)
    changed()
    def on_page(path,report):
        observed(dict(complete=False,initial_index_attempted=True,
            scope=f'正在读取 {len(report["pages"])} 个收藏视图；尚未读完',
            source_report=str(path),snapshot_at=report['at'],
            items=[dict(i,scan=str(Path(path).resolve())) for i in report['items']]))
    path,report=scan(MAX_SCAN_VIEWS,cancel,progress=on_page)
    library=catalog.read(library_path);catalog.merge_qq(library,path,cancel=cancel.exists,match_originals=False)
    library['clients']['qq']['initial_index_attempted']=True;catalog.save(library,library_path);changed()
    if not report['items']:raise ValueError(report.get('reason','qq_no_observations'))
    return {'reason':report.get('reason')}


def prepare_wechat(library_path,cancel,changed,observed,index_only=False):
    from wechat_prepare import prepare
    return prepare(library_path,cancel,lambda *args:changed(),preview_first=True,index_only=index_only)


def run(library_path=None,cancel=None,progress=None,index_only=False):
    library_path=Path(library_path) if library_path is not None else catalog.PATH
    library_path=Path(library_path)
    started=time.perf_counter();initial=catalog.read(library_path)
    if any(side['items'] for side in initial['clients'].values()):
        raise ValueError('first_use_empty_library_required')
    folder=library_path.parent/'startup'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    working={};events=queue.Queue();result={};last_publish=0
    # Workers never write the shared library; each sees only its own side.
    for client in ('qq','wechat'):
        working[client]=folder/(client+'.json')
        isolated=deepcopy(initial)
        if client=='qq':isolated['clients']['qq']['initial_index_attempted']=True
        catalog.save(isolated,working[client],compact=True)
    def execute(client,worker):
        try:
            options={'index_only':True} if index_only else {}
            return worker(working[client],cancel,lambda:events.put((client,None)),
                   lambda side:events.put((client,deepcopy(side))),**options)
        finally:events.put((client,None))
    with single_instance(library_path.with_suffix('.startup.lock')),ThreadPoolExecutor(max_workers=2) as pool:
        from contextvars import copy_context
        futures={c:pool.submit(copy_context().run,execute,c,w) for c,w in (('qq',prepare_qq),('wechat',prepare_wechat))}
        finished=set()
        while True:
            updates={}
            try:
                client,side=events.get(timeout=.15);updates[client]=side
                while True:
                    client,side=events.get_nowait();updates[client]=side
            except queue.Empty:pass
            for client,future in futures.items():
                if future.done() and client not in finished:
                    finished.add(client);updates[client]=None
                    try:
                        value=future.result() or {}
                        result[client]={'worker':'finished','reason':value.get('reason')}
                    except Exception as exc:
                        result[client]={'worker':'stopped','reason':str(exc) if isinstance(exc,(ValueError,StopAutomation)) else type(exc).__name__}
            if updates:
                if len(finished)<2:time.sleep(max(0,.25-(time.perf_counter()-last_publish)))
                while True:
                    try:client,side=events.get_nowait();updates[client]=side
                    except queue.Empty:break
                library=catalog.read(library_path)
                for client,side in updates.items():
                    current=side if side is not None else catalog.read(working[client])['clients'][client]
                    failure=result.get(client,{}).get('reason')
                    if failure:
                        # Preserve observed previews after an unexpected failure
                        # before a worker's final merge, without granting readiness.
                        if not current['items'] and library['clients'][client]['items']:
                            current=library['clients'][client]
                        current['last_read_failure']=failure
                    library['clients'][client]=current
                catalog.save(library,library_path,compact=True)
                last_publish=time.perf_counter()
                if progress:progress()
            if len(finished)==2:break
    library=catalog.read(library_path)
    counts={c:{'observed':len(s['items']),
               'ready':sum(i.get('original_state')=='ready' and not i.get('transfer_block_reason') for i in s['items'])}
            for c,s in library['clients'].items()}
    report=dict(seconds=round(time.perf_counter()-started,3),clients=result,counts=counts,
                cancelled=bool(cancel and Path(cancel).exists()),messages_sent=0,target_additions=0)
    save_json(folder/'result.json',report)
    return report
