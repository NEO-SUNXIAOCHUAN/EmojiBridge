"""Experimental screenshot-only WeChat layout observations.

This module grants no permission to send. It does not access client memory,
activate accessibility, or use UIA. Unknown layouts and ambiguous anchors stop.
"""
from dataclasses import dataclass
import json
import math
import re
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .windows import StopAutomation


def normalized(text):
    return ''.join(str(text).split())


def ocr_lines(result):
    if result.get('ok') is not True:
        raise StopAutomation(result.get('reason', 'wechat_visual_ocr_failed'))
    lines = []
    for line in result.get('lines', []):
        words = line.get('words', [])
        bounds = [w.get('rect') for w in words]
        if not bounds or any(not isinstance(b, list) or len(b) != 4 for b in bounds):
            raise StopAutomation('wechat_visual_ocr_geometry_invalid')
        if any(not all(isinstance(v, (int, float)) and math.isfinite(v) for v in b)
               or b[0] >= b[2] or b[1] >= b[3] for b in bounds):
            raise StopAutomation('wechat_visual_ocr_geometry_invalid')
        lines.append((normalized(line.get('text', '')),
                      (min(b[0] for b in bounds), min(b[1] for b in bounds),
                       max(b[2] for b in bounds), max(b[3] for b in bounds))))
    return lines


def green(a):
    a = np.asarray(a, dtype=np.int16)
    return (a[..., 1] > a[..., 0] + 35) & (a[..., 1] > a[..., 2] + 20) & (a[..., 1] > 100)


def helper_labels(result):
    """Exact consecutive OCR words; a date/icon in the same line is not a title."""
    ocr_lines(result)  # Validate every coordinate before deriving a sub-line.
    found = []
    for line in result.get('lines', []):
        words = line['words']
        for start in range(len(words)):
            text = ''
            for end in range(start, len(words)):
                text += normalized(words[end].get('text', ''))
                if not '文件传输助手'.startswith(text):break
                if text == '文件传输助手':
                    prefix = ''.join(normalized(word.get('text','')) for word in words[:start])
                    suffix = ''.join(normalized(word.get('text','')) for word in words[end+1:])
                    if re.search(r'[\u4e00-\u9fffA-Za-z]',prefix+suffix):break
                    boxes = [word['rect'] for word in words[start:end+1]]
                    rect = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                            max(b[2] for b in boxes), max(b[3] for b in boxes))
                    found.append(rect)
                    break
    return found


def popup_surface(image, cv2):
    """Exclude the transparent menu shadow and messages visible behind it."""
    a=np.asarray(image.convert('RGB'))
    colors,counts=np.unique(a.reshape(-1,3),axis=0,return_counts=True)
    bg=colors[counts.argmax()].astype(float)
    mask=(np.abs(a.astype(float)-bg).max(axis=2)<=3).astype('uint8')
    count,_,stats,_=cv2.connectedComponentsWithStats(mask,8)
    candidates=[]
    for x,y,w,h,area in stats[1:]:
        if w>image.width*.5 and h>image.height*.5 and area>w*h*.7:
            candidates.append((int(x),int(y),int(x+w),int(y+h)))
    if len(candidates)!=1:raise StopAutomation('wechat_context_menu_not_ready')
    return candidates[0]


def sidebar_boundary(image, scale):
    """Observe the long pane divider, independent of the client's UI zoom."""
    a = np.asarray(image.convert('RGB'), dtype=float)
    height, width = a.shape[:2]
    top, bottom = max(1, round(height*.14)), height-max(8, round(20*scale))
    difference = np.mean(np.abs(a[top:bottom, 3:]-a[top:bottom, :-3]), axis=2)
    score = (difference > 4).mean(axis=0)
    start, end = max(30, round(100*scale)), min(width-80, round(width*.65))
    candidates = [x for x in range(start, end) if score[x] > .80]
    groups = []
    for x in candidates:
        if not groups or x-groups[-1][-1] > 5:groups.append([x])
        else:groups[-1].append(x)
    if len(groups) != 1:
        raise StopAutomation('wechat_visual_layout_unsupported')
    return round(float(np.median(groups[0])))+2


