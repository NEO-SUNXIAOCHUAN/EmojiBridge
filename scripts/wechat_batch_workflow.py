"""Prepare the selection once; bounded send/add groups without source UI."""
from pathlib import Path
from collections import Counter
from datetime import datetime
from emoji_bridge import catalog
from emoji_bridge.state import save_json,single_instance
from emoji_bridge.transfer import SUCCESS,INTERRUPTIONS
from wechat_batch import DONE,SUBMITTED


def sent_unadded(job):
    if job.get('submission_state')!='may_have_started' or not job.get('target_asset'):return False
    try:
        from local_bridge import ROOT
        from emoji_bridge.media import load_asset
        asset=load_asset(job['target_asset']);ledger=catalog.read(ROOT/'runtime-data/T004/wechat'/(asset['source_sha256']+'.json'))
        return (ledger['status'] in SUBMITTED and ledger['prepared_sha256']==asset['prepared_sha256']
                and Path(ledger['asset']).resolve()==Path(job['target_asset']).resolve())
    except (OSError,ValueError,KeyError):return False


def run(path,library_path,storage,resume=False,progress=None,execute_batch=None,prepare=None,preflight=None,clear_cancel=True):
    from qq_source_group import prepare as source_prepare
    from wechat_batch import execute
    from client_preflight import check_clients,pause_if_blocked
    path=Path(path);plan=catalog.read(path);cancel=path.with_suffix('.cancel')
    if resume and clear_cancel:cancel.unlink(missing_ok=True)
    execute_batch=execute_batch or execute;prepare=prepare or source_prepare;preflight=preflight or check_clients
    def save():
        plan['counts']=dict(Counter(j['status'] for j in plan['jobs']))
        plan['updated']=datetime.now().astimezone().isoformat();save_json(path,plan)
    def notify(n,stage,send_group=None):
        plan['progress']={'position':n+1,'total':len(plan['jobs']),'stage':stage,
                          'completed':sum(j['status'] in DONE for j in plan['jobs']),
                          'confirmed':sum(j.get('collection_verified',False) or j['status'] in ('desktop_confirmed','already_exists') for j in plan['jobs'])}
        if send_group:plan['progress']['send_group']=send_group
        save()
        if progress:progress(plan['progress'])
    def dispatch(assets,n,resume_sent=False):
        options={'resume_sent':True} if resume_sent else {}
        if execute_batch is execute:
            approvals={str(Path(j['target_asset']).resolve()):j['retry_approval'] for j in plan['jobs']
                       if j.get('target_asset') in assets and j.get('retry_approval')}
            if approvals:options['retry_approvals']=approvals
            def update(value):
                if isinstance(value,dict):
                    for j in plan['jobs']:
                        r=value.get('results',{}).get(str(Path(j.get('target_asset','')).resolve()))
                        if r:
                            for k in ('status','reason','collection_verified','collection_persisted','completion_check','membership_evidence','submission_state','file_selection_step','file_submission','file_path_verified','file_window_observation','pause_window'):
                                if k in r:j[k]=r[k]
                                elif k in ('file_selection_step','file_submission','file_path_verified','file_window_observation','pause_window'):
                                    j.pop(k,None)
                    notify(n,value['stage'],value.get('send_group'))
                else:notify(n,value)
            options['progress']=update
        return execute_batch(assets,cancel,**options)
    with single_instance(path.with_suffix('.lock')):
        if resume and execute_batch is execute and not cancel.exists():
            candidates=[j for j in plan['jobs'] if j.get('target_asset') and not j.get('collection_verified')
                        and (j.get('submission_state')=='may_have_started' or j['status']=='add_executed')]
            if candidates:
                # A saved unknown add is verification-only. Absence from the
                # index never resets its submission state or permits a resend.
                notify(0,'checking_result')
                checked=execute([j['target_asset'] for j in candidates],cancel,verify_only=True)
                plan.setdefault('verification_batches',[]).append(checked['report_path'])
                for j in candidates:
                    result=checked['results'].get(str(Path(j['target_asset']).resolve()),{})
                    if result.get('collection_verified'):
                        j.setdefault('verification_history',[]).append({k:j.get(k) for k in ('status','reason','result')})
                        j.update(status='already_exists',reason=result['reason'],collection_verified=True,
                                 completion_check=result['completion_check'],membership_evidence=result.get('membership_evidence'),
                                 result=result['report_path'])
                save()
        pending=[(n,j) for n,j in enumerate(plan['jobs']) if j['status'] not in DONE]
        if not pending:plan['run_state']='finished';save();return plan
        if cancel.exists():plan['run_state']='cancelled';save();return plan
        if pause_if_blocked(plan,path,['wechat'],preflight):return plan
        from wechat_retry import valid
        from wechat_batch import ROOT as data_root
        for _,j in pending:
            if j.get('target_asset') and valid(j['target_asset'],j.get('retry_approval'),data_root):
                j.update(submission_state='not_started',status='queued')
        plan['run_state']='running';plan.pop('pause_reason',None);save()
        recovery=[(n,j) for n,j in pending if resume and sent_unadded(j)]
        if cancel.exists():plan['run_state']='cancelled';save();return plan
        if recovery:
            notify(recovery[0][0],'transfer')
            result=dispatch(list(dict.fromkeys(j['target_asset'] for _,j in recovery)),recovery[0][0],resume_sent=True)
            plan.setdefault('target_batches',[]).append(result['report_path'])
            for _,j in recovery:
                r=result['results'].get(str(Path(j['target_asset']).resolve()),{})
                j.setdefault('recovery_history',[]).append({k:j.get(k) for k in ('status','reason','result')})
                j.update(status=r.get('status','pending_confirmation'),reason=r.get('reason'),result=r.get('report_path'),
                         collection_verified=r.get('collection_verified',False),collection_persisted=False,
                         completion_check=r.get('completion_check'),membership_evidence=r.get('membership_evidence'))
            save();pending=[(n,j) for n,j in pending if (n,j) not in recovery]
            if any(j['status'] not in DONE for _,j in recovery):
                plan['run_state']='cancelled' if cancel.exists() else 'paused' if any(j.get('reason') in INTERRUPTIONS for _,j in recovery) else 'partial'
                save();return plan
        # Unknown add/send boundaries are not authorization to move on to the
        # unsent tail. Resolve the interrupted group before another send.
        if any(j.get('submission_state')=='may_have_started' for _,j in pending):
            for _,j in pending:
                if j.get('submission_state')=='may_have_started':
                    j.update(status='pending_confirmation',reason=j.get('reason') or '上次操作结果未知，未自动重发或重加')
            plan['run_state']='partial';save();return plan
        for selected in [pending]:
            if cancel.exists():break
            proofs={}
            try:
                fresh=[]
                for n,j in selected:
                    if j.get('submission_state')=='may_have_started':
                        j.update(status='pending_confirmation',reason='上次操作结果未知，未自动重发或重加');continue
                    fresh.append((n,j))
                if not fresh:continue
                library=catalog.read(library_path);known={i['id']:i for i in library['clients']['qq']['items']}
                notify(fresh[0][0],'source_group')
                # Prepare only the chosen unresolved observations, offline.
                # Do not change an unknown target submission or rescan QQ.
                if prepare is source_prepare:
                    wanted=[j['item_id'] for _,j in fresh if known[j['item_id']].get('original_state')!='ready']
                    if wanted:
                        from qq_appearance_prepare import prepare as selected_prepare
                        selected_prepare(library_path,cancel,ids=wanted)
                        known={i['id']:i for i in catalog.read(library_path)['clients']['qq']['items']}
                group=prepare([known[j['item_id']] for _,j in fresh],library_path,cancel,allow_ui=False)
                proofs=group['proofs'];plan.setdefault('source_groups',[]).append(group['report'])
                if group.get('blocked'):
                    plan.update(run_state='paused',pause_reason=group.get('reason','source_index_unavailable'));break
                active=[]
                for n,j in fresh:
                    if cancel.exists():break
                    if j['item_id'] not in proofs:
                        result=group.get('results',{}).get(j['item_id'],{})
                        j.update(status='pending_confirmation',reason=result.get('reason','QQ索引尚未对应原件'),
                                 submission_state='not_started',stage='acquisition',acquisition_report=result.get('report'));continue
                    try:
                        pairs=catalog.transfer_selection(catalog.read(library_path),'qq',[j['item_id']],storage)
                        source=proofs[j['item_id']].consume(pairs[0]['source_asset'])
                    except (OSError,ValueError,KeyError) as exc:
                        if str(exc) in INTERRUPTIONS or str(exc) in ('cancel_requested','cancelled_escape') or cancel.exists():raise
                        j.update(status='pending_confirmation',reason='source_preparation_failed',
                                 diagnostic=str(exc),stage='acquisition',submission_state='not_started')
                        continue
                    j.update(source_asset=pairs[0]['source_asset'],target_asset=pairs[0]['target_asset'],
                             source_proof=source['report_path'],stage='transfer')
                    active.append((n,j))
                if not active:save();continue
                if cancel.exists():break
                for _,j in active:j.update(status='running',submission_state='may_have_started')
                notify(active[0][0],'transfer')  # Durable before any native send.
                assets=list(dict.fromkeys(j['target_asset'] for _,j in active))
                result=dispatch(assets,active[0][0])
                plan.setdefault('target_batches',[]).append(result['report_path'])
                for n,j in active:
                    r=result['results'].get(str(Path(j['target_asset']).resolve()),{})
                    j.update(status=r.get('status','pending_confirmation'),reason=r.get('reason'),
                             result=r.get('report_path'),collection_persisted=r.get('collection_persisted',False),
                             collection_verified=r.get('collection_verified',False),
                             completion_check=r.get('completion_check'),membership_evidence=r.get('membership_evidence'),
                             submission_state=r.get('submission_state',j['submission_state']),
                             file_selection_step=r.get('file_selection_step'),
                             file_submission=r.get('file_submission'),file_path_verified=r.get('file_path_verified'),
                             file_window_observation=r.get('file_window_observation'),pause_window=r.get('pause_window'))
                notify(active[-1][0],'done')
                if any(j.get('reason') in INTERRUPTIONS for _,j in active):
                    plan['run_state']='paused';break
            except Exception as exc:
                for _,j in selected:
                    if j['status'] not in DONE:j.update(status='pending_confirmation',reason=str(exc))
                if str(exc) in INTERRUPTIONS or cancel.exists():plan['run_state']='paused';break
            finally:
                for proof in proofs.values():proof.close()
                save()
        plan['run_state']='cancelled' if cancel.exists() else ('paused' if plan['run_state']=='paused'
            else 'finished' if all(j['status'] in DONE for j in plan['jobs']) else 'partial')
        save();return plan
