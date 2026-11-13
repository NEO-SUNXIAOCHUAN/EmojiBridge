"""Acquire every selected WeChat original first, then import bounded QQ groups."""
from collections import Counter
from datetime import datetime
from pathlib import Path
from emoji_bridge import catalog
from emoji_bridge.state import save_json,single_instance
from emoji_bridge.transfer import make_export_plan,SUCCESS
from emoji_bridge.batch_transfer import run_qq_plan


def run(path,library_path,storage,resume=False,acquire=None,execute_batch=None,source_check=None,progress=None,preflight=None,clear_cancel=True):
    if execute_batch is None and preflight is None:
        from client_preflight import check_clients
        preflight=check_clients
    from wechat_acquire import index_session,acquire_selected
    from local_bridge import recheck_source
    from qq_batch_import import execute_batch as native_batch
    execute_batch=execute_batch or native_batch;source_check=source_check or recheck_source
    path=Path(path).resolve();plan=catalog.read(path);cancel=path.with_suffix('.cancel')
    if plan.get('schema')!='selected-workflow-v1' or plan['source_client']!='wechat':raise ValueError('wechat_to_qq_workflow_required')
    if resume and clear_cancel:cancel.unlink(missing_ok=True)
    batch=Path(plan.get('batch_plan',path.parent/(path.stem+'-qq-batch.json')))
    # Keep completed batch evidence immutable; a later explicit resume only
    # builds a new aggregate for the previously unavailable source items.
    if batch.exists() and all(j['status'] in SUCCESS for j in catalog.read(batch)['jobs']):
        completed=catalog.read(batch)
        for single in completed['jobs']:
            n=single['workflow_index'];child=Path(single['legacy_child']);old=catalog.read(child)
            if (not 0<=n<len(plan['jobs']) or old['jobs'][0]['id']!=single['id']
                    or child.resolve()!=path.parent.joinpath(path.stem+f'-item-{n}.json').resolve()):
                raise ValueError('batch_workflow_changed')
            plan['jobs'][n].update(status=single['status'],reason=single.get('reason'),result=single.get('result'),
                collection_persisted=single.get('collection_persisted',False),stage='transfer')
        plan['counts']=dict(Counter(j['status'] for j in plan['jobs']))
        if all(j['status'] in SUCCESS for j in plan['jobs']):
            plan['run_state']='finished';save_json(path,plan);return plan
        prior=plan.setdefault('completed_batch_plans',[])
        if str(batch) not in prior:prior.append(str(batch))
        batch=path.parent/(path.stem+f'-qq-batch-{len(prior)+1}.json')
    def save(n,stage):
        plan['counts']=dict(Counter(j['status'] for j in plan['jobs']))
        plan['progress']={'position':n+1,'total':len(plan['jobs']),'stage':stage}
        plan['progress']['confirmed']=sum(j['status'] in SUCCESS for j in plan['jobs'])
        if stage=='transfer':plan['progress']['batch_size']=plan.get('active_batch_size',0)
        plan['updated']=datetime.now().astimezone().isoformat();save_json(path,plan)
        if progress:progress(plan['progress'])
    with single_instance(path.with_suffix('.lock')),index_session():
        if all(j['status'] in SUCCESS for j in plan['jobs']):plan.pop('environment_block',None)
        if preflight and any(j['status'] not in SUCCESS for j in plan['jobs']):
            from client_preflight import pause_if_blocked
            if pause_if_blocked(plan,path,['qq'],preflight):return plan
        if not batch.exists():
            if acquire is None and execute_batch is native_batch:
                side=catalog.read(library_path)['clients']['wechat'];known={i['id']:i for i in side['items']}
                wanted=[j['item_id'] for n,j in enumerate(plan['jobs']) if j['status'] not in SUCCESS
                        and (j['status']!='pending_confirmation' or resume)
                        and not path.parent.joinpath(path.stem+f'-item-{n}.json').exists()
                        and known[j['item_id']].get('original_state')!='ready']
                if wanted:
                    from wechat_prepare import prepare
                    prepare(library_path,cancel,lambda n,total:save(0,'acquisition'),ids=wanted)
            jobs=[];ready=True
            for n,job in enumerate(plan['jobs']):
                if cancel.exists():ready=False;break
                if job['status'] in SUCCESS:continue
                child=path.parent/(path.stem+f'-item-{n}.json')
                try:
                    if not child.exists():
                        if job['status']=='failed' or (job['status']=='pending_confirmation' and not resume):
                            ready=False;continue
                        library=catalog.read(library_path);side=library['clients']['wechat']
                        item=next(i for i in side['items'] if i['id']==job['item_id'])
                        if item.get('original_state')!='ready':
                            job.update(status='running',stage='acquisition');save(n,'acquisition')
                            # The parallel selected pass already exhausted its
                            # finite attempts. Do not retry again in this loop.
                            if acquire is None and execute_batch is native_batch:
                                job.update(status='pending_confirmation',reason=item.get('reason','source_original_pending'))
                                ready=False;save(n,'acquisition');continue
                            result=acquire('wechat',item,side.get('source_report'),cancel) if acquire else acquire_selected(item,side['source_report'],cancel)
                            catalog.apply_acquisition(item,result);catalog.save(library,library_path)
                            job['acquisition_report']=result.get('report')
                            if item.get('original_state')!='ready':
                                job.update(status='pending_confirmation',reason=result.get('reason','source_original_pending'))
                                ready=False;save(n,'acquisition');continue
                        make_export_plan(catalog.transfer_selection(library,'wechat',[job['item_id']],storage),child)
                    data=catalog.read(child);single=dict(data['jobs'][0])
                    single['workflow_index']=n;single['legacy_child']=str(child)
                    jobs.append(single)
                    job.update(child_plan=str(child),stage='prepared',status=single['status'])
                    save(n,'prepared')
                except Exception as exc:
                    job.update(status='pending_confirmation',reason=str(exc));ready=False;save(n,'acquisition')
            if cancel.exists() or not jobs:
                plan['run_state']='cancelled' if cancel.exists() else 'paused'
                plan['batch_reason']='originals_not_all_prepared_no_new_submission';save(0,'prepared');return plan
            # Legacy per-item histories survive migration. This aggregate now
            # owns submission intent; never rebuild it after an interrupted run.
            save_json(batch,{'schema':'selected-transfer-v1','jobs':jobs,'scope':'explicit complete original selection',
                             'created':datetime.now().astimezone().isoformat()})
        plan['batch_plan']=str(batch)
        def mirror(data):
            indices=[j['workflow_index'] for j in data['jobs']]
            if len(set(indices))!=len(indices) or any(not 0<=n<len(plan['jobs']) for n in indices):raise ValueError('batch_workflow_changed')
            last=0;active=set(data.get('active_batch',[]))
            plan['active_batch_size']=len(active)
            for single in data['jobs']:
                n=single['workflow_index'];job=plan['jobs'][n]
                if single['id'] in active or single.get('result'):last=max(last,n)
                job.update(status=single['status'],reason=single.get('reason'),result=single.get('result'),
                           collection_persisted=single.get('collection_persisted',False),stage='transfer')
                child=Path(single['legacy_child']);old=catalog.read(child)
                if old['jobs'][0]['id']!=single['id']:raise ValueError('batch_child_changed')
                replacement={k:v for k,v in single.items() if k not in ('workflow_index','legacy_child')}
                if old['jobs'][0]!=replacement:
                    old['jobs']=[replacement]
                    old.update(counts={single['status']:1},run_state=data.get('run_state','running'));save_json(child,old)
            plan['run_state']=data.get('run_state','running')
            if plan['run_state']=='finished' and not all(j['status'] in SUCCESS for j in plan['jobs']):plan['run_state']='partial'
            save(last,'transfer' if any(j['status']=='running' for j in data['jobs']) else 'done')
        try:
            def dispatch(requests,token):
                if execute_batch is native_batch:
                    return execute_batch(requests,token,progress=lambda stage:save(0,stage))
                return execute_batch(requests,token)
            run_qq_plan(batch,dispatch,source_check,cancel,after_save=mirror)
            plan.pop('batch_reason',None)
        except Exception as exc:
            plan.update(run_state='paused',batch_reason=str(exc));save(0,'done')
        return plan
