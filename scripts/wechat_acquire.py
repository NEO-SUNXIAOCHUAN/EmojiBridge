"""One explicitly selected indexed favorite: current membership -> digest -> bytes.

No send/add path, no account discovery, and no image-cache fallback. Cancellation
keeps the downloaded file; another explicit request validates it without fetching
it again. Authenticated source membership is distinct from target UI success.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from contextvars import ContextVar
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
from emoji_bridge import wechat_index as index
from emoji_bridge.media import inspect,prepare_asset
from emoji_bridge.originals import attach_receipt,register_authenticated_original,validate_receipt
from emoji_bridge.state import save_json,sha,single_instance
from emoji_bridge.windows import file_version,qq_windows
from emoji_bridge.client_sources import running_wechat

_session=ContextVar('wechat_selected_index_session',default=None)


@contextmanager
def index_session():
    """Reuse authenticated members only while exact DB/WAL snapshots agree.

    Task-local memory only; cleared on cancel/exception/finish. No key survives.
    """
    state={};token=_session.set(state)
    try:yield
    finally:state.clear();_session.reset(token)


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def cancelled(token):
    if token and Path(token).exists():raise index.IndexErrorSafe('cancel_requested')


def context_for(item,source_report):
    digest=item.get('member',{}).get('md5','')
    if (not re.fullmatch('[a-f0-9]{32}',digest) or item.get('id')!='wechat:'+digest
            or item['member'].get('membership_table')!='kFavEmoticonOrderTable'):
        raise index.IndexErrorSafe('explicit_favorite_selection_required')
    report_path=Path(source_report).resolve()
    if not report_path.is_relative_to(ROOT/'reports'):
        raise index.IndexErrorSafe('index_report_outside_project')
    previous=read(report_path)
    if (previous.get('status')!='index_decrypted_and_integrity_verified'
            or not previous.get('snapshot_current_consistent')
            or sum(m.get('md5')==digest for m in previous.get('index_members',[]))!=1):
        raise index.IndexErrorSafe('selected_member_not_in_verified_snapshot')
    return digest,previous


from emoji_bridge.timing import measured

@measured("index")
def current_index(previous,cancel):
    cancelled(cancel)
    pid,exe=running_wechat()
    from emoji_bridge.compatibility import require_version,record_index_check,REASONS
    from emoji_bridge.client_sources import settings
    disabled=settings().get('disabled_sources',{}).get('wechat')
    if disabled:raise index.IndexErrorSafe(disabled)
    version=require_version('wechat',file_version(exe))
    key=plain=conn=None
    try:
        # Exact previously authorized database; never enumerate account folders.
        db,wal,snapshot=index.snapshot(Path(previous['source']))
        session=_session.get();identity=(str(previous['source']),pid,str(exe),version)
        cached=session.get(identity) if session is not None else None
        if cached and all(snapshot[k]==cached[1]['snapshot'][k] for k in ('db_sha256','wal_sha256','checkpoint')):
            cancelled(cancel);report=deepcopy(cached[1]);report['session_reused_unchanged_snapshot']=True
            return cached[0],report
        key,scan=index.scan_key(pid,exe,db[:4096],cancel_check=lambda:cancelled(cancel))
        cancelled(cancel)
        plain,wal_report=index.decrypt_snapshot(db,wal,key)
        conn=index.open_index(plain);membership_summary={}
        members=index.favorites(conn,summary=membership_summary)
        if file_version(exe)!=version:raise index.IndexErrorSafe('client_version_changed')
        checkpoint=snapshot['checkpoint']
        if not (checkpoint.get('checked') and checkpoint['mx_frame']==wal_report['valid_frames']-wal_report['uncommitted_frames']):
            raise index.IndexErrorSafe('snapshot_current_state_unproven')
        cancelled(cancel)
        report={'at':datetime.now().astimezone().isoformat(),
            'status':'index_decrypted_and_integrity_verified','source':previous['source'],
            'client_version':file_version(exe),'snapshot':snapshot,'wal':wal_report,'scan':scan,
            'snapshot_current_consistent':True,'index_count':len(members),'membership_summary':membership_summary,
            'index_members':[index.public_item(m) for m in members],'index_scope':'authenticated local favorite index snapshot',
            'secret_persisted':False,'memory_dump_written':False,'complete_collection_proven':False}
        if session is not None:session[identity]=(members,deepcopy(report))
        record_index_check(pid,version)
        return members,report
    except (index.IndexErrorSafe,ValueError) as exc:
        if str(exc) in REASONS:record_index_check(pid,version,str(exc))
        raise
    finally:
        if conn is not None:conn.close()
        if plain is not None:plain[:]=b'\0'*len(plain)
        key=None


def current_member(previous,digest,cancel):
    members,report=current_index(previous,cancel)
    chosen=[m for m in members if m['md5']==digest]
    if len(chosen)!=1:raise index.IndexErrorSafe('selected_favorite_no_longer_in_index')
    report.update(index_members=[index.public_item(chosen[0])],index_scope='selected member only')
    return chosen[0],report


def saved_download(state,digest):
    path=Path(state['acquisition'])
    if sha(path)!=state['acquisition_sha256']:raise index.IndexErrorSafe('acquisition_evidence_changed')
    report=read(path);items=report.get('acquisitions',[])
    if len(items)!=1 or items[0]['member']['md5']!=digest:
        raise index.IndexErrorSafe('cached_selection_mismatch')
    original=items[0]
    if (original.get('status')!='original_verified' or not original.get('md5_matches_favorite')
            or original.get('url_field')!='cdn_url'):
        raise index.IndexErrorSafe('cached_original_unverified')
    if not Path(original['path']).is_file():raise FileNotFoundError()
    metadata,_=inspect(Path(original['path']))
    if metadata['sha256']!=original['metadata']['sha256'] or hashlib.md5(Path(original['path']).read_bytes()).hexdigest()!=digest:
        raise index.IndexErrorSafe('cached_original_changed')
    return report,original


def failure_reason(code,attempts=()):
    if code=='cancel_requested':return 'cancelled','已取消；已有文件保留，继续时先核验。'
    if code=='selected_favorite_no_longer_in_index':return 'membership_missing','当前收藏索引中已找不到这一项；不据此判断用户删除过原图。'
    if code=='FileNotFoundError':return 'local_file_missing','所需的本地文件不存在，请核对原件或索引文件。'
    if code=='PermissionError':return 'local_access_denied','本地文件无法访问。'
    if code=='original_unavailable':
        if not attempts:return 'resource_missing','该收藏没有可用的原件下载地址。'
        if any(a.get('http_status') in (404,410) for a in attempts):return 'resource_unavailable','原件服务返回资源不存在；具体原因未确认。'
        errors={a.get('error') for a in attempts}
        if 'TimeoutError' in errors:return 'download_timeout','原件下载超时，有限重试后仍未取得；已有文件保留，继续时只补未完成项。'
        if errors & {'favorite_md5_mismatch','existing_original_changed'}:return 'integrity_failed','文件与收藏摘要不符，不能作为原件。'
        if errors & {'UnidentifiedImageError','OSError'}:return 'decode_or_io_failed','文件解码或读写失败；尚不能确定是素材损坏。'
        return 'download_failed','原件获取未成功；请查看本项诊断记录，有限重试已结束。'
    if code in ('cached_original_changed','acquisition_evidence_changed','cached_selection_mismatch','cached_original_unverified','cached_source_mismatch','cached_asset_mismatch'):
        return 'integrity_failed','已有文件或来源证据校验失败，未覆盖重取。'
    if code=='alpha_conversion_not_implemented_original_preserved':
        return 'format_unsupported','原件已保留；当前核验转换尚不支持这张透明图片，未转换或添加。'
    return 'environment_or_index_unconfirmed','微信环境或收藏索引尚未通过核对，原件状态未确认。'


@measured("original")
def acquire_selected(item,source_report,cancel=None):
    # Parallel preparation can receive the same Windows clock tick. A timestamp
    # alone made different favorites overwrite/lock the same result JSON.
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+uuid4().hex
    report_path=ROOT/'reports/T005'/f'wechat-acquire-{stamp}.json'
    result={'status':'pending_confirmation','report':str(report_path),'item_id':item.get('id'),
            'new_download':False,'target_transfer_performed':False}
    acquired=None
    try:
        cancelled(cancel);digest,previous=context_for(item,source_report)
        folder=ROOT/'private/T005/wechat-acquire'/digest;state_path=folder/'state.json'
        folder.mkdir(parents=True,exist_ok=True)
        with single_instance(ROOT/'runtime-data/T005/wechat-previews'/f'{digest}.lock'):
            if state_path.exists():
                state=read(state_path);acquired,original=saved_download(state,digest)
                if Path(acquired['source']).resolve()!=Path(previous['source']).resolve():
                    raise index.IndexErrorSafe('cached_source_mismatch')
                if state.get('phase')=='verified':
                    from emoji_bridge.catalog import valid_original
                    validate_receipt(state['receipt'],original['metadata']['sha256'])
                    asset,origin=valid_original(state['asset'])
                    if asset['target']!='wechat' or asset['source_sha256']!=original['metadata']['sha256']:
                        raise index.IndexErrorSafe('cached_asset_mismatch')
                    result.update(status='original_verified',asset=state['asset'],receipt=state['receipt'])
                    save_json(report_path,result);return result
                # A changed snapshot needs a fresh membership check, by digest,
                # never by the old ordinal. Existing bytes need no redownload.
                _,_,now=index.snapshot(Path(acquired['source']))
                if not all(now[k]==acquired['snapshot'][k] for k in ('db_sha256','wal_sha256','checkpoint')):
                    member,fresh=current_member(previous,digest,cancel)
                    original=dict(original,member=index.public_item(member))
                    fresh['acquisitions']=[original];acquired=fresh
            else:
                member,acquired=current_member(previous,digest,cancel)
                result['download_attempted']=any(field=='cdn_url' for field,_ in member['urls'])
                original=index.download_original(member,folder,lambda:cancelled(cancel))
                result['new_download']=original['status']=='original_verified' and not original.get('reused_download')
                acquired['acquisitions']=[original]
                if original['status']!='original_verified':
                    acquisition=folder/f'acquisition-{stamp}.json';save_json(acquisition,acquired)
                    result['acquisition']=str(acquisition)
                    kind,message=failure_reason('original_unavailable',original.get('attempts',[]))
                    result.update(status='original_unavailable',failure_kind=kind,reason=message)
                    save_json(report_path,result);return result
            acquisition=folder/f'acquisition-{stamp}.json';save_json(acquisition,acquired)
            save_json(state_path,{'phase':'downloaded','acquisition':str(acquisition),
                'acquisition_sha256':sha(acquisition)})
            result.update(status='downloaded_pending_verification',downloaded_file=original['path'],
                acquisition=str(acquisition),metadata=original['metadata'])
            cancelled(cancel)
            asset,_=prepare_asset(Path(original['path']),'wechat',ROOT/'private/T005/assets',native=True)
            receipt=folder/f'receipt-{stamp}.json'
            register_authenticated_original(acquisition,receipt)
            attach_receipt(asset,receipt)
            save_json(state_path,{'phase':'verified','acquisition':str(acquisition),
                'acquisition_sha256':sha(acquisition),'asset':str(asset),'receipt':str(receipt)})
            result.update(status='original_verified',asset=str(asset),receipt=str(receipt),reason=None,
                          source_proof='authenticated_index_and_original_digest',source_ui_verified=False,
                          source_playback_verified=False,target_collection_verified=False)
    except Exception as exc:
        code=str(exc) if isinstance(exc,index.IndexErrorSafe) else type(exc).__name__
        if isinstance(exc,ValueError) and str(exc)=='alpha_conversion_not_implemented_original_preserved':code=str(exc)
        kind,message=failure_reason(code)
        result.update(failure_kind=kind,reason=message,diagnostic=code)
    save_json(report_path,result);return result