def inside(a, b):
    return b[0] <= a[0] < a[2] <= b[2] and b[1] <= a[1] < a[3] <= b[3]


def search_box(image, divider, scale, cv2):
    """Observe the rounded search field above the session list, not the composer."""
    gray = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
    contours, _ = cv2.findContours(cv2.Canny(gray, 8, 24), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x,y,w,h = cv2.boundingRect(contour)
        if (45*scale < x < 110*scale and 20*scale < y < 80*scale
                and 70*scale < w < divider-x and 18*scale < h < 45*scale
                and x+w < divider-15*scale):
            rect = (x,y,x+w,y+h)
            if not any(max(abs(a-b) for a,b in zip(rect,old)) < 4*scale for old in boxes):
                boxes.append(rect)
    if len(boxes) != 1:
        raise StopAutomation('own_transfer_search_layout_unsupported')
    return boxes[0]


def helper_function(image, result, scale, cv2):
    """Only the built-in function section, excluding contacts/history matches."""
    lines = ocr_lines(result)
    headings = [rect for text,rect in lines if text == '功能' and rect[1] < 80*scale]
    if len(headings) != 1:
        raise StopAutomation('own_transfer_search_result_unsupported')
    heading = headings[0]
    boundaries = [rect[1] for text,rect in lines if text in ('联系人','群聊','聊天记录','收藏') and rect[1] > heading[3]]
    bottom = min(boundaries) if boundaries else heading[3]+90*scale
    matches = [rect for rect in helper_labels(result) if heading[3] < rect[1] < rect[3] < bottom
               and rect[0] > heading[0]+20*scale]
    if len(matches) != 1:
        raise StopAutomation('own_transfer_search_result_unsupported')
    helper_icon(image, matches[0], scale, cv2)
    return matches[0]


def helper_icon(image, label, scale, cv2):
    """Additional visual witness: white folder with a green right arrow."""
    x, y, _, bottom = label
    region = (max(0, int(x-55*scale)), max(0, int(y-8*scale)),
              int(x-8*scale), min(image.height, int(bottom+28*scale)))
    a = np.asarray(image.convert('RGB').crop(region))
    white = (a.min(axis=2) > 210).astype('uint8')*255
    # A light list/search background surrounds the green avatar. The white
    # folder is then a nested contour; EXTERNAL discards it entirely.
    contours, _ = cv2.findContours(white, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    template = Image.new('L', (32, 26))
    d = ImageDraw.Draw(template)
    d.polygon([(0, 0), (10, 0), (13, 3), (31, 3), (31, 25), (0, 25)], fill=255)
    d.polygon([(9, 12), (18, 12), (18, 9), (24, 14), (18, 19),
               (18, 16), (9, 16)], fill=0)
    target = np.asarray(template) > 128
    found = []
    for c in contours:
        left, top, w, h = cv2.boundingRect(c)
        if not (12*scale <= w <= 30*scale and 10*scale <= h <= 26*scale):
            continue
        shape = np.asarray(Image.fromarray(white[top:top+h, left:left+w]).resize((32, 26))) > 128
        # Shape alone is insufficient: the hole must be the surrounding green.
        colors = np.asarray(Image.fromarray(a[top:top+h, left:left+w]).resize((32, 26)))
        if (shape != target).mean() < .15 and green(colors)[~target].mean() > .6:
            found.append((region[0]+left, region[1]+top, region[0]+left+w, region[1]+top+h))
    if len(found) != 1:
        raise StopAutomation('wechat_visual_helper_icon_unproven')
    return found[0]


def folder_template():
    # Generic line geometry, drawn here; no client artwork is distributed.
    im = Image.new('L', (32, 32))
    d = ImageDraw.Draw(im)
    d.line([(3, 8), (11, 8), (15, 11), (28, 11), (28, 27),
            (3, 27), (3, 8)], fill=255, width=2)
    d.line([(3, 15), (28, 15)], fill=255, width=2)
    return np.asarray(im.crop((2, 7, 30, 29)).resize((32, 32))) > 96


def folder_candidates(image, toolbar, scale, cv2):
    x, y, right, bottom = toolbar
    a = np.asarray(image.convert('RGB'))[y:bottom, x:right]
    background = np.median(a, axis=(0, 1))
    mask = (np.max(np.abs(a.astype(float) - background), axis=2) > 35).astype('uint8') * 255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    template = folder_template()
    found = []
    for c in contours:
        cx, cy, w, h = cv2.boundingRect(c)
        if not (11*scale <= w <= 23*scale and 9*scale <= h <= 21*scale and 1 <= w/h <= 1.65):
            continue
        actual = np.asarray(Image.fromarray(mask[cy:cy+h, cx:cx+w]).resize((32, 32))) > 96
        # Symmetric distance tolerates antialiasing, not missing/rearranged strokes.
        distance_a = cv2.distanceTransform((~actual).astype('uint8'), cv2.DIST_L2, 3)
        distance_t = cv2.distanceTransform((~template).astype('uint8'), cv2.DIST_L2, 3)
        error = (float(distance_a[template].mean()) + float(distance_t[actual].mean())) / 2
        if error < 1.15:
            found.append((x+cx, y+cy, x+cx+w, y+cy+h))
    return found


def composer_borders(edges, header, scale):
    """Recover four observed edges when a message touches the outer contour.

    Never invent a composer from window ratios. Both vertical sides and the
    bottom must be continuous; a bounded interruption of the top is permitted.
    Independent candidates stay ambiguous, even if one would be convenient.
    """
    height,width=edges.shape
    def groups(indices):
        parts=np.split(indices,np.flatnonzero(np.diff(indices)>max(2,round(3*scale)))+1)
        return [int(round(float(np.median(p)))) for p in parts if len(p)]
    def horizontal(y,left,right):
        region=edges[max(0,y-2):min(height,y+3),left:right]
        return float((region>0).any(axis=0).mean()) if region.size else 0.
    left_min=max(0,round(header[0]-24*scale));left_max=round(header[0]+24*scale)
    right_min=max(left_max,round(width-45*scale));right_max=width-round(3*scale)
    inner_left=left_max+round(12*scale);inner_right=right_min-round(12*scale)
    if inner_right<=inner_left:return []
    ys=np.flatnonzero((edges[:,inner_left:inner_right]>0).mean(axis=1)>.65)
    levels=groups(ys)
    bottoms=[y for y in levels if height-45*scale<y<height-3*scale]
    found=[]
    for bottom in bottoms:
        for top in levels:
            if not header[3]+70*scale<top<bottom-80*scale:continue
            a=top+round(12*scale);b=bottom-round(12*scale)
            support=(edges[a:b]>0).mean(axis=0)
            lefts=groups(np.flatnonzero(support[left_min:left_max]>.80)+left_min)
            rights=groups(np.flatnonzero(support[right_min:right_max]>.80)+right_min)
            for left in lefts:
                for right in rights:
                    if right-left<=width*.40:continue
                    inset=round(12*scale)
                    if (horizontal(top,left+inset,right-inset)<.70 or
                            horizontal(bottom,left+inset,right-inset)<.95):continue
                    rect=(left,top,right+1,bottom+1)
                    if not any(max(abs(v-u) for v,u in zip(rect,old))<5*scale for old in found):
                        found.append(rect)
    return found


@dataclass(frozen=True)
class Layout:
    header: tuple
    selected_helper: tuple
    input: tuple
    composer: tuple
    toolbar: tuple
    messages: tuple
    file_button: tuple
    send_button: tuple
    input_empty: bool
    send_enabled: bool

    def diagnostic(self):
        # Pixels and matching labels are observations, not native conversation
        # identity or permission to send. Blank pixels cannot exclude whitespace.
        return {'helper_title_visible': True, 'selected_label_visible': True,
                'visible_input_blank': self.input_empty, 'send_looks_enabled': self.send_enabled,
                'actions_authorized': False,
                'geometry': {key: list(getattr(self, key)) for key in
                             ('header', 'input', 'composer', 'messages', 'file_button', 'send_button')}}


def draft_mask(image, rect, scale):
    """Non-background pixels, allowing only a narrow green insertion caret."""
    a = np.asarray(image.convert('RGB').crop(rect))
    if a.size == 0:
        raise StopAutomation('wechat_visual_composer_unproven')
    # In a narrow composer, staged thumbnails can cover most of its surface.
    # Use the actual empty perimeter, not the images, to estimate background.
    edge = np.concatenate((a[:2].reshape(-1,3), a[-2:].reshape(-1,3),
                           a[:, :2].reshape(-1,3), a[:, -2:].reshape(-1,3)))
    bg = np.median(edge, axis=0)
    if (np.max(np.abs(edge.astype(float)-bg),axis=1)>14).mean() > .20:
        raise StopAutomation('wechat_visual_composer_unproven')
    # A background gradient or textured draft cannot be declared empty.
    mask = np.max(np.abs(a.astype(float)-bg), axis=2) > 14
    caret = green(a)
    ys, xs = np.nonzero(caret)
    if len(xs) and xs.max()-xs.min() <= max(2, round(2*scale)) and ys.max()-ys.min() <= 25*scale:
        if xs.max() <= 15*scale and ys.min() <= 15*scale:
            mask[caret] = False
            # Remove only the antialiased green fringe adjacent to a proven,
            # narrow insertion caret. Ordinary draft text remains evidence.
            aa = a.astype(np.int16)
            fringe = (aa[...,1] > aa[...,0]+8) & (aa[...,1] > aa[...,2]+5) & (aa[...,1] > 100)
            vicinity = np.zeros(mask.shape, dtype=bool)
            vicinity[max(0,ys.min()-1):ys.max()+2,max(0,xs.min()-1):xs.max()+2] = True
            mask[fringe & vicinity] = False
    return mask


def analyze(image, result, dpi, cv2, require_selected=True):
    if dpi not in (96, 120, 144):
        raise StopAutomation('client_display_scale_unsupported')
    scale = dpi / 96
    width, height = image.size
    lines = ocr_lines(result)
    if any(not inside(b, (0, 0, width, height)) for _, b in lines):
        raise StopAutomation('wechat_visual_ocr_geometry_invalid')
    helpers = helper_labels(result)
    headers = [b for b in helpers if b[1] < 85*scale and b[0] > 200*scale]
    if len(headers) != 1:
        raise StopAutomation('wechat_visual_helper_not_confirmed')
    header = headers[0]
    # Require a second witness in the selected session, outside chat messages.
    selected = []
    for b in helpers:
        if b == header or b[2] >= header[0]-12*scale or b[1] < 75*scale:
            continue
        region = (max(0, int(b[0]-8*scale)), max(0, int(b[1]-6*scale)),
                  min(width, int(b[2]+8*scale)), min(height, int(b[3]+6*scale)))
        if green(np.asarray(image.crop(region))).mean() > .55:
            selected.append(b)
    if len(selected) > 1 or (require_selected and len(selected) != 1):
        raise StopAutomation('wechat_visual_selected_helper_not_confirmed')
    # Locate the actual rounded composer border. No window-size ratio clicks.
    gray = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 10, 30)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # Media drafts expand upward. Anchor to the verified chat header and
        # window edges, not to a percentage of the former empty input layout.
        if (abs(x-header[0]) < 24*scale and y > header[3]+70*scale and
                80*scale <= h < height-header[3]-70*scale and w > width*.40 and
                width-45*scale < x+w < width and height-45*scale < y+h < height):
            # IME labels just above the composer can join an outer contour in
            # light mode. Require the actual continuous top border, not merely
            # a bounding box around those labels and the composer below them.
            top_edge=edges[max(0,y-2):y+4,x+round(w*.15):x+round(w*.85)]
            if not (top_edge>0).any(axis=0).mean()>.75:
                continue
            rect = (x, y, x+w, y+h)
            if not any(max(abs(v-u) for v, u in zip(rect, old)) < 5*scale for old in boxes):
                boxes.append(rect)
    if not boxes:
        boxes = composer_borders(edges, header, scale)
    if len(boxes) != 1:
        raise StopAutomation('wechat_visual_composer_unproven')
    composer = boxes[0]
    left, top, right, bottom = composer
    toolbar = (left+round(8*scale), bottom-round(37*scale),
               min(right-round(100*scale), left+round(260*scale)), bottom-round(5*scale))
    files = folder_candidates(image, toolbar, scale, cv2)
    if len(files) != 1:
        raise StopAutomation('wechat_visual_file_button_unproven')
    # Interior excludes the toolbar and rounded border, but includes all draft text.
    content = (left+round(5*scale), top+round(5*scale),
               right-round(5*scale), toolbar[1]-round(4*scale))
    send = (right-round(61*scale), bottom-round(36*scale),
            right-round(9*scale), bottom-round(7*scale))
    # Client font/zoom may differ from system DPI. Observe the actual green
    # button within the composer's output corner instead of using a fixed box.
    search = (max(left, right-round(120*scale)), bottom-round(50*scale),
              right-round(3*scale), bottom-round(3*scale))
    mask = green(np.asarray(image.crop(search))).astype('uint8')*255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    buttons = []
    for c in contours:
        x,y,w,h = cv2.boundingRect(c)
        if (20*scale < w < 110*scale and 12*scale < h < 48*scale and 1.4 < w/h < 4.5
                and (mask[y:y+h,x:x+w]>0).mean() > .60):
            buttons.append((search[0]+x,search[1]+y,search[0]+x+w,search[1]+y+h))
    if len(buttons)>1:raise StopAutomation('wechat_visual_send_button_unproven')
    send_enabled = len(buttons)==1
    if send_enabled:send=buttons[0]
    empty = not draft_mask(image, content, scale).any()
    if empty and send_enabled:
        raise StopAutomation('wechat_visual_empty_draft_conflict')
    # The composer border is the actual message viewport boundary. Reserving
    # an assumed IME strip clipped the newest image and prevented its complete
    # pixel proof (and consequently every context-menu action).
    messages = (left, math.ceil(header[3]+16*scale), right, top-max(1,round(2*scale)))
    if not inside(messages, (0, 0, width, height)) or messages[3] <= messages[1]:
        raise StopAutomation('wechat_visual_message_area_unproven')
    return Layout(header, selected[0] if selected else (), content, composer, toolbar, messages, files[0], send, empty, send_enabled)


class LabelRecognizer:
    """Reuse only the bundled text recognizer for short, low-contrast labels.

    No detector, download, screen scan or client access. One CPU session is
    retained by the transfer's visual adapter; strict text/score checks remain.
    """
    def __init__(self):
        import sys, hashlib
        from .capabilities import dependencies
        from .editing import chinese_font_path
        root=dependencies('vision')
        model=root/'rapidocr/models/ch_PP-OCRv4_rec_infer.onnx'
        if not model.is_file() or hashlib.sha256(model.read_bytes()).hexdigest() != '48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b':
            raise StopAutomation('wechat_visual_runtime_missing')
        path=str(root);sys.path.insert(0,path)
        try:
            from rapidocr.utils.parse_parameters import ParseParams
            from rapidocr.ch_ppocr_rec import TextRecognizer, TextRecInput
            cfg=ParseParams.load(root/'rapidocr/config.yaml')
            cfg.Rec.engine_cfg=cfg.EngineConfig.onnxruntime
            cfg.Rec.engine_cfg.intra_op_num_threads=2
            cfg.Rec.engine_cfg.inter_op_num_threads=1
            cfg.Rec.model_path=str(model)
            cfg.Rec.font_path=chinese_font_path()
            self.engine=TextRecognizer(cfg.Rec);self.Input=TextRecInput
        finally:sys.path.remove(path)

    def read(self, image):
        if image.width>1000 or image.height>250:
            raise StopAutomation('wechat_visual_layout_unsupported')
        result=self.engine(self.Input(img=np.asarray(image.convert('RGB'))[:,:,::-1].copy()))
        if not result.txts or len(result.txts)!=1:return '',0.0
        return normalized(result.txts[0]),float(result.scores[0])


class WindowsOCR:
    """Bounded subprocess; temporary screenshot belongs to this call only."""
    def __init__(self, cancel_check=lambda: None):
        self.cancel_check = cancel_check

    def read(self, image):
        from .client_sources import powershell_executable
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix='eb-visual-') as temporary:
            path = Path(temporary)/'frame.png'
            image.save(path)
            # Files avoid stdout pipe backpressure on a densely populated image.
            with (Path(temporary)/'result.json').open('wb') as output:
                process = subprocess.Popen([str(powershell_executable()), '-NoProfile', '-NonInteractive',
                    '-ExecutionPolicy', 'Bypass', '-File', str(root/'scripts/wechat_visual_ocr.ps1'),
                    '-ImagePath', str(path)], stdout=output, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    deadline = time.monotonic()+15
                    while process.poll() is None:
                        self.cancel_check()
                        if time.monotonic() >= deadline:
                            raise StopAutomation('wechat_visual_ocr_timeout')
                        time.sleep(.04)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
            self.cancel_check()
            try:
                value = json.loads((Path(temporary)/'result.json').read_text('utf-8-sig'))
            except (OSError, ValueError):
                raise StopAutomation('wechat_visual_ocr_failed')
            if not isinstance(value, dict) or not value.get('ok') or process.returncode:
                reason = value.get('reason') if isinstance(value, dict) else None
                raise StopAutomation(reason if reason == 'wechat_visual_chinese_ocr_unavailable'
                                     else 'wechat_visual_ocr_failed')
            return value
def menu_text_rows(image):
    """Locate text bands on the observed menu, independent of row index/theme/DPI.

    Per-scanline background also handles a hovered row. Separators and borders
    are not text. Recognition must still prove the complete exact action label.
    """
    import numpy as np
    a = np.asarray(image.convert('RGB'), dtype=float)
    h, w = a.shape[:2]
    inset = max(3, round(w * .05))
    if w < 60 or h < 20:
        return []
    body = a[:, inset:w-inset]
    background=np.median(body,axis=1)[:,None,:]
    # Keep glyph polarity relative to the menu theme: a hovered green row's
    # dark rounded border is not a text stroke and must not join adjacent rows.
    direction=-1 if float(np.median(a))>128 else 1
    polarity=(body.mean(axis=2)-background.mean(axis=2))*direction>20
    contrast = np.max(np.abs(body-background),axis=2)*polarity
    counts = (contrast > 28).sum(axis=1)
    ink = (counts >= 3) & (counts < body.shape[1] * .8)
    bands = []
    start = None
    for y in range(h + 1):
        if y < h and ink[y]:
            if start is None:
                start = y
        elif start is not None and (y == h or not ink[y:min(h, y+2)].any()):
            if 5 <= y-start <= h*.22:
                top, bottom = start, y
                # Tight ink bounds with proportional padding give the short
                # recognizer a stable aspect ratio. Disabled grey labels fail
                # the contrast gate before recognition.
                yy, xx = np.nonzero(contrast[top:bottom] >= 90)
                if len(xx) >= 20:
                    p = max(3, round((int(yy.max()-yy.min())+1)*.25))
                    bands.append((max(inset,inset+int(xx.min())-p),
                                  max(0,top+int(yy.min())-p),
                                  min(w-inset,inset+int(xx.max())+1+p),
                                  min(h,top+int(yy.max())+1+p)))
            start = None
    return bands
