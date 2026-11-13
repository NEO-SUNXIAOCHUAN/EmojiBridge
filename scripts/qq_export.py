"""Acquire one explicitly selected QQ favorite through the confirmed self chat.

No chat-cache lookup. Persist intent before each submission. An uncertain
attempt is never automatically sent again. Only a source-verified original
receives a transferable receipt.
"""
import ctypes as c,json,sys,time,hashlib
from datetime import datetime
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
from emoji_bridge.client_sources import qq_profile, executable
from qq_import import QQ
from local_bridge import handoff_to,read_json
from emoji_bridge.state import save_json,sha,single_instance
from emoji_bridge.client_geometry import qq_grid_rect,qq_panel_point,qq_panel_box,client_scale
from emoji_bridge.windows import (StopAutomation,click,scroll,guard,hover,restore_pointer,
    qq_windows,dialog_action,dialog_controls,user,pid_of)
from emoji_bridge.paging import difference,page_anchors_match,align_scroll
from emoji_bridge.media import prepare_asset,load_asset,references,inspect
from emoji_bridge.recognition import find_in_cells,frame_evidence,animation_verdict,FrameMatcher,QQFrameMatcher,rgb
from emoji_bridge.vision import matches
from emoji_bridge.originals import register_save_as,attach_receipt

PROFILE=ROOT/'private/T005/profile'
BINDING=ROOT/'private/T004-originals/qq-own/binding.json'
INPUT=(272,561,992,674)


def check_cancel(cancel):
    if cancel and Path(cancel).exists():raise StopAutomation('已请求取消')


def save_boundary(cancel,ledger):
    check_cancel(cancel)
    save_json(ledger,{'phase':'before_save'})


def own_chat(q):
    binding=read_json(BINDING)
    if q.window.dpi!=96 or binding['window'].get('dpi',96)!=q.window.dpi or tuple(binding['window']['rect'])!=q.window.rect:
        raise StopAutomation('own_session_binding_geometry_changed')
    if q.window.hwnd!=binding['window']['hwnd'] or q.window.pid!=binding['window']['pid']:
        raise StopAutomation('本人会话绑定已失效，需要重新确认')
    reference=BINDING.parent/'header.png'
    if sha(reference)!=binding['header_sha256']:raise StopAutomation('本人会话证据已改变')
    expected=Image.open(reference).crop((8,18,70,47))
    current=q.frame().crop(tuple(binding['header_roi'])).crop((8,18,70,47))
    if difference(current,expected)>.001:raise StopAutomation('当前 QQ 会话不是已确认的本人会话')


def first_panel(q,limit=48,cancel=None):
    check_cancel(cancel)
    if hasattr(type(q),'first_favorites_panel'):
        return q.first_favorites_panel(limit,cancel)
    if hasattr(type(q),'native_controls'):
        controls=q.native_controls();state=controls.open();controls.top(state)
        box=current_panel_box(q)
        return q.frame().crop(box),box,None
    roi=tuple(q.config['panel_search_roi'])
    try:heart=q.icon(q.frame(),'heart',roi)
    except StopAutomation as exc:
        if str(exc)!='heart_not_uniquely_identified':raise
        # A closed panel may remember a lower scroll position. Open it using
        # the proven toolbar, then seek the top only if positioning needs it.
        q.click_icon(q.smile(),'smile',tuple(q.config['toolbar_roi']))
        heart=q.icon(q.frame(),'heart',roi)
    box=(heart.x-128,heart.y-300,heart.x+322,heart.y+37)
    for _ in range(limit+1):
        check_cancel(cancel)
        try:return q.panel()
        except StopAutomation as exc:
            if str(exc) not in ('plus_not_uniquely_identified','favorite_panel_geometry_changed'):raise
        fresh=q.icon(q.frame(),'heart',roi)
        if fresh.center!=heart.center:raise StopAutomation('收藏面板位置已改变')
        if _==limit:break
        scroll(q.window,q.exe,*qq_panel_point(box,410,160),1);time.sleep(.65)
    raise StopAutomation('无法确认收藏首屏，未点击条目')


