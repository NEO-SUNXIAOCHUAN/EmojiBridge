"""Opt-in trial adapter. Native window/file-dialog/index code stays in charge.

No process-memory access, accessibility activation, network or input injection
is implemented here. All input goes through the existing guarded Win32 helpers.
"""
from pathlib import Path
from dataclasses import replace
import sys
import time
import numpy as np
from PIL import Image, ImageOps, ImageGrab

from .windows import StopAutomation, guard, capture, scroll, click, pid_of
from .wechat_visual import WindowsOCR, LabelRecognizer, analyze, ocr_lines, helper_icon, draft_mask, green, helper_labels, sidebar_boundary
from .wechat_visual import search_box, helper_function, popup_surface, menu_text_rows


def load_cv2():
    try:
        import cv2
        return cv2
    except ImportError:
        from .capabilities import dependencies
        path = str(dependencies('vision'))
        sys.path.insert(0, path)
        try:
            import cv2
            return cv2
        except ImportError as exc:
            raise StopAutomation('wechat_visual_runtime_missing') from exc
        finally:
            sys.path.remove(path)


def media_proof(image, layout, runners, scale):
    """Prove every expected intact image and reject all extra visible draft."""
    from .message_media import staged_matches
    crop = image.crop(layout.input)
    mask = draft_mask(image, layout.input, scale)
    hits = []
    for runner in runners:
        runner.cancelled()
        found = staged_matches(crop, runner.refs, runner.matcher, scale=scale)
        if len(found) != 1:
            raise StopAutomation('staged_batch_item_not_unique')
        hit = found[0]
        if any(abs(hit.center[0]-old.center[0]) < 8 and
               abs(hit.center[1]-old.center[1]) < 8 for old in hits):
            raise StopAutomation('staged_batch_items_overlap')
        hits.append(hit)
        pad = max(2, round(2*scale))
        mask[max(0, hit.y-pad):hit.y+hit.height+pad,
             max(0, hit.x-pad):hit.x+hit.width+pad] = False
    # Qt's caret follows the tallest object on the current line, even when
    # the LAST object is shorter. Require the last proven object's baseline
    # and right edge; never treat arbitrary green content as a caret.
    caret = green(np.asarray(crop)) & mask
    ys, xs = np.nonzero(caret)
    if len(xs) and xs.max()-xs.min() <= max(2, round(2*scale)):
        for hit in sorted(hits,key=lambda h:h.x+h.width,reverse=True)[:1]:
            row=[h for h in hits if abs(h.y+h.height-hit.y-hit.height)<=6*scale]
            top=min(h.y for h in row)
            if (hit.x+hit.width <= xs.min() <= hit.x+hit.width+6*scale and
                top-6*scale <= ys.min() and ys.max() <= hit.y+hit.height+6*scale):
                mask[caret] = False
                break
    if not hits or mask.any():
        raise StopAutomation('composer_not_expected_media_batch')
    return hits


