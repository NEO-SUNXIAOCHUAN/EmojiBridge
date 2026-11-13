"""Selected QQ favorite -> intact personal Ori -> fresh source proof. No send fallback."""
import hashlib,json,os,sys,time
from datetime import datetime
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
from emoji_bridge.client_sources import qq_profile, executable
from emoji_bridge import qq_cache as cache
from emoji_bridge.state import save_json,sha,single_instance
from emoji_bridge.media import prepare_asset,load_asset
from emoji_bridge.recognition import find_in_cells,QQFrameMatcher
from emoji_bridge.paging import content_bottom
from emoji_bridge.originals import attach_receipt,register_cache_export,origin_for_asset,validate_receipt
from emoji_bridge.appearance_originals import read_snapshot


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def cancelled(cancel):
    if cancel and Path(cancel).exists():raise ValueError('cancel_requested')


def context(item):
    path=Path(item['scan']).resolve()
    if not path.is_relative_to(ROOT/'reports'):raise ValueError('favorite_scan_outside_project')
    scan=read_snapshot(path)
    if scan.get('schema')!='qq-favorite-observations-v1' or scan.get('source_kind')!='personal_favorites_ui':
        raise ValueError('personal_favorite_scan_required')
    found=[i for i in scan['items'] if i['id']==item['id']]
    if len(found)!=1 or any(found[0][k]!=item[k] for k in ('position','page','rect')):
        raise ValueError('selection_changed_refresh_required')
    page=scan['pages'][item['page']]
    if sha(page['image'])!=page['sha256']:raise ValueError('favorite_scan_image_changed')
    return scan,found[0]


def current_inventory(cancel=None,preview_sink=None):
    from emoji_bridge.client_sources import qq_personal_root
    root=qq_personal_root()
    # Windows directory enumeration already carries file metadata. Path.stat()
    # repeated three times per entry caused thousands of extra system calls
    # for every selected original; keep the exact same fingerprint contract.
    signature=inventory_signature(root,cancel)
    fingerprint=hashlib.sha256(json.dumps(signature).encode()).hexdigest()
    folder=ROOT/'private/T006/cache-index'/f'v{cache.INVENTORY_VERSION}-{fingerprint}';path=folder/'inventory.json'
    if path.exists():
        report=read_snapshot(path)
        if Path(report['root'])!=root:raise ValueError('cache_index_root_changed')
        cache.LAST_DIAGNOSTICS.clear();cache.LAST_DIAGNOSTICS.update(cache.diagnostic_summary(report))
        return report,path
    cancelled(cancel)
    options={'on_preview':preview_sink} if preview_sink is not None else {}
    report=cache.inventory(root,folder/'previews',lambda:cancelled(cancel),**options)
    report['directory_fingerprint']=fingerprint;save_json(path,report,compact=True)
    cache.LAST_DIAGNOSTICS.clear();cache.LAST_DIAGNOSTICS.update(cache.diagnostic_summary(report))
    return report,path


def inventory_signature(root,cancel=None):
    entries=[]
    with os.scandir(root) as directory:
        for entry in directory:
            cancelled(cancel)
            if entry.is_file():
                stat=entry.stat()
                entries.append((entry.name,stat.st_size,stat.st_mtime_ns))
    # Match WindowsPath ordering, including its case-insensitive comparison.
    return sorted(entries,key=lambda entry:Path(entry[0]))


def candidates(scan,item,inventory,cancel=None):
    """First-frame leads only. Every lead must be accounted for, never top-one guessing."""
    page=scan['pages'][item['page']];found=[]
    with Image.open(page['image']) as grid:
        for entry in inventory['items']:
            cancelled(cancel)
            with Image.open(entry['preview']) as picture:refs=[picture.convert('RGBA')]
            matched=selection_match(grid,refs,item['rect'])
            if matched:found.append(dict(entry,selection_match=matched))
    if inventory.get('failures'):raise ValueError('cache_candidates_incomplete')
    if not found:raise ValueError('selected_favorite_original_not_matched_in_cache')
    if len(found)!=1:raise ValueError('selected_favorite_has_multiple_cache_candidates')
    return found[0]


