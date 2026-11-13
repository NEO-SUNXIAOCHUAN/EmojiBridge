"""One user action, separate durable acquisition and at-most-once transfer stages."""
from collections import Counter
from datetime import datetime
from pathlib import Path
import time
from contextlib import nullcontext,contextmanager
from emoji_bridge import catalog
from emoji_bridge.state import save_json,single_instance
from emoji_bridge.transfer import make_export_plan,run_plan,SUCCESS,INTERRUPTIONS
from emoji_bridge.timing import recorded
from emoji_bridge.media import inspection_session


def create(library,client,ids,path):
    if client not in ('wechat','qq') or not ids or len(set(ids))!=len(ids):raise ValueError('explicit_selection_required')
    if len(ids)>500:raise ValueError('当前一次最多选择500项；仅执行明确勾选的项目')
    known={i['id'] for i in catalog.display_items(library['clients'][client])}
    if not set(ids)<=known:raise ValueError('selection_changed_refresh_required')
    if Path(path).exists():raise ValueError('plan_already_exists')
    result={'schema':'selected-workflow-v1','source_client':client,'created':datetime.now().astimezone().isoformat(),
        'jobs':[{'item_id':i,'status':'queued','stage':'acquisition'} for i in ids],'counts':{'queued':len(ids)}}
    if client=='qq':result['execution_policy']='wechat_batch_action_only_v1'
    save_json(path,result);return result


@contextmanager
def source_group_scope(proofs):
    try:yield
    finally:
        for proof in proofs.values():proof.close()


def needs_source(child):
    if not child.exists():return True
    job=catalog.read(child)['jobs'][0]
    return job['status'] not in SUCCESS and (job['status']=='queued' or job.get('submission_state')=='not_started')


