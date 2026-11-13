"""Enrich known observations only, using existing original acquisition; no UI scan.

The collection worker owns the account-scoped writer lease. A cover is never a
collection receipt, and QQ appearance associations remain explicitly uncertain.
"""
from pathlib import Path
from contextlib import nullcontext
import hashlib,time,json
from PIL import Image,ImageOps
from emoji_bridge import catalog
from emoji_bridge.state import save_json

def original_file(item):
    if item.get('managed_original') and Path(item['managed_original']).is_file():return Path(item['managed_original'])
    if item.get('asset'):
        asset,_=catalog.valid_original(item['asset'])
        return Path(asset['original_copy'])
    return None

def prioritized_ids(ids,priority_file,cancel,deferred=None):
    """Bounded mailbox: promote pending work, never repeat a completed item."""
    waiting=list(ids);done=set()
    while waiting and len(done)<54 and not cancel.exists():
        if priority_file and Path(priority_file).exists():
            try:
                mailbox=json.loads(Path(priority_file).read_text('utf8'))
                if mailbox.get('yield') and deferred is not None:
                    deferred.extend(waiting);return
                urgent=mailbox.get('ids',[])[:18]
                waiting=list(dict.fromkeys([i for i in urgent if i not in done]+waiting))[:36]
            except (OSError,ValueError,TypeError):pass
        ident=waiting.pop(0);done.add(ident)
        yield ident

def enrich(library_path,client,ids,cancel,progress,priority_file=None):
    library_path=Path(library_path);root=library_path.parents[2]
    library=catalog.read(library_path);side=library['clients'][client]
    selected={i['id']:i for i in side['items'] if i['id'] in ids and not i.get('source_receipt_only')}
    # UI batches are 18; an interrupted writer may carry its bounded promoted
    # remainder (up to 36) to the next turn.
    if not ids or len(ids)>36 or not set(ids)<=selected.keys():raise ValueError('所选条目已改变，请更新后重试')
    results=[];deferred=[]
    if client=='qq':
        from qq_appearance_prepare import prepare
        progress(stage='校验已读 QQ 条目的本地原件；不操作客户端')
    if client=='wechat':
        import wechat_acquire as acquire
        session=acquire.index_session()
    else:session=nullcontext()
    with session:
        for n,ident in enumerate(prioritized_ids(ids,priority_file,cancel,deferred)):
            if cancel.exists():break
            library=catalog.read(library_path);side=library['clients'][client]
            item=next((i for i in side['items'] if i['id']==ident and not i.get('source_receipt_only')),None)
            if item is None:continue
            try:
                progress(n,0,'补齐清晰预览与原件；已有封面保持可看')
                # Existing verified originals do not need the QQ inventory.
                try:original=original_file(item)
                except (OSError,ValueError,KeyError):original=None
                if client=='qq' and original is None:
                    prepare(library_path,cancel,ids=[ident])
                    library=catalog.read(library_path);side=library['clients'][client]
                    item=next(i for i in side['items'] if i['id']==ident)
                if client=='qq' and item.get('matching_basis')=='appearance' and not item.get('original_available'):
                    raise ValueError(item.get('reason') or '外观候选尚未核对，保留已有封面')
                original=original_file(item) if client=='qq' else original
                if original is None and client=='wechat':
                    result=acquire.acquire_selected(item,side.get('source_report'),cancel)
                    catalog.apply_acquisition(item,result)
                    original=original_file(item) if result.get('status')=='original_verified' else None
                if cancel.exists():break
                if original is None:raise ValueError(item.get('reason') or '本地缓存尚未取得完整原件；请在来源客户端加载后重试')
                stat=original.stat();key=hashlib.sha256((str(original)+str(stat.st_size)+str(stat.st_mtime_ns)).encode()).hexdigest()
                cover=root/'private/T005/clear-previews'/(key+'.png')
                if not cover.exists():
                    with Image.open(original) as image:
                        frame=ImageOps.exif_transpose(image).convert('RGBA');frame.thumbnail((1024,1024),Image.Resampling.LANCZOS)
                    cover.parent.mkdir(parents=True,exist_ok=True)
                    temp=cover.with_suffix('.partial');frame.save(temp,'PNG');temp.replace(cover)
                item.update(clear_preview=str(cover),preview_quality='original_cover',enrichment_state='ready')
                item.pop('preview_error',None);item.pop('enrichment_error',None)
                results.append({'id':ident,'state':'ready'})
            except Exception as exc:
                if cancel.exists():break
                # Preserve the last readable cover and all original receipts.
                item.update(enrichment_state='failed',enrichment_error=str(exc))
                results.append({'id':ident,'state':'failed','reason':str(exc)})
            finally:
                item['enrichment_at']=time.time();catalog.save(library,library_path)
    return dict(text=f'本批已检查 {len(results)} 项，清晰预览就绪 {sum(r["state"]=="ready" for r in results)} 项；未完成项可在详情重试。',
                items=results,remaining_ids=deferred,cancelled=cancel.exists(),failed=any(r['state']=='failed' for r in results))
