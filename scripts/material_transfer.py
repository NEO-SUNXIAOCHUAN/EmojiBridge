"""Local-library adapter into the existing QQ and WeChat target engines."""
from collections import Counter
from pathlib import Path
import uuid

from emoji_bridge.materials import MaterialStore, now
from emoji_bridge.media import prepare_asset, load_asset, inspection_session
from emoji_bridge.state import save_json, single_instance
from emoji_bridge.wechat_index import key_scan_session


def account_label(profile, target, *, full=False):
    import json
    try:
        config=json.loads((Path(profile)/'runtime-data/client-sources.json').read_text(encoding='utf-8'))
        key='qq_ori' if target=='qq' else 'wechat_emoticon_db'
        if not config.get(key):return '该端尚未配置'
        parts=Path(config[key]).parts
        marker='nt_qq' if target=='qq' else 'db_storage'
        identity=parts[parts.index(marker)-1]
        return identity if full else '本人账号 · '+identity[-3:]
    except (OSError,ValueError,KeyError,TypeError):return '已确认本人配置'


def job_stage(job):
    """User-facing evidence level, independent for each target and byte digest."""
    if job.get('status') == 'desktop_confirmed' and job.get('confirmation_source') == 'user':
        return '用户已确认完成'
    if job.get('collection_verified') or job.get('status') in ('desktop_confirmed', 'already_exists'):
        return '已确认收藏'
    if job.get('historical_target_receipt'):return '核验历史结果（未重新发送）'
    if job.get('status') == 'add_executed': return '待收藏确认'
    if job.get('status') == 'batch_message_sent': return '已发送，待收藏确认'
    if job.get('file_submission') in ('send_requested','submitted_to_client','send_pending'): return '已交给客户端，发送待确认'
    if job.get('file_submission') == 'selected_not_sent': return '已选入客户端，尚未发送'
    if job.get('status') == 'running': return '转移中'
    if job.get('submission_state') == 'may_have_started': return '提交结果待核验'
    if job.get('status') == 'failed': return '失败'
    if job.get('status') == 'waiting_original': return '待取得原件'
    if job.get('status') == 'acquiring_original': return '正在取得原件'
    if job.get('status') == 'cancelled': return '已取消'
    return '转移中' if job.get('status') == 'running' else '等待转移' if job.get('target_asset') else '准备素材'


def plan_stage(plan,job):
    if plan.get('run_state')=='preparing_output':return '准备成品'
    stage=job_stage(job)
    if plan.get('run_state') in ('paused','cancelled') and stage=='转移中' and job.get('submission_state')=='may_have_started':return '提交结果待核验'
    if job.get('submission_state')=='not_started' and stage not in ('已确认收藏','用户已确认完成','失败','待取得原件'):
        if plan.get('run_state')=='cancelled':return '已取消，未提交'
        if plan.get('run_state')=='paused':return '已暂停，未提交'
    return stage


