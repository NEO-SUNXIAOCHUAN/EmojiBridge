"""Stream sealed favorite pages to bounded local preparation workers. No extra UI."""
from concurrent.futures import ThreadPoolExecutor,Future
from contextvars import copy_context
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Lock
import queue,time

from emoji_bridge import catalog
from emoji_bridge.state import save_json,sha
from emoji_bridge.timing import stage
import qq_cache_acquire as acquire


def seal_page(path,report,items):
    """Keep the observed native page intact; no receipt hashes a growing report."""
    page_number=items[0]['page']
    if any(i['page']!=page_number for i in items):raise ValueError('one_observed_page_required')
    page=deepcopy(report['pages'][page_number])
    if sha(page['image'])!=page['sha256']:raise ValueError('favorite_scan_image_changed')
    sealed={k:deepcopy(v) for k,v in report.items() if k not in ('pages','items')}
    selected=[dict(deepcopy(i),page=0) for i in items]
    sealed.update(pages=[page],items=selected,status='sealed_page',complete=False,
                  parent_scan=str(Path(path).resolve()),parent_page=page_number)
    target=Path(path).with_suffix('')/f'sealed-{page_number}.json'
    if target.exists():raise ValueError('sealed_page_already_exists')
    save_json(target,sealed,compact=True)
    return [dict(i,scan=str(target.resolve())) for i in selected]


