"""Ordinary local media: prepare, add/verify and read a bounded favorites view."""
import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys
import time
from contextlib import contextmanager
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
from emoji_bridge.client_sources import qq_profile, executable
from emoji_bridge.media import prepare_asset,load_asset,references
from emoji_bridge.recognition import find_media,find_in_cells,frame_evidence,animation_verdict,FrameMatcher,QQFrameMatcher
from emoji_bridge.vision import Match
from emoji_bridge.state import save_json,single_instance,sha
from emoji_bridge.timing import measured
from emoji_bridge.windows import StopAutomation,capture,guard,click,hover,restore_pointer,qq_windows,dialog_action,user,process_path,pid_of
from emoji_bridge.wechat import WeChat
from emoji_bridge.originals import origin_for_asset
from emoji_bridge.client_geometry import qq_grid_crop,qq_grid_cells
from qq_import import QQ
from wechat_import import relative


def read_json(path):return json.loads(Path(path).read_text(encoding='utf8'))


def handoff_to(target):
    """Validate the target; its adapter owns activation and fresh identity checks."""
    # Target.bind restores/activates its own identified main window. Opening
    # the OTHER client's panel here added work and required both windows/chat
    # sessions even when source bytes had already been authenticated directly.
    if target not in ('qq','wechat'):raise ValueError('unknown_target')


def recheck_media_cell(image,refs,hit,matcher):
    """Recheck ALL decoded frames at the already identified media rectangle.

    Global coarse pose proposals can miss a newly displayed GIF frame. The
    position and full-pixel threshold stay fixed; unrelated/moved media fails.
    """
    # This is the actual media rectangle, NOT a square favorite tile. Fitting
    # it inside min(width,height) a second time corrupts non-square GIF checks.
    x,y,w,h=hit.x,hit.y,hit.width,hit.height
    if not (0<=x<x+w<=image.width and 0<=y<y+h<=image.height):return []
    frame,error=matcher(image.crop((x,y,x+w,y+h)))
    return [Match(x,y,w,h,error)] if frame is not None and error<.04 else []


