"""Prepare the observed QQ library once; transfers never trigger window scans."""
from datetime import datetime
from pathlib import Path
import time
from PIL import Image,ImageOps
import qq_cache_acquire as acquire
import qq_snapshot
from emoji_bridge import catalog
from emoji_bridge.media import references
from emoji_bridge.originals import attach_receipt
from emoji_bridge.snapshot_originals import register
from emoji_bridge.state import save_json,sha
from emoji_bridge.paging import full_cell
from emoji_bridge.snapshot_matching import CellMatcher,NATIVE_PROFILE

VERSION=6


def target_readiness(item):
    """Expose known conversion limitations before selection, not on transfer."""
    meta=catalog.read(item['asset'])
    reason=None
    if meta['original_metadata']['format']!='GIF':
        with Image.open(meta['original_copy']) as im:
            extrema=im.convert('RGBA').getextrema()[3]
            if 0<extrema[1]<128:
                reason='这张图过于透明，转GIF会丢失全部可见内容；原文件已保留。'
    if reason:item['transfer_block_reason']=reason
    else:item.pop('transfer_block_reason',None)


def needs_prepare(side,fingerprint=None):
    built=side.get('index_build',{})
    return bool(side.get('items')) and (built.get('state')!='finished' or built.get('version')!=VERSION
        or (fingerprint is not None and built.get('fingerprint')!=fingerprint))


def mark_result(item,result):
    if result['status'] in ('ready','reused'):
        item.pop('index_reason',None);return
    reason=result.get('reason','original_mapping_unconfirmed');item['index_reason']=reason
    names={'selected_favorite_original_not_matched_in_cache':'本地文件尚未与这张收藏对应，暂不可搬运。',
           'selected_favorite_has_multiple_cache_candidates':'有多个相似原件，暂不能唯一对应。',
           'saved_cell_clipped_refresh_index_required':'旧预览不完整，需要更新索引。',
           'saved_original_match_not_strong_enough':'完整文件与收藏预览仍有差异，暂不可搬运。',
           'cache_candidates_incomplete':'部分缓存候选无法读取，暂不能排除歧义。'}
    item['reason']=names.get(reason,reason)
    if item.get('asset'):
        item.update(original_state='downloaded',original_available=False)


def animation_leads(inventory,cells,cancel=None):
    """Search later GIF poses too; a first-frame hit must not hide ambiguity."""
    results={ident:{} for ident in cells}
    if not cells:return results
    for entry in inventory['items']:
        acquire.cancelled(cancel)
        if entry['metadata']['format']!='GIF':continue
        path=acquire.cache.candidate_path(inventory['root'],entry['name']);before=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(entry['size'],entry['mtime_ns']):raise ValueError('cache_candidate_changed')
        with Image.open(path) as im:
            count=getattr(im,'n_frames',1)
            if count>2000 or im.width*im.height*count>256_000_000:raise ValueError('cache_animation_scan_incomplete')
            if count<2:continue
            def frames():
                for n in range(1,count):
                    acquire.cancelled(cancel);im.seek(n);frame=ImageOps.exif_transpose(im).convert('RGBA')
                    frame.thumbnail((96,96),Image.Resampling.LANCZOS);yield n,frame
            matchers={edge:CellMatcher(frames(),edge=edge,prefilter=len(cells)>=8) for edge in {min(c.size) for c in cells.values()}}
            for ident,cell in cells.items():
                hits=matchers[min(cell.size)].match(cell)
                if hits:
                    n=min(hits,key=lambda n:hits[n]['error'])
                    results[ident][entry['name']]=dict(hits[n],frame=n)
        after=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('cache_candidate_changed')
    return results


def native_frames(path,cancel=None):
    """Do not shrink to a preview first: double resampling loses fine text."""
    with Image.open(path) as im:
        count=getattr(im,'n_frames',1)
        if count>2000 or im.width*im.height*count>256_000_000:raise ValueError('cache_animation_scan_incomplete')
        for n in range(count):
            acquire.cancelled(cancel);im.seek(n)
            yield n,ImageOps.exif_transpose(im).convert('RGBA')


def native_leads(inventory,cells,cancel=None):
    results={ident:{} for ident in cells}
    if not cells:return results
    for entry in inventory['items']:
        acquire.cancelled(cancel)
        path=acquire.cache.candidate_path(inventory['root'],entry['name']);before=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(entry['size'],entry['mtime_ns']):raise ValueError('cache_candidate_changed')
        matchers={edge:CellMatcher(native_frames(path,cancel),edge=edge,native=True,prefilter=len(cells)>=8) for edge in {min(c.size) for c in cells.values()}}
        for ident,cell in cells.items():
            hits=matchers[min(cell.size)].match(cell)
            if hits:
                n=min(hits,key=lambda n:hits[n]['error'])
                results[ident][entry['name']]=dict(hits[n],frame=n)
        after=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('cache_candidate_changed')
    return results


