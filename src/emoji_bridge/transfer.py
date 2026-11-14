"""Selected transfers only. Durable intent before UI; unknowns are verify-only."""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import uuid

from .media import load_asset
from .state import save_json
from .originals import origin_for_asset

SUCCESS=('desktop_confirmed','already_exists')
INTERRUPTIONS={'foreground_changed','foreground_switch_denied','window_not_visible','window_moved_or_resized',
              'client_display_scale_unsupported','foreground_handoff_timeout','foreground_handoff_access_denied','foreground_focus_control_not_unique',
              'uia_worker_stopped_no_retry','uia_startup_timeout','uia_helper_exited','uia_response_timeout','uia_protocol_error','uia_helper_io_error',
              'file_dialog_unexpected_foreground','file_dialog_resume_unproven','file_dialog_existing_selection',
              'file_name_control_unavailable','wrong_dialog_owner','file_dialog_not_ready','file_dialog_close_unconfirmed',
              'client_display_scale_changed','display_work_area_unavailable','display_too_small_for_calibrated_window',
              'calibrated_window_placement_failed','calibrated_window_placement_unconfirmed',
    'capture_requires_foreground','target_occluded','user_input_in_progress','window_unavailable',
    'plus_not_uniquely_identified','heart_not_uniquely_identified','favorite_panel_geometry_changed',
    'qq_uia_top_not_observed','qq_uia_panel_did_not_close','qq_uia_personal_favorites_not_open',
    'process_identity_changed','client_main_window_missing_or_ambiguous','client_restore_failed',
    'client_restore_unconfirmed','target_window_ambiguous_or_layout_changed',
    'wechat_main_window_not_unique_or_minimized','client_version_changed','client_family_unadapted','own_transfer_session_not_confirmed',
    'own_transfer_entry_not_visible','own_transfer_navigation_not_confirmed',
    'wechat_control_missing','wechat_control_ambiguous','wechat_favorites_check_unavailable','wechat_header_layout_unsupported','own_transfer_search_not_empty',
    'own_transfer_search_changed','own_transfer_search_layout_unsupported',
    'own_transfer_search_result_unsupported','own_transfer_search_result_not_found',
    'composer_not_empty','composer_not_one_media_object','staged_media_changed','staged_media_requires_identity_check',
    'wechat_popup_not_unique','wechat_add_settle_timeout','wechat_add_rejected','message_list_outside_window','message_row_identity_ambiguous',
    'input_not_cleared_after_send','sent_resume_requires_empty_composer','uia_control_not_unique'}

INTERRUPTIONS.update({'wechat_visual_'+name for name in (
    'open_helper_first','helper_not_confirmed','selected_helper_not_confirmed',
    'helper_icon_unproven','composer_unproven','file_button_unproven','send_button_unproven',
    'empty_draft_conflict','runtime_missing','chinese_ocr_unavailable','ocr_failed','ocr_timeout',
    'layout_unsupported','action_unsupported','ocr_geometry_invalid')})


def make_export_plan(selected,path):
    """Queue explicit original-export pairs using validated source receipts."""
    if Path(path).exists():raise ValueError('plan_already_exists')
    jobs=[];seen=set()
    for selection in selected:
        source=load_asset(selection['source_asset']);target=load_asset(selection['target_asset'])
        origin=origin_for_asset(source)
        if not origin.get('exported_from_client'):raise ValueError('verified_source_client_export_required')
        if source['source_sha256']!=target['source_sha256'] or source['target']==target['target']:
            raise ValueError('transfer_asset_mismatch')
        key=(target['target'],target['source_sha256'])
        if key in seen:continue
        seen.add(key)
        jobs.append({'id':str(uuid.uuid4()),'source_asset':str(Path(selection['source_asset']).resolve()),
                     'source_receipt':origin['original_provenance'],'target_asset':str(Path(selection['target_asset']).resolve()),
                     'source_matching_basis':origin.get('matching_basis','verified_correspondence'),
                     'target':target['target'],'source_sha256':target['source_sha256'],'status':'queued','attempts':0})
    plan={'schema':'selected-transfer-v1','jobs':jobs,'created':datetime.now().astimezone().isoformat(),
          'scope':'explicit selected client files with recorded matching basis; limited selection, not all favorites'}
    save_json(path,plan);return plan


