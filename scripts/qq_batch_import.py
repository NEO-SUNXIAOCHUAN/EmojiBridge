"""One native QQ multi-file submission, shared reopen, per-original outcomes."""
from datetime import datetime
from pathlib import Path
import time
from local_bridge import OrdinaryImport,ROOT,StopAutomation
from emoji_bridge.state import save_json,single_instance
from emoji_bridge.transfer import SUCCESS,INTERRUPTIONS

from emoji_bridge.limits import QQ_BATCH_LIMIT as MAX_BATCH


def ambiguous_members(hits):
    """One visible tile cannot prove two different selected originals."""
    ambiguous=set()
    for n,found in enumerate(hits):
        if len(found)!=1:continue
        for other in range(n):
            if len(hits[other])==1 and all(abs(a-b)<20 for a,b in zip(found[0].center,hits[other][0].center)):
                ambiguous.update((n,other))
    return ambiguous


from emoji_bridge.timing import measured

@measured("adding_and_verification")
def execute_batch(requests,cancel=None,progress=None):
    if not 1<=len(requests)<=MAX_BATCH:raise ValueError('qq_batch_size_limit')
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder=ROOT/'reports/T006'/('qq-batch-'+stamp)
    evidence=ROOT/'private/T006'/('qq-batch-'+stamp)
    runners=[];reports=[];start=time.perf_counter();submissions=0;q=None
    startup=[]
    def phase(stage):
        from emoji_bridge.state import task_progress
        task_progress(stage)
        startup.append({'stage':stage,'seconds':round(time.perf_counter()-start,4)})
        save_json(folder/'startup.json',startup)
        if progress:progress(stage)
    for n,request in enumerate(requests):
        if request['command'] not in ('add','verify'):raise ValueError('batch_command_invalid')
        reports.append({'command':request['command'],'asset':str(request['asset']),
                        'submission_state':'not_started' if request['command']=='add' else 'may_have_started',
                        'batch_report':str(folder/'batch.json')})
    def finish(r,confirmed,was_existing=False):
        if confirmed:
            r.record('desktop_confirmed')
            r.report.pop('reason', None)
            r.report.update(status='already_exists' if was_existing else 'desktop_confirmed',desktop_confirmed=True)
        else:r.report.update(status='pending_confirmation',reason='favorite_or_animation_not_confirmed_no_retry')
    try:
        with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
            for n,request in enumerate(requests):
                dest=evidence/str(n);dest.mkdir(parents=True,exist_ok=True)
                r=OrdinaryImport(request['asset'],reports[n],dest,cancel)
                if r.target!='qq' or (r.asset.get('source_only') and request['command']=='add'):
                    raise ValueError('qq_target_asset_required')
                if request['command']=='add' and request.get('new_intent_completed') and r.prior and r.prior.get('status') in ('desktop_confirmed','already_exists'):
                    save_json(dest/'previous-completed-intent.json',r.prior)
                    r.prior=None;r.report['submission_state']='not_started'
                runners.append(r)
            if len({r.asset['source_sha256'] for r in runners})!=len(runners):raise ValueError('duplicate_batch_original')
            q=runners[0].q;runners[0].cancelled();phase('opening_qq');q.bind()
            for r in runners:r.q=q;r.report['client_version']=q.report['client_version']
            phase('opening_favorites')
            first,window,box=runners[0].panel()
            phase('checking_duplicates')
            hits=[r.locate(first) for r in runners]
            ambiguous=ambiguous_members(hits)
            shared=None
            if any(hits):
                second,window,box=runners[0].panel(reopen=True)
                shared=(first,second,window,box)
            additions=[];unresolved=[]
            for n,r in enumerate(runners):
                r.cancelled()
                if n in ambiguous:r.report.update(status='pending_confirmation',reason='batch_members_not_visually_distinguishable_no_add')
                elif hits[n]:finish(r,r.verify(shared=shared,keep_open=True),True)
                elif requests[n]['command']=='verify' or (r.prior and r.prior.get('status')!='not_submitted'):
                    r.report.update(status='pending_confirmation',reason='prior_attempt_no_blind_resubmit')
                    unresolved.append(n)
                else:additions.append(r)
            if unresolved:
                # Resume searches the unresolved batch together, not one full
                # collection traversal per file. It never calls the picker.
                phase('recovering_favorites')
                from qq_batch_verify import recover
                recover(runners,unresolved,finish)
            if any(r.report.get('status')=='pending_confirmation' for r in runners):
                for r in additions:
                    r.report.update(status='pending_confirmation',reason='earlier_batch_members_need_verification',
                                    submission_state='not_started')
                additions=[]
            if additions:
                # Only one picker and one submit for every file in this batch.
                q.open_panel();dialog=q.picker()
                def boundary():
                    for r in additions:r.boundary('favorite_pending')
                selection=q.dialog_action(dialog,'ChooseMany',[Path(r.asset['prepared']) for r in additions],boundary)
                submissions=1
                for r in additions:r.report['file_selection']=selection
                phase('checking_result')
                deadline=time.monotonic()+15
                q.wait_panel(15)
                while True:
                    first,window,box=runners[0].panel()
                    if all(len(r.locate(first))==1 for r in additions) or time.monotonic()>=deadline:break
                    runners[0].cancelled();time.sleep(.2)
                second,window,box=runners[0].panel(reopen=True)
                shared=(first,second,window,box)
                ambiguous=ambiguous_members([r.locate(second) for r in additions])
                for n,r in enumerate(additions):
                    r.cancelled()
                    if n in ambiguous:r.report.update(status='pending_confirmation',reason='batch_members_not_visually_distinguishable_no_retry')
                    else:finish(r,r.verify(shared=shared,keep_open=True))
            runners[0].close_panel(q.window)
    except Exception as exc:
        reason=str(exc)
        import traceback
        site=traceback.extract_tb(exc.__traceback__)[-1]
        for report in reports:
            # Preserve proven earlier outcomes if a later animation/close fails.
            if report.get('status') in SUCCESS:continue
            report['failure_step']={'stage':startup[-1]['stage'] if startup else 'preparing',
                                    'module':Path(site.filename).name,'function':site.name,'line':site.lineno}
            report.update(status='pending_confirmation' if report.get('submission_state')=='may_have_started'
                          or reason in INTERRUPTIONS else 'cancelled' if reason in ('cancel_requested','cancelled_escape') else 'failed',reason=reason)
    finally:
        if q and hasattr(q,'close'):q.close()
    for n,report in enumerate(reports):
        report.setdefault('status','pending_confirmation')
        report['report_path']=str(folder/f'item-{n}.json')
        save_json(report['report_path'],report)
    result={'schema':'qq-native-batch-v1','items':reports,'native_submit_calls':submissions,
            'selected_count':len(requests),'elapsed_seconds':round(time.perf_counter()-start,3),
            'scope':'explicit selection; original bytes; shared bounded recovery views; no messages'}
    save_json(folder/'batch.json',result)
    return reports