def selection_match(grid,refs,rect):
    """Recover a legacy clipped selection as a lead, never as a source receipt.

    Only the calibrated footer is excluded, with at least 80% of the tile
    visible. All candidate leads are compared; full fresh collection proof is
    still required after copying, including source animation for a GIF.
    """
    left,top,right,bottom=rect;visible=content_bottom(grid)
    if bottom<=visible:
        return {'kind':'full_saved_cell'} if find_in_cells(grid,refs,[rect],QQFrameMatcher(refs),pixel_tolerance=2) else None
    if not (0<=left<right<=grid.width and 0<=top<visible<bottom<=grid.height):return None
    if (visible-top)/(bottom-top)<.8:return None
    # Preserve alpha until comparison so a saved light-theme cell is composited
    # against the same background as the full-cell path.
    template=refs[0].convert('RGBA').copy()
    template.thumbnail((min(right-left,bottom-top),)*2,Image.Resampling.LANCZOS)
    width,height=template.size
    sizes=[(width,height)]
    if width<height:sizes.extend((width+d,height) for d in (-1,1))
    elif height<width:sizes.extend((width,height+d) for d in (-1,1))
    found=[]
    for width,height in sizes:
        if width>right-left or height>bottom-top:continue
        x=round((left+right-width)/2);y=round((top+bottom-height)/2)
        if not (y<visible<y+height):continue
        crop=grid.crop((x,y,x+width,visible))
        expected=template.resize((width,height),Image.Resampling.LANCZOS).crop((0,0,width,visible-y))
        index,error=QQFrameMatcher([expected])(crop)
        if index is not None and error<.04:
            found.append({'kind':'legacy_footer_clipped_lead','visible_rect':[x,y,x+width,visible],
                          'excluded_footer_pixels':bottom-visible,'error':error,'requires_fresh_full_favorite':True})
    return min(found,key=lambda m:m['error']) if found else None


def verify(scan,item,asset,folder,cancel=None):
    from qq_import import QQ
    from qq_export import verify_source
    from local_bridge import handoff_to
    cancelled(cancel)
    with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
        handoff_to('qq');q=QQ(qq_profile(),{});q.cancel=cancel
        try:
            q.bind();path=verify_source(q,scan,item,asset,folder,cancel,content_locator=True)
        finally:q.close()
    result=read(path);result.update(selected_item_id=item['id'],messages_sent=0)
    save_json(path,result);return path


class FreshSourceProof:
    """One-use, process-local proof from a just-completed source UI check.

    Never stored in the journal or reconstructed when resuming. The next stage
    still validates immutable bytes/receipt; target verification is unchanged.
    """
    def __init__(self,asset,receipt,verification,cancel):
        self.asset=Path(asset).resolve();self.receipt=Path(receipt)
        self.verification=Path(verification);self.digest=sha(verification)
        self.created=time.monotonic();self.used=False;self.cancel=cancel

    def consume(self,asset):
        if self.used or time.monotonic()-self.created>60:return None
        self.used=True;cancelled(self.cancel)
        if Path(asset).resolve()!=self.asset:raise ValueError('fresh_source_asset_mismatch')
        a=load_asset(asset);validate_receipt(self.receipt,a['source_sha256'])
        if sha(self.verification)!=self.digest:raise ValueError('fresh_source_evidence_changed')
        result=read(self.verification)
        if result.get('status') not in ('already_exists','desktop_confirmed'):raise ValueError('fresh_source_not_verified')
        return dict(result,report_path=str(self.verification),reused_in_same_workflow=True)