def build(library_path=None,cancel=None,progress=None,stage=None,after_basic=None,practical_first=False):
    library_path=Path(library_path) if library_path is not None else catalog.PATH
    started=time.perf_counter();freshly_prepared=set()
    if practical_first:
        # The accepted representative policy can prepare clear first-frame
        # matches without first searching every animation frame in the cache.
        # Each result still preserves full files and an appearance receipt.
        from qq_appearance_prepare import prepare
        if stage:stage('先按外观准备 QQ 收藏；完整原件与动画保留，未对应项目随后补查。')
        practical=prepare(library_path,cancel,progress=progress)
        freshly_prepared={r['id'] for r in practical.get('results',[]) if r['status']=='ready'}
        if after_basic:
            after_basic()
            after_basic=None
    library=catalog.read(library_path);side=library['clients']['qq']
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder=acquire.ROOT/'private/T006/offline-index'/stamp;results=[]
    if stage:stage('正在读取 QQ 本地原件目录；首次需要建立对应记录，不发送消息。')
    inventory,inv_path=acquire.current_inventory(cancel)
    # Decode each first-frame preview only once for the whole library. The
    # Later GIF poses join the same candidate set before uniqueness is decided.
    entries={entry['name']:entry for entry in inventory['items']}
    duplicate_entries=len(entries)!=len(inventory['items'])
    def frames():
        for entry in entries.values():
            acquire.cancelled(cancel)
            with Image.open(entry['preview']) as im:yield entry['name'],im.convert('RGBA')
    pages={};cells={};reusable=set(freshly_prepared)
    for item in side['items']:
        acquire.cancelled(cancel)
        # New results were fully validated by this same call's preparation.
        # Previously saved receipts are checked once per build, not twice.
        if item['id'] in reusable or qq_snapshot.reusable(item):
            reusable.add(item['id']);continue
        try:
            scan,_=acquire.context(item)
            image_path=scan['pages'][item['page']]['image']
            if image_path not in pages:
                with Image.open(image_path) as im:pages[image_path]=im.convert('RGB')
            if not full_cell(pages[image_path],item['rect']):continue
            cells[item['id']]=pages[image_path].crop(item['rect'])
        except (OSError,ValueError,KeyError):continue
    matchers={edge:CellMatcher(frames(),edge=edge,prefilter=len(cells)>=8) for edge in {min(c.size) for c in cells.values()}}
    if stage and cells:stage(f'正在补查 {len(cells)} 项收藏与本地动图画面；已准备项目可先浏览。')
    later=animation_leads(inventory,cells,cancel)
    candidates={ident:matchers[min(cell.size)].match(cell) for ident,cell in cells.items()}
    for ident,hits in candidates.items():
        for name,hit in later.get(ident,{}).items():
            if name not in hits or hit['error']<hits[name]['error']:hits[name]=hit
    unresolved={ident:cells[ident] for ident,hits in candidates.items() if len(hits)!=1}
    for item in side['items']:
        if item['id'] not in unresolved:continue
        multiple=bool(candidates[item['id']])
        item['index_reason']='selected_favorite_has_multiple_cache_candidates' if multiple else 'selected_favorite_original_not_matched_in_cache'
        item['reason']=('多个原件画面相近，等待区分版本；其他项目先准备。' if multiple
                        else '预览与本地文件尚未对应，等待进一步读取；其他项目先准备。')
    catalog.save(library,library_path)
    extra={};hard_started=False
    # Persist easy originals FIRST. A few uncertain cells must not hide all the
    # ready rows or block preparation of the other client. Keep stored ordering.
    ordered=([i['id'] for i in side['items'] if i['id'] not in unresolved]
             +[i['id'] for i in side['items'] if i['id'] in unresolved])
    by_id={i['id']:i for i in side['items']}
    # Reuse this immutable directory inventory for this build, not per item.
    for n,ident in enumerate(ordered):
        acquire.cancelled(cancel)
        if ident in unresolved and not hard_started:
            hard_started=True
            if after_basic:
                after_basic()
                # Callback may prepare WeChat. Re-read so its new receipts and
                # progress cannot be overwritten by this QQ worker's old copy.
                library=catalog.read(library_path);side=library['clients']['qq']
                by_id={i['id']:i for i in side['items']}
                if set(by_id)!=set(ordered):raise ValueError('library_selection_changed')
            if stage:stage(f'已准备的项目先显示；正在单独区分 {len(unresolved)} 项相似原件。')
            extra=native_leads(inventory,unresolved,cancel)
            for key,hits in extra.items():
                for name,hit in hits.items():
                    prior=candidates[key].get(name)
                    if prior is None or hit['error']<prior['error']:candidates[key][name]=hit
        item=by_id[ident]
        if ident in reusable:
            target_readiness(item)
            results.append({'id':item['id'],'status':'reused'});continue
        result={'id':item['id'],'status':'pending_confirmation'}
        try:
            scan,selected=acquire.context(item)
            if duplicate_entries:raise ValueError('selected_favorite_has_multiple_cache_candidates')
            if inventory.get('failures'):raise ValueError('cache_candidates_incomplete')
            image_path=scan['pages'][item['page']]['image']
            if image_path not in pages:
                with Image.open(image_path) as im:pages[image_path]=im.convert('RGB')
            if not full_cell(pages[image_path],item['rect']):raise ValueError('saved_cell_clipped_refresh_index_required')
            cell=pages[image_path].crop(item['rect']);leads=candidates.get(item['id'],{})
            if len(leads)!=1:
                candidate_path=folder/f'candidates-{n}.json'
                save_json(candidate_path,{'item_id':item['id'],'scan':item['scan'],'scan_sha256':sha(item['scan']),
                    'inventory':str(inv_path),'inventory_sha256':sha(inv_path),
                    'candidate_scope':'all_gif_frames_and_other_first_frames',
                    'native_raster_candidates_complete':item['id'] in extra,
                    'candidates':leads})
                item['candidate_evidence']=str(candidate_path)
            if not leads:raise ValueError('selected_favorite_original_not_matched_in_cache')
            if len(leads)!=1:raise ValueError('selected_favorite_has_multiple_cache_candidates')
            name=next(iter(leads));entry=entries[name]
            target=folder/str(n);target.mkdir(parents=True,exist_ok=True)
            copy=acquire.cache.copied_original(inventory['root'],entry,target/'original')
            asset,meta=acquire.prepare_asset(Path(copy['file']),'qq',acquire.ROOT/'private/T006/assets',native=True)
            native=leads[name].get('profile')==NATIVE_PROFILE
            hits=(CellMatcher(native_frames(meta['original_copy'],cancel),edge=min(cell.size),native=True).match(cell) if native
                  else CellMatcher(enumerate(references(meta)),edge=min(cell.size)).match(cell))
            if not hits:raise ValueError('saved_original_match_not_strong_enough')
            matched=min(hits.values(),key=lambda hit:hit['error'])
            selection={'source_kind':'personal_favorites_ui','item_id':item['id'],'selected':selected,
                       'scan':item['scan'],'scan_sha256':sha(item['scan']),
                       'page_image':scan['pages'][item['page']]['image'],'page_sha256':scan['pages'][item['page']]['sha256'],
                       'candidate_count':1,'candidate_name':entry['name'],'candidate_match':leads[name],
                       'candidate_scope':'all_gif_frames_and_other_first_frames',
                       'native_raster_candidates_complete':native,
                       'inventory':str(inv_path)}
            save_json(target/'selection.json',selection);save_json(target/'copy.json',copy)
            save_json(target/'matching.json',{'scope':'recorded_favorite_view_full_original','item_id':item['id'],
                       'source_sha256':meta['source_sha256'],'match_count':1,**matched,
                       'full_frames_decoded':meta['original_metadata']['frames'],'source_playback_verified':False})
            receipt=target/'receipt.json';register(target/'selection.json',target/'copy.json',target/'matching.json',receipt)
            attach_receipt(asset,receipt);catalog.attach_original(item,asset)
            target_readiness(item)
            item.pop('source_snapshot',None)
            result.update(status='ready',asset=str(asset),receipt=str(receipt))
        except Exception as exc:
            if str(exc) in ('cancel_requested','cancelled_escape'):raise
            result['reason']=str(exc)
        mark_result(item,result)
        results.append(result)
        side['index_build']={'state':'building','processed':n+1,'total':len(side['items']),'report':str(folder/'result.json')}
        catalog.save(library,library_path)
        if progress:progress(n+1,len(side['items']))
    side['index_build']={'state':'finished','scan':side.get('source_report'),'processed':len(results),
                        'version':VERSION,'fingerprint':inventory.get('directory_fingerprint'),
                        'ready':sum(r['status'] in ('ready','reused') for r in results),
                        'report':str(folder/'result.json'),'at':datetime.now().astimezone().isoformat()}
    catalog.save(library,library_path)
    report={'items':results,'seconds':round(time.perf_counter()-started,3),'native_ui_calls':0,
            'complete_collection_proven':False,'source_scope':'saved observed collection; not all cache files'}
    save_json(folder/'result.json',report);return report
