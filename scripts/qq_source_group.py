"""Prepare a bounded group, prove it once, then hand off immutable originals.

Proofs describe a dated selected snapshot, not live/full QQ membership.
Proven originals can be reused; single-use tokens are never restored from disk.
"""
from emoji_bridge.client_sources import qq_profile, executable
from datetime import datetime
from pathlib import Path
import time
import qq_cache_acquire as acquire
import qq_snapshot
from emoji_bridge import catalog
from emoji_bridge.media import load_asset
from emoji_bridge.originals import origin_for_asset,validate_receipt,register_cache_export,attach_receipt
from emoji_bridge.state import single_instance,save_json,sha
from emoji_bridge.transfer import INTERRUPTIONS


class GroupProof:
    def __init__(self,asset,receipt,verification,cancel,snapshot=None):
        self.asset=Path(asset).resolve();self.receipt=Path(receipt);self.path=Path(verification)
        self.digest=sha(self.path);self.cancel=cancel;self.used=False;self.closed=False
        self.receipt_digest=sha(self.receipt) if self.receipt.is_file() else None
        self.snapshot=dict(snapshot) if snapshot else None

    def close(self):self.closed=True

    def consume(self,asset):
        if self.closed or self.used:raise ValueError('source_group_proof_unavailable')
        acquire.cancelled(self.cancel)
        if Path(asset).resolve()!=self.asset:raise ValueError('source_group_asset_changed')
        a=load_asset(asset);validate_receipt(self.receipt,a['source_sha256'])
        if self.receipt_digest and sha(self.receipt)!=self.receipt_digest:raise ValueError('source_receipt_changed')
        if self.snapshot and qq_snapshot.lookup(self.snapshot) is None:raise ValueError('source_snapshot_unavailable')
        if sha(self.path)!=self.digest:raise ValueError('source_group_evidence_changed')
        result=catalog.read(self.path)
        if result.get('status')!='already_exists':raise ValueError('source_group_not_verified')
        self.used=True
        return dict(result,report_path=str(self.path),reused_selected_group_snapshot=True)


