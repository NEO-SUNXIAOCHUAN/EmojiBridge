"""Prepare every authenticated local favorite before transfer, with no UI sends.

Only the authenticated index defines membership. Preview files never count as
originals. Preparation is resumable and does not claim cloud completeness.
"""
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from datetime import datetime
from pathlib import Path
from collections import Counter
import sys,time,traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
from emoji_bridge import catalog
from emoji_bridge.state import save_json,single_instance
from emoji_bridge.media import inspection_session
from emoji_bridge.windows import StopAutomation
import wechat_acquire as acquire
from wechat_catalog import PreviewReader


def prepare(library_path=None,cancel=None,progress=None,workers=3,preview_first=False,ids=None,index_only=False):
    from emoji_bridge.paths import DATA_ROOT as ROOT
    if library_path is None:library_path=catalog.PATH
    start=time.perf_counter();stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    report_path=ROOT/'reports/T006'/f'wechat-prepare-{stamp}.json'
    report={'schema':'wechat-preparation-v1','at':datetime.now().astimezone().isoformat(),
            'status':'preparing','results':[],'messages_sent':0,'target_additions':0,
            'complete_collection_proven':False,'scope':'authenticated local favorites snapshot only'}
    library_path=Path(library_path)
    def record():
        report['seconds']=round(time.perf_counter()-start,3)
        report['counts']=dict(Counter(r['status'] for r in report['results']))
        save_json(report_path,report)
        library=catalog.read(library_path)
        library['clients']['wechat']['preparation']={k:report[k] for k in (
            'status','at','counts','seconds','complete_collection_proven')}
        library['clients']['wechat']['preparation'].update(report=str(report_path),
            reason=report.get('reason'),
            total=report.get('total'),processed=len(report['results']),
            all_indexed_originals_ready=report.get('all_indexed_originals_ready',False))
        catalog.save(library,library_path)
    with single_instance(library_path.with_suffix('.prepare.lock')),acquire.index_session():
        try:
            acquire.cancelled(cancel)
            side=catalog.read(library_path)['clients']['wechat']
            if not side.get('source_report'):
                from emoji_bridge.client_sources import emoticon_database
                settings=ROOT/'runtime-data/client-sources.json'
                explicit=catalog.read(settings).get('wechat_emoticon_db') if settings.exists() else None
                members,initial=acquire.current_index({'source':str(emoticon_database(explicit=explicit))},cancel)
                initial_path=ROOT/'reports/T005'/f'wechat-initial-index-{stamp}.json'
                save_json(initial_path,initial)
                library=catalog.read(library_path);catalog.merge_wechat(library,initial_path);catalog.save(library,library_path)
            reader=PreviewReader();reader.refresh_library(library_path,cancel)
            side=catalog.read(library_path)['clients']['wechat']
            if ids is not None and (not ids or len(set(ids))!=len(ids) or not set(ids)<={i['id'] for i in side['items']}):
                raise ValueError('selected_member_not_in_current_index')
            chosen=[i for i in side['items'] if ids is None or i['id'] in ids]
            report.update(index=str(reader.path),total=len(chosen),indexed_total=len(reader.members),selected_only=ids is not None)
            todo=iter(chosen);record()
            if progress:progress(0,report['total'])
            if preview_first:
                # Show the first viewport without waiting for full originals.
                # Preview-only files never grant an asset or source receipt.
                reader.load(library_path,[i['id'] for i in side['items'][:9]],cancel,
                            on_item=lambda ident:progress(0,report['total']) if progress else None)
            if index_only:
                report.update(status='index_ready',all_indexed_originals_ready=False)
                record();return dict(report,report=str(report_path))
            @inspection_session()
            def fetch(item):
                acquire.cancelled(cancel)
                if item.get('original_state')=='ready':
                    # Current membership was refreshed above. Revalidate the
                    # immutable bytes and origin instead of downloading again.
                    try:
                        _,origin=catalog.valid_original(item['asset'])
                        return {'status':'original_verified','asset':item['asset'],
                                'report':origin['original_provenance'],'reused':True,
                                'target_prepare_error':item.get('transfer_block_reason')}
                    except (OSError,ValueError,KeyError):
                        return {'status':'pending_confirmation','report':str(report_path),
                                'reason':'saved_original_validation_failed','failure_kind':'integrity_failed'}
                result=acquire.acquire_selected(item,reader.path,cancel)
                if result['status']=='original_verified':
                    # Check the target's immutable input now; never add it.
                    probe={'clients':{'wechat':{'items':[dict(item)]}}}
                    catalog.attach_original(probe['clients']['wechat']['items'][0],result['asset'])
                    try:
                        pair=catalog.transfer_selection(probe,'wechat',[item['id']],ROOT/'private/T005/assets')[0]
                        result['target_asset']=pair['target_asset']
                    except (ValueError,OSError) as exc:
                        result['target_prepare_error']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
                return result
            # Each copied context shares only the in-memory authenticated index
            # session. DB/WAL changes are checked by the existing acquisition API.
            with ThreadPoolExecutor(max_workers=max(1,min(3,workers))) as pool:
                pending={}
                def fill():
                    while len(pending)<max(1,min(3,workers)):
                        acquire.cancelled(cancel);item=next(todo,None)
                        if item is None:break
                        pending[pool.submit(copy_context().run,fetch,item)]=item['id']
                fill()
                while pending:
                    completed,_=wait(pending,timeout=.25,return_when=FIRST_COMPLETED)
                    for future in completed:
                        ident=pending.pop(future);result=future.result()
                        library=catalog.read(library_path)
                        item=next(i for i in library['clients']['wechat']['items'] if i['id']==ident)
                        catalog.apply_acquisition(item,result)
                        if result.get('target_prepare_error'):item['transfer_block_reason']=result['target_prepare_error']
                        else:item.pop('transfer_block_reason',None)
                        catalog.save(library,library_path)
                        state='ready' if result['status']=='original_verified' and not result.get('target_prepare_error') else 'pending'
                        report['results'].append({'id':ident,'status':state,'acquisition':result['report'],
                            'failure_kind':result.get('failure_kind'),'diagnostic':result.get('diagnostic'),
                            'reason':result.get('target_prepare_error') or result.get('reason')})
                        record()
                        if progress:progress(len(report['results']),report['total'])
                    fill()
            acquire.cancelled(cancel)
            _,_,now=acquire.index.snapshot(Path(reader.report['source']))
            same=all(now[k]==reader.report['snapshot'][k] for k in ('db_sha256','wal_sha256','checkpoint'))
            report['membership_snapshot_still_current']=same
            report['selected_originals_ready']=same and len(report['results'])==report['total'] and all(r['status']=='ready' for r in report['results'])
            report['all_indexed_originals_ready']=report['selected_originals_ready'] and len(chosen)==len(reader.members)
            report['status']='ready_for_local_snapshot' if report['all_indexed_originals_ready'] else 'selected_ready' if report['selected_originals_ready'] else 'incomplete'
        except Exception as exc:
            code=str(exc) if isinstance(exc,(ValueError,StopAutomation,acquire.index.IndexErrorSafe)) else type(exc).__name__
            report.update(status='cancelled' if code=='cancel_requested' else 'blocked',reason=code,
                          all_indexed_originals_ready=False)
            report['diagnostic_frames']=[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno}
                                         for f in traceback.extract_tb(exc.__traceback__)]
            if isinstance(exc,OSError):report.update(errno=exc.errno,winerror=getattr(exc,'winerror',None),
                                                     failed_file=Path(exc.filename).name if exc.filename else None)
        record()
    return dict(report,report=str(report_path))


if __name__=='__main__':
    import json
    result=prepare(progress=lambda n,total:print(f'{n}/{total}',flush=True))
    print(json.dumps({k:v for k,v in result.items() if k!='results'},ensure_ascii=False))