@recorded
@inspection_session()
def run(path,library_path,storage,resume=False,acquire=None,execute=None,source_check=None,progress=None,execute_batch=None,prepare_group=None,preflight=None,clear_cancel=True):
    path=Path(path).resolve();cancel=path.with_suffix('.cancel');plan=catalog.read(path)
    if plan.get('schema')!='selected-workflow-v1':raise ValueError('workflow_schema_required')
    if (plan.get('execution_policy')=='wechat_batch_action_only_v1' and acquire is None
            and execute is None and source_check is None and prepare_group is None):
        from wechat_batch_workflow import run as batch_run
        return batch_run(path,library_path,storage,resume,progress,preflight=preflight,clear_cancel=clear_cancel)
    if plan['source_client']=='wechat' and (execute is None or execute_batch is not None):
        from qq_batch_workflow import run as run_batch
        return run_batch(path,library_path,storage,resume,acquire,execute_batch,source_check,progress,preflight,clear_cancel=clear_cancel)
    if path.parent.joinpath(path.stem+'-qq-batch.json').exists():
        raise ValueError('existing_batch_requires_batch_executor')
    selected_qq_check=source_check is None
    native_group=plan['source_client']=='qq' and acquire is None and execute is None and source_check is None
    if native_group and preflight is None:
        from client_preflight import check_clients
        preflight=check_clients
    if native_group and prepare_group is None:
        from qq_source_group import prepare as prepare_group
    if execute is None or source_check is None:
        from local_bridge import execute_recovery as client_execute,recheck_source
        execute=execute or client_execute;source_check=source_check or recheck_source
    if resume and clear_cancel:cancel.unlink(missing_ok=True)
    client=plan['source_client']
    from wechat_acquire import index_session
    def save_progress(n,stage):
        plan['counts']=dict(Counter(j['status'] for j in plan['jobs']))
        plan['progress']={'position':n+1,'total':len(plan['jobs']),'stage':stage}
        save_json(path,plan)
        if progress:progress(plan['progress'])
    paused=False;confirmed={};group_proofs={};group_pending={};plan.pop('pause_reason',None)
    with single_instance(path.with_suffix('.lock')),source_group_scope(group_proofs),index_session() if client=='wechat' else nullcontext():
        pending=[(n,j) for n,j in enumerate(plan['jobs']) if j['status'] not in SUCCESS
                 and (j['status']!='failed' or (resume and j.get('reason') in INTERRUPTIONS))
                 and (j['status']!='pending_confirmation' or resume)]
        if not pending:plan.pop('environment_block',None)
        if preflight and pending:
            from client_preflight import pause_if_blocked
            clients=['wechat' if client=='qq' else 'qq']
            if client=='qq':
                from qq_snapshot import reusable
                try:known={i['id']:i for i in catalog.read(library_path)['clients']['qq']['items']}
                except (OSError,ValueError,KeyError):known={}
                if any(needs_source(path.parent/(path.stem+f'-item-{n}.json')) and
                       not reusable(known.get(j['item_id'],{})) for n,j in pending):clients.append('qq')
            if pause_if_blocked(plan,path,clients,preflight):return plan
        ordered=list(enumerate(plan['jobs']))
        if resume:
            # Recover an existing target-side attempt before staging a new
            # source item. In particular, an unsent GIF still in the composer
            # must not make every earlier pending source fail composer checks.
            # Keep the durable/user-visible selection order unchanged.
            ordered.sort(key=lambda pair:0 if pair[1]['status'] not in SUCCESS and
                         not needs_source(path.parent/(path.stem+f'-item-{pair[0]}.json')) else 1)
        for n,job in ordered:
            if cancel.exists():break
            if job['status'] in SUCCESS:continue
            if job['status']=='failed':
                child=path.parent/(path.stem+f'-item-{n}.json')
                if not (resume and job.get('reason') in INTERRUPTIONS and child.exists()
                        and catalog.read(child)['jobs'][0].get('submission_state')=='not_started'):continue
                job['status']='pending_confirmation'
            if job['status']=='pending_confirmation' and not resume:continue
            started=time.perf_counter()
            try:
                # Only populated by a fresh successful acquisition in this
                # invocation. Existing originals / resumed child jobs recheck.
                fresh=[]
                child=path.parent/(path.stem+f'-item-{n}.json')
                if prepare_group is not None and needs_source(child) and job['item_id'] not in group_proofs and job['item_id'] not in group_pending:
                    for proof in group_proofs.values():proof.close()
                    group_proofs.clear()
                    library=catalog.read(library_path);known={i['id']:i for i in library['clients']['qq']['items']}
                    chosen=[]
                    for k in range(n,min(n+8,len(plan['jobs']))):
                        other=plan['jobs'][k]
                        if other['status'] in SUCCESS or (other['status']=='failed' and other.get('reason') not in INTERRUPTIONS):continue
                        if needs_source(path.parent/(path.stem+f'-item-{k}.json')):chosen.append(known[other['item_id']])
                    save_progress(n,'source_group')
                    group=prepare_group(chosen,library_path,cancel)
                    plan.setdefault('source_groups',[]).append(group['report'])
                    if group.get('blocked',not group['proofs']):
                        results=group.get('results',{})
                        for other in plan['jobs'][n:n+8]:
                            result=results.get(other['item_id'])
                            if result is not None and other['status'] not in SUCCESS:
                                other.update(status='pending_confirmation',stage='acquisition',
                                             reason=result.get('reason') or group.get('reason','source_group_pending'),
                                             acquisition_report=result.get('report') or group['report'])
                        if not results:
                            job.update(status='pending_confirmation',stage='acquisition',reason=group.get('reason','source_group_pending'))
                        plan['pause_reason']=group.get('reason','source_group_pending')
                        paused=True;save_progress(n,'done');break
                    group_proofs.update(group['proofs'])
                    group_pending.update({ident:r for ident,r in group.get('results',{}).items() if ident not in group_proofs})
                if job['item_id'] in group_pending and needs_source(child):
                    result=group_pending[job['item_id']]
                    job.update(status='pending_confirmation',stage='acquisition',reason=result.get('reason','source_original_pending'),
                               acquisition_report=result.get('report'))
                    save_progress(n,'done');continue
                # Child intent is durable before the executor can submit. Even
                # if the outer process died before storing its path, reuse it.
                if not child.exists():
                    library=catalog.read(library_path);side=library['clients'][client]
                    item=next((i for i in side['items'] if i['id']==job['item_id']),None)
                    if item is None:raise ValueError('selected_item_no_longer_in_catalog')
                    if item.get('original_state')!='ready':
                        job.update(stage='acquisition',status='running');save_progress(n,'acquisition')
                        if acquire is not None:result=acquire(client,item,side.get('source_report'),cancel)
                        elif client=='wechat':
                            from wechat_acquire import acquire_selected
                            result=acquire_selected(item,side['source_report'],cancel)
                        else:
                            from qq_cache_acquire import acquire_or_resume
                            result=acquire_or_resume(item,cancel,on_verified=fresh.append)
                        catalog.apply_acquisition(item,result);catalog.save(library,library_path)
                        job['acquisition_report']=result.get('report')
                        if item.get('original_state')!='ready':
                            job.update(status='pending_confirmation',reason=result.get('reason','source_original_pending'))
                            save_json(path,plan)
                            if job['reason'] in INTERRUPTIONS:paused=True;break
                            continue
                    pairs=catalog.transfer_selection(library,client,[job['item_id']],storage)
                    make_export_plan(pairs,child)
                if cancel.exists():break
                child_data=catalog.read(child);record=child_data['jobs'][0]
                key=(record['target'],record['source_sha256'])
                if key in confirmed:
                    original=confirmed[key]
                    job.update(status='already_exists',stage='transfer',reason='duplicate_of_confirmed_job',
                               duplicate_of=original['item_id'],result=original.get('result'))
                    record.update(status='already_exists',reason='duplicate_of_confirmed_job',result=job.get('result'),submission_state='not_started')
                    child_data.update(run_state='finished',counts={'already_exists':1});save_json(child,child_data)
                    save_progress(n,'done');continue
                job.update(stage='transfer',status='running',child_plan=str(child));save_progress(n,'transfer')
                # The child queue owns target submission state. Never infer a
                # safe re-add from the outer workflow's interruption status.
                def check_source(asset):
                    if job['item_id'] in group_proofs:return group_proofs[job['item_id']].consume(asset)
                    proof=fresh.pop().consume(asset) if fresh else None
                    if proof is not None:return proof
                    if selected_qq_check and client=='qq':
                        from qq_cache_acquire import recheck_selected
                        current=catalog.read(library_path)['clients']['qq']['items']
                        chosen=next((i for i in current if i['id']==job['item_id']),None)
                        if chosen is None:return {'status':'pending_confirmation','reason':'selected_item_no_longer_in_catalog'}
                        return recheck_selected(asset,chosen,cancel)
                    return source_check(asset)
                result=run_plan(child,lambda asset,command,token:execute(asset,command,cancel),
                                check_source,clear_cancel=resume and clear_cancel)
                single=result['jobs'][0]
                job.update(status=single['status'],reason=single.get('reason'),result=single.get('result'))
                job['collection_persisted']=single.get('collection_persisted',False)
                if job['status'] in SUCCESS:confirmed[key]=dict(job)
                if result.get('run_state')=='paused':paused=True
            except Exception as exc:
                job.update(status='pending_confirmation',reason=str(exc))
                if str(exc) in INTERRUPTIONS:paused=True
            job['last_run_seconds']=round(time.perf_counter()-started,3);save_progress(n,'done')
            if cancel.exists() or paused:break
        plan['run_state']='cancelled' if cancel.exists() else ('paused' if paused else 'finished')
        plan['counts']=dict(Counter(j['status'] for j in plan['jobs']))
        plan['updated']=datetime.now().astimezone().isoformat();save_json(path,plan)
    return plan