def acquire_or_resume(item,cancel=None,on_verified=None,defer_verification=False):
    ident=hashlib.sha256(item['id'].encode()).hexdigest()[:20]
    folder=ROOT/'private/T006/selected-cache'/ident;folder.mkdir(parents=True,exist_ok=True)
    report=folder/'result.json'
    result={'item_id':item['id'],'report':str(report),'status':'pending_confirmation',
            'messages_sent':0,'source_route':'personal_cache_and_current_favorite_ui','automatic_chat_fallback':False}
    try:
        with single_instance(folder/'acquire.lock'):
            cancelled(cancel);scan,selected=context(item)
            if report.exists() and read(report).get('status')=='original_verified':
                prior=read(report);load_asset(prior['asset']);return prior
            # Resume intact bytes. Find the same content in current favorites;
            # the recorded ordinal is never treated as a permanent identity.
            copied=folder/'copy.json';selection=folder/'selection.json'
            if copied.exists():
                copy=cache.validate_copy(read(copied));proof=read(selection)
                if proof['item_id']!=item['id'] or proof['scan_sha256']!=sha(item['scan']):raise ValueError('cache_selection_changed')
            else:
                inventory,path=current_inventory(cancel);entry=candidates(scan,selected,inventory,cancel)
                cancelled(cancel);copy=cache.copied_original(inventory['root'],entry,folder/'original')
                proof={'source_kind':'personal_favorites_ui','item_id':item['id'],'scan':item['scan'],
                       'scan_sha256':sha(item['scan']),'page_image':scan['pages'][selected['page']]['image'],
                       'page_sha256':scan['pages'][selected['page']]['sha256'],'selected':selected,
                       'candidate_name':entry['name'],'candidate_count':1,'inventory':str(path)}
                proof['candidate_match']=entry['selection_match']
                save_json(selection,proof);save_json(copied,copy)
            asset,_=prepare_asset(Path(copy['file']),'qq',ROOT/'private/T006/assets',native=True)
            result.update(downloaded_file=copy['file'],metadata=copy['metadata'],
                          display_preview=item.get('preview'),original_bytes_preserved=True)
            if defer_verification:
                result.update(status='downloaded_pending_verification',candidate_asset=str(asset),
                              selection=str(selection),copy_report=str(copied),reason='等待本批收藏对应核验')
                save_json(report,result);return result
            cancelled(cancel)
            attempt=folder/datetime.now().strftime('%Y%m%d-%H%M%S-%f');attempt.mkdir()
            verification=verify(scan,selected,asset,attempt,cancel)
            cache.validate_copy(copy);cancelled(cancel)
            receipt=attempt/'receipt.json';register_cache_export(selection,copied,verification,receipt)
            attach_receipt(asset,receipt)
            result.update(status='original_verified',asset=str(asset),receipt=str(receipt),verification=str(verification),
                          reason=None,original_bytes_preserved=True)
            if on_verified:on_verified(FreshSourceProof(asset,receipt,verification,cancel))
    except Exception as exc:
        code=str(exc)
        reasons={'selected_favorite_original_not_matched_in_cache':'本地原件暂未与所选收藏匹配；未发送消息。',
                 'selected_favorite_has_multiple_cache_candidates':'有多个相似原件，无法唯一对应；未搬运。',
                 'personal_cache_root_ambiguous_or_missing':'个人表情缓存目录缺失或有多个账号目录，尚未确定来源。',
                 'cache_candidates_incomplete':'部分候选无法读取，暂不能排除重复原件。',
                 'selected_original_not_found_in_bounded_current_favorites':'原件已保留，本轮收藏范围内未找到唯一对应；当前收藏待确认。',
                 'current_favorite_content_ambiguous':'原件已保留，但当前视图有多个相似收藏；对应关系待确认。',
                 'cancel_requested':'已取消，取得的原件保留，尚未搬运。'}
        is_cancelled=code in ('cancel_requested','已请求取消','cancelled_escape')
        result.update(reason_code=code,reason=reasons['cancel_requested'] if is_cancelled else reasons.get(code,code),
                      failure_kind='cancelled' if is_cancelled else 'source_unconfirmed')
        if result.get('downloaded_file') and not is_cancelled:result['status']='downloaded_pending_verification'
    save_json(report,result);return result


def recheck_acquired(asset):
    a=load_asset(asset);receipt=read(origin_for_asset(a)['original_provenance'])
    selection=read(receipt['evidence'][0]['path']);item=dict(selection['selected'],scan=selection['scan'])
    folder=ROOT/'private/T006/rechecks'/datetime.now().strftime('%Y%m%d-%H%M%S-%f');folder.mkdir(parents=True)
    try:
        scan,selected=context(item);path=verify(scan,selected,asset,folder)
        return dict(read(path),report_path=str(path))
    except Exception as exc:return {'status':'pending_confirmation','reason':str(exc),'messages_sent':0}


def recheck_selected(asset,item,cancel=None):
    """Bind a retained original to THIS selection, not its old export ordinal."""
    folder=ROOT/'private/T006/rechecks'/datetime.now().strftime('%Y%m%d-%H%M%S-%f');folder.mkdir(parents=True)
    try:
        cancelled(cancel);a=load_asset(asset)
        if (a['target']!='qq' or not origin_for_asset(a).get('exported_from_client')
                or Path(item['asset']).resolve()!=Path(asset).resolve()):raise ValueError('selected_original_changed')
        scan,selected=context(item);path=verify(scan,selected,asset,folder,cancel)
        return dict(read(path),report_path=str(path),current_selection_rechecked=True)
    except Exception as exc:return {'status':'pending_confirmation','reason':str(exc),'messages_sent':0}
