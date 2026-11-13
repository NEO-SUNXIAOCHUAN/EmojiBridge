"""Prepare once; send/add five at a time; no favorites-panel check."""
from datetime import datetime
from pathlib import Path
import time,hashlib,json
from emoji_bridge.state import save_json,single_instance
from emoji_bridge.windows import StopAutomation,qq_windows,dialog_action,dialog_controls,selection_text,click,scroll,guard,user
from emoji_bridge.windows import foreground_dialog,dialog_owned_by,filename_is_empty,activate
from emoji_bridge.windows import pid_of,class_name,process_path
from emoji_bridge.message_media import staged_matches,row_regions,match_rows,prepare_rows,WeChatFrameMatcher
from emoji_bridge.client_sources import settings
from local_bridge import ROOT,OrdinaryImport,relative,recheck_media_cell
from emoji_bridge.wechat_index import key_scan_session
from emoji_bridge.client_geometry import client_scale


DONE=('desktop_confirmed','already_exists','add_executed')
SUBMITTED=('batch_message_sent','batch_message_submitted','batch_send_requested')
INITIAL_ADD_WAIT=0
# User-selected operating size, not a claimed WeChat upload limit.
SEND_GROUP_SIZE=5


def staged_identity(q,runners,snap):
    if not snap.get('input_only_media_objects') or snap.get('media_object_count')!=len(runners):
        raise StopAutomation('composer_not_expected_media_batch')
    rect=relative(snap['input'],q.window);image=q.frame().crop(rect);hits=[]
    for runner in runners:
        found=staged_matches(image,runner.refs,runner.matcher)
        runner.report['staged_candidates']=len(found)
        if getattr(runner.matcher,'last_spatial_check',None):runner.report['candidate_spatial_check']=runner.matcher.last_spatial_check
        if len(found)!=1:raise StopAutomation('staged_batch_item_not_unique')
        if any(abs(found[0].center[0]-h.center[0])<8 and abs(found[0].center[1]-h.center[1])<8 for h in hits):
            raise StopAutomation('staged_batch_items_overlap')
        hits.append(found[0])
    return rect,hits