class OrdinaryImport:
    def __init__(self,asset_path,report,evidence,cancel=None):
        self.asset_path=Path(asset_path).resolve();self.asset=load_asset(asset_path)
        self.refs=references(self.asset);self.target=self.asset['target']
        from emoji_bridge.message_media import WeChatFrameMatcher
        self.matcher=WeChatFrameMatcher(self.refs,self.asset['prepared']) if self.target=='wechat' else QQFrameMatcher(self.refs)
        self.report=report;self.evidence=evidence;self.cancel=cancel
        # User policy S0033: success requires actual persistent membership,
        # not an additional timed animation playback observation.
        self.check_playback=False
        self.ledger=ROOT/'runtime-data/T004'/self.target/(self.asset['source_sha256']+'.json')
        self.prior=read_json(self.ledger) if self.ledger.exists() else None
        self.q=QQ(qq_profile(),report) if self.target=='qq' else WeChat(executable('wechat'),report)
        if self.target=='qq':self.q.cancel=cancel
        if self.target=='wechat':self.q.persistent=True;self.q.cancel_check=self.cancelled
        report.update(target=self.target,asset=str(self.asset_path),source_sha256=self.asset['source_sha256'],
                      prepared_sha256=self.asset['prepared_sha256'],conversion=self.asset['conversion'],
                      prior_state=self.prior.get('status') if self.prior else None,phone='not_confirmed',
                      submission_state='not_started' if not self.prior or self.prior.get('status')=='not_submitted' else 'may_have_started',
                      dedupe_scope='local source-content journal + current personal-favorites view; not full collection')

    def cancelled(self):
        if self.cancel and self.cancel.exists():raise StopAutomation('cancel_requested')

    @contextmanager
    def timed(self,name):
        start=time.perf_counter()
        try:yield
        finally:
            timings=self.report.setdefault('timings_seconds',{})
            timings[name]=round(timings.get(name,0)+time.perf_counter()-start,4)

    def record(self,status):
        save_json(self.ledger,{'status':status,'asset':str(self.asset_path),'source_sha256':self.asset['source_sha256'],
                              'prepared_sha256':self.asset['prepared_sha256'],'report':str(self.evidence),
                              'updated':datetime.now().astimezone().isoformat()})

    def boundary(self,status):
        self.cancelled();load_asset(self.asset_path)
        self.report.update(submission_started=True,submission_state='may_have_started')
        self.record(status)

    def panel(self,reopen=False):
        self.cancelled()
        if self.target=='qq':
            panel,box,_=self.q.reopen_panel() if reopen else self.q.open_panel()
            grid,rect=qq_grid_crop(panel,box)
            return grid,self.q.window,rect
        grid,popup,box=self.q.panel(open_if_closed=True)
        if reopen:
            self.q.close_popup(popup);grid,popup,box=self.q.panel(open_if_closed=True)
        return grid,popup,box

    def locate(self,grid):
        # Geometry comes from the freshly proven favorite panel / UIA, never
        # the chat behind it. Check ALL cells and ALL source frames so duplicate
        # candidates still block success. No costly whole-image search per pose.
        with self.timed('favorite_matching'):
            cells=getattr(self.q,'last_cells',[]) if self.target=='wechat' else getattr(self.q,'last_cells',qq_grid_cells(grid))
            if cells:
                hits=find_in_cells(grid,self.refs,cells,self.matcher,**({'pixel_tolerance':2} if self.target=='qq' else {}))
                if self.target=='qq' and len(hits)>1:
                    from emoji_bridge.recognition import distinguish_candidates
                    hits,evidence=distinguish_candidates(grid,self.refs,hits,((34,34,34),(253,253,253)))
                    self.report['candidate_spatial_check']=evidence
                return hits
            return [] if self.target=='qq' else find_media(grid,self.refs,(72,70,74))

    def close_panel(self,window):
        self.cancelled()
        if self.target=='wechat':self.q.close_popup(window)
        else:self.q.click_icon(self.q.smile(),'smile',tuple(self.q.config['toolbar_roi']))

    @measured('verification')
    def verify(self,wait=0,leave_missing_open=False,shared=None,keep_open=False):
        deadline=time.monotonic()+wait
        while True:
            if shared is None:grid,window,box=self.panel()
            else:grid,unused,window,box=shared
            found=self.locate(grid)
            if found or time.monotonic()>=deadline:break
            self.cancelled();time.sleep(.2)
        self.report['favorite_candidates']=len(found);self.report['sample_seen']=bool(found)
        grid.save(self.evidence/'favorites-before-reopen.png')
        if len(found)!=1:
            if not leave_missing_open and not keep_open:self.close_panel(window)
            return False
        if shared is None:grid,window,box=self.panel(reopen=True)
        else:unused,grid,window,box=shared
        found=self.locate(grid)
        grid.save(self.evidence/'favorites-after-reopen.png')
        self.report['favorite_match_after']=[asdict(m) for m in found]
        passed=len(found)==1
        if passed:
            self.report['collection_persisted']=True
            if len(self.refs)>1:
                if not getattr(self,'check_playback',False):
                    self.report['animation']={'status':'not_tested','reason':'target_playback_check_disabled_by_user',
                                              'playback_confirmed':False}
                    self.report['acceptance']='favorite_membership_and_reopen_only'
                    if not keep_open:self.close_panel(window)
                    return True
                capability=animation_verdict([],self.refs,[])
                if capability['required_visual_states']<2:
                    # The current thumbnail measurement cannot distinguish this
                    # source's motion. Nine seconds of sampling cannot fix that.
                    self.report['animation']=dict(capability,reason='source_motion_below_current_visual_resolution')
                    self.report['animation_wait']='skipped_unresolvable_thumbnail_motion'
                    if not keep_open:self.close_panel(window)
                    return False
                hit=found[0];region=(box[0]+hit.x,box[1]+hit.y,box[0]+hit.x+hit.width,box[1]+hit.y+hit.height)
                if self.target=='wechat':
                    # UIA plus full-source matching can consume the initial
                    # preview cycle. Membership and geometry were verified
                    # above; capture immediately on reopening, then revalidate
                    # the grid afterward. No message or add action occurs.
                    self.q.close_popup(window);self.q.control('toggle-panel')
                    window=self.q.popup()
                    self.report['animation_restart']='capture_immediately_after_panel_reopen'
                if self.target=='wechat':
                    # Hovering a favorite can start a separate enlarged preview
                    # and stop the small tile we sample. Keep the pointer on the
                    # UIA-identified custom tab, without selecting/sending media.
                    l,t,r,b=self.q.last_tab
                    point=((l+r)//2,(t+b)//2)
                    self.report['animation_pointer']='custom_favorites_tab_no_sticker_hover'
                else:point=((region[0]+region[2])//2,(region[1]+region[3])//2)
                old,expected=hover(window,self.q.exe,*point)
                background=(34,34,34)
                if self.target=='qq':
                    # Observed QQ hover enlarges the media from a 58 px box to
                    # a centered 64 px box; compare actual content at that size.
                    width,height=self.asset['prepared_metadata']['oriented_size']
                    scale=64*(box[2]-box[0])/434/max(width,height);width=round(width*scale);height=round(height*scale)
                    cx,cy=box[0]+hit.center[0],box[1]+hit.center[1]
                    region=(cx-width//2,cy-height//2,cx-width//2+width,cy-height//2+height)
                    self.report['animation_geometry']='QQ centered 64 px hover media box'
                    # Measured on QQ 9.9.20.37625 dark theme: the hovered
                    # transparent media box is RGB 54, rather than idle RGB 37.
                    # Retain full-pixel/source-frame thresholds; do not ignore alpha.
                    background=(54,54,54)
                    self.report['animation_background_rgb']=list(background)
                    time.sleep(.3)
                observations=[];samples=[];saved={};start=time.monotonic()
                try:
                    while time.monotonic()-start<9:
                        self.cancelled()
                        guard(window,self.q.exe)
                        cell=capture(window).crop(region);index,error=self.matcher(cell,background)
                        if index is None and not (self.evidence/'animation-unmatched.png').exists():
                            cell.save(self.evidence/'animation-unmatched.png')
                        observations.append({'elapsed':round(time.monotonic()-start,3),'frame':index,'error':error})
                        samples.append(cell)
                        if index is not None and index not in saved and len(saved)<8:
                            p=self.evidence/f'animation-{index}.png';cell.save(p);saved[index]=str(p)
                        if len(saved)>=2 and animation_verdict(observations,self.refs,samples)['playback_confirmed']:
                            self.report['animation_wait']='stopped_on_full_playback_witness'
                            break
                        time.sleep(.15)
                    if self.target=='wechat':
                        meta=self.q.uia('panel',window)
                        actual=tuple(round(v-origin) for v,origin in zip(meta['grid'],window.rect[:2]*2))
                        if actual!=box:raise StopAutomation('animation_grid_geometry_changed')
                    else:self.q.panel()
                finally:restore_pointer(old,expected)
                verdict=animation_verdict(observations,self.refs,samples)
                witnesses=[]
                for index in verdict['witness_observations']:
                    path=self.evidence/f'animation-witness-{index}.png';samples[index].save(path)
                    witnesses.append({'observation':index,'frame':observations[index]['frame'],
                                      'path':str(path),'sha256':sha(path)})
                self.report['animation']={**verdict,'observations':observations,'evidence':saved,'visual_witnesses':witnesses}
                passed=verdict['playback_confirmed']
        if not keep_open:self.close_panel(window)
        return passed

    def run(self,command='add'):
        if self.asset.get('source_only') and command!='verify':raise StopAutomation('source_only_asset_cannot_be_submitted')
        self.cancelled()
        with self.timed('window_bind'):
            handoff_to(self.target);self.q.bind()
        if command=='discard-staged':
            if self.target!='wechat' or not self.prior or self.prior['status'] not in ('send_pending','input_staged'):raise StopAutomation('no_known_unsent_preview')
            if self.prior['prepared_sha256']!=self.asset['prepared_sha256']:raise StopAutomation('staged_asset_changed')
            snap=self.q.uia()
            saved=Path(self.prior['report'])/'staged-composer.png'
            if not saved.exists() or not snap['input_only_object']:raise StopAutomation('unsent_preview_evidence_required')
            before=self.q.frame().crop(relative(snap['input'],self.q.window));expected=Image.open(saved).convert('RGB')
            if before.size!=expected.size or np.abs(np.asarray(before,dtype=float)-np.asarray(expected,dtype=float)).mean()/255>.003:raise StopAutomation('unsent_preview_changed')
            before.save(self.evidence/'discarded-unsent-preview.png');self.q.uia('clear-staged')
            if not self.q.uia()['input_empty']:raise StopAutomation('composer_clear_not_confirmed')
            self.record('not_submitted');self.report.update(status='unsent_preview_discarded');return
        with self.timed('precheck'):
            existing=self.verify(leave_missing_open=self.target=='qq')
        if existing:
            self.record('desktop_confirmed');self.report.update(status='already_exists',desktop_confirmed=True);return
        if self.report.get('sample_seen'):
            self.report.update(status='pending_confirmation',reason='favorite_candidate_not_confirmed_no_add');return
        phase=self.prior.get('status') if self.prior else None
        staged=command=='resume' and phase in ('send_pending','input_staged')
        sent=command=='resume' and phase=='send_click_pending'
        if command=='verify' or (self.prior and phase!='not_submitted' and not staged and not sent):
            self.report.update(status='pending_confirmation',reason='verification_did_not_confirm_favorite' if command=='verify' else 'prior_attempt_no_blind_resubmit');return
        if command=='resume' and not self.prior:raise StopAutomation('no_prior_attempt')
        self.cancelled()
        with self.timed('submit'):
            if self.target=='qq':
                self.q.open_panel()
                dialog=self.q.picker()
                self.report['file_selection']=self.q.dialog_action(dialog,'Choose',Path(self.asset['prepared']),lambda:self.boundary('favorite_pending'))
                time.sleep(.3)
            else:self.send_wechat(staged,sent)
        # Import progress is not success. Bounded read-only waits allow the client
        # to finish; no second submit occurs even if this wait expires.
        with self.timed('verify_after_submit'):
            confirmed=self.verify(wait=15)
        if confirmed:
            self.record('desktop_confirmed');self.report.update(status='desktop_confirmed',desktop_confirmed=True)
        else:self.report.update(status='pending_confirmation',reason='favorite_not_confirmed_no_retry')

    def send_wechat(self,staged,sent,send_only=False):
        q=self.q
        if not staged and not sent:
            if not q.uia()['input_empty']:raise StopAutomation('composer_not_empty')
            self.boundary('input_pending');q.control('open-file')
            dialogs=[w for w in qq_windows(q.exe) if w.kind=='#32770' and w.pid==q.window.pid]
            if len(dialogs)!=1:raise StopAutomation('file_dialog_not_unique')
            self.report['file_selection']=dialog_action(dialogs[0],q.window,q.exe,'Choose',Path(self.asset['prepared']),lambda:self.boundary('send_pending'))
            time.sleep(1)
        snap=q.uia();composer=relative(snap['input'],q.window)
        if not snap['input_empty']:
            if sent:raise StopAutomation('sent_resume_requires_empty_composer')
            crop=q.frame().crop(composer);crop.save(self.evidence/'staged-composer.png')
            from emoji_bridge.message_media import staged_matches
            hits=staged_matches(crop,self.refs,self.matcher)
            if not hits and staged and self.prior and self.prior.get('status')=='input_staged':
                # Resume the known unsent object even when its GIF pose has
                # changed. The saved crop supplies coordinates only; current
                # pixels must independently match the intact original.
                saved=Path(self.prior['report'])/'staged-composer.png'
                if saved.is_file():
                    with Image.open(saved) as old:
                        leads=staged_matches(old,self.refs,self.matcher) if old.size==crop.size else []
                    if len(leads)==1:hits=recheck_media_cell(crop,self.refs,leads[0],self.matcher)
            self.report['composer_matches']=[asdict(m) for m in hits]
            if len(hits)!=1 or not snap.get('input_only_object') or not snap['send_enabled']:raise StopAutomation('staged_media_requires_identity_check')
            self.record('input_staged');meta=q.uia('send')
            current=relative(meta['input'],q.window)
            fresh=recheck_media_cell(q.frame().crop(current),self.refs,hits[0],self.matcher)
            if current!=composer or len(fresh)!=1 or fresh[0].center!=hits[0].center:raise StopAutomation('staged_media_changed')
            self.boundary('send_click_pending');target=relative(meta['target'],q.window)
            click(q.window,q.exe,(target[0]+target[2])//2,(target[1]+target[3])//2)
            time.sleep(1);snap=q.uia();composer=relative(snap['input'],q.window)
            if not snap['input_empty']:raise StopAutomation('input_not_cleared_after_send')
        if send_only:return
        self.add_wechat_message()

    def add_wechat_message(self,exclude_ids=(),timeout=3,located=None):
        q=self.q
        from emoji_bridge.message_media import locate,row_regions
        hit,identity,row=located or locate(q,self.refs,self.cancelled,self.report,self.evidence,timeout=timeout,matcher=self.matcher,exclude_ids=exclude_ids)
        self.report['message_candidates']=[asdict(hit)]
        self.cancelled();meta=q.uia('message-rows');frame=q.frame()
        _,rows=row_regions(meta,q.window,frame.size)
        if [r for i,r in rows if i==identity]!=[row]:raise StopAutomation('message_moved')
        fresh=recheck_media_cell(frame,self.refs,hit,self.matcher)
        if len(fresh)!=1 or fresh[0].center!=hit.center:raise StopAutomation('message_moved')
        self.cancelled()
        click(q.window,q.exe,*hit.center,right=True)
        # The native popup has its own bounded readiness wait. Do not insert
        # the old fixed 400 ms delay between every two additions.
        menu=q.popup(menu=True);state=q.uia('menu',menu)
        # Use the existing add action immediately. This is not a send receipt;
        # exact native rejections are handled separately, without resending.
        if state.get('available') is not True:
            q.close_popup(menu)
            raise StopAutomation('message_not_ready_to_add')
        target=state['target'];self.boundary('favorite_pending')
        click(menu,q.exe,round((target[0]+target[2])/2)-menu.rect[0],round((target[1]+target[3])/2)-menu.rect[1],owner=q.window)
        try:q.wait_for_import_settle()
        except StopAutomation as exc:
            if str(exc)=='wechat_add_rejected':
                # Only the exact native rejection resolves this ADD attempt.
                # Preserve the submitted message: Continue checks membership
                # first, then may add that message, but must never resend it.
                self.report['add_rejected_by_client']=True
                self.record('batch_message_submitted')
            raise
        finally:
            if isinstance(q.report,dict) and isinstance(q.report.get('last_import_settle'),dict):
                self.report['import_settle']=dict(q.report['last_import_settle'])


def execute(asset,command='add',cancel=None):
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder=ROOT/'reports/T004'/stamp;evidence=ROOT/'private/T004/evidence'/stamp
    evidence.mkdir(parents=True);report={'command':command,'started':datetime.now().astimezone().isoformat()}
    runner=None;started=time.perf_counter()
    try:
        with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
            preparation=time.perf_counter();runner=OrdinaryImport(asset,report,evidence,cancel)
            report['timings_seconds']={'load_and_decode':round(time.perf_counter()-preparation,4)}
            runner.run(command)
    except Exception as exc:
        cancelled=str(exc) in ('cancel_requested','cancelled_escape')
        report.update(status='pending_confirmation' if report.get('submission_started') or report.get('prior_state') else ('cancelled' if cancelled else 'failed'),reason=str(exc))
    finally:
        if runner is not None and runner.target=='wechat':
            try:runner.q.close()
            except Exception:
                # Cleanup must not discard the durable outcome of an import.
                report['helper_cleanup']='unconfirmed'
        report.setdefault('timings_seconds',{})['total']=round(time.perf_counter()-started,4)
    report['finished']=datetime.now().astimezone().isoformat();report['evidence']=str(evidence)
    save_json(folder/'result.json',report);report['report_path']=str(folder/'result.json');return report


def execute_recovery(asset,command='add',cancel=None):
    """Resume only a durable, proven pre-send object; uncertain sends stay verify-only.

    The adapter rechecks the original, self session, unique current composer,
    and a fresh all-frame pixel match. It never opens the picker on this path.
    """
    if command=='verify':
        a=load_asset(asset)
        ledger=ROOT/'runtime-data/T004'/a['target']/(a['source_sha256']+'.json')
        prior=read_json(ledger) if ledger.exists() else {}
        if (a['target']=='wechat' and prior.get('status') in ('send_pending','input_staged')
                and prior.get('source_sha256')==a['source_sha256']
                and prior.get('prepared_sha256')==a['prepared_sha256']
                and Path(prior.get('asset','')).resolve()==Path(asset).resolve()):
            command='resume'
    return execute(asset,command,cancel)


def recheck_source(asset):
    """Recheck authenticated index membership or the recorded client UI source."""
    a=load_asset(asset);origin=origin_for_asset(a)
    if origin.get('original_origin')=='personal_cache_original_from_this_collection':
        from qq_cache_acquire import recheck_acquired
        return recheck_acquired(asset)
    if a['target']=='qq' and origin.get('original_origin')=='client_save_as_from_this_collection':
        receipt=read_json(origin['original_provenance'])
        selection=read_json(receipt['evidence'][0]['path'])
        if selection.get('scan') and selection.get('item_id'):
            from qq_export import recheck_acquired
            return recheck_acquired(asset)
        # Added items shift old sources below the first viewport. This is only
        # fresh membership rechecking; the validated export receipt already
        # carries the original animation and close/reopen evidence.
        from qq_pages import read_pages
        pages_path,pages=read_pages(3)
        refs=references(a);found=[]
        for page in pages['pages']:
            from emoji_bridge.paging import observed_cells
            with Image.open(page['image']) as grid:
                cells=[c['rect'] for c in page.get('cells',[]) if c.get('membership')=='native_collection_sticker'] or [c['rect'] for c in observed_cells(grid,page.get('offset',0))]
                hits=find_in_cells(grid,refs,cells,QQFrameMatcher(refs),pixel_tolerance=2)
            if hits:found.append({'view':page['view'],'matches':[asdict(hit) for hit in hits]})
        passed=pages['status']=='bounded_views_captured' and found and all(len(x['matches'])==1 for x in found)
        report={'method':'bounded_qq_favorite_membership_with_prior_export_receipt','status':'already_exists' if passed else 'pending_confirmation',
                'receipt':origin['original_provenance'],'source_sha256':a['source_sha256'],'views_report':str(pages_path),
                'matches':found,'scope':'three viewports, overlap possible; not global uniqueness or new playback test'}
        path=pages_path.with_name(pages_path.stem+'-membership.json');save_json(path,report);report['report_path']=str(path);return report
    if origin.get('original_origin')!='favorite_index_original_from_this_collection':
        return execute(asset,'verify')
    from emoji_bridge.wechat_index import snapshot
    receipt=read_json(origin['original_provenance'])
    acquisition=read_json(receipt['evidence'][0]['path'])
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    path=ROOT/'reports/T004-index'/('source-recheck-'+stamp+'.json')
    report={'method':'unchanged_authenticated_favorite_index_and_digest_verified_original',
            'source_ui_verified':receipt.get('source_ui_verified',receipt['schema']=='selected-favorite-index-export-v1'),
            'source_sha256':a['source_sha256'],'receipt':origin['original_provenance'],'status':'pending_confirmation'}
    try:
        _,_,current=snapshot(acquisition['source']);previous=acquisition['snapshot']
        report['snapshot_unchanged']=all(current[k]==previous[k] for k in ('db_sha256','wal_sha256','checkpoint'))
        if report['snapshot_unchanged']:report['status']='already_exists'
        else:
            from wechat_acquire import current_member
            member,fresh=current_member(acquisition,receipt['member']['md5'],None)
            report.update(status='already_exists',method='fresh_authenticated_local_favorite_member_and_unchanged_original',
                          current_index=fresh,source_ui_repeated=False)
    except Exception as exc:report['reason']=type(exc).__name__
    save_json(path,report);report['report_path']=str(path);return report


def inventory(target,assets):
    """Read only an anchored personal-favorites view. Never browse chat caches.

    Known original bytes come from immutable user-supplied import assets, NOT
    from thumbnails. Unknown visible cells remain thumbnail-only/unexportable.
    """
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    evidence=ROOT/'private/T004/inventory'/stamp;evidence.mkdir(parents=True)
    result={'schema':'favorites-visible-v1','source_kind':'personal_favorites_ui','target':target,
            'complete':False,'scope':'one current visible personal-favorites grid; no scrolling',
            'total_collection_count':None,'original_export_complete':False,'items':[],
            'unknown_items':'Only thumbnails in the grid image; originals and animation metadata unavailable',
            'captured':datetime.now().astimezone().isoformat()}
    with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
        handoff_to(target)
        q=QQ(qq_profile(),result) if target=='qq' else WeChat(executable('wechat'),result)
        q.bind()
        if target=='qq':
            panel,box,_=q.open_panel();grid,box=qq_grid_crop(panel,box);window=q.window
            # Known calibrated slots only; unknown/empty slots are not claimed
            # as individual collected originals. Exclude the plus button.
            slots=q.last_cells
            slot_kind='calibrated_visible_slot; occupancy_unconfirmed'
        else:
            grid,window,box=q.panel(open_if_closed=True)
            meta=q.uia('panel',window);slots=[]
            for cell in meta.get('cells',[]):
                left,top,right,bottom=cell['rect'];g=meta['grid']
                if g[0]<=left<right<=g[2] and g[1]<=top<bottom<=g[3]:slots.append(tuple(round(v) for v in (left-g[0],top-g[1],right-g[0],bottom-g[1])))
            slot_kind='visible_UIA_button_in_custom_favorites_list'
        path=evidence/'personal-favorites-visible.png';grid.save(path);result['grid_image']=str(path)
        result['grid_sha256']=sha(path)
        result['visible_slots']=[]
        for index,rect in enumerate(slots):
            preview=evidence/f'slot-{index:02d}.png';grid.crop(rect).save(preview)
            result['visible_slots'].append({'slot':index,'rect':rect,'kind':slot_kind,'preview':str(preview),
                'preview_only':True,'original_available':False,'animation':'unknown','favorite_count_claim':False})
        for path in assets:
            a=load_asset(path)
            if a['target']!=target:raise ValueError('inventory_asset_wrong_client')
            refs=references(a)
            hits=find_in_cells(grid,refs,slots,QQFrameMatcher(refs),pixel_tolerance=2) if target=='qq' else find_media(grid,refs,(72,70,74))
            result['items'].append({'id':a['source_sha256'],'asset':str(Path(path).resolve()),'match_count':len(hits),
                'matches':[asdict(h) for h in hits],'original_available':len(hits)==1,
                **origin_for_asset(a),'prepared_sha256':a['prepared_sha256']})
            if len(hits)==1:
                x,y=hits[0].center
                for slot in result['visible_slots']:
                    l,t,r,b=slot['rect']
                    if l<=x<r and t<=y<b:slot.update(bound_item=a['source_sha256'],original_available=True)
        if target=='qq':q.click_icon(q.smile(),'smile',tuple(q.config['toolbar_roi']))
        else:q.close_popup(window)
    path=ROOT/'reports/T004/inventory'/f'{target}-{stamp}.json';save_json(path,result)
    return path,result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('prepare','add','verify','resume','discard-staged','inventory','plan','run','cancel'))
    p.add_argument('--asset',type=Path);p.add_argument('--file',type=Path);p.add_argument('--target',choices=('qq','wechat'))
    p.add_argument('--max-edge',type=int);p.add_argument('--cancel-file',type=Path)
    p.add_argument('--known-asset',type=Path,action='append',default=[])
    p.add_argument('--selection',type=Path);p.add_argument('--plan',type=Path);p.add_argument('--continue-cancelled',action='store_true')
    a=p.parse_args()
    required={'prepare':('file','target'),'inventory':('target',),'plan':('selection','plan'),
              'run':('plan',),'cancel':('plan',)}.get(a.command,('asset',))
    for key in required:
        if getattr(a,key) is None:p.error('--'+key.replace('_','-')+' is required')
    if a.command=='prepare':
        path,m=prepare_asset(a.file,a.target,ROOT/'private/T004/assets',a.max_edge)
        print(json.dumps({'asset':str(path),'prepared':m['prepared'],'bytes':m['prepared_metadata']['bytes']},ensure_ascii=False));return 0
    if a.command=='inventory':
        path,r=inventory(a.target,a.known_asset);print(json.dumps({'inventory':str(path),'complete':False,'bound_originals':sum(x['original_available'] for x in r['items'])},ensure_ascii=False));return 0
    if a.command in ('plan','run','cancel'):
        from emoji_bridge.transfer import make_plan,make_export_plan,run_plan
        if a.command=='cancel':a.plan.with_suffix('.cancel').touch();print('cancel_requested');return 0
        if a.command=='plan':
            selected=read_json(a.selection)
            r=(make_export_plan if selected and 'source_asset' in selected[0] else make_plan)(selected,a.plan)
        else:
            with single_instance(ROOT/'runtime-data/T004/queue.lock'):
                r=run_plan(a.plan,execute,recheck_source,a.continue_cancelled)
        print(json.dumps({'plan':str(a.plan),'run_state':r.get('run_state'),'counts':r.get('counts'),'jobs':len(r['jobs'])},ensure_ascii=False));return 0
    r=execute(a.asset,a.command,a.cancel_file)
    print(json.dumps({k:r.get(k) for k in ('status','reason','report_path')},ensure_ascii=False))
    return 0 if r['status'] in ('desktop_confirmed','already_exists','unsent_preview_discarded') else 2


if __name__=='__main__':raise SystemExit(main())
