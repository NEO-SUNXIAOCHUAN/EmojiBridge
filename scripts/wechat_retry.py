"""Explicit recovery of a completed PRE-send failure, never an unknown send."""
from pathlib import Path
from datetime import datetime
from emoji_bridge import catalog
from emoji_bridge.state import save_json,sha,single_instance
from emoji_bridge.paths import DATA_ROOT

PRE_SEND={'batch_input_pending','batch_send_pending'}


def evidence(asset_path,root=DATA_ROOT):
    path=Path(asset_path).resolve();asset=catalog.read(path)
    if asset.get('target')!='wechat':raise ValueError('wechat_target_required')
    ledger=Path(root)/'runtime-data/T004/wechat'/(asset['source_sha256']+'.json')
    record=catalog.read(ledger)
    if record.get('status') not in PRE_SEND:raise ValueError('not_a_proven_pre_send_attempt')
    if (Path(record['asset']).resolve()!=path or record.get('prepared_sha256')!=asset['prepared_sha256']
            or record.get('source_sha256')!=asset['source_sha256']):raise ValueError('pre_send_asset_changed')
    report_path=Path(record['report'])/'result.json';report=catalog.read(report_path)
    if (report.get('status')!='pending_confirmation' or Path(report.get('asset','')).resolve()!=path
            or report.get('source_sha256')!=asset['source_sha256']
            or report.get('prepared_sha256')!=asset['prepared_sha256']):raise ValueError('pre_send_report_unproven')
    return {'asset':str(path),'prepared_sha256':asset['prepared_sha256'],
            'ledger_sha256':sha(ledger),'report_sha256':sha(report_path),
            'prior_phase':record['status'],'prior_report':str(report_path)}


def valid(asset_path,approval,root=DATA_ROOT):
    if not isinstance(approval,dict) or approval.get('confirmation')!='draft_removed_and_not_manually_sent':return False
    try:return all(approval.get(k)==v for k,v in evidence(asset_path,root).items())
    except (OSError,ValueError,KeyError,TypeError):return False


def staged_evidence(assets,root=DATA_ROOT):
    """Only the complete known, selected-but-never-sent batch may resume.

    This proves history, not current input. The adapter must additionally prove
    the own conversation, exact media count and every current prepared image.
    """
    try:
        proofs=[evidence(a,root) for a in assets]
        if not proofs or any(p['prior_phase']!='batch_send_pending' for p in proofs):return None
        reports=[catalog.read(p['prior_report']) for p in proofs]
        if any(r.get('file_submission')!='selected_not_sent' for r in reports):return None
        folders={Path(p['prior_report']).parent.parent for p in proofs}
        if len(folders)!=1:return None
        folder=next(iter(folders));intent=catalog.read(folder/'send-intent.json')
        if intent.get('destination')!='文件传输助手':return None
        if {Path(a).resolve() for a in intent['assets']}!={Path(a).resolve() for a in assets}:return None
        return proofs
    except (OSError,ValueError,KeyError,TypeError):return None


def candidates(plan,root=DATA_ROOT):
    items=[]
    if (plan.get('source_client')!='qq' and not
            (plan.get('source_kind')=='local_material_library' and plan.get('target')=='wechat')):return items
    for job in plan.get('jobs',[]):
        if job.get('status')!='pending_confirmation' or not job.get('target_asset'):continue
        if valid(job['target_asset'],job.get('retry_approval'),root):continue
        try:proof=evidence(job['target_asset'],root)
        except (OSError,ValueError,KeyError,TypeError):continue
        items.append({'item_id':job['item_id'],'evidence':proof})
    return items


def confirmation_candidates(plan,root=DATA_ROOT):
    """Known complete unsent drafts are checked in place by the adapter.

    Do not ask the user to remove them before that check can run. The history
    proof does not itself authorize Send: the live composer is checked again.
    """
    items=candidates(plan,root)
    assets=[item['evidence']['asset'] for item in items]
    return [] if assets and staged_evidence(assets,root) else items


def approve(path,ids,*,confirmed=False,root=DATA_ROOT):
    """Only the UI's explicit, named-item confirmation grants retry authority.

    Keep the old ledger/report intact. Execution rechecks this fingerprint,
    full original and empty own composer before starting a new attempt.
    """
    if confirmed is not True:raise ValueError('explicit_unsent_confirmation_required')
    path=Path(path)
    with single_instance(path.with_suffix('.lock')):
        plan=catalog.read(path);eligible={x['item_id']:x['evidence'] for x in candidates(plan,root)}
        if not ids or any(i not in eligible for i in ids):raise ValueError('retry_candidates_changed')
        stamp=datetime.now().astimezone().isoformat()
        for job in plan['jobs']:
            if job['item_id'] not in ids:continue
            approval=dict(eligible[job['item_id']],confirmation='draft_removed_and_not_manually_sent',at=stamp)
            job.setdefault('retry_approvals',[]).append(approval)
            job['retry_approval']=approval
        save_json(path,plan)
    return plan
