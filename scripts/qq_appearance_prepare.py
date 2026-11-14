"""Prepare saved favorites using the user's practical appearance policy; no UI."""
from datetime import datetime
from pathlib import Path
import hashlib,json,time
from contextlib import nullcontext,contextmanager
from contextvars import ContextVar
from threading import Lock
import numpy as np
from PIL import Image
from emoji_bridge import catalog
from emoji_bridge.state import save_json,sha
from emoji_bridge.snapshot_matching import CellMatcher
from emoji_bridge.appearance_originals import POLICY,shortlist,choose,register,evidence_session
from emoji_bridge.originals import attach_receipt
from emoji_bridge.media import inspection_session
from emoji_bridge.recognition import rgb
from emoji_bridge.paging import full_cell
import qq_cache_acquire as acquire


from emoji_bridge.timing import measured,stage

_session=ContextVar('qq_preparation_candidates',default=None)

@contextmanager
def preparation_session():
    """Reuse decoding within one account writer; never across worker runs."""
    if _session.get() is not None:
        yield
        return
    token=_session.set({})
    try:yield
    finally:_session.reset(token)


class Candidates:
    """One preparation worker's immutable matcher; never shared across runs."""
    def __init__(self,cancel=None):
        previews={};memory=0
        def remember(name,frame):
            nonlocal memory
            size=frame.width*frame.height*4
            if memory+size<=48*1024*1024:
                previews[name]=frame;memory+=size
        self.inventory,self.path=acquire.current_inventory(cancel,remember)
        # This route selects a validated appearance representative, not a
        # unique historical variant. Unreadable candidates remain recorded.
        self.digest=sha(self.path)
        self._locks={};self._lock_guard=Lock()
        def frames():
            for entry in self.inventory['items']:
                acquire.cancelled(cancel)
                im=previews.pop(entry['name'],None)
                if im is not None:yield entry['name'],im
                else:
                    with Image.open(entry['preview']) as im:yield entry['name'],im.convert('RGBA')
        with stage('qq_matcher_build'):
            self.matcher=CellMatcher(frames(),prefilter=True)
        self.matchers={58:self.matcher}
        previews.clear()

    def matcher_for(self,edge):
        if edge not in self.matchers:
            def frames():
                for entry in self.inventory['items']:
                    with Image.open(entry['preview']) as image:yield entry['name'],image.convert('RGBA')
            self.matchers[edge]=CellMatcher(frames(),edge=edge,prefilter=True)
        return self.matchers[edge]

    def check(self,cancel):
        current,path=acquire.current_inventory(cancel)
        if (path!=self.path or current.get('directory_fingerprint')!=self.inventory.get('directory_fingerprint')
                or sha(self.path)!=self.digest):raise ValueError('cache_inventory_changed')

    def asset_lock(self,digest):
        # Different pages may contain the same original. Preserve all origins
        # without racing the shared content-addressed asset manifest.
        with self._lock_guard:return self._locks.setdefault(digest,Lock())