class VisualBridge:
    def __init__(self, client):
        self.q = client
        self.cv2 = load_cv2()
        self.ocr = WindowsOCR(client.check_cancel)
        self.header_pixels = None
        self.header_result = None
        self.expected = []
        self.popup_cache = None
        self.label_recognizer = None
        self.placeholder_cache = None
        self.stats = {'backend': 'visual_trial', 'ocr_calls': 0,
                      'header_cache_hits': 0, 'ocr_seconds': 0.0}
        client.report['visual_compatibility'] = self.stats

    def read_ocr(self, image):
        self.q.check_cancel()
        key=(image.mode,image.size,image.tobytes()) if image.width*image.height<=65536 else None
        cache=getattr(self,'ocr_cache',None)
        if cache is None:self.ocr_cache=cache={}
        if key is not None and key in cache:
            self.stats['ocr_cache_hits']=self.stats.get('ocr_cache_hits',0)+1
            return cache[key]
        started = time.perf_counter()
        result = self.ocr.read(image)
        self.stats['ocr_calls'] += 1
        self.stats['ocr_seconds'] += round(time.perf_counter()-started, 4)
        self.q.check_cancel()
        if key is not None:
            if len(cache)>=16:cache.pop(next(iter(cache)))
            cache[key]=result
        return result

    def label_read(self, image):
        self.q.check_cancel()
        # Cache exact freshly captured pixels, never a position or old window.
        # Repeated menus/send labels across a batch are identical even though
        # their HWND and screen coordinates change. Bounded to small crops.
        key=(image.mode,image.size,image.tobytes()) if image.width*image.height<=32768 else None
        cache=getattr(self,'label_cache',None)
        if cache is None:self.label_cache=cache={}
        if key is not None and key in cache:
            self.stats['label_cache_hits']=self.stats.get('label_cache_hits',0)+1
            return cache[key]
        started=time.perf_counter()
        if self.label_recognizer is None:self.label_recognizer=LabelRecognizer()
        text,score=self.label_recognizer.read(image)
        self.q.check_cancel()
        self.stats['label_reads']=self.stats.get('label_reads',0)+1
        self.stats['label_seconds']=self.stats.get('label_seconds',0)+round(time.perf_counter()-started,4)
        if key is not None:
            if len(cache)>=64:cache.pop(next(iter(cache)))
            cache[key]=(text,score)
        return text, score

    def label_matches(self, image, expected):
        text, score = self.label_read(image)
        return text == expected and score >= .98

    def menu_label_matches(self, image):
        text, score = self.label_read(image)
        if text != '添加到表情' or score < .90:
            return False
        if score >= .98:
            return True
        # Small anti-aliased fonts: require independent padding to agree on
        # every character. No fuzzy text matching and no positional shortcut.
        fill=tuple(int(v) for v in np.median(np.asarray(image),axis=(0,1)))
        second=self.label_read(ImageOps.expand(image,border=max(2,round(image.height*.06)),fill=fill))
        if score>=.94 and second[0]==text and second[1]>=.94:return True
        readings=[second,self.label_read(ImageOps.expand(image,border=max(2,round(image.height*.24)),fill=fill))]
        return all(label==text and confidence>=.97 for label,confidence in readings) and max(c for _,c in readings)>=.98

    def layout_ocr(self, image):
        # Separate columns: full-screen OCR can join the sidebar's plus icon or
        # timestamp onto the helper title. Neither region contains chat history.
        scale = self.q.window.dpi/96
        divider = sidebar_boundary(image, scale)
        self.sidebar_divider = divider
        regions = [(divider+3, round(20*scale), min(image.width-round(50*scale), divider+round(280*scale)), round(85*scale))]
        sidebar = (round(45*scale), round(85*scale), divider-3, image.height-round(20*scale))
        mask = green(np.asarray(image.crop(sidebar))).astype('uint8')*255
        contours, _ = self.cv2.findContours(mask, self.cv2.RETR_EXTERNAL, self.cv2.CHAIN_APPROX_SIMPLE)
        selected = []
        for c in contours:
            x,y,w,h = self.cv2.boundingRect(c)
            if (w > divider*.45 and 20*scale < h < 140*scale and w/h > 2
                    and abs(sidebar[0]+x+w-divider) < 12*scale
                    and (mask[y:y+h,x:x+w]>0).mean() > .65):
                selected.append((sidebar[0]+x, sidebar[1]+y, w, h))
        if len(selected)>1:raise StopAutomation('wechat_visual_selected_helper_not_confirmed')
        if selected:
            x,y,w,h=selected[0]
            text_left=round(x+h*.85)
            regions.append((text_left,round(y+h*.08),min(x+w-round(5*scale),round(text_left+2*h)),round(y+h*.57)))
        else:regions.append(sidebar)
        lines = []
        for index, rect in enumerate(regions):
            if rect[0] >= rect[2] or rect[1] >= rect[3]:
                raise StopAutomation('wechat_visual_layout_unsupported')
            crop=image.crop(rect)
            factor=2
            if index==1 and selected:
                # A white selected title on green is easily dropped by OCR.
                # Keep only its bright glyphs; this never changes the client.
                crop=ImageOps.invert(ImageOps.autocontrast(Image.fromarray(np.asarray(crop).min(axis=2)))).convert('RGB')
            crop=ImageOps.expand(crop.resize((crop.width*factor,crop.height*factor)),border=12,fill='white')
            result = self.read_ocr(crop)
            for line in result['lines']:
                words = [{'text': word['text'], 'rect': [(v-12)/factor+offset for v, offset in
                          zip(word['rect'], rect[:2]*2)]} for word in line['words']]
                lines.append({'text': line['text'], 'words': words})
        if selected and not any(rect[2]<divider for rect in helper_labels({'ok':True,'lines':lines})):
            rect=regions[1]
            if self.label_matches(image.crop(rect),'文件传输助手'):
                lines.append({'text':'文件传输助手','words':[{'text':'文件传输助手','rect':list(rect)}]})
        if selected and not any(rect[2]<divider for rect in helper_labels({'ok':True,'lines':lines})):
            # One read of the visible sidebar may locate an unselected helper.
            result=self.read_ocr(image.crop(sidebar))
            for line in result['lines']:
                words=[{'text':word['text'],'rect':[v+offset for v,offset in zip(word['rect'],sidebar[:2]*2)]} for word in line['words']]
                lines.append({'text':line['text'],'words':words})
        if not any(rect[0]>divider for rect in helper_labels({'ok':True,'lines':lines})):
            rect=regions[0]
            if self.label_matches(image.crop(rect),'文件传输助手'):
                lines.append({'text':'文件传输助手','words':[{'text':'文件传输助手','rect':list(rect)}]})
        return {'ok': True, 'lines': lines}

    def absolute(self, rect, window=None):
        w = window or self.q.window
        return [v+o for v, o in zip(rect, w.rect[:2]*2)]

    def bind(self):
        """Require the exact helper header, selected label AND folder-arrow icon.

        An already selected helper is never clicked again. An incomplete title
        observation cannot authorize scrolling away from a visible helper.
        """
        q = self.q
        self.fit_collapsed_window()
        navigated = False
        searched = False
        for attempt in range(3):
            image = q.frame()
            result = self.layout_ocr(image)
            scale = q.window.dpi/96
            try:layout = analyze(image, result, q.window.dpi, self.cv2, False)
            except StopAutomation as exc:
                if str(exc) != 'wechat_visual_helper_not_confirmed':raise
                layout = None
            if layout is None:
                entries = [rect for rect in helper_labels(result)
                           if rect[2] < self.sidebar_divider and rect[1] > 85*scale]
                if len(entries) > 1:
                    raise StopAutomation('wechat_visual_selected_helper_not_confirmed')
                if entries:
                    if navigated:
                        raise StopAutomation('wechat_visual_helper_not_confirmed')
                    helper_icon(image, entries[0], scale, self.cv2)
                    a,b,c,d = entries[0]
                    region = (max(0, int(a-8*scale)), max(0, int(b-6*scale)),
                              int(c+8*scale), int(d+6*scale))
                    if green(np.asarray(image.crop(region))).mean() > .55:
                        # Do not toggle an already selected conversation when
                        # OCR missed its header. Re-observe without any input.
                        if attempt == 2:raise StopAutomation('wechat_visual_helper_not_confirmed')
                        time.sleep(.12)
                        continue
                    click(q.window, q.exe, round((a+c)/2), round((b+d)/2))
                    navigated = True
                    time.sleep(.25)
                    continue
            if layout is not None and layout.selected_helper:
                helper_icon(image, layout.selected_helper, q.window.dpi/96, self.cv2)
                self.remember_header(image, result, layout)
                self.stats['helper_witness'] = 'exact_header_selected_label_folder_arrow'
                return self.snapshot(image, layout)
            if attempt == 2:
                raise StopAutomation('wechat_visual_open_helper_first')
            if layout is None and not entries and not searched:
                self.search_helper(image)
                searched = True
            time.sleep(.12)
        raise StopAutomation('wechat_visual_open_helper_first')

    def fit_collapsed_window(self):
        """Only the fallback path expands an unusably narrow task boundary.

        Identity witnesses must remain visible. Never resize mid-submission or
        infer the helper from a chat title after the session sidebar disappears.
        """
        from . import windows as win
        q=self.q;old=q.window;scale=old.dpi/96
        width=old.rect[2]-old.rect[0];height=old.rect[3]-old.rect[1]
        area=win.monitor_work_area(old.hwnd)
        desired=win.visual_window_rect(old.rect,area,old.dpi)
        if desired==old.rect:return
        q.check_cancel();win.guard(old,q.exe)
        if any(win.user.GetAsyncKeyState(k)&0x8000 for k in (1,2,16,17,18,91,92)):
            raise StopAutomation('user_input_in_progress')
        w=desired[2]-desired[0];h=desired[3]-desired[1]
        if win.user.IsZoomed(old.hwnd):
            # Restore only at bind, before any input or submission.
            win.user.ShowWindowAsync(old.hwnd,9)
            time.sleep(.15);q.check_cancel()
        if not win.user.SetWindowPos(old.hwnd,0,desired[0],desired[1],w,h,0x14):
            raise StopAutomation('calibrated_window_resize_failed')
        time.sleep(.2);q.check_cancel()
        new=win.Window(old.hwnd,old.pid,old.kind,win.bounds(old.hwnd),int(win.user.GetDpiForWindow(old.hwnd)))
        win.guard(new,q.exe)
        if new.rect!=desired or new.dpi!=old.dpi:raise StopAutomation('calibrated_window_resize_failed')
        q.window=new
        self.stats['window_adjustment']={'before':old.rect,'after':new.rect,'reason':'keep_complete_visual_surface_visible'}

    def search_helper(self, image):
        """One empty visual search; select only the built-in helper function."""
        from .windows import qq_windows, user, INPUT, c
        q = self.q
        scale = q.window.dpi/96
        box = search_box(image, self.sidebar_divider, scale, self.cv2)
        left,top,right,bottom = box
        height = bottom-top
        text_rect = (left+height,top+4,right-height,bottom-4)

        def empty_search(frame):
            # A microphone may appear at the right when focused. Exclude that
            # icon, require the remaining field blank and the hint low contrast.
            tail = np.asarray(frame.crop((round(left+height*2.4),top+5,right-height,bottom-5)),dtype=float)
            if tail.size == 0 or (np.abs(tail-np.median(tail,axis=(0,1))).max(axis=2)>14).any():
                return False
            text_pixels=np.asarray(frame.crop(text_rect),dtype=float)
            if np.abs(text_pixels-np.median(text_pixels,axis=(0,1))).max()>145:
                return False
            return self.label_matches(frame.crop(text_rect),'搜索')

        if not empty_search(image):raise StopAutomation('own_transfer_search_not_empty')
        click(q.window,q.exe,(left+right)//2,(top+bottom)//2)
        time.sleep(.12)
        for attempt in range(3):
            focused = q.frame()
            if empty_search(focused):break
            if attempt == 2:raise StopAutomation('own_transfer_search_changed')
            q.check_cancel();time.sleep(.2)
        border = green(np.asarray(focused.crop((left-2,top-2,right+2,bottom+2))))
        if not (border[:5].mean()>.12 and border[-5:].mean()>.12):
            raise StopAutomation('own_transfer_search_layout_unsupported')
        # Send only Unicode characters, no Enter/shortcuts/clipboard replacement.
        # The focused green search field and its empty hint were just observed.
        q.check_cancel();guard(q.window,q.exe)
        if any(user.GetAsyncKeyState(key)&0x8000 for key in (1,2,16,17,18,91,92)):
            raise StopAutomation('user_input_in_progress')
        query='文件传输助手'
        events=(INPUT*(len(query)*2))()
        for index,char in enumerate(query):
            for offset,flags in ((0,4),(1,6)):
                event=events[index*2+offset];event.type=1;event.ki.wScan=ord(char);event.ki.dwFlags=flags
        if user.SendInput(len(events),events,c.sizeof(INPUT))!=len(events):
            raise StopAutomation('input_not_delivered')
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            q.check_cancel();time.sleep(.15)
            opened=[w for w in qq_windows(q.exe) if w.pid==q.window.pid and w.kind=='Qt51514QWindowToolSaveBits']
            if len(opened)>1:raise StopAutomation('wechat_popup_not_unique')
            guard(q.window,q.exe,foreground=False)
            if user.GetForegroundWindow() not in [q.window.hwnd]+[w.hwnd for w in opened]:
                raise StopAutomation('foreground_changed')
            if not opened:continue
            pop=opened[0];guard(pop,q.exe,owner=q.window)
            # Re-read the main query. User edits or a changed search stop here.
            frame=ImageGrab.grab(bbox=q.window.rect,all_screens=True).convert('RGB')
            query_rect=(text_rect[0],text_rect[1],right-round(height*.8),text_rect[3])
            if not self.label_matches(frame.crop(query_rect),query):
                # A blinking insertion caret can affect a short text read.
                # Re-observe only; never clear/retype or click an uncertain query.
                continue
            screen=ImageGrab.grab(bbox=pop.rect,all_screens=True).convert('RGB')
            region=screen.crop((0,0,screen.width,min(screen.height,round(160*scale))))
            # Native OCR drops the small grey “功能” heading on light themes.
            # Preserve geometry, normalize foreground contrast, and enlarge
            # before reading. Still require the exact function section, title
            # and folder-arrow icon; contact/history names remain excluded.
            pixels=np.asarray(region,dtype=np.int16)
            background=np.median(pixels,axis=(0,1))
            ink=np.abs(pixels-background).max(axis=2)>25
            normalized=Image.fromarray(np.where(ink,0,255).astype('uint8')).convert('RGB')
            result=self.read_ocr(normalized.resize((region.width*2,region.height*2)))
            result={'ok':result.get('ok'),'lines':[
                {'text':line['text'],'words':[dict(word,rect=[v/2 for v in word['rect']]) for word in line['words']]}
                for line in result.get('lines',[])]}
            if not helper_labels(result):
                # Thresholding can confuse a dense title glyph. Use the
                # original colour read for titles and keep the proven grey
                # section headings from the contrast read.
                raw=self.read_ocr(region)
                headings={'功能','联系人','群聊','聊天记录','收藏'}
                result={'ok':raw.get('ok'),'lines':[
                    line for line in result['lines'] if ''.join(line['text'].split()) in headings]+[
                    line for line in raw.get('lines',[]) if ''.join(line['text'].split()) not in headings]}
            try:target=helper_function(screen,result,scale,self.cv2)
            except StopAutomation as exc:
                if str(exc)!='own_transfer_search_result_unsupported':raise
                continue
            try:guard(pop,q.exe,owner=q.window)
            except StopAutomation as exc:
                if str(exc)=='window_moved_or_resized':continue
                raise
            a,b,d,e=target
            click(pop,q.exe,round((a+d)/2),round((b+e)/2),owner=q.window)
            self.stats['helper_navigation']='visual_empty_search_builtin_function'
            time.sleep(.2)
            return
        raise StopAutomation('own_transfer_search_result_not_found')

    def remember_header(self, image, result, layout):
        self.header_rect = (max(0, int(layout.header[0]-6)), max(0, int(layout.header[1]-5)),
                            int(layout.header[2]+6), int(layout.header[3]+5))
        self.header_pixels = image.crop(self.header_rect).tobytes()
        self.header_result = {'ok': True, 'lines': [{'text': '文件传输助手',
            'words': [{'text': '文件传输助手', 'rect': list(layout.header)}]}]}

    def observe(self):
        # A send can resize the composer while Qt is repainting its border.
        # Only re-observe; no cached coordinates, extra clicks or sends.
        for attempt in range(3):
            self.q.check_cancel()
            try:return self.observe_once()
            except StopAutomation as exc:
                if str(exc)!='wechat_visual_composer_unproven':raise
                self.stats['layout_rechecks']=self.stats.get('layout_rechecks',0)+1
                if attempt==2:raise
                time.sleep(.08)

    def observe_once(self):
        image = self.q.frame()
        if self.header_pixels is None:
            raise StopAutomation('wechat_visual_helper_not_confirmed')
        if image.crop(self.header_rect).tobytes() == self.header_pixels:
            result = self.header_result
            self.stats['header_cache_hits'] += 1
        else:
            result = self.layout_ocr(image)
            layout = analyze(image, result, self.q.window.dpi, self.cv2)
            helper_icon(image, layout.selected_helper, self.q.window.dpi/96, self.cv2)
            self.remember_header(image, result, layout)
        return image, analyze(image, result, self.q.window.dpi, self.cv2, False)

    def snapshot(self, image, layout):
        layout = self.with_placeholder(image, layout)
        only_media = False
        count = 0
        if not layout.input_empty and self.expected:
            hits = media_proof(image, layout, self.expected, self.q.window.dpi/96)
            only_media = True
            count = len(hits)
        return {'ok': True, 'backend': 'visual_trial', 'own_session': '文件传输助手',
                'header': self.absolute(layout.header), 'input': self.absolute(layout.input),
                'input_empty': layout.input_empty and not layout.send_enabled,
                'input_only_media_objects': only_media, 'media_object_count': count,
                'send_enabled': layout.send_enabled}

    def with_placeholder(self, image, layout):
        """Only the exact disabled, grey voice hint may stand in for blank input."""
        if layout.input_empty or layout.send_enabled:
            return layout
        scale = self.q.window.dpi/96
        crop = image.crop(layout.input).convert('RGB')
        mask = draft_mask(image, layout.input, scale)
        ys, xs = np.nonzero(mask)
        if not len(xs):
            return layout
        x, y, right, bottom = xs.min(), ys.min(), xs.max()+1, ys.max()+1
        if not (x <= 15*scale and y <= 15*scale and bottom-y <= 25*scale
                and 60*scale <= right-x <= 220*scale):
            return layout
        pixels = np.asarray(crop, dtype=float)
        ink = pixels[mask]
        contrast = np.abs(ink-np.median(pixels, axis=(0,1))).max(axis=1)
        if (ink.max(axis=1)-ink.min(axis=1)).max() > 20 or contrast.max() > 120:
            return layout
        key = (crop.size, crop.tobytes())
        cached = getattr(self, 'placeholder_cache', None)
        if cached and cached[0] == key:
            matched = cached[1]
        else:
            hint = crop.crop((max(0,x-3),max(0,y-3),min(crop.width,right+3),min(crop.height,bottom+3)))
            matched = self.label_matches(hint, '长按鼠标语音输入')
            self.placeholder_cache = (key, matched)
        return replace(layout, input_empty=True) if matched else layout

    def request(self, action, window=None):
        q = self.q
        if action in ('menu', 'import-status'):
            # A Qt popup may expose native controls even when its main doesn't.
            try:
                native = ({'ok': True, 'state': 'unknown'} if q.report.get('visual_forced_test')
                          else q.native_uia('menu-observe' if action == 'menu' else action, window))
                if (action == 'menu' and (native.get('available') is True or 'target' in native)) or (
                        action == 'import-status' and native.get('state') != 'unknown'):
                    self.stats['native_popup_reads'] = self.stats.get('native_popup_reads', 0)+1
                    return native
            except StopAutomation as exc:
                from .uia_worker import UIA_FAILURES
                if str(exc) not in UIA_FAILURES | {'wechat_control_missing',
                                    'wechat_context_menu_not_ready'}:
                    raise
            return self.popup_observation(action, window)
        image, layout = self.observe()
        if action in ('snapshot', 'open-file', 'send-batch'):
            result = self.snapshot(image, layout)
            if action == 'open-file':
                if not result['input_empty']:
                    raise StopAutomation('composer_not_empty')
                result['target'] = self.absolute(layout.file_button)
            elif action == 'send-batch':
                if not result['input_only_media_objects'] or not layout.send_enabled:
                    raise StopAutomation('composer_not_expected_media_batch')
                # Keep the original low-contrast glyphs. Thresholding >200
                # erased the light/transparent labels seen in the friend's clip.
                button = image.crop(layout.send_button)
                inset=max(2,round(min(button.size)*.12))
                button=button.crop((inset,inset,button.width-inset,button.height-inset))
                # Keep anti-aliased glyphs, but remove green hue that can lower
                # short-label confidence at smaller native button sizes.
                if not self.label_matches(button.convert('L').convert('RGB'),'发送'):
                    raise StopAutomation('wechat_visual_send_button_unproven')
                result['target'] = self.absolute(layout.send_button)
            return result
        if action in ('message-rows', 'latest-messages'):
            area = layout.messages
            if action == 'latest-messages':
                # Preserve the established small guarded wheel input bound.
                for _ in range(12):
                    q.check_cancel()
                    scroll(q.window, q.exe, area[2]-20, (area[1]+area[3])//2, -3)
                    time.sleep(.04)
            # Explicit viewport identity, never represented as a native message ID.
            absolute = self.absolute(area)
            return {'ok': True, 'backend': 'visual_viewport', 'list': absolute,
                    'rows': [{'identity': ['visual_viewport', *area], 'rect': absolute}],
                    'scroll': {'supported': True, 'method': 'guarded_wheel'}}
        raise StopAutomation('wechat_visual_action_unsupported')

    def popup_observation(self, action, window):
        q = self.q
        if window is None or window.pid != q.window.pid:
            raise StopAutomation('wechat_popup_not_unique')
        def still_present():
            try:guard(window, q.exe, owner=q.window)
            except StopAutomation as exc:
                # A result toast can close between enumeration and inspection.
                # This authorizes only another observation, never another add.
                if action!='import-status' or str(exc)!='process_identity_changed' or pid_of(window.hwnd)!=0:raise
                guard(q.window,q.exe)
                return False
            return True
        expired={'ok': True, 'state': 'unknown', 'read_only': True, 'expired': True}
        if not still_present():return expired
        # Qt menus can be owned non-activating windows while the main retains
        # foreground. The normal owner/process/DPI/geometry guard still applies.
        image = ImageGrab.grab(bbox=window.rect, all_screens=True).convert('RGB')
        if image.size != (window.rect[2]-window.rect[0], window.rect[3]-window.rect[1]):
            raise StopAutomation('capture_dimensions_mismatch')
        surface = popup_surface(image,self.cv2) if action=='menu' else (0,0,image.width,image.height)
        surface_image=image.crop(surface)
        cache_key = (action, window.hwnd, tuple(window.rect), surface, surface_image.tobytes())
        if self.popup_cache and self.popup_cache[0] == cache_key:
            if not still_present():return expired
            self.stats['popup_cache_hits'] = self.stats.get('popup_cache_hits', 0)+1
            return dict(self.popup_cache[1])
        if action == 'menu':
            # Full-menu OCR can read the real label as 添加至裱情. Recognize
            # each observed text row instead; never infer an action by position.
            labels = []
            for rect in menu_text_rows(surface_image):
                if self.menu_label_matches(surface_image.crop(rect).convert('L').convert('RGB')):
                    labels.append(('添加到表情', tuple(v+o for v,o in zip(rect,surface[:2]*2))))
        else:
            # Animated spinners change every capture while the status text
            # stays still. Recognize observed text bands, whose exact pixels
            # can be reused; unknown labels still use the full OCR fallback.
            labels=[]
            status_labels={'添加失败','表情添加失败','添加失败，请重试',
                           '表情添加失败，请稍后再试','正在添加','正在添加…','已添加','我知道了'}
            for rect in menu_text_rows(surface_image):
                text,confidence=self.label_read(surface_image.crop(rect))
                if confidence>=.98 and text in status_labels:
                    labels.append((text,tuple(v+offset for v,offset in zip(rect,surface[:2]*2))))
            if not any(text!='我知道了' for text,_ in labels):
                labels = [(text,tuple(v+offset for v,offset in zip(rect,surface[:2]*2)))
                          for text,rect in ocr_lines(self.read_ocr(surface_image))]
        if action == 'import-status' and pid_of(window.hwnd) == 0:
            # A short-lived toast may disappear during read-only OCR. Do not
            # reuse its coordinates or infer success; re-enumerate next loop.
            guard(q.window, q.exe)
            return {'ok': True, 'state': 'unknown', 'read_only': True, 'expired': True}
        if not still_present():return expired
        if action == 'menu':
            choices = [rect for text, rect in labels if text == '添加到表情']
            if not choices:
                return {'ok': True, 'available': False}
            if len(choices) != 1:
                raise StopAutomation('uia_button_not_unique')
            rect = choices[0]
            # Grey disabled menu labels have much less contrast than enabled text.
            a = np.asarray(image.convert('RGB').crop(rect), dtype=float)
            contrast = np.max(np.abs(a-np.median(a, axis=(0, 1))), axis=2)
            if np.count_nonzero(contrast >= 90) < max(20, a.shape[0]*a.shape[1]*.015):
                return {'ok': True, 'available': False}
            result = {'ok': True, 'available': True, 'backend': 'visual_trial',
                      'target': self.absolute(rect, window)}
            self.popup_cache=(cache_key,dict(result))
            return result
        texts = [text.rstrip('。.') for text, _ in labels]
        failed = any(text in ('添加失败', '表情添加失败', '添加失败，请重试',
                              '表情添加失败，请稍后再试') for text in texts)
        state = ('failed' if failed else 'adding' if any(text in ('正在添加', '正在添加…') for text in texts)
                 else 'acknowledged' if '已添加' in texts else 'unknown')
        result = {'ok': True, 'state': state, 'read_only': True, 'backend': 'visual_trial'}
        targets = [rect for text, rect in labels if text == '我知道了']
        if failed and len(targets) == 1:
            result['ack_target'] = self.absolute(targets[0], window)
        self.popup_cache = (cache_key, dict(result))
        return result