def recovery_text(plan):
    """Outcome and a next action, without treating a stopped worker as success."""
    jobs=plan.get('jobs',[])
    if plan.get('run_state')=='cancelled':return '已取消；完成项保留。可继续未完成项，已确认成功的不再提交。'
    waiting=sum(j.get('status')=='waiting_original' for j in jobs)
    if waiting:
        reasons=list(dict.fromkeys(j.get('reason','原件尚未取得') for j in jobs if j.get('status')=='waiting_original'))
        return f'等待原件 {waiting} 项，任务尚未完成。'+ '；'.join(reasons[:2])+' 打开来源客户端的表情收藏，待原图加载后点“继续 / 重试未完成”；沿用本任务。'
    if jobs and all(job_stage(j) in ('已确认收藏','用户已确认完成') for j in jobs):return '本次收藏已确认；作品和结果已保留。'
    uncertain=[j for j in jobs if j.get('submission_state')=='may_have_started' or j.get('file_submission') in ('send_requested','submitted_to_client','send_pending')]
    if uncertain:return '提交结果待核验；点“继续 / 重试未完成”先核验已有结果，不盲目重发。'
    reason=plan.get('pause_reason') or next((j.get('reason') for j in jobs if j.get('reason')), '')
    if plan.get('target')=='qq':
        from emoji_bridge.qq_controls import explain_error
        reason=explain_error(reason)
    else:
        from emoji_bridge.compatibility import REASONS
        reason={
            'own_transfer_entry_not_visible':'文件传输助手入口位置未通过核对，请打开微信文件传输助手后继续',
            'own_transfer_search_result_not_found':'没有读到唯一的文件传输助手搜索结果，请打开文件传输助手后继续',
            'own_transfer_search_not_empty':'微信搜索框已有其他内容，请保留需要的内容并打开文件传输助手',
            'own_transfer_navigation_not_confirmed':'尚未确认已进入文件传输助手，请打开该会话后继续',
            'wechat_main_window_not_unique_or_minimized':'未找到唯一的微信聊天主窗口，请登录微信并打开聊天窗口',
        }.get(reason,REASONS.get(reason,reason))
    if 'foreground' in reason:
        client='QQ 主聊天窗口' if plan.get('target')=='qq' else '微信文件传输助手'
        return f'尚未提交：未能保持目标窗口在前台。请将{client}放到前台，再点“继续 / 重试未完成”；已准备原件会复用。'
    if plan.get('run_state')=='paused':return '任务已暂停，尚未完成：'+(reason or '客户端尚未就绪')+'。处理后点“继续 / 重试未完成”。'
    return '本轮处理停止；请查看各项结果，失败项可重试，未确认项先核验。'


def prior_jobs(store, plan, profile, current):
    """Only durable same-account/same-target/same-bytes evidence may be inherited."""
    from emoji_bridge.catalog import read
    found = {}
    for file in sorted((store.root / 'tasks').glob('*.json'), reverse=True):
        if file.resolve() == current.resolve(): continue
        try: previous = read(file)
        except (OSError, ValueError): continue
        if (not previous.get('profile') or Path(previous['profile']).resolve()!=Path(profile).resolve()
                or previous.get('target') != plan['target']):continue
        for job in previous.get('jobs', []):
            if job['item_id'] in found: continue
            if (job.get('collection_verified') or job.get('status') in ('desktop_confirmed', 'already_exists', 'add_executed')
                    or job.get('submission_state') == 'may_have_started'):
                found[job['item_id']] = {**job, 'previous_plan': str(file)}
    return found


def refresh_target(target, cancel, progress=None):
    """Explicit user-requested source refresh, never a send or collection mutation."""
    from emoji_bridge import catalog
    # Source updates and target refresh write the same catalog. Hold the same
    # account resource, in the same order as the ordinary refresh worker.
    with single_instance(catalog.PATH.parent/'collection.lock'):
        return _refresh_target_locked(target,cancel,progress)


def _refresh_target_locked(target,cancel,progress=None):
    from emoji_bridge import catalog
    catalog.bootstrap(catalog.PATH)  # Offline-library users may never have opened the client list.
    result={'state': 'done', 'at': now()}
    if target == 'wechat':
        from scan_view import observed_ids,snapshot_key
        before=observed_ids(catalog.read(catalog.PATH)['clients']['wechat'])
        from wechat_prepare import prepare
        value = prepare(catalog.PATH, cancel, index_only=True, preview_first=False)
        if value.get('status') != 'index_ready': raise ValueError(value.get('reason', '微信索引未就绪'))
        after=catalog.read(catalog.PATH)['clients']['wechat']
        result.update(wechat_recent_ids=sorted(observed_ids(after)-before),wechat_snapshot=list(snapshot_key(after)))
    else:
        from qq_catalog import scan, MAX_SCAN_VIEWS
        path, value = scan(MAX_SCAN_VIEWS, cancel)
        if not value.get('items'): raise ValueError(value.get('reason', 'QQ 收藏列表未读到；原结果保留'))
        library = catalog.read(catalog.PATH); catalog.merge_qq(library, path, cancel=cancel.exists, match_originals=False); catalog.save(library)
    return result