@measured("original")
@evidence_session()
@inspection_session()
def prepare(library_path=None,cancel=None,progress=None,ids=None,*,candidates=None,on_item=None):
    library_path=Path(library_path) if library_path is not None else catalog.PATH
    start=time.perf_counter();library=catalog.read(library_path)
    known={i['id'] for i in library['clients']['qq']['items']}
    if ids is not None and (not ids or len(set(ids))!=len(ids) or not set(ids)<=known):raise ValueError('explicit_selection_required')
    pending=[i for i in library['clients']['qq']['items'] if (ids is None or i['id'] in ids)
             and (not i.get('original_available') or needs_refinement(i)) and not i.get('source_receipt_only')]
    if not pending:return dict(results=[],native_ui_calls=0,messages_sent=0)
    session=_session.get()
    if candidates is None and session is not None:
        candidates=session.get('candidates')
        if candidates is not None:
            try:candidates.check(cancel)
            except ValueError as exc:
                if str(exc)!='cache_inventory_changed':raise
                candidates=None
        if candidates is None:
            candidates=Candidates(cancel);session['candidates']=candidates
    if candidates is not None:candidates.check(cancel)
    inventory,inv_path=((candidates.inventory,candidates.path) if candidates is not None else acquire.current_inventory(cancel))
    acquire.cancelled(cancel)
    library['clients']['qq']['cache_diagnostics']=acquire.cache.diagnostic_summary(inventory)
    catalog.save(library,library_path)
    unreadable=len(inventory.get('failures',[]))
    cells={};paddings={};selected={};keys={}
    for item in pending:
        acquire.cancelled(cancel);scan,observation=acquire.context(item)
        page=scan['pages'][item['page']]
        key=hashlib.sha256(json.dumps([POLICY,'native-cell-dpi-v1',item['id'],sha(item['scan']),sha(inv_path),page['sha256']]).encode()).hexdigest()
        if item.get('appearance_attempt',{}).get('key')==key:continue
        with Image.open(page['image']) as im:
            if not full_cell(im,item['rect']):continue
            left,top,right,bottom=item['rect']
            pad=2 if full_cell(im,(left-2,top-2,right+2,bottom+2)) else 0
            cells[item['id']]=im.crop((left-pad,top-pad,right+pad,bottom+pad));paddings[item['id']]=pad
        selected[item['id']]=(item,scan,observation,page);keys[item['id']]=key
    if not cells:return dict(results=[],reused_unchanged_attempts=True,native_ui_calls=0,messages_sent=0)
    def frames():
        for entry in inventory['items']:
            acquire.cancelled(cancel)
            with Image.open(entry['preview']) as im:yield entry['name'],im.convert('RGBA')
    with stage('qq_matcher_build'):
        matchers={edge:(candidates.matcher_for(edge) if candidates is not None else CellMatcher(frames(),edge=edge,prefilter=True))
                  for edge in {min(cell.size)-2*paddings[ident] for ident,cell in cells.items()}}
    with stage('qq_match_cells'):
        hits={ident:matchers[min(cell.size)-2*paddings[ident]].match(cell,appearance=True,padding=paddings[ident],cancel_check=lambda:acquire.cancelled(cancel)) for ident,cell in cells.items()}
    folder=acquire.ROOT/'private/T006/appearance-bindings'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    search_path=folder/'search.json'
    save_json(search_path,dict(policy=POLICY,scope='cached_first_frame_appearance_candidates',
                              inventory_sha256=sha(inv_path),candidates=hits))
    entries={i['name']:i for i in inventory['items']};results=[]
    for ident,(item,scan,observation,page) in selected.items():
        acquire.cancelled(cancel);out=dict(id=ident,position=item['position'],status='pending_confirmation')
        try:
            group=shortlist(hits[ident]);target=folder/str(item['position']);copies={};small={}
            for name in group:
                acquire.cancelled(cancel)
                with stage('qq_copy_decode'):
                    c=acquire.cache.copied_original(inventory['root'],entries[name],target/'originals')
                copies[name]=c
                _,im=acquire.cache.first_frame(c['file'])
                # Copy decoded bytes must still yield the saved preview used by matching.
                with Image.open(entries[name]['preview']) as saved:
                    if saved.convert('RGBA').size!=im.size or saved.convert('RGBA').tobytes()!=im.tobytes():
                        raise ValueError('appearance_preview_changed')
                small[name]=np.asarray(rgb(im,(34,34,34)).resize((64,64)),dtype=np.int16)
            reference=small[group[0]]
            comparison={name:float(np.abs(image-reference).mean()/255) for name,image in small.items()}
            name=choose(hits[ident],copies,comparison)
            current,_=acquire.current_inventory(cancel)
            if current.get('directory_fingerprint')!=inventory.get('directory_fingerprint'):raise ValueError('cache_inventory_changed')
            acquire.cancelled(cancel)
            selection=target/'selection.json';copy_path=target/'copies.json';receipt=target/'receipt.json'
            save_json(selection,dict(policy=POLICY,item_id=ident,selected=observation,scan=item['scan'],
                        scan_sha256=sha(item['scan']),page_image=page['image'],page_sha256=page['sha256'],
                        candidate_name=name,comparison=comparison,preference='same_media_kind_then_resolution_then_bytes'))
            with stage('qq_provenance_and_asset'):
                save_json(copy_path,copies);register(selection,copy_path,search_path,inv_path,receipt)
                lock=candidates.asset_lock(copies[name]['sha256']) if candidates is not None else nullcontext()
                with lock:
                    acquire.cancelled(cancel)
                    asset,_=acquire.prepare_asset(Path(copies[name]['file']),'qq',acquire.ROOT/'private/T006/assets',native=True)
                    attach_receipt(asset,receipt);catalog.attach_original(item,asset)
            from qq_offline_index import target_readiness
            target_readiness(item)
            for field in ('source_snapshot','index_reason','thumbnail_diagnostic'):item.pop(field,None)
            item.update(matching_basis='appearance',exact_original_identity_proven=False,
                        appearance_candidate_count=len(group),
                          reason='外观匹配；同类型候选优先保留分辨率和较大文件，静图与动图歧义不自动选择。' if len(group)>1 else '外观匹配；完整文件已保留。')
            item['unreadable_cache_candidates']=unreadable
            if unreadable:item['reason']='外观匹配；完整文件已校验，另有缓存未读，不保证精确历史版本。'
            out.update(status='ready',receipt=str(receipt),candidate=name,alternatives=len(group),
                       frames=copies[name]['metadata']['frames'],bytes=copies[name]['metadata']['bytes'])
        except (OSError,ValueError) as exc:
            if str(exc) in ('cancel_requested','cache_inventory_changed'):raise
            out['reason']='cache_candidates_incomplete' if unreadable and str(exc)=='appearance_no_candidate' else str(exc)
            if needs_refinement(item):item.update(original_available=False,original_state='downloaded',reason=out['reason'])
        item['appearance_attempt']=dict(key=keys[ident],policy=POLICY,status=out['status'],reason=out.get('reason'))
        with stage('qq_publish'):catalog.save(library,library_path,compact=candidates is not None)
        results.append(out)
        if on_item:on_item(item)
        if progress:progress(len(results),len(selected))
    result=dict(results=results,policy=POLICY,seconds=round(time.perf_counter()-start,3),
                native_ui_calls=0,messages_sent=0,exact_original_identity_proven=False)
    save_json(folder/'result.json',result);return result


def needs_refinement(item):
    return item.get('matching_basis')=='appearance' and item.get('appearance_attempt',{}).get('policy')!=POLICY