def current_panel_box(q):
    """Fresh personal-grid geometry, including views without the import tile.

    Keep the source matcher's calibrated crop; a decorative heart is no
    longer an anchor for native clients. Unsupported geometry still stops.
    """
    if hasattr(type(q),'native_controls'):
        state=q.native_controls().read('panel')
        if not state.get('favorites_open'):raise StopAutomation('qq_uia_personal_favorites_not_open')
        return qq_panel_box(q.window,state)
    heart=q.icon(q.frame(),'heart',tuple(q.config['panel_search_roi']))
    return (heart.x-128,heart.y-300,heart.x+322,heart.y+37)


def open_retained_panel(q):
    if hasattr(type(q),'native_controls'):
        q.native_controls().open()
    else:q.click_icon(q.smile(),'smile',tuple(q.config['toolbar_roi']))


def selected_page(q,scan,item,cancel=None):
    panel,box,_=first_panel(q,cancel=cancel)
    def grid_now():return q.frame().crop(qq_grid_rect(box))
    grid=grid_now();first=scan['pages'][0]
    if sha(first['image'])!=first['sha256']:raise StopAutomation('分页证据已改变')
    if not page_anchors_match(Image.open(first['image']),grid,first['cells'],item['position'])[0]:
        raise StopAutomation('首屏收藏顺序已变，请重新读取')
    anchor=current_panel_box(q)
    offset=0;recorded=scan['pages'][item['page']]
    if sha(recorded['image'])!=recorded['sha256']:raise StopAutomation('分页证据已改变')
    for step in range(49):
        check_cancel(cancel)
        delta=recorded['offset']-offset
        rect=[item['rect'][0],item['rect'][1]+delta,item['rect'][2],item['rect'][3]+delta]
        if 0<=rect[1] and rect[3]<=grid.height:break
        if rect[1]<0 or step==48:raise StopAutomation('滚动跳过所选条目，未点击')
        previous=grid
        scroll(q.window,q.exe,*qq_panel_point(box,410,160),-1);time.sleep(.65)
        if current_panel_box(q)!=anchor:
            raise StopAutomation('收藏面板位置已改变')
        grid=grid_now();offset+=align_scroll(previous,grid)['pixels']
    page=dict(recorded,offset=offset,selected_rect=rect,cells=[])
    for cell in recorded['cells']:
        l,t,r,b=cell['rect'];translated=[l,t+delta,r,b+delta]
        if 0<=translated[1] and translated[3]<=grid.height:
            page['cells'].append(dict(cell,rect=translated))
    saved=Image.new('RGB',grid.size);saved.paste(Image.open(recorded['image']),(0,delta))
    passed,count=page_anchors_match(saved,grid,page['cells'],item['position'])
    if not passed:
        folder=ROOT/'private/T005/page-mismatch';folder.mkdir(parents=True,exist_ok=True)
        grid.save(folder/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.png'))
        raise StopAutomation('分页位置无法重新核对，未点击条目')
    expected=Image.open(recorded['image']).crop(item['rect']);deadline=time.monotonic()+4
    while difference(expected,grid.crop(rect))>.025:
        check_cancel(cancel)
        if time.monotonic()>=deadline:raise StopAutomation('所选条目画面未与读取证据吻合，未点击')
        time.sleep(.15);grid=grid_now()
    return grid,box,page


def reset_panel(q,box,steps,cancel=None):
    first_panel(q,cancel=cancel);check_cancel(cancel)
    q.click_icon(q.smile(),'smile',tuple(q.config['toolbar_roi']))


def close_selected_panel(q,box,cancel=None):
    check_cancel(cancel)
    if current_panel_box(q)!=box:raise StopAutomation('favorite_panel_anchor_changed')
    if hasattr(type(q),'native_controls'):q.native_controls().close_panel()
    else:q.click_icon(q.smile(),'smile',tuple(q.config['toolbar_roi']))


def reopen_selected_page(q,grid,box,page,scan,item,cancel=None):
    """Reopen at the retained position and recheck neighbors; otherwise relocate.

    No persisted position or stale screenshot is accepted as fresh membership.
    """
    close_selected_panel(q,box,cancel)
    open_retained_panel(q)
    check_cancel(cancel)
    actual=current_panel_box(q)
    if actual!=box:raise StopAutomation('favorite_panel_anchor_changed')
    fresh=q.frame().crop(qq_grid_rect(box))
    if page_anchors_match(grid,fresh,page['cells'],item['position'])[0]:
        q.report['source_reopen_retained_view']=True
        return fresh,box,page
    q.report['source_reopen_retained_view']=False
    return selected_page(q,scan,item,cancel)


def native_filename(dialog):
    found=[x for x in dialog_controls(dialog) if x['class']=='Edit' and x['id'] in (1148,1001)]
    if len(found)!=1:raise StopAutomation('另存文件名控件未唯一识别')
    buf=c.create_unicode_buffer(32768);out=c.c_size_t()
    if not user.SendMessageTimeoutW(found[0]['hwnd'],0x000D,len(buf),c.addressof(buf),2,5000,c.byref(out)):
        raise StopAutomation('无法读取另存文件类型')
    extension=Path(buf.value).suffix.lower()
    if extension not in ('.png','.jpg','.jpeg','.gif','.webp'):
        raise StopAutomation('另存文件类型未确认')
    return extension


def latest_media_point(frame):
    # The bound self-chat's newest outgoing media ends above the composer;
    # exclude avatars, timestamps and all other conversation columns.
    a=np.asarray(frame.crop((700,340,955,508)),dtype=float)
    mask=(np.max(np.abs(a-(34,34,34)),axis=2)>28)
    rows=np.where(mask.sum(axis=1)>12)[0]
    if not len(rows) or rows[-1]<110:raise StopAutomation('未识别对应的最新本人图片消息')
    bottom=rows[-1];top=bottom
    while top>0 and mask[top-1].sum()>12:top-=1
    if bottom-top<12:raise StopAutomation('最新消息媒体区域不明确')
    y=(top+bottom)//2;xs=np.where(mask[y])[0]
    return 700+int(xs[len(xs)//2]),340+int(y)


class SourceAnimationPending(StopAutomation):
    """Only this item's playback proof is incomplete; not a client interruption."""


class QQHoverMatcher:
    """QQ 9.9.20 hover paints white at 20/255 over opaque pixels too.

    Keep full-frame thresholds and original frame identities. This fixed paint
    model is limited to a freshly identified QQ favorite under the pointer.
    """
    def __init__(self,refs,plain):
        self.plain=plain
        self.painted=FrameMatcher([Image.blend(rgb(ref),Image.new('RGB',ref.size,'white'),20/255) for ref in refs])

    def __call__(self,crop):
        plain=self.plain(crop,(54,54,54));painted=self.painted(crop)
        return (*painted,'qq_white_hover_20') if painted[1]<plain[1] else (*plain,'original')


class QQCellMatcher:
    """A user pointer can already hover a cell during a read-only scan.

    Both models compare full source frames at the unchanged acceptance
    threshold. The painted/transparent-background model is QQ-specific and
    must not change matching of WeChat or generic image candidates.
    """
    def __init__(self,refs):
        self.plain=QQFrameMatcher(refs);self.hover=QQHoverMatcher(refs,self.plain)

    def __call__(self,crop,background=(34,34,34)):
        plain=self.plain(crop,background)
        if plain[1]<.04:return plain
        painted=self.hover(crop)[:2]
        return painted if painted[1]<plain[1] else plain


def hover_regions(x,y,width,height):
    """Native shorter-edge rounding may differ by one pixel, as in idle cells."""
    sizes=[(width,height)]
    if width<height:sizes.extend((width+d,height) for d in (-1,1))
    elif height<width:sizes.extend((width,height+d) for d in (-1,1))
    return [(x-w//2,y-h//2,x-w//2+w,y-h//2+h) for w,h in sizes]


def verify_animation(q,a,refs,matcher,hit,box,folder,result,cancel=None):
    if len(refs)>1:
        origin=qq_grid_rect(box);x=origin[0]+hit.center[0];y=origin[1]+hit.center[1]
        old,expected=hover(q.window,q.exe,x,y)
        w,h=a['prepared_metadata']['oriented_size'];scale=64*client_scale(q.window.dpi)/max(w,h);w=round(w*scale);h=round(h*scale)
        regions=hover_regions(x,y,w,h);observations=[];samples=[]
        hover_matcher=QQHoverMatcher(refs,matcher.plain if isinstance(matcher,QQCellMatcher) else matcher)
        time.sleep(.3);start=time.monotonic()
        try:
            while time.monotonic()-start<8:
                check_cancel(cancel)
                image=q.frame();choices=[]
                for region in regions:
                    cell=image.crop(region);frame,error,paint=hover_matcher(cell)
                    choices.append((error,frame,paint,cell,region))
                error,frame,paint,cell,region=min(choices,key=lambda c:c[0])
                observations.append({'frame':frame,'error':error,'paint_model':paint,'media_rect':list(region)})
                samples.append(cell)
                if frame is not None and len({x['frame'] for x in observations})<9:cell.save(folder/f'animation-{frame}.png')
                if len({x['frame'] for x in observations if x['frame'] is not None})>=2 and animation_verdict(observations,refs,samples)['playback_confirmed']:break
                time.sleep(.17)
        finally:restore_pointer(old,expected)
        verdict=animation_verdict(observations,refs,samples);witnesses=[]
        for index in verdict['witness_observations']:
            path=folder/f'animation-witness-{index}.png';samples[index].save(path)
            witnesses.append({'observation':index,'frame':observations[index]['frame'],'path':str(path),'sha256':sha(path)})
        result['animation']={**verdict,'observations':observations,'visual_witnesses':witnesses}
        if not result['animation']['playback_confirmed']:
            if samples:samples[-1].save(folder/'animation-unconfirmed.png')
            raise SourceAnimationPending('原件已保存但源收藏动画待确认')


def verify_source(q,scan,item,asset,folder,cancel=None,content_locator=False):
    check_cancel(cancel)
    a=load_asset(asset);refs=references(a);matcher=QQCellMatcher(refs);result={'command':'verify','target':'qq','source_sha256':a['source_sha256'],
        'client_version':q.report['client_version'],'evidence':str(folder),'status':'pending_confirmation'}
    for reopen in (False,True):
        if content_locator:
            import qq_source_locator as locator
            grid,box,page=(locator.reopen(q,grid,box,page,refs,matcher,folder,cancel) if reopen
                           else locator.locate(q,refs,matcher,folder,cancel))
            result.setdefault('content_locations',[]).append({k:v for k,v in page.items() if k!='cells'})
            if reopen:q.report['source_reopen_retained_view']=page.get('retained_view',False)
        else:
            grid,box,page=reopen_selected_page(q,grid,box,page,scan,item,cancel) if reopen else selected_page(q,scan,item,cancel)
        hits=find_in_cells(grid,refs,[i['rect'] for i in page['cells']],matcher)
        l,t,r,b=page['selected_rect'];selected=[h for h in hits if l<=h.center[0]<r and t<=h.center[1]<b]
        grid.save(folder/('favorites-after-reopen.png' if reopen else 'favorites-before-reopen.png'))
        if len(hits)!=1 or len(selected)!=1:
            reset_panel(q,box,item['page'],cancel);raise StopAutomation('原文件未与所选源收藏唯一匹配')
    result['source_reopen_retained_view']=q.report.get('source_reopen_retained_view',False)
    hit=selected[0];result['favorite_match_after']=[hit.__dict__];result['collection_persisted']=True
    verify_animation(q,a,refs,matcher,hit,box,folder,result,cancel)
    close_selected_panel(q,box,cancel);result['status']='already_exists'
    path=folder/'source-verification.json';save_json(path,result);return path


def acquire_selected(item,cancel=None,resume_staged=False):
    ident=hashlib.sha256(item['id'].encode()).hexdigest()[:20]
    folder=ROOT/'private/T005/qq-export'/ident;folder.mkdir(parents=True,exist_ok=True)
    report=ROOT/'reports/T005'/('qq-export-'+ident+'.json');ledger=folder/'phase.json'
    result={'status':'pending_confirmation','report':str(report),'item_id':item['id'],'source_kind':'personal_favorites_ui'}
    def boundary(phase):
        check_cancel(cancel)
        own_chat(q);save_json(ledger,{'phase':phase,'at':datetime.now().astimezone().isoformat()})
    try:
        check_cancel(cancel)
        if ledger.exists():
            if report.exists() and read_json(report).get('status')=='original_verified':return read_json(report)
            previous=read_json(ledger)
            if not resume_staged or previous.get('phase')!='staged':
                raise StopAutomation('先前获取尚未确认，禁止自动重发')
        profile=read_json(PROFILE/'manifest.json')
        for name in ('empty-input.png','send.png','save-as.png'):
            if sha(PROFILE/name)!=profile['sha256'][name]:raise StopAutomation('导出校准证据已改变')
        scan=read_json(item['scan'])
        if scan.get('source_kind')!='personal_favorites_ui':raise StopAutomation('来源不是个人收藏')
        recorded=next((i for i in scan['items'] if i['id']==item['id']),None)
        if not recorded or any(recorded[k]!=item[k] for k in ('page','position','rect')):raise StopAutomation('选择与分页证据不一致')
        with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
            check_cancel(cancel)
            handoff_to('qq');q=QQ(qq_profile(),{});q.bind();own_chat(q)
            empty=Image.open(PROFILE/'empty-input.png')
            if resume_staged:
                previous=read_json(ledger)
                if sha(folder/'staged-input.png')!=previous.get('staged_sha256'):
                    raise StopAutomation('暂存对象证据已改变，未发送')
                if difference(q.frame().crop(INPUT),Image.open(folder/'staged-input.png'))>.001:
                    raise StopAutomation('暂存输入已改变，未发送')
            else:
                if difference(q.frame().crop(INPUT),empty)>.003:raise StopAutomation('本人会话输入框非空，未操作')
                grid,box,page=selected_page(q,scan,item,cancel);grid.save(folder/'source-grid.png')
                grid.crop(page['selected_rect']).save(folder/'source-preview.png')
                save_json(folder/'selection.json',{'source_kind':'personal_favorites_ui','source_cell':page['selected_rect'],
                    'scan':item['scan'],'page':item['page'],'position':item['position'],'item_id':item['id']})
                save_json(folder/'send-intent.json',{'phase':'before_personal_favorite_click','own_session_binding':str(BINDING)})
                boundary('before_favorite_click');l,t,r,b=page['selected_rect'];click(q.window,q.exe,qq_grid_rect(box)[0]+(l+r)//2,qq_grid_rect(box)[1]+(t+b)//2);time.sleep(.7)
                # Empty -> one object in the observed top-left composer area. Any
                # other changed content prevents sending; never clear user text.
                current=q.frame().crop(INPUT);current.save(folder/'staged-input.png')
                mask=np.max(np.abs(np.asarray(current,dtype=float)-np.asarray(empty,dtype=float)),axis=2)>18
                yy,xx=np.where(mask)
                if len(xx)<150 or max(xx)>116 or max(yy)>109:raise StopAutomation('输入框不是单一表情对象，未发送')
                save_json(ledger,{'phase':'staged','staged_sha256':sha(folder/'staged-input.png')})
            send=matches(q.frame().crop((880,672,995,719)),Image.open(PROFILE/'send.png'),.025,count=3)
            if len(send)!=1:raise StopAutomation('发送按钮未唯一识别')
            save_json(folder/'message-submit.json',{'phase':'before_send_button','own_session_binding':str(BINDING),'reviewed_input':'staged-input.png'})
            boundary('before_send');hit=send[0];click(q.window,q.exe,880+hit.center[0],672+hit.center[1]);time.sleep(.9)
            own_chat(q)
            check_cancel(cancel)
            if difference(q.frame().crop(INPUT),empty)>.003:raise StopAutomation('发送后输入框状态待确认')
            frame=q.frame();point=latest_media_point(frame);frame.crop((700,340,955,508)).save(folder/'self-message.png')
            click(q.window,q.exe,*point,right=True);time.sleep(.4)
            menus=matches(q.frame(),Image.open(PROFILE/'save-as.png'),.03,count=3)
            if len(menus)!=1:raise StopAutomation('消息另存菜单未唯一识别')
            check_cancel(cancel)
            click(q.window,q.exe,*menus[0].center);time.sleep(.5)
            dialogs=[];deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                check_cancel(cancel)
                dialogs=[w for w in qq_windows(q.exe) if w.kind=='#32770' and w.pid==q.window.pid]
                if len(dialogs)==1:break
                if len(dialogs)>1:raise StopAutomation('另存窗口未唯一识别')
                time.sleep(.2)
            if len(dialogs)!=1:raise StopAutomation('另存窗口未唯一识别')
            dialog=dialogs[0];extension=native_filename(dialog);destination=folder/('client-export'+extension)
            save_json(folder/'save-intent.json',{'destination':str(destination),'source_chain':'selected_personal_favorite -> confirmed_self_chat_message -> Save As'})
            check_cancel(cancel)
            dialog_action(dialog,q.window,q.exe,'SaveNew',destination,lambda:save_boundary(cancel,ledger),output_root=folder)
            deadline=time.monotonic()+10
            while time.monotonic()<deadline and not destination.exists():check_cancel(cancel);time.sleep(.25)
            check_cancel(cancel)
            metadata,_=inspect(destination);save_json(ledger,{'phase':'saved'})
            check_cancel(cancel);q.bind();own_chat(q)
            asset,_=prepare_asset(destination,'qq',ROOT/'private/T005/assets')
            verification=verify_source(q,scan,item,asset,folder,cancel)
            receipt=folder/'original-receipt.json'
            register_save_as(destination,'qq',folder/'selection.json',folder/'save-intent.json',verification,receipt)
            attach_receipt(asset,receipt)
            result.update(status='original_verified',asset=str(asset),file=str(destination),metadata=metadata,receipt=str(receipt),source_verification=str(verification))
            save_json(ledger,{'phase':'original_verified','asset':str(asset)})
    except Exception as exc:result['reason']=str(exc)
    save_json(report,result);return result


def resume_saved_acquisition(item,cancel=None):
    """Continue an already open owned Save As dialog or verify an existing file.

    This path contains no favorite selection or message submission.
    """
    ident=hashlib.sha256(item['id'].encode()).hexdigest()[:20]
    folder=ROOT/'private/T005/qq-export'/ident;ledger=folder/'phase.json'
    report=ROOT/'reports/T005'/('qq-export-'+ident+'.json')
    result={'status':'pending_confirmation','report':str(report),'item_id':item['id'],'source_kind':'personal_favorites_ui'}
    try:
        check_cancel(cancel)
        phase=read_json(ledger)['phase']
        if phase not in ('before_send','before_save','saved'):
            raise StopAutomation('当前阶段不允许只保存或核验恢复')
        selection=read_json(folder/'selection.json');scan=read_json(selection['scan'])
        recorded=next(i for i in scan['items'] if i['id']==item['id'])
        if any(recorded[k]!=item[k] for k in ('page','position','rect')):raise StopAutomation('选择证据已改变')
        with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
            check_cancel(cancel)
            q=QQ(qq_profile(),{})
            existing=folder/'save-intent.json'
            destination=Path(read_json(existing)['destination']) if existing.exists() else None
            if destination is None or not destination.exists():
                binding=read_json(BINDING)
                windows=[w for w in qq_windows(q.exe) if w.hwnd==binding['window']['hwnd'] and w.pid==binding['window']['pid']]
                if len(windows)!=1:raise StopAutomation('本人窗口绑定已失效')
                q.window=windows[0]
                dialogs=[w for w in qq_windows(q.exe) if w.kind=='#32770' and w.pid==q.window.pid]
                if len(dialogs)!=1:raise StopAutomation('没有唯一的已打开另存窗口，禁止重新发送')
                dialog=dialogs[0];guard(dialog,q.exe)
                destination=folder/('client-export'+native_filename(dialog))
                save_json(existing,{'destination':str(destination),'source_chain':'selected_personal_favorite -> confirmed_self_chat_message -> Save As'})
                check_cancel(cancel)
                dialog_action(dialog,q.window,q.exe,'SaveNew',destination,lambda:save_boundary(cancel,ledger),output_root=folder)
                deadline=time.monotonic()+10
                while time.monotonic()<deadline and not destination.exists():check_cancel(cancel);time.sleep(.25)
            check_cancel(cancel)
            metadata,_=inspect(destination);save_json(ledger,{'phase':'saved'})
            check_cancel(cancel);q.bind();own_chat(q);asset,_=prepare_asset(destination,'qq',ROOT/'private/T005/assets')
            verification=verify_source(q,scan,item,asset,folder,cancel);receipt=folder/'original-receipt.json'
            register_save_as(destination,'qq',folder/'selection.json',existing,verification,receipt);attach_receipt(asset,receipt)
            result.update(status='original_verified',asset=str(asset),file=str(destination),metadata=metadata,receipt=str(receipt),source_verification=str(verification))
            save_json(ledger,{'phase':'original_verified','asset':str(asset)})
    except Exception as exc:result['reason']=str(exc)
    save_json(report,result);return result


def acquire_or_resume(item,cancel=None):
    """One explicit UI request; never re-send an uncertain submitted message."""
    ident=hashlib.sha256(item['id'].encode()).hexdigest()[:20]
    folder=ROOT/'private/T005/qq-export'/ident;ledger=folder/'phase.json'
    if cancel and Path(cancel).exists():return {'status':'pending_confirmation','reason':'已请求取消','report':str(ROOT/'reports/T005'/('qq-export-'+ident+'.json'))}
    if ledger.exists():
        phase=read_json(ledger)['phase']
        if phase in ('before_send','before_save','saved'):return resume_saved_acquisition(item,cancel)
        if phase=='staged':return acquire_selected(item,cancel,resume_staged=True)
    return acquire_selected(item,cancel)


def recheck_acquired(asset):
    """Revisit this exact selected source position; do not re-export or send."""
    from emoji_bridge.originals import origin_for_asset
    a=load_asset(asset);receipt=read_json(origin_for_asset(a)['original_provenance'])
    selection=read_json(receipt['evidence'][0]['path']);scan=read_json(selection['scan'])
    item=next(x for x in scan['items'] if x['id']==selection['item_id'])
    folder=ROOT/'private/T005/rechecks'/datetime.now().strftime('%Y%m%d-%H%M%S-%f');folder.mkdir(parents=True)
    result={'status':'pending_confirmation','source_sha256':a['source_sha256']}
    try:
        with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
            handoff_to('qq');q=QQ(qq_profile(),{});q.bind()
            path=verify_source(q,scan,item,asset,folder);result=read_json(path);result['report_path']=str(path)
    except Exception as exc:result['reason']=str(exc)
    return result