def prepare(items,library_path,cancel=None,progress=None,allow_ui=True):
    # The eight-item cap belongs to live panel verification. Saved originals
    # need no panel scan; use the same bound as the explicit-selection queue.
    limit=8 if allow_ui else 500
    if not items or len(items)>limit:raise ValueError(f'source_group_limit_{limit}')
    if len({item['id'] for item in items})!=len(items):raise ValueError('duplicate_selection')
    started=time.perf_counter();requests=[];prepared={};proofs={}
    folder=acquire.ROOT/'private/T006/source-groups'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder.mkdir(parents=True)
    results={}
    try:
        for item in items:
            acquire.cancelled(cancel)
            try:
                acquire.context(item)
                saved=qq_snapshot.lookup(item)
            except (OSError,ValueError,KeyError) as exc:
                if allow_ui or str(exc) in INTERRUPTIONS or str(exc) in ('cancel_requested','cancelled_escape'):
                    raise
                # A missing/changed saved original is local to this selection.
                # Keep its evidence, withhold its token, and prepare neighbors.
                failure=folder/'invalid'/str(len(results))/'result.json'
                results[item['id']]={'status':'pending_confirmation','item_id':item['id'],
                    'reason':'saved_source_invalid','diagnostic':str(exc),'report':str(failure)}
                save_json(failure,results[item['id']]);continue
            if saved:
                verification=folder/'saved'/str(len(proofs))/'verification.json';save_json(verification,saved)
                result={'status':'original_verified','asset':saved['asset'],'receipt':saved['receipt'],
                        'item_id':item['id'],'source_scope':saved['membership_scope'],
                        'membership_verified_at':saved['membership_verified_at'],'current_source_status':'saved_snapshot',
                        'verification':str(verification)}
                results[item['id']]=result
                proofs[item['id']]=GroupProof(saved['asset'],saved['receipt'],verification,cancel,snapshot=item)
                continue
            if not allow_ui:
                results[item['id']]={'status':'index_required','item_id':item['id'],
                                    'reason':item.get('index_reason') or '请先建立QQ索引；搬运阶段不自动滚动QQ'}
                continue
            if item.get('original_state')=='ready':
                asset=item['asset'];a=load_asset(asset);receipt=origin_for_asset(a)['original_provenance']
                validate_receipt(receipt,a['source_sha256'])
                result={'status':'original_verified','asset':asset,'receipt':receipt,'item_id':item['id']}
            else:result=acquire.acquire_or_resume(item,cancel,defer_verification=True)
            results[item['id']]=result
            asset=result.get('asset') or result.get('candidate_asset')
            # An unmatched cache item is an individual result. It says nothing
            # about the remaining selected items; do not mark them unavailable.
            if not asset:
                if result.get('failure_kind')=='cancelled':raise ValueError('cancel_requested')
                continue
            prepared[item['id']]=result;requests.append({'id':item['id'],'asset':asset})
        from qq_import import QQ
        from qq_source_batch import verify_many
        acquire.cancelled(cancel)
        verified={}
        if requests:
            with single_instance(acquire.ROOT/'runtime-data/T003/client-ui.lock'):
                q=QQ(qq_profile(),{});q.cancel=cancel
                try:
                    q.bind();verified=verify_many(q,requests,folder/'verification',cancel,progress=progress)
                finally:q.close()
        for request in requests:
            ident=request['id'];result=prepared[ident];verification=verified[ident];asset=request['asset']
            evidence=catalog.read(verification)
            if evidence.get('status')!='already_exists':
                result.update(current_source_status='pending_confirmation',verification=str(verification),
                              reason=evidence.get('reason','源收藏对应待确认'))
                if result.get('report'):save_json(result['report'],result)
                continue
            if result['status']!='original_verified':
                receipt=Path(verification).parent/'receipt.json'
                register_cache_export(result['selection'],result['copy_report'],verification,receipt)
                attach_receipt(asset,receipt);result['receipt']=str(receipt)
            result.update(status='original_verified',asset=asset,verification=str(verification),reason=None,current_source_status='verified')
            item=next(i for i in items if i['id']==ident)
            result['source_snapshot']=qq_snapshot.record(item,asset,result['receipt'],verification,
                                                       Path(verification).parent/'snapshot-binding.json')
            if result.get('report'):save_json(result['report'],result)
            proofs[ident]=GroupProof(asset,result['receipt'],verification,cancel)
    except Exception as exc:
        for proof in proofs.values():proof.close()
        proofs={}
        for ident,result in results.items():
            if ident not in prepared:continue
            # Keep any prior proven original in the catalog; fresh membership
            # failure pauses this run, it does not destroy its old receipt.
            if result.get('status')!='original_verified':
                result.update(status='downloaded_pending_verification' if result.get('downloaded_file') else 'pending_confirmation',reason=str(exc))
                if str(exc) in ('cancel_requested','已请求取消','cancelled_escape'):result['failure_kind']='cancelled'
            result.update(current_source_status='pending_confirmation',reason=str(exc))
        save_json(folder/'outcome.json',{'status':'pending_confirmation','reason':str(exc),'seconds':round(time.perf_counter()-started,3)})
        return {'proofs':{},'results':results,'reason':str(exc),'report':str(folder/'outcome.json'),'blocked':True}
    finally:
        library=catalog.read(library_path)
        for item in library['clients']['qq']['items']:
            if item['id'] in results and results[item['id']]['status']!='index_required':catalog.apply_acquisition(item,results[item['id']])
        catalog.save(library,library_path)
    report=folder/'outcome.json'
    save_json(report,{'status':'verified' if len(proofs)==len(items) else 'partial','items':len(proofs),
                     'saved_snapshot_items':sum(r.get('source_scope')=='saved_verified_favorite_snapshot' for r in results.values()),
                     'fresh_ui_items':len(requests),
                     'selected':len(items),'unmatched':[i['id'] for i in items if i['id'] not in proofs],
                     'seconds':round(time.perf_counter()-started,3)})
    return {'proofs':proofs,'results':results,'report':str(report),'blocked':False}