def latest_messages(q,cancelled=lambda:None):
    cancelled()
    meta=q.uia('latest-messages')
    if meta.get('scroll',{}).get('supported'):return
    # RuntimeIds are virtual row handles, not durable message IDs. Use them
    # only for immediate geometry stability, never to blacklist future rows.
    previous=None
    for _ in range(12):
        cancelled()
        meta=q.uia('message-rows');area,rows=row_regions(meta,q.window,q.frame().size)
        layout=tuple(rows)
        if layout==previous:return
        previous=layout
        scroll(q.window,q.exe,area[2]-20,(area[1]+area[3])//2,-3);time.sleep(.15)


from emoji_bridge.timing import measured,stage as timing_stage

@measured("adding")
def add_visible(active,q,folder,timeout=60,progress=None,search_history=False,recheck_rejected=None):
    latest_messages(q,active[0].cancelled);remaining=list(active);views=0;total_views=0;started=time.perf_counter()
    max_views=20 if search_history else max(4,len(active)*2)
    deadline=time.monotonic()+timeout;seen=search_history;waits=0;match_passes=0
    search_head=remaining[0];order=[];forward=False;geometry_seconds=0.;matching_seconds=0.;diagnostic_saved=False
    trace={'order':'selected batch order','total':len(active),'completed_positions':order,
           'state':'waiting_for_first_message','send_calls':0}
    def trace_state(state,runner,**extra):
        trace.update(state=state,next_position=active.index(runner)+1,**extra)
        save_json(folder/'add-order.json',trace)
    trace_state('waiting_for_first_message',search_head)
    # Read native readiness immediately; a fixed post-send delay cannot prove
    # upload completion. Keep this field in timing evidence for comparison.
    initial_wait=0 if search_history else min(INITIAL_ADD_WAIT,timeout)
    settle_until=time.monotonic()+initial_wait
    if initial_wait and progress:progress('waiting_media')
    while time.monotonic()<settle_until:
        remaining[0].cancelled();time.sleep(min(.1,max(0,settle_until-time.monotonic())))
    def wait_ready():
        nonlocal waits
        waits+=1
        save_json(folder/'readiness.json',{'state':'waiting_for_addable_message','remaining':len(remaining),
                  'polls':waits,'seconds':round(time.perf_counter()-started,4),
                  'delivery_confirmed':False,'resend_calls':0})
        if progress:progress('waiting_media')
        if time.monotonic()>=deadline:raise StopAutomation('wechat_media_not_ready_no_resend')
        remaining[0].cancelled();time.sleep(.25)
    while remaining:
        match_passes+=1
        remaining[0].cancelled();meta=q.uia('message-rows');frame=q.frame()
        area,rows=row_regions(meta,q.window,frame.size);candidates=[]
        scale=client_scale(q.window.dpi)
        geometry_start=time.perf_counter();prepared=prepare_rows(frame,rows,scale)
        geometry_seconds+=time.perf_counter()-geometry_start;matching_start=time.perf_counter()
        for runner in remaining:
            runner.cancelled()
            # A later easy match must not prevent the earlier item's bounded
            # geometry fallback from running (transparent images in particular).
            for fallback in (False,True):
                hits=match_rows(frame,rows,runner.refs,runner.matcher,fallback,prepared_rows=prepared,scale=scale)
                if len(hits)>1:raise StopAutomation('multiple_matching_batch_messages')
                if len(hits)==1:
                    identity,hit=hits[0];row=next(r for ident,r in rows if ident==identity)
                    candidates.append((runner,hit,identity,row))
                    break
                if getattr(runner.matcher,'batch_geometry_only',False) is True:break
        matching_seconds+=time.perf_counter()-matching_start
        if candidates:seen=True
        head_found=any(c[0] is remaining[0] for c in candidates)
        if search_head is not remaining[0]:
            search_head=remaining[0]
            # Continue towards newer rows from the last confirmed image. Do
            # not jump to the tail and re-search all earlier rows for each item.
            if order:forward=True;views=0;seen=True
        if head_found:
            for runner in list(remaining):
                candidate=next((c for c in candidates if c[0] is runner),None)
                if candidate is None:break
                _,hit,identity,row=candidate
                runner.cancelled()
                if sum(abs(c[1].center[0]-hit.center[0])<8 and abs(c[1].center[1]-hit.center[1])<8 for c in candidates)!=1:
                    raise StopAutomation('batch_message_matches_multiple_assets')
                trace_state('checking_message',runner)
                action_started=time.perf_counter()
                try:runner.add_wechat_message(located=(hit,identity,row))
                except StopAutomation as exc:
                    if str(exc)=='wechat_add_rejected' and runner.report.get('add_rejected_by_client') is True and recheck_rejected:
                        retries=runner.report.get('native_add_retries',0)
                        if retries>=2:raise
                        # Fast path has no extra scan or delay. Only an exact
                        # client rejection can enter this bounded add-only path.
                        q.dismiss_import_rejection()
                        runner.report['native_add_retries']=retries+1
                        trace_state('checking_rejected_add',runner,retries=retries+1)
                        recheck_rejected([runner])
                        if runner.report.get('collection_verified') is True:
                            remaining.remove(runner);order.append(active.index(runner)+1)
                            continue
                        runner.report.pop('add_rejected_by_client',None)
                        # Let the server recover only after a rejection; the
                        # normal path and later successful items never wait.
                        until=min(deadline,time.monotonic()+min(2,retries+1))
                        while time.monotonic()<until:
                            runner.cancelled();time.sleep(max(0,min(.1,until-time.monotonic())))
                        if time.monotonic()>=deadline:raise
                        break # re-locate current row/pixels; never reuse coordinates
                    # These happen before the durable favorite_pending boundary.
                    # Never retry an uncertain add click or a changed foreground.
                    trace_state('waiting' if str(exc) in ('message_not_ready_to_add','wechat_context_menu_not_ready','message_moved') else 'stopped',runner,reason=str(exc))
                    if str(exc) not in ('message_not_ready_to_add','wechat_context_menu_not_ready','message_moved'):raise
                    # Do not overtake this message. These failures are before
                    # the add boundary; an uncertain click is never retried.
                    wait_ready()
                    break
                runner.report.setdefault('timings_seconds',{})['add_action']=round(time.perf_counter()-action_started,4)
                runner.record('add_executed');runner.report.update(status='add_executed',
                    reason='add_action_completed',collection_verified=False,collection_persisted=False,
                    batch_position=active.index(runner)+1)
                save_json(runner.evidence/'result.json',runner.report);remaining.remove(runner)
                deadline=time.monotonic()+timeout
                order.append(active.index(runner)+1)
                trace_state('completed' if not remaining else 'adding_in_order',remaining[0] if remaining else runner,reason=None)
                if progress:progress('transfer')
                # Continue the already matched visible group. Each action
                # rechecks its own current native row AND pixels immediately
                # before clicking; a moved row returns to relocation below.
            continue
        trace_state('locating_next_message',remaining[0])
        # Keep one diagnostic view, not synchronous PNG writes on every wheel.
        if not diagnostic_saved:
            frame.crop(area).save(folder/'unmatched-visible-messages.png');diagnostic_saved=True
        if search_history and views>=max_views:
            save_json(folder/'readiness.json',{'state':'submitted_messages_not_found_in_bounded_history',
                      'remaining':len(remaining),'scroll_views':total_views,'resend_calls':0})
            raise StopAutomation('wechat_submitted_messages_not_found_no_resend')
        if not seen or views>=max_views:
            wait_ready()
            if seen:latest_messages(q,remaining[0].cancelled);views=0;seen=False;forward=False
            continue
        scroll(q.window,q.exe,area[2]-20,(area[1]+area[3])//2,-2 if forward else 2);views+=1;total_views+=1;time.sleep(.15)
    save_json(folder/'add-visible.json',{'added':len(active),'scroll_views':total_views,
        'seconds':round(time.perf_counter()-started,4),'readiness_polls':waits,
        'match_passes':match_passes,'initial_settle_seconds':initial_wait,
        'order':'selected batch order','completed_positions':order,
        'geometry_seconds':round(geometry_seconds,4),'matching_seconds':round(matching_seconds,4)})


def exact_member(asset, hashes, cancelled=lambda:None):
    """Accept the submitted copy or SHA-validated intact original, never a cover.

    WeChat can already contain the original while the independent compatibility
    copy has a different MD5. Matching either exact file in this account's fresh
    authenticated index is membership evidence, not proof of a new upload.
    """
    for field in ('prepared','original_copy'):
        value=asset.get(field)
        if not value:continue
        md5=hashlib.md5();sha=hashlib.sha256()
        try:
            with Path(value).open('rb') as stream:
                while chunk:=stream.read(1024*1024):
                    cancelled();md5.update(chunk);sha.update(chunk)
        except OSError:
            # An optional old copy may have been cleaned up. It grants no
            # membership, but must not discard another item's valid proof.
            if field=='original_copy':continue
            raise
        expected=asset.get('source_sha256' if field=='original_copy' else 'prepared_sha256')
        if field=='original_copy' and (not expected or sha.hexdigest()!=expected):continue
        if field=='prepared' and expected and sha.hexdigest()!=expected:
            raise ValueError('prepared_file_changed')
        if md5.hexdigest() in hashes:return md5.hexdigest(),field
    return None,None


def require_current_index(report, previous):
    if (report.get('status')!='index_decrypted_and_integrity_verified'
            or not report.get('snapshot_current_consistent') or report.get('source')!=previous.get('source')):
        raise ValueError('local_membership_snapshot_unproven')


@measured("verification")
def confirm_index(runners,folder,cancel=None,source=None):
    """One fresh, read-only local membership check for the whole batch.

    Missing/unavailable is unknown, not evidence of failed upload, and never
    authorizes retry. No favorites panel, animation wait or chat manipulation.
    """
    from emoji_bridge import catalog
    from wechat_acquire import current_index,cancelled
    cancelled(cancel)
    eligible=[r for r in runners if r.report.get('status')=='add_executed' or
              (r.report.get('status')=='pending_confirmation' and r.report.get('submission_state')=='may_have_started')]
    if not eligible:return
    started=time.perf_counter()
    try:
        previous=({'source':str(source)} if source is not None else
                  catalog.read(catalog.read(ROOT/'runtime-data/T005/library.json')['clients']['wechat']['source_report']))
        members,report=current_index(previous,cancel)
        require_current_index(report,previous)
        cancelled(cancel)
        proof=folder/'completion-index.json';save_json(proof,report)
        hashes={m['md5'] for m in members}
        for r in eligible:
            cancelled(cancel)
            try:
                digest,representation=exact_member(r.asset,hashes,lambda:cancelled(cancel))
            except (OSError,ValueError) as exc:
                r.report.update(completion_check='local_media_unavailable',
                                membership_error_type=type(exc).__name__)
                continue
            found=digest is not None
            r.report.update(collection_verified=found,collection_persisted=False,
                            completion_check='confirmed_in_local_index' if found else 'not_yet_in_local_index',
                            membership_evidence=str(proof),member_md5=digest,member_representation=representation,
                            membership_scope='authenticated local snapshot; phone and reopen not tested')
            if found and r.report.get('status')=='pending_confirmation':
                r.report.update(status='already_exists',reason='exact_file_in_authenticated_local_favorites_index')
                r.record('already_exists')
        save_json(folder/'completion-summary.json',{'checked':len(eligible),
                  'confirmed':sum(r.report.get('collection_verified',False) for r in eligible),
                  'seconds':round(time.perf_counter()-started,4),'client_ui_calls':0})
    except Exception as exc:
        if str(exc) in ('cancel_requested','cancelled_escape'):raise
        for r in eligible:r.report['completion_check']='local_index_unavailable'
        save_json(folder/'completion-summary.json',{'status':'unavailable','error_type':type(exc).__name__,
                  'seconds':round(time.perf_counter()-started,4),'client_ui_calls':0})


@measured("deduplication")
def skip_index_members(runners,folder,cancel,source=None):
    """Pre-add dedupe from the authenticated local index, no favorites panel."""
    from emoji_bridge import catalog
    from wechat_acquire import current_index
    path=ROOT/'runtime-data/T005/library.json'
    if not path.exists() and source is None:raise StopAutomation('wechat_favorites_check_unavailable')
    started=time.perf_counter()
    try:
        previous=({'source':str(source)} if source is not None else
                  catalog.read(catalog.read(path)['clients']['wechat']['source_report']))
        if source is None and previous.get('status')!='index_decrypted_and_integrity_verified':
            raise StopAutomation('wechat_favorites_check_unavailable')
        members,report=current_index(previous,cancel)
        require_current_index(report,previous)
        proof=folder/'pre-add-index.json';save_json(proof,report)
        hashes={m['md5'] for m in members};matched=[]
        for r in runners:
            from wechat_acquire import cancelled
            try:
                digest,representation=exact_member(r.asset,hashes,lambda:cancelled(cancel))
            except (OSError,ValueError) as exc:
                r.report.update(membership_check='local_media_unavailable',
                                membership_error_type=type(exc).__name__)
                continue
            if digest is None:continue
            r.report.update(status='already_exists',reason='exact_file_in_authenticated_local_favorites_index',
                            collection_verified=True,collection_persisted=False,
                            membership_evidence=str(proof),member_md5=digest,member_representation=representation,
                            membership_scope='current authenticated local snapshot')
            r.record('already_exists');matched.append(str(r.asset_path))
        save_json(folder/'pre-add-dedupe.json',{'matched':matched,'seconds':round(time.perf_counter()-started,4),
                  'client_ui_calls':0,'post_add_check':False})
    except Exception as exc:
        if str(exc) in ('cancel_requested','cancelled_escape'):raise
        # A missing dedupe proof must not silently become permission to send.
        save_json(folder/'pre-add-dedupe.json',{'status':'unavailable','error_type':type(exc).__name__})
        raise StopAutomation('wechat_favorites_check_unavailable') from exc


@key_scan_session()
def execute(assets,cancel=None,resume_sent=False,progress=None,retry_approvals=None,verify_only=False,index_source=None,resume_staged=False):
    if not assets:raise ValueError('empty_wechat_batch')
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f');folder=ROOT/'private/T006/wechat-batches'/stamp
    folder.mkdir(parents=True);runners=[];q=None;started=time.perf_counter()
    current=[];group_info=None
    # Library users can legitimately have no full bridge catalog. Verification
    # must use the explicitly authorized account path, just like that entrypoint.
    if index_source is None:
        config=settings()
        if config.get('read_authorized'):index_source=config.get('wechat_emoticon_db')
    index_options={'source':index_source} if index_source is not None else {}
    def notify(stage):
        from emoji_bridge.state import task_progress
        task_progress(stage)
        if progress:progress({'stage':stage,'send_group':group_info,
                              'results':{str(r.asset_path):dict(r.report) for r in runners}})
    try:
        with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
            if resume_staged:
                from wechat_retry import staged_evidence
                if not staged_evidence(assets,ROOT):raise StopAutomation('staged_batch_history_not_proven')
            for n,asset in enumerate(assets):
                evidence=folder/str(n);evidence.mkdir();report={'command':'batch-add','acceptance':'add_action_then_local_index_no_panel',
                    'collection_verified':False,'collection_persisted':False,'animation':{'status':'not_tested'}}
                runner=OrdinaryImport(asset,report,evidence,cancel);runners.append(runner)
                # Standard outgoing rows use native geometry/full-frame checks.
                # Do not search every GIF pose over unrelated chat history.
                if isinstance(runner.matcher,WeChatFrameMatcher):runner.matcher.batch_geometry_only=True
                report['dedupe_scope']='local completed journal only; target favorites not inspected'
                if runner.target!='wechat' or runner.asset.get('source_only'):raise ValueError('wechat_target_asset_required')
                if runner.prior:
                    phase=runner.prior['status']
                    report['prior_phase']=phase
                    if phase in DONE:
                        report['status']='pending_confirmation'
                        report['reason']='historical_membership_requires_verification'
                    elif phase=='batch_send_pending' and resume_staged:
                        if runner.prior.get('prepared_sha256')!=runner.asset['prepared_sha256']:raise ValueError('staged_batch_original_changed')
                    elif phase in SUBMITTED and resume_sent:
                        if runner.prior.get('prepared_sha256')!=runner.asset['prepared_sha256']:
                            raise ValueError('sent_batch_original_changed')
                    elif phase!='not_submitted':
                        from wechat_retry import PRE_SEND,valid
                        approval=(retry_approvals or {}).get(str(runner.asset_path))
                        if phase in PRE_SEND and valid(runner.asset_path,approval,ROOT):
                            report.update(submission_state='not_started',retry_approval=approval)
                        else:
                            reason='prior_unsent_draft_requires_confirmation' if phase in PRE_SEND else 'prior_sent_batch_add_only' if phase in SUBMITTED else 'prior_add_result_unknown'
                            report.update(status='pending_confirmation',reason=reason)
            # A saved uncertain attempt can since have been added manually.
            # Positive current membership resolves it; absence grants no retry.
            if verify_only:
                # An interrupted add can already be in the authenticated local
                # index. Only positive membership resolves it; never touch UI.
                for r in runners:r.report.pop('status',None)
            possible=[r for r in runners if r.report.get('status') not in DONE]
            if possible:
                if verify_only:
                    with timing_stage('verification'):skip_index_members(possible,folder,cancel,**index_options)
                else:skip_index_members(possible,folder,cancel,**index_options)
            if verify_only:
                for r in runners:
                    if r.report.get('status')=='already_exists':
                        r.report.update(collection_verified=True,collection_persisted=False,
                                        completion_check='confirmed_in_local_index')
                    else:r.report.update(status='pending_confirmation',reason='local_membership_not_confirmed_no_retry')
                return finish(runners,folder,started)
            active=[r for r in runners if 'status' not in r.report]
            if not active:return finish(runners,folder,started)
            current=active[:SEND_GROUP_SIZE]
            # Persist NOT started for later groups before any native action.
            # An interrupted task must not strand unsent groups as unknown.
            notify('prepared')
            if resume_sent and any(not r.prior or r.prior['status'] not in SUBMITTED for r in active):
                raise ValueError('known_sent_unadded_batch_required')
            notify('opening_wechat')
            q=active[0].q;q.persistent=True;q.cancel_check=active[0].cancelled
            recover_empty_picker(active,q)
            q.bind()
            active[0].report['client_ready_seconds']=round(time.perf_counter()-started,4)
            for runner in active:runner.q=q;runner.cancelled()
            groups=[active[n:n+SEND_GROUP_SIZE] for n in range(0,len(active),SEND_GROUP_SIZE)]
            manifest={'group_size':SEND_GROUP_SIZE,'total':len(active),'groups':[
                {'number':n+1,'state':'queued','assets':[str(r.asset_path) for r in group]}
                for n,group in enumerate(groups)]}
            save_json(folder/'groups.json',manifest)
            for n,current in enumerate(groups):
                current[0].cancelled()
                group_info={'number':n+1,'total':len(groups),'size':len(current)}
                group_folder=folder if len(groups)==1 else folder/'groups'/str(n+1)
                group_folder.mkdir(parents=True,exist_ok=True)
                manifest['groups'][n].update(state='running',evidence=str(group_folder))
                save_json(folder/'groups.json',manifest);notify('sending_group')
                if resume_staged:
                    snap=q.uia();rect,hits=staged_identity(q,current,snap)
                    save_json(group_folder/'staged-recovery.json',{'verified_count':len(hits),'picker_calls':0,'source':'known_unsent_batch'})
                    send_staged_batch(current,q,rect,hits,notify if progress else None)
                elif not resume_sent:
                    if not q.uia()['input_empty']:raise StopAutomation('composer_not_empty')
                    send_batch(current,q,group_folder,progress=notify if progress else None)
                else:save_json(group_folder/'recovery.json',{'send_calls':0,'assets':[str(r.asset_path) for r in current]})
                options={}
                def recheck_rejected(rejected):
                    check=group_folder/'rejected-add-checks'/str(sum(r.report.get('native_add_retries',0) for r in current))
                    check.mkdir(parents=True,exist_ok=True)
                    skip_index_members(rejected,check,cancel,**index_options)
                options['recheck_rejected']=recheck_rejected
                if progress:options['progress']=notify
                if resume_sent:options['search_history']=True
                add_visible(current,q,group_folder,**options)
                # Never stage the next group while this group is unresolved.
                if any(r.report.get('status') not in DONE for r in current):
                    raise StopAutomation('wechat_group_incomplete_no_next_send')
                manifest['groups'][n]['state']='add_actions_completed'
                save_json(folder/'groups.json',manifest);notify('group_done')
            active[0].cancelled()
            current=[];group_info=None
            notify('checking_result')
            confirm_index(runners,folder,cancel,**index_options)
            notify('done')
    except Exception as exc:
        focus=None
        if q and q.window:
            h=user.GetForegroundWindow()
            focus={'expected':('main' if current and current[0].report.get('file_selection_step') in ('waiting_composer','sending') else 'main_or_owned_file_picker'),
                   'actual':('main' if h==q.window.hwnd else 'no_foreground' if not h else
                             'client_native_dialog' if pid_of(h)==q.window.pid and class_name(h)=='#32770' else
                             'other_client_window' if pid_of(h)==q.window.pid else 'other_application'),
                   'same_client_process':bool(h and pid_of(h)==q.window.pid)}
        for runner in runners:
            if runner.report.get('status') in DONE:continue
            if 'status' in runner.report:continue
            if current and runner not in current and runner.report.get('submission_state')=='not_started':
                runner.report.update(status='queued',reason='waiting_for_previous_send_group')
            else:
                runner.report.update(status='paused_before_submit' if runner.report.get('submission_state')=='not_started' else 'pending_confirmation',reason=str(exc))
                if focus:runner.report['pause_window']=focus
        if 'manifest' in locals():
            for group in manifest['groups']:
                if group['state']=='running':group.update(state='stopped',reason=str(exc))
            save_json(folder/'groups.json',manifest)
        # Settle earlier proven actions even when a later item blocks. One
        # read-only batch check, never a per-item panel scan or a second send.
        if str(exc) not in ('cancel_requested','cancelled_escape') and not (cancel and Path(cancel).exists()):
            confirm_index(runners,folder,cancel,**index_options)
    finally:
        if q:
            try:q.close()
            except Exception:
                for runner in runners:runner.report['helper_cleanup']='unconfirmed'
    return finish(runners,folder,started)


@measured("sending")
def send_batch(active,q,folder,progress=None):
    files=prepare_send_files(active,folder)
    def step(value):
        for r in active:r.report['file_selection_step']=value
        if progress:progress('file_selection')
    save_json(folder/'send-intent.json',{'assets':[str(r.asset_path) for r in active],
              'destination':'文件传输助手'})
    step('opening')
    for r in active:r.report['file_submission']='not_selected'
    q.control('open-file')
    try:
        dialog=wait_file_dialog(q)
    finally:
        observation=q.report.get('file_window_observation') if isinstance(q.report,dict) else None
        if observation:
            for r in active:r.report['file_window_observation']=observation
    # Persist only an empty, owned picker. A resumed task may close this exact
    # shell, recheck the own conversation, then open anew with CURRENT paths.
    remember_empty_picker(active,q,dialog)
    step('filling')
    def before_choose():
        for r in active:
            r.report.update(file_path_verified=True,file_submission='picker_submit_pending')
            r.boundary('batch_send_pending')
    selected=dialog_action(dialog,q.window,q.exe,'ChooseMany',files,before_choose,batch_limit=len(files))
    save_json(folder/'selected.json',selected)
    for r in active:r.report['file_submission']='selected_not_sent'
    step('waiting_composer')
    snap,rect,hits=wait_staged_batch(q,dialog,active)
    save_json(folder/'composer.json',snap)
    q.frame().crop(relative(snap['input'],q.window)).save(folder/'staged-batch.png')
    step('sending')
    send_staged_batch(active,q,rect,hits,progress)


def send_staged_batch(active,q,rect,hits,progress=None):
    """Send only the already matched complete draft; never selects files."""
    meta=q.uia('send-batch')
    if meta.get('media_object_count')!=len(active) or relative(meta['input'],q.window)!=rect:
        raise StopAutomation('staged_batch_changed')
    image=q.frame().crop(rect)
    for runner,hit in zip(active,hits):
        if not recheck_media_cell(image,runner.refs,hit,runner.matcher):raise StopAutomation('staged_batch_changed')
    for runner in active:
        runner.report['file_submission']='send_pending'
        runner.boundary('batch_send_click_pending')
    target=relative(meta['target'],q.window)
    click(q.window,q.exe,(target[0]+target[2])//2,(target[1]+target[3])//2)
    # Click acknowledgement permits add-only recovery, never a second send.
    for runner in active:
        runner.record('batch_send_requested');runner.report['file_submission']='send_requested'
    deadline=time.monotonic()+30
    while not q.uia()['input_empty']:
        active[0].cancelled()
        if progress:progress('waiting_send')
        if time.monotonic()>deadline:raise StopAutomation('input_not_cleared_after_send')
        time.sleep(.1)
    # Empty input means submitted to the client, not uploaded/delivered.
    for runner in active:
        runner.record('batch_message_submitted')
        runner.report['file_submission']='submitted_to_client'
        runner.report.pop('file_selection_step',None)


def prepare_send_files(active,folder):
    """The native multi-file picker requires one directory for the batch."""
    if not active or len(active)>SEND_GROUP_SIZE:raise StopAutomation('batch_selection_limit')
    destination=Path(folder)/'send-files'
    destination.mkdir()  # Each execution/group has its own evidence directory.
    files=[]
    for n,runner in enumerate(active,1):
        runner.cancelled()
        source=Path(runner.asset['prepared'])
        data=source.read_bytes()
        digest=runner.asset['prepared_sha256']
        if hashlib.sha256(data).hexdigest()!=digest:raise StopAutomation('prepared_file_changed')
        file=destination/f'{n:02d}{source.suffix}'
        file.write_bytes(data)
        if hashlib.sha256(file.read_bytes()).hexdigest()!=digest:raise StopAutomation('staged_file_copy_mismatch')
        files.append(file.resolve())
    # Keep these files for the client's asynchronous read and any later audit.
    return files


@measured('file_dialog_wait')
def wait_file_dialog(q,timeout=6):
    """Await this client's native picker, without another click or selection."""
    deadline=time.monotonic()+timeout
    while True:
        q.check_cancel()
        guard(q.window,q.exe,foreground=False)
        # Read foreground first: a picker can appear during EnumWindows.
        # Reading it afterwards falsely labels that newly opened picker as
        # an unrelated window because it is absent from the older enumeration.
        foreground=user.GetForegroundWindow()
        dialogs=[w for w in qq_windows(q.exe) if w.kind=='#32770' and w.pid==q.window.pid]
        # Windows can give the newly created picker foreground BEFORE its
        # visible flag. EnumWindows filtered by visibility then misses it.
        # Recognize only a native shell owned by this checked main window;
        # controls/visibility/foreground are still required before any input.
        transitioning=foreground_dialog(q.window,q.exe) if foreground not in (0,q.window.hwnd) else None
        expected=transitioning.hwnd if transitioning else None
        observation={'expected':'owned_file_picker','actual':('main' if foreground==q.window.hwnd else
                     'owned_file_picker' if expected==foreground else 'no_foreground' if not foreground else 'unexpected'),
                     'visible_picker_count':len(dialogs),'owned_shell_not_visible':bool(transitioning and not user.IsWindowVisible(transitioning.hwnd))}
        if isinstance(q.report,dict):
            prior=q.report.get('file_window_observation',{})
            observation['observed_hidden_transition']=observation['owned_shell_not_visible'] or prior.get('observed_hidden_transition',False)
            q.report['file_window_observation']=observation
        if len(dialogs)>1:raise StopAutomation('file_dialog_not_unique')
        if any(not dialog_owned_by(w,q.window) for w in dialogs):raise StopAutomation('wrong_dialog_owner')
        if foreground and foreground not in [q.window.hwnd,expected]+[w.hwnd for w in dialogs]:
            raise StopAutomation('file_dialog_unexpected_foreground')
        if len(dialogs)==1:
            guard(dialogs[0],q.exe,foreground=False)
            if foreground==dialogs[0].hwnd and picker_controls_ready(dialogs[0]):return dialogs[0]
        if time.monotonic()>=deadline:raise StopAutomation('file_name_control_unavailable' if dialogs else 'file_dialog_not_ready')
        time.sleep(.05)


def remember_empty_picker(active,q,dialog):
    from emoji_bridge.active_emoticon import process_started
    if not filename_is_empty(dialog,q.exe):raise StopAutomation('file_dialog_existing_selection')
    token={'dialog':dialog.__dict__,'owner':q.window.__dict__,'process_started':process_started(q.window.pid),
           'controls':dialog_controls(dialog)}
    for r in active:
        r.record('not_submitted')
        record=json.loads(r.ledger.read_text(encoding='utf8'))
        record['empty_picker']=token;save_json(r.ledger,record)


def recover_empty_picker(active,q):
    from emoji_bridge.windows import Window
    from emoji_bridge.active_emoticon import process_started
    proofs=[r.prior.get('empty_picker') for r in active if r.prior and r.prior.get('status')=='not_submitted']
    proofs=[p for p in proofs if p]
    dialogs=[w for w in qq_windows(q.exe) if w.kind=='#32770']
    if not dialogs:return
    if len(dialogs)!=1 or not proofs or any(p!=proofs[0] for p in proofs):
        raise StopAutomation('file_dialog_resume_unproven')
    proof=proofs[0];dialog=dialogs[0];owner=Window(**proof['owner']);owner.rect=tuple(owner.rect)
    saved=proof['dialog']
    if (dialog.hwnd!=saved['hwnd'] or dialog.pid!=saved['pid']
            or process_started(dialog.pid)!=proof['process_started'] or not dialog_owned_by(dialog,owner)
            or dialog_controls(dialog)!=proof['controls']):raise StopAutomation('file_dialog_resume_unproven')
    for r in active:
        if r.prior and r.prior.get('empty_picker'):
            if (r.prior.get('prepared_sha256')!=r.asset['prepared_sha256']
                    or r.prior.get('source_sha256')!=r.asset['source_sha256']):
                raise StopAutomation('prepared_file_changed')
    guard(owner,q.exe,foreground=False);activate(dialog,q.exe,cancel_check=q.check_cancel)
    if not filename_is_empty(dialog,q.exe):raise StopAutomation('file_dialog_existing_selection')
    dialog_action(dialog,owner,q.exe,'Cancel')
    deadline=time.monotonic()+2
    while user.IsWindowVisible(dialog.hwnd):
        q.check_cancel()
        if time.monotonic()>=deadline:raise StopAutomation('file_dialog_close_unconfirmed')
        time.sleep(.05)
    for r in active:r.report['empty_picker_recovered']=True


def picker_controls_ready(dialog):
    controls=dialog_controls(dialog)
    edits=[c['hwnd'] for c in controls if c['class']=='Edit' and c['id']==1148]
    buttons=[c['hwnd'] for c in controls if c['class']=='Button' and c['id']==1]
    # Open can be disabled until a filename is entered. Only the edit must
    # already accept input; dialog_action checks the button after filling it.
    return len(edits)==len(buttons)==1 and bool(user.IsWindowEnabled(edits[0]))


def hidden_picker_return(q,hwnd):
    """Qt's observed invisible modal bridge, only while returning from a picker.

    Grants waiting, never input. Visible/unknown popups and unrelated windows
    still stop. Composer access additionally requires the enabled main window.
    """
    return (bool(hwnd) and pid_of(hwnd)==q.window.pid and process_path(q.window.pid)==q.exe
            and class_name(hwnd)=='Qt51514QWindowIcon' and user.GetWindow(hwnd,4)==q.window.hwnd
            and not user.IsWindowVisible(hwnd) and not user.IsIconic(hwnd))


def wait_staged_batch(q,dialog,active,timeout=15):
    """Await selection acceptance and matching previews; never submit twice."""
    deadline=time.monotonic()+timeout
    reason='file_dialog_selection_not_accepted'
    while True:
        q.check_cancel();guard(q.window,q.exe,foreground=False)
        foreground=user.GetForegroundWindow()
        dialogs=[w for w in qq_windows(q.exe) if w.kind=='#32770' and w.pid==q.window.pid]
        if any(w.hwnd!=dialog.hwnd for w in dialogs):
            raise StopAutomation('file_dialog_selection_not_accepted')
        if foreground and foreground not in (q.window.hwnd,dialog.hwnd):
            if dialogs or not hidden_picker_return(q,foreground):raise StopAutomation('foreground_changed')
            for runner in active:runner.report['hidden_picker_return_observed']=True
        if not dialogs and foreground==q.window.hwnd and user.IsWindowEnabled(q.window.hwnd):
            snap=q.uia()
            count=snap.get('media_object_count',0)
            if not snap.get('input_empty') and (not snap.get('input_only_media_objects') or count>len(active)):
                raise StopAutomation('composer_not_expected_media_batch')
            reason='composer_media_loading_timeout'
            if snap.get('input_only_media_objects') and count==len(active):
                try:
                    rect,hits=staged_identity(q,active,snap)
                    return snap,rect,hits
                except StopAutomation as exc:
                    if str(exc) not in ('staged_batch_item_not_unique','staged_batch_items_overlap'):raise
                    reason=str(exc)
        if time.monotonic()>=deadline:raise StopAutomation(reason)
        time.sleep(.1)


def finish(runners,folder,started):
    results={}
    for runner in runners:
        runner.report.setdefault('status','pending_confirmation')
        path=runner.evidence/'result.json';save_json(path,runner.report)
        results[str(runner.asset_path)]=dict(runner.report,report_path=str(path))
    result={'results':results,'report_path':str(folder/'result.json'),'seconds':round(time.perf_counter()-started,4),
            'post_add_verification':any('completion_check' in r.report for r in runners),
            'favorites_panel_opened':False}
    save_json(folder/'result.json',result);return result