def create(store, ids, target, path):
    if target not in ('qq', 'wechat') or not ids:
        raise ValueError('explicit_selection_required')
    if Path(path).exists():
        raise ValueError('plan_already_exists')
    jobs = []
    for ident in dict.fromkeys(ids):
        item = store.get(ident)
        jobs.append({'id': str(uuid.uuid4()), 'item_id': ident, 'name': item['name'],
                     'source_sha256': ident, 'target': target, 'status': 'queued',
                     'attempts': 0, 'submission_state': 'not_started'})
    plan = {'schema': 'selected-transfer-v1', 'source_kind': 'local_material_library',
            'library_root': str(store.root), 'target': target, 'jobs': jobs, 'created': now(),
            'scope': 'explicit user-imported files; not claimed as client favorites'}
    from emoji_bridge.compatibility_copy import settings
    plan['compatibility']=settings(store.root,target)
    save_json(path, plan)
    return plan


@key_scan_session()
def run(path, data_root, *, resume=False, clear_cancel=True, progress=None, preflight=None, wx_execute=None, qq_execute=None, refresher=None):
    # A local plan can be created before the shell chooses a client account.
    # Import account-bound modules only at execution, after configure_data_root.
    from emoji_bridge import catalog
    from emoji_bridge.transfer import SUCCESS
    DONE = (*SUCCESS, 'add_executed')
    path = Path(path).resolve(); data_root = Path(data_root).resolve()
    plan = catalog.read(path); cancel = path.with_suffix('.cancel')
    if plan.get('source_kind') != 'local_material_library':
        raise ValueError('local_material_plan_required')
    store = MaterialStore(plan['library_root'])
    if resume and clear_cancel:
        cancel.unlink(missing_ok=True)

    def save(value=None):
        from emoji_bridge.state import task_progress
        task_progress(plan.get('stage') or plan.get('run_state','准备互通'))
        plan['counts'] = dict(Counter(j['status'] for j in plan['jobs']))
        plan['updated'] = now()
        save_json(path, plan)
        if progress:
            progress(plan)

    plan_owned=False
    def waiting(owner):
        if not plan_owned:
            if progress:progress(dict(plan,waiting_for=owner or {}))
            return
        if owner:plan['waiting_for']=owner
        else:plan.pop('waiting_for',None)
        save()
    from emoji_bridge.state import task_scope
    execution_bound=False
    with task_scope(path.stem,'转到'+('QQ' if plan['target']=='qq' else '微信'),cancel=cancel.exists,on_wait=waiting), single_instance(path.with_suffix('.lock')), inspection_session():
        # Another executor may have finished this SAME plan while we waited.
        # Never overwrite its journal or re-submit from the pre-wait snapshot.
        plan=catalog.read(path);plan_owned=True;plan.pop('waiting_for',None)
        try:
            # Bind once to the chosen profile: another account must not inherit successes.
            if plan.get('profile') and Path(plan['profile']) != data_root:
                raise ValueError('请使用创建此队列时的同一账号配置')
            execution_bound=True
            from collection_transfer import check_profile
            check_profile(plan, data_root)
            plan.pop('pause_reason', None)
            plan['profile'] = str(data_root); plan['run_state'] = 'preparing'
            if plan.get('source_selection'):
                from collection_transfer import prepare
                prepare(plan, path, data_root, store, cancel, save)
            prior = prior_jobs(store, plan, data_root, path)
            for job in plan['jobs']:
                if job.get('attempts', 0) == 0 and job['item_id'] in prior:
                    # Reuse target evidence, never overwrite this selection's
                    # source observation/binding with a different earlier row.
                    fields=('status','attempts','submission_state','result','previous_plan',
                            'target_asset','conversion','prepared_metadata','collection_verified',
                            'collection_persisted','completion_check','membership_evidence',
                            'confirmation_source','file_selection_step','file_submission',
                            'file_path_verified','file_window_observation','pause_window','reason','retry_approval')
                    job.update({k:v for k,v in prior[job['item_id']].items() if k in fields})
                    if job['status'] in SUCCESS or job.get('collection_verified'):
                        # A NEW user intent must not turn a historical receipt
                        # into proof of current membership. Keep the receipt,
                        # but recheck only this item/batch, never resubmit it.
                        job['historical_target_receipt']={k:job.get(k) for k in ('status','result','collection_verified','previous_plan')}
                        job.update(status='pending_confirmation',collection_verified=False,
                                   collection_persisted=False,submission_state='may_have_started',
                                   reason='historical_membership_requires_verification')
                    if job.get('target_asset'):job.setdefault('source_asset',job['target_asset'])
            save()
            for job in plan['jobs']:
                if job['item_id'].startswith('catalog:'): continue
                if job['status'] in SUCCESS or (job['status']=='add_executed' and job.get('collection_verified')):
                    continue
                if ((job.get('source_ref') or {}).get('client')==plan['target'] and not job.get('attempts')
                        and job.get('submission_state','not_started')=='not_started'):
                    job.update(status='failed',preparation_error='来源与目标相同，请在来源页选择另一端',reason='来源与目标相同，该项未提交')
                    save();continue
                if cancel.exists():
                    plan['run_state'] = 'cancelled'; save(); return plan
                try:
                    if job.get('target_asset'):
                        load_asset(job['target_asset']); continue
                    source = store.original(job['item_id'])
                    from client_material_import import Cancel
                    asset, info = prepare_asset(source, plan['target'], data_root / 'runtime-data/material-assets',cancel=Cancel(cancel),**plan.get('compatibility',{}))
                    job.update(source_asset=str(asset), target_asset=str(asset), conversion=info['conversion'],
                               prepared_metadata=info['prepared_metadata'],source_kind='local_material_library', status='queued')
                    job.pop('preparation_error',None)
                except (ValueError,OSError) as exc:
                    job.update(status='failed', preparation_error=str(exc), reason='原件准备失败：'+str(exc))
                save()
            if preflight is None:
                from client_preflight import check_clients
                preflight = check_clients
            from client_preflight import pause_if_blocked
            if cancel.exists():
                plan['run_state'] = 'cancelled'; save(); return plan
            if all(j['status'] in SUCCESS or (j['status'] == 'add_executed' and j.get('collection_verified'))
                   for j in plan['jobs']):
                plan['run_state'] = 'finished'; save(); return plan
            if not any(j.get('target_asset') and not j.get('preparation_error') and j['status'] not in SUCCESS for j in plan['jobs']):
                plan['run_state'] = 'paused'; save(); return plan
            check_profile(plan, data_root)
            if pause_if_blocked(plan, path, [plan['target']], preflight):
                save(); return plan
            plan['run_state'] = 'running'; save()
            if plan['target'] == 'qq':
                from emoji_bridge.batch_transfer import run_qq_plan
                if qq_execute is None:
                    from qq_batch_import import execute_batch
                    def qq_execute(requests,token):
                        def present_stage(stage):
                            # Forward adapter observations without rewriting
                            # the runner's durable submission/result ledger.
                            if progress:progress(dict(catalog.read(path),stage=stage))
                        return execute_batch(requests,token,progress=present_stage)
                execute_target=qq_execute
                def guarded_qq(*args,**kwargs):
                    check_profile(plan,data_root)
                    return execute_target(*args,**kwargs)

                def source_check(asset):
                    check_profile(plan, data_root)
                    info = load_asset(asset)
                    store.original(info['source_sha256'])
                    return {'status': 'already_exists', 'method': 'owned_original_digest', 'report_path': str(store.db)}

                # Retry only proven pre-submit failures; native ledger still guards unknowns.
                if resume:
                    for job in plan['jobs']:
                        if job['status'] not in DONE and not job.get('preparation_error') and job.get('submission_state') == 'not_started':
                            job['status'] = 'queued'
                    save()
                plan = run_qq_plan(path, guarded_qq, source_check, cancel, after_save=progress, batch_size=5)
            else:
                from wechat_retry import valid
                approvals = {str(Path(j['target_asset']).resolve()): j['retry_approval'] for j in plan['jobs']
                             if j.get('target_asset') and valid(j['target_asset'], j.get('retry_approval'), data_root)}
                for job in plan['jobs']:
                    if job.get('target_asset') and str(Path(job['target_asset']).resolve()) in approvals and job['status'] not in DONE:
                        job.update(status='queued', submission_state='not_started')
                save()
                if wx_execute is None:
                    from functools import partial
                    from emoji_bridge.client_sources import settings
                    from wechat_batch import execute
                    config = settings()
                    source = config.get('wechat_emoticon_db') if config.get('read_authorized') else None
                    # Same authenticated membership check, no previous full-library scan required.
                    wx_execute = partial(execute, index_source=source, retry_approvals=approvals)

                def merge(result):
                    for job in plan['jobs']:
                        if not job.get('target_asset'): continue
                        outcome = result.get('results', {}).get(str(Path(job['target_asset']).resolve()))
                        if not outcome:
                            continue
                        for key in ('status', 'reason', 'collection_verified', 'collection_persisted',
                                    'completion_check', 'membership_evidence', 'submission_state', 'file_selection_step', 'file_submission', 'file_path_verified', 'file_window_observation','pause_window'):
                            if key in outcome:
                                job[key] = outcome[key]
                            elif key in ('file_selection_step','file_submission','file_path_verified','file_window_observation','pause_window'):
                                job.pop(key,None)
                        if outcome.get('report_path'):
                            job['result'] = outcome['report_path']
                    plan['stage'] = result.get('stage', 'transfer'); save()

                unknown = [j for j in plan['jobs'] if j['status'] not in SUCCESS and not j.get('collection_verified') and
                           (j.get('submission_state') == 'may_have_started' or j['status'] == 'add_executed')]
                if unknown:
                    check_profile(plan, data_root)
                    merge(wx_execute(list(dict.fromkeys(j['target_asset'] for j in unknown)), cancel, verify_only=True))
                    from wechat_batch_workflow import sent_unadded
                    recover = [j for j in unknown if j['status'] not in DONE and sent_unadded(j)]
                    if recover and not cancel.exists():
                        merge(wx_execute([j['target_asset'] for j in recover], cancel, resume_sent=True, progress=merge))
                    # A complete, proven unsent draft can be resumed in place.
                    # Never reopen the picker or clear a user's changed input.
                    from wechat_retry import staged_evidence
                    staged=[j for j in unknown if j['status'] not in DONE]
                    if resume and staged and not cancel.exists() and staged_evidence([j['target_asset'] for j in staged],data_root):
                        merge(wx_execute([j['target_asset'] for j in staged],cancel,resume_staged=True,progress=merge))
                    if any(j['status'] not in DONE for j in unknown):
                        plan['run_state'] = 'paused'; save(); return plan
                fresh = [j for j in plan['jobs'] if j['status'] not in DONE and not j.get('preparation_error')]
                if fresh and not cancel.exists():
                    check_profile(plan, data_root)
                    for job in fresh:
                        job.update(status='running', submission_state='may_have_started', attempts=job['attempts'] + 1)
                    save()  # Durable before handing control to the native five-at-a-time engine.
                    merge(wx_execute(list(dict.fromkeys(j['target_asset'] for j in fresh)), cancel, progress=merge))
            for job in plan['jobs']:
                if job.get('historical_target_receipt') and job['status'] in SUCCESS:
                    job.update(status='already_exists',reason='current_target_membership_reverified')
            plan['run_state'] = ('cancelled' if cancel.exists() else
                                 'finished' if all(j['status'] in DONE for j in plan['jobs']) else 'paused')
        except Exception as exc:
            # A batch engine may have persisted partial successes before raising.
            # Never replace those durable results with our pre-call copy.
            plan=catalog.read(path)
            plan['run_state'] = 'cancelled' if cancel.exists() else 'paused'
            plan['pause_reason'] = str(exc)
        # Refresh is a separate result. Failure never changes collection evidence
        # and never invokes the transfer engine again.
        confirmed = any(job_stage(j) == '已确认收藏' for j in plan['jobs'])
        if execution_bound and confirmed and refresher and not cancel.exists() and not plan.get('target_refresh'):
            plan['target_refresh'] = {'state': 'running'}; save()
            try:
                plan['target_refresh'] = refresher(plan['target'], cancel)
            except Exception as exc:
                plan['target_refresh'] = {'state': 'failed', 'reason': str(exc), 'at': now()}
        save()
    return plan
