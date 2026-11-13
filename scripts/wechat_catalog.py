"""Authenticated favorite previews, loaded on demand without any client clicks.

Previews decode the first complete frame, without waiting for the whole GIF or
full-animation checks. A preview never grants a transferable source receipt.
Resource URLs remain in this process; no key or URL cache is written.
"""
from datetime import datetime
from pathlib import Path
import sys
import time
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
import wechat_acquire as acquire
from emoji_bridge import catalog,wechat_index as index
from emoji_bridge.state import save_json,sha,single_instance


class PreviewReader:
    def __init__(self,workers=3):
        self.members={};self.report=None;self.path=None
        self.workers=max(1,min(3,workers))

    def refresh(self,source_report,cancel=None):
        path=Path(source_report).resolve()
        if not path.is_relative_to(ROOT/'reports'):raise ValueError('index_report_outside_project')
        previous=catalog.read(path)
        if previous.get('status')!='index_decrypted_and_integrity_verified':raise ValueError('verified_index_required')
        members,report=acquire.current_index(previous,cancel)
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.path=ROOT/'reports/T005'/f'wechat-index-{stamp}.json'
        save_json(self.path,report)
        self.members={m['md5']:m for m in members};self.report=report
        return self.path,report

    def preview(self,item,cancel=None):
        acquire.cancelled(cancel)
        digest=item['member']['md5']
        if (len(digest)!=32 or any(c not in '0123456789abcdef' for c in digest)
                or item['id']!='wechat:'+digest or digest not in self.members):raise ValueError('preview_member_not_in_current_index')
        member=self.members[digest]
        folder=ROOT/'private/T005/wechat-acquire'/digest;folder.mkdir(parents=True,exist_ok=True)
        state_path=folder/'state.json'
        result={'report':str(self.path),'new_download':False}
        with single_instance(ROOT/'runtime-data/T005/wechat-previews'/f'{digest}.lock'):
            if state_path.exists():
                source,original=acquire.saved_download(catalog.read(state_path),digest)
                if Path(source['source']).resolve()!=Path(self.report['source']).resolve():raise ValueError('cached_source_mismatch')
            else:
                # Keep preview-only data outside the intact-original directory.
                preview=index.download_preview(member,ROOT/'private/T005/preview-only'/digest,
                                               lambda:acquire.cancelled(cancel))
                return dict(result,**preview)
            # A small display derivative is separate from the intact original.
            display=folder/'display.png'
            valid=False
            if display.exists():
                try:
                    with Image.open(display) as small:small.verify()
                    valid=True
                except (OSError,ValueError):pass
            if not valid:
                with Image.open(original['path']) as image:
                    frame=ImageOps.exif_transpose(image).convert('RGBA')
                    frame.thumbnail((96,96),Image.Resampling.LANCZOS);frame.save(display)
            return dict(result,status='downloaded_pending_verification',downloaded_file=original['path'],display_preview=str(display),
                        metadata=original['metadata'],reason='可预览；搬运时核验源收藏。')

    def refresh_library(self,library_path,cancel=None):
        library=catalog.read(library_path)
        path,report=self.refresh(library['clients']['wechat']['source_report'],cancel)
        catalog.merge_wechat(library,path);catalog.save(library,library_path)
        return {'report':str(path),'count':report['index_count']}

    def load(self,library_path,ids,cancel=None,on_item=None,repair_ids=(),*,update_catalog=True):
        started=time.perf_counter()
        if len(ids)>18 or len(set(ids))!=len(ids):raise ValueError('visible_preview_batch_limit')
        library=catalog.read(library_path);side=library['clients']['wechat']
        selected_now={i['id']:i for i in side['items']}
        if all(i not in selected_now or (i not in repair_ids and selected_now[i].get('preview') and Path(selected_now[i]['preview']).is_file()) for i in ids):return {'loaded':0,'failed':0,'cached':len(ids)}
        if not self.report:
            path,report=self.refresh(side['source_report'],cancel)
            if update_catalog:catalog.merge_wechat(library,path);catalog.save(library,library_path);side=library['clients']['wechat']
        # Do not start new network requests using a changed index snapshot.
        _,_,now=index.snapshot(Path(self.report['source']))
        if not all(now[k]==self.report['snapshot'][k] for k in ('db_sha256','wal_sha256','checkpoint')):
            path,report=self.refresh(side['source_report'],cancel)
            if update_catalog:catalog.merge_wechat(library,path);catalog.save(library,library_path);side=library['clients']['wechat']
        selected={i['id']:i for i in side['items']};results=[]
        if not set(repair_ids)<=set(ids):raise ValueError('preview_repair_outside_selection')
        todo=iter(ident for ident in ids if ident in selected and (ident in repair_ids or not (
            selected[ident].get('preview') and Path(selected[ident]['preview']).is_file())))
        index_seconds=time.perf_counter()-started
        def fetch(ident):
            item=selected[ident];begin=time.perf_counter()
            try:
                result=self.preview(item,cancel)
            except index.IndexErrorSafe as exc:
                if str(exc)=='cancel_requested':raise
                result={'status':'preview_unavailable','error':str(exc),'reason':'预览读取未通过，详见本机记录。'}
            except Exception as exc:
                result={'status':'preview_unavailable','error':type(exc).__name__,'reason':'预览文件或读取环境未通过检查。'}
            return dict(result,item_id=ident,elapsed_seconds=round(time.perf_counter()-begin,3))
        # At most three downloads are in flight, and no work for the next view
        # is queued after cancellation. Library writes stay on this coordinator.
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            pending={}
            def fill():
                while len(pending)<self.workers:
                    acquire.cancelled(cancel)
                    ident=next(todo,None)
                    if ident is None:break
                    pending[pool.submit(fetch,ident)]=ident
            fill()
            while pending:
                completed,_=wait(pending,return_when=FIRST_COMPLETED)
                for future in completed:
                    ident=pending.pop(future);result=future.result();item=selected[ident]
                    if result['status']=='preview_available':
                        # No asset, frames count, acquisition state or receipt.
                        item.update(preview=result['display_preview'],preview_kind='first_frame_only')
                        item.pop('preview_error',None)
                    elif result['status']=='downloaded_pending_verification':
                        if item.get('original_state')=='ready':
                            # Preview repair must not downgrade verified origin receipts.
                            item['preview']=result['display_preview']
                        else:catalog.apply_acquisition(item,result)
                        item.pop('preview_error',None)
                    else:item.update(preview_error=result['reason'])
                    results.append(result);catalog.save(library,library_path)
                    if on_item:on_item(ident)
                fill()
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        report=ROOT/'reports/T005'/f'wechat-previews-{stamp}.json'
        save_json(report,{'scope':'explicit visible preview items only','results':results,'client_actions':0,'index':str(self.path),
                         'workers':self.workers,'index_seconds':round(index_seconds,3),'elapsed_seconds':round(time.perf_counter()-started,3)})
        passed=('preview_available','downloaded_pending_verification')
        return {'report':str(report),'loaded':sum(r['status'] in passed for r in results),
                'failed':sum(r['status'] not in passed for r in results)}
