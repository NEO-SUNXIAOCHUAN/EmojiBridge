"""Durable QQ group intent. Unknown group results resume as verification only."""
from collections import Counter
from datetime import datetime
from pathlib import Path
from .media import load_asset
from .state import save_json
from .transfer import SUCCESS,INTERRUPTIONS
from .catalog import read
from .limits import QQ_BATCH_LIMIT


def run_qq_plan(path,execute_batch,source_check,cancel,after_save=None,batch_size=QQ_BATCH_LIMIT):
    path=Path(path);plan=read(path)
    if plan.get('schema')!='selected-transfer-v1' or not 1<=batch_size<=QQ_BATCH_LIMIT:raise ValueError('qq_batch_plan_required')
    if any(j['target']!='qq' for j in plan['jobs']):raise ValueError('qq_only_batch')
    def save():
        plan['counts']=dict(Counter(j['status'] for j in plan['jobs']))
        plan['updated']=datetime.now().astimezone().isoformat();save_json(path,plan)
        if after_save:after_save(plan)
    pending=[];owners={};aliases=[];paused=False
    def flush():
        nonlocal paused
        if not pending or Path(cancel).exists():return
        # One atomic file marks ALL group members before any client call.
        for job,command in pending:
            job.update(status='running',attempts=job.get('attempts',0)+1,submission_state='may_have_started')
        plan['active_batch']=[job['id'] for job,command in pending]
        plan['batch_progress']={'size':len(pending),'limit':batch_size,
                               'confirmed':sum(j['status'] in SUCCESS for j in plan['jobs']),
                               'total':len(plan['jobs'])}
        save()
        requests=[{'asset':j['target_asset'],'command':c,'new_intent_completed':bool(j.get('previous_completed_intent'))} for j,c in pending]
        results=execute_batch(requests,cancel)
        if len(results)!=len(pending):raise ValueError('batch_result_count_mismatch')
        if any(str(r.get('asset'))!=str(req['asset']) for r,req in zip(results,requests)):
            raise ValueError('batch_result_identity_mismatch')
        for (job,command),result in zip(pending,results):
            reason=result.get('reason');state=result.get('status','pending_confirmation')
            if reason in INTERRUPTIONS:state='pending_confirmation';paused=True
            if reason in ('cancel_requested','cancelled_escape'):paused=True
            # An unresolved submitted group owns the foreground workflow until
            # verified. Do not send later groups just because a new adapter
            # error code has not yet been added to INTERRUPTIONS.
            if state=='pending_confirmation':paused=True
            job.update(status=state,reason=reason,result=result.get('report_path'),
                       collection_persisted=result.get('collection_persisted',False),
                       submission_state=result.get('submission_state','may_have_started') if command=='add' else 'may_have_started')
        pending.clear();plan.pop('active_batch',None);save()
    for job in plan['jobs']:
        # Prefer an already-confirmed owner even if it occurs later in the plan.
        if job['status'] in SUCCESS:owners[(job['target'],job['source_sha256'])]=job
    try:
        for job in plan['jobs']:
            if Path(cancel).exists() or paused:break
            if job['status'] in SUCCESS or job['status'] in ('failed','waiting_original') or job.get('preparation_error'):continue
            key=(job['target'],job['source_sha256'])
            if key in owners and owners[key] is not job:
                aliases.append((job,owners[key]));continue
            owners[key]=job
            source=load_asset(job['source_asset']);target=load_asset(job['target_asset'])
            if source['source_sha256']!=job['source_sha256'] or target['source_sha256']!=job['source_sha256']:
                raise ValueError('job_asset_changed')
            # Only queued work or a proven pre-submit interruption can be added.
            first=job['status']=='queued' or job.get('submission_state')=='not_started'
            if first:
                check=source_check(job['source_asset']);job['source_recheck']=check.get('report_path')
                if Path(cancel).exists():break
                if check.get('status') not in SUCCESS:
                    job.update(status='pending_confirmation',reason='source_favorite_not_reconfirmed',
                               source_reason=check.get('reason'),submission_state='not_started')
                    save()
                    # Do not submit part of a prepared group with a failed source.
                    paused=True;break
            pending.append((job,'add' if first else 'verify'))
            if len(pending)==batch_size:
                flush()
        if not paused:flush()
        for alias,owner in aliases:
            if owner['status'] in SUCCESS:
                alias.update(status='already_exists',reason='duplicate_of_confirmed_job',duplicate_of=owner['id'],
                             result=owner.get('result'),collection_persisted=owner.get('collection_persisted',False),submission_state='not_started')
            else:alias.update(status='pending_confirmation',reason='duplicate_result_pending',submission_state='not_started')
    except Exception:
        plan['run_state']='paused';save();raise
    plan['run_state']='cancelled' if Path(cancel).exists() else 'paused' if paused else 'finished'
    save();return plan