def prepare(library_path,cancel,changed,observed):
    from qq_catalog import scan,MAX_SCAN_VIEWS
    from qq_appearance_prepare import prepare as prepare_page,Candidates
    from qq_offline_index import build,VERSION
    from qq_prepare_remaining import complete_observed
    start=time.perf_counter();library_path=Path(library_path)
    library=catalog.read(library_path);side=library['clients']['qq']
    if side['items']:raise ValueError('first_use_empty_qq_library_required')
    side.update(initial_index_attempted=True,complete=False,items=[])
    work=library_path.parent/'qq-page-preparation';work.mkdir(parents=True)
    report_path=work/'pipeline.json';jobs=queue.Queue(maxsize=4);updates=queue.Queue();items={}
    metrics=dict(schema='qq-startup-pipeline-v1',pages_queued=0,pages_prepared=0,
                 max_queued_pages=0,local_workers=2,messages_sent=0,target_additions=0)
    candidate_future=Future();metric_lock=Lock()
    catalog.save(library,library_path,compact=True);changed()
    last_publish=0

    def publish(force=False):
        nonlocal last_publish
        # Page catalogs already journal every result. Coalesce shared-library
        # writes to the outer UI coordinator's cadence, with final forced flush.
        if not force and time.perf_counter()-last_publish<.25:return
        dirty=force
        while True:
            try:value=updates.get_nowait()
            except queue.Empty:break
            prior=items.get(value['id'])
            if prior is None or any(prior[k]!=value[k] for k in ('scan','page','rect','position')):
                raise ValueError('pipeline_selection_changed')
            prior.update(value)
            dirty=True
        if not dirty:return
        side['items']=list(items.values())
        if candidate_future.done() and candidate_future.exception() is None:
            side['cache_diagnostics']=acquire.cache.diagnostic_summary(candidate_future.result().inventory)
        with stage('qq_pipeline_save'):catalog.save(library,library_path,compact=True)
        last_publish=time.perf_counter();changed()

    def finalize_observations(path,report):
        # The scanner can catch callback errors after saving a new observation.
        # Keep every saved row even if its preparation job was never queued.
        pending=[]
        for row in report['items']:
            item=items.setdefault(row['id'],deepcopy(row))
            if item.get('original_state')!='ready':
                item.update(scan=str(Path(path).resolve()),page=row['page'],rect=row['rect'])
                pending.append(item)
        if len(items)!=len(report['items']):raise ValueError('pipeline_observation_count_changed')
        side.update(source_report=str(path),snapshot_at=report['at'],observations_count=len(items),
                    current_snapshot_only=True,read_reason=report.get('reason'),
                    scope=f'本次读取 {len(report["pages"])} 个收藏视图；未读到的不显示，非全库')
        publish(True)
        return pending

    def consume(initialize=False):
        # Two bounded local workers own separate page catalogs. Shared asset
        # manifests are serialized per content digest, retaining every origin.
        # The scanner and outer startup coordinator remain the only writers of
        # their respective catalogs. No parallel client input is introduced.
        if initialize:
            try:
                candidates=Candidates(cancel)
                metrics['candidates_ready_seconds']=round(time.perf_counter()-start,3)
                candidate_future.set_result(candidates)
            except BaseException as exc:
                candidate_future.set_exception(exc);raise
        else:candidates=candidate_future.result()
        while True:
            acquire.cancelled(cancel)
            try:job=jobs.get(timeout=.1)
            except queue.Empty:continue
            if job is None:break
            number,rows=job
            page_library=work/f'page-{number}.json'
            catalog.save({'clients':{'qq':{'items':rows},'wechat':{'items':[]}}},page_library,compact=True)
            def item_ready(item):
                if item.get('original_available'):
                    with metric_lock:metrics.setdefault('first_original_seconds',round(time.perf_counter()-start,3))
                updates.put(deepcopy(item))
            with stage('qq_page_prepare'):
                prepare_page(page_library,cancel,candidates=candidates,on_item=item_ready)
            with metric_lock:metrics['pages_prepared']+=1
        with metric_lock:metrics['local_finished_seconds']=round(time.perf_counter()-start,3)
        return candidates.inventory.get('directory_fingerprint')

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(copy_context().run,consume,initial) for initial in (True,False)]
        def check_workers():
            for future in futures:
                if future.done():future.result()
        def enqueue(job):
            while True:
                acquire.cancelled(cancel)
                check_workers()
                try:jobs.put(job,timeout=.05);break
                except queue.Full:publish()
            metrics['max_queued_pages']=max(metrics['max_queued_pages'],jobs.qsize())

        def on_page(path,report):
            fresh=[i for i in report['items'] if i['id'] not in items]
            if fresh:
                rows=seal_page(path,report,fresh)
                for item in rows:items[item['id']]=item
            side.update(source_report=str(path),snapshot_at=report['at'],
                        current_snapshot_only=True,
                        scope=f'正在读取 {len(report["pages"])} 个收藏视图；已封存页面同步准备原件')
            publish(True)
            if fresh:
                enqueue((len(report['pages'])-1,deepcopy(rows)));metrics['pages_queued']+=1
        path=report=None
        try:
            path,report=scan(MAX_SCAN_VIEWS,cancel,progress=on_page)
            metrics['scan_finished_seconds']=round(time.perf_counter()-start,3)
            for _ in futures:enqueue(None)
            while not all(future.done() for future in futures):
                publish();time.sleep(.05)
            check_workers();fingerprint=candidate_future.result().inventory.get('directory_fingerprint');publish(True)
        except BaseException as exc:
            # Wake a worker waiting for pages even if scan/publishing failed.
            # On cancel the worker also checks the shared token before each item.
            for _ in futures:
                while not all(future.done() for future in futures):
                    try:jobs.put(None,timeout=.05);break
                    except queue.Full:pass
            for future in futures:
                try:future.result()
                except Exception:pass
            publish(True)
            if report is not None:finalize_observations(path,report)
            ready=sum(i.get('original_state')=='ready' and not i.get('transfer_block_reason') for i in items.values())
            metrics.update(state='stopped',reason=str(exc),observed=len(items),ready=ready,pending=len(items)-ready,
                           seconds=round(time.perf_counter()-start,3))
            side['index_build']=dict(metrics,version=VERSION,report=str(report_path))
            publish(True)
            save_json(report_path,metrics)
            raise

    # Final scan remains the collection-wide record. Ready originals keep the
    # smaller immutable page receipt; unresolved rows use the final scan for
    # the existing full-frame/hover fallback and later interrupted-run recovery.
    pending=finalize_observations(path,report)
    if pending and not report.get('reason'):
        # Only unresolved items enter the old expensive fallback. Never rebuild
        # or rebind successful receipts to the final, larger report.
        fallback=work/'remaining.json'
        catalog.save({'clients':{'qq':dict(side,items=deepcopy(pending)),'wechat':{'items':[]}}},fallback)
        def merge_fallback(*args):
            for item in catalog.read(fallback)['clients']['qq']['items']:items[item['id']].update(item)
            publish(True)
        try:
            build(fallback,cancel,merge_fallback,practical_first=True)
            if any(i.get('original_state')!='ready' for i in catalog.read(fallback)['clients']['qq']['items']):
                complete_observed(fallback,cancel,merge_fallback)
        except Exception as exc:
            # A fallback may save an item just before its callback is cancelled.
            # Merge durable progress even when it cannot return a final result.
            merge_fallback()
            ready=sum(i.get('original_state')=='ready' and not i.get('transfer_block_reason') for i in items.values())
            metrics.update(state='stopped',reason=str(exc),observed=len(items),ready=ready,pending=len(items)-ready,
                           seconds=round(time.perf_counter()-start,3))
            save_json(report_path,metrics)
            side['index_build']=dict(metrics,version=VERSION,report=str(report_path))
            publish(True)
            raise
        merge_fallback()
    ready=sum(i.get('original_state')=='ready' and not i.get('transfer_block_reason') for i in items.values())
    reason=report.get('reason') or (None if items else 'qq_no_observations')
    metrics.update(state='finished' if items and ready==len(items) and not reason else 'incomplete',
                   observed=len(items),ready=ready,pending=len(items)-ready,reason=reason,
                   seconds=round(time.perf_counter()-start,3))
    save_json(report_path,metrics)
    side['index_build']=dict(state=metrics['state'],version=VERSION,fingerprint=fingerprint,
        processed=len(items),ready=ready,scan=str(path),report=str(report_path),at=datetime.now().astimezone().isoformat())
    publish(True);return dict(metrics,report=str(report_path))
