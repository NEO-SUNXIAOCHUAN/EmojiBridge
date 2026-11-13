"""A bounded fallback using actual personal Thumb renders; no window operations."""
from datetime import datetime
from pathlib import Path
import hashlib
import json
from PIL import Image
from emoji_bridge import catalog,qq_thumbnails as thumbs
from emoji_bridge.state import save_json,sha
from emoji_bridge.thumb_originals import register
from emoji_bridge.originals import attach_receipt
import qq_cache_acquire as acquire
from qq_offline_index import target_readiness


def prepare(library_path=None,cancel=None,positions=None):
    library_path=Path(library_path) if library_path is not None else catalog.PATH
    library=catalog.read(library_path);side=library['clients']['qq'];chosen={};cells={}
    for item in side['items']:
        if item.get('original_available') or (positions is not None and item['position'] not in positions):continue
        path=item.get('candidate_evidence')
        if not path:continue
        prior=catalog.read(path)
        # This route cannot discard an already-known alternative or choose a
        # static encoding in place of a same-first-frame animation.
        if (prior.get('candidates')!={} or not prior.get('native_raster_candidates_complete')
                or prior.get('candidate_scope') not in ('all_gif_frames_and_other_first_frames','all_native_frames_at_observed_hover')):continue
        scan,_=acquire.context(item)
        if prior['item_id']!=item['id'] or prior['scan_sha256']!=sha(item['scan']):raise ValueError('thumbnail_source_changed')
        page=scan['pages'][item['page']]
        if item['rect'][3]>279:continue
        with Image.open(page['image']) as im:cells[item['id']]=im.crop(item['rect'])
        chosen[item['id']]=(item,prior,page)
    if not chosen:return dict(results=[],client_operations=0)
    inventory,inv_path=acquire.current_inventory(cancel)
    if inventory.get('failures'):raise ValueError('cache_candidates_incomplete')
    for item,prior,_ in chosen.values():
        if prior['inventory_sha256']!=sha(inv_path):raise ValueError('cache_inventory_changed')
    try:thumbnail_fingerprint=thumbs.fingerprint(thumbs.thumbnail_root(inventory['root']))
    except (OSError,ValueError) as exc:
        return dict(results=[],client_operations=0,reason=str(exc))
    attempts={}
    for ident,(item,prior,page) in list(chosen.items()):
        key=hashlib.sha256(json.dumps([1,ident,sha(item['scan']),sha(item['candidate_evidence']),
                sha(inv_path),page['sha256'],thumbnail_fingerprint]).encode()).hexdigest()
        attempts[ident]=key
        if item.get('thumbnail_attempt',{}).get('key')==key:
            chosen.pop(ident);cells.pop(ident)
    if not chosen:return dict(results=[],client_operations=0,reused_unchanged_attempts=True)
    search=thumbs.search(inventory['root'],cells,lambda:acquire.cancelled(cancel))
    folder=acquire.ROOT/'private/T006/thumb-bindings'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    search_path=folder/'search.json';save_json(search_path,search);results=[]
    current,_=acquire.current_inventory(cancel)
    if current.get('directory_fingerprint')!=inventory.get('directory_fingerprint'):raise ValueError('cache_inventory_changed')
    for ident,(item,prior,page) in chosen.items():
        acquire.cancelled(cancel);result=dict(id=ident,position=item['position'],status='pending_confirmation')
        try:
            hits=search['candidates'][ident]
            if search['failures']:raise ValueError('thumbnail_candidates_incomplete')
            if len(hits)!=1:raise ValueError('thumbnail_not_matched' if not hits else 'thumbnail_candidates_ambiguous')
            name=next(iter(hits));digest=Path(name).stem.lower()
            entries=[e for e in inventory['items'] if Path(e['name']).stem.lower()==digest]
            if len(entries)!=1:raise ValueError('thumbnail_original_missing_or_ambiguous')
            target=folder/str(item['position']);target.mkdir(parents=True)
            raw=thumbs.thumb_bytes(search['root'],name);thumbnail=target/name
            thumbnail.write_bytes(raw)
            if sha(thumbnail)!=hits[name]['thumbnail_sha256']:raise ValueError('thumbnail_changed')
            copy=acquire.cache.copied_original(inventory['root'],entries[0],target/'original')
            correspondence=thumbs.static_correspondence(copy['file'],thumbnail)
            selection=target/'selection.json';copy_path=target/'copy.json';receipt=target/'receipt.json'
            save_json(selection,dict(item_id=ident,thumbnail_name=name,correspondence=correspondence))
            save_json(copy_path,copy)
            if thumbs.fingerprint(Path(search['root']))!=search['fingerprint']:raise ValueError('thumbnail_inventory_changed')
            register(selection,copy_path,search_path,item['candidate_evidence'],inv_path,thumbnail,item['scan'],page['image'],receipt)
            asset,_=acquire.prepare_asset(Path(copy['file']),'qq',acquire.ROOT/'private/T006/assets',native=True)
            attach_receipt(asset,receipt);catalog.attach_original(item,asset);target_readiness(item)
            item.pop('source_snapshot',None);item.pop('index_reason',None)
            result.update(status='ready',receipt=str(receipt))
        except (OSError,ValueError) as exc:
            if str(exc)=='cancel_requested':raise
            result['reason']=str(exc)
            # Preserve the original failure classification plus this additional
            # evidence. A missing thumbnail is not a missing original.
            item['thumbnail_diagnostic']=dict(reason=str(exc),report=str(search_path))
        item['thumbnail_attempt']=dict(key=attempts[ident],status=result['status'],report=str(search_path))
        results.append(result);catalog.save(library,library_path)
    report=dict(results=results,client_operations=0,messages_sent=0,report=str(folder/'result.json'))
    save_json(folder/'result.json',report);return report