def make_plan(selected,path):
    if Path(path).exists():raise ValueError('plan_already_exists')
    jobs=[];seen=set()
    for selection in selected:
        inventory=json.loads(Path(selection['inventory']).read_text(encoding='utf8'))
        if inventory.get('schema')!='favorites-visible-v1' or inventory.get('source_kind')!='personal_favorites_ui':
            raise ValueError('source_is_not_favorites_evidence')
        item=next((v for v in inventory['items'] if v['id']==selection['id']),None)
        if not item or not item.get('original_available') or item.get('match_count')!=1:raise ValueError('source_original_unavailable_or_ambiguous')
        source=load_asset(item['asset']);target=load_asset(selection['target_asset'])
        if source['source_sha256']!=target['source_sha256'] or source['target']==target['target']:raise ValueError('transfer_asset_mismatch')
        key=(target['target'],target['source_sha256'])
        if key in seen:continue
        seen.add(key)
        jobs.append({'id':str(uuid.uuid4()),'source_inventory':str(Path(selection['inventory']).resolve()),
                     'source_item':item['id'],'source_asset':item['asset'],'target_asset':str(Path(selection['target_asset']).resolve()),
                     'target':target['target'],'source_sha256':target['source_sha256'],'status':'queued','attempts':0})
    plan={'schema':'selected-transfer-v1','jobs':jobs,'created':datetime.now().astimezone().isoformat(),
          'scope':'explicit selections; source originals bound to visible favorites; incomplete collection'}
    save_json(path,plan);return plan


def run_plan(path,execute,source_check,clear_cancel=False,after_item=None):
    path=Path(path);cancel=path.with_suffix('.cancel')
    plan=json.loads(path.read_text(encoding='utf8'))
    if plan.get('schema')!='selected-transfer-v1':raise ValueError('invalid_transfer_plan')
    if clear_cancel and cancel.exists():cancel.unlink()
    for job in plan['jobs']:
        if cancel.exists():plan['run_state']='cancelled';break
        if job['status'] in SUCCESS:continue
        if job['status']=='failed':
            if not (clear_cancel and job.get('reason') in INTERRUPTIONS and job.get('submission_state')=='not_started'):continue
            job['status']='pending_confirmation'
        if job['status']=='cancelled' and not clear_cancel:continue
        prior=job['status']
        if prior=='cancelled' and job.get('submission_state')=='not_started':prior='queued'
        # A failed prerequisite has not submitted anything. Recheck it before
        # the first add; only a possibly submitted job is verification-only.
        if (prior=='pending_confirmation' and job.get('reason')=='source_favorite_not_reconfirmed'
                and (job.get('attempts')==0 or job.get('submission_state')=='not_started')):
            prior='queued'
        if (clear_cancel and prior=='pending_confirmation' and job.get('reason') in INTERRUPTIONS
                and job.get('submission_state')=='not_started'):
            prior='queued'
        source=load_asset(job['source_asset']);target=load_asset(job['target_asset'])
        if source['source_sha256']!=job['source_sha256'] or target['source_sha256']!=job['source_sha256']:raise ValueError('job_asset_changed')
        if prior=='queued':
            check=source_check(job['source_asset'])
            job['source_recheck']=check.get('report_path')
            if cancel.exists():plan['run_state']='cancelled';break
            if check.get('status') not in SUCCESS:
                job.update(status='pending_confirmation',reason='source_favorite_not_reconfirmed',source_reason=check.get('reason'),submission_state='not_started')
                save_json(path,plan)
                if check.get('reason') in INTERRUPTIONS:
                    plan['run_state']='paused';break
                continue
        if cancel.exists():plan['run_state']='cancelled';break
        # Persist BEFORE calling anything that can send/import. An interrupted
        # running job is verification-only on resume, never a second add.
        job.update(status='running',attempts=job['attempts']+1,submission_state='may_have_started');save_json(path,plan)
        result=execute(job['target_asset'],'add' if prior=='queued' else 'verify',cancel)
        if result.get('reason') in INTERRUPTIONS:result['status']='pending_confirmation'
        job.update(status=result['status'],reason=result.get('reason'),result=result.get('report_path'),
                   collection_persisted=result.get('collection_persisted',False),
                   submission_state=result.get('submission_state','may_have_started') if prior=='queued' else 'may_have_started')
        save_json(path,plan)
        if after_item:after_item(job,path)
        if cancel.exists() or job['status']=='cancelled' or result.get('reason') in ('cancel_requested','cancelled_escape'):
            plan['run_state']='cancelled';break
        if result.get('reason') in INTERRUPTIONS:
            plan['run_state']='paused';break
    else:plan['run_state']='finished'
    plan['counts']=dict(Counter(j['status'] for j in plan['jobs']))
    plan['updated']=datetime.now().astimezone().isoformat();save_json(path,plan);return plan
