"""Last-resort QQ favorite navigation, never a message sender.

All rectangles are measured from fresh pixels at the current window DPI. The
native providers must both report no semantic controls before this is used.
"""
from pathlib import Path
import hashlib
import json
import time
import numpy as np
from PIL import Image

from .paths import APP_ROOT
from .windows import StopAutomation


class LayoutReader:
    def __init__(self):
        from .wechat_visual_bridge import load_cv2
        self.cv = load_cv2()
        self.templates = {}
        old = APP_ROOT/'assets/qq/9.9.20-dark-96'
        profile = json.loads((old/'profile.json').read_text('utf-8-sig'))
        new = APP_ROOT/'assets/qq/visual-anchors'
        manifest = json.loads((new/'manifest.json').read_text('utf-8'))
        for key in ('smile', 'heart', 'plus'):
            self.templates[key] = [self.load(old/(key+'.png'), profile['templates'][key])]
        for key, digest in manifest['sha256'].items():
            group=key.removesuffix('-phase')
            self.templates.setdefault(group,[]).insert(0,self.load(new/(key+'.png'), digest))

    def load(self, path, digest):
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise StopAutomation('calibration_template_changed')
        with Image.open(path) as image:
            return np.asarray(image.convert('L'), dtype=np.uint8)

    def hits(self, image, key, roi, threshold=.89):
        left, top, right, bottom = (int(v) for v in roi)
        if left < 0 or top < 0 or right > image.shape[1] or bottom > image.shape[0]:return []
        area = image[top:bottom, left:right]
        found = []
        for template in self.templates[key]:
            h,w = template.shape
            if area.shape[0]<h or area.shape[1]<w:continue
            # Contrast-normalized glyphs work in both light and dark palettes.
            scores = np.abs(self.cv.matchTemplate(area,template,self.cv.TM_CCOEFF_NORMED))
            for _ in range(12):
                _,value,_,(x,y) = self.cv.minMaxLoc(scores)
                if value<threshold:break
                if np.std(area[y:y+h,x:x+w])>8:
                    hit=(left+x+w/2,top+y+h/2,float(value))
                    if not any(abs(hit[0]-v[0])<5 and abs(hit[1]-v[1])<5 for v in found):found.append(hit)
                scores[max(0,y-h//2):y+h//2+1,max(0,x-w//2):x+w//2+1]=0
        return found

    def read(self, image, dpi):
        from .client_geometry import client_scale
        scale=client_scale(dpi)
        gray=np.asarray(image.resize((round(image.width/scale),round(image.height/scale)),Image.Resampling.LANCZOS).convert('L'))
        h,w=gray.shape
        candidates=[]
        for x,y,score in self.hits(gray,'smile',(0,int(h*.25),w,max(0,h-65)),.88):
            # Three separate toolbar glyphs on one row. A footer smile alone
            # or a smile appearing inside a message cannot authorize a click.
            scissors=self.hits(gray,'scissors',(round(x+18),round(y-16),round(x+47),round(y+16)),.88)
            folder=self.hits(gray,'folder',(round(x+58),round(y-16),round(x+88),round(y+16)),.88)
            if scissors and folder and abs(scissors[0][1]-y)<3 and abs(folder[0][1]-y)<3:
                candidates.append((x,y))
        if len(candidates)!=1:raise StopAutomation('qq_visual_chat_toolbar_not_unique')
        x,y=candidates[0]
        state=dict(ok=True,backend='visual',toolbar_ready=True,panel_open=False,
                   favorites_open=False,favorite_tab_ready=False,performed=False,
                   original_mapping_proven=False,enumeration_complete=False,
                   messages_or_favorite_mutations=0,import_ready=False,at_top=False,
                   cells=[],loaded_cells=0,fully_visible_cells=0)
        physical=lambda box:[round(v*scale) for v in box]
        state['toolbar_rect']=physical((x-13,y-13,x+13,y+13))
        # Footer anchors establish the actual panel, independently of window
        # size, sidebar width, and a remembered popup position.
        panels=[]
        for hx,hy,_ in self.hits(gray,'heart',(0,max(0,round(y-350)),w,round(y)),.88):
            gif=self.hits(gray,'gif-tab',(round(hx+43),round(hy-17),round(hx+69),round(hy+17)),.88)
            search=self.hits(gray,'search-tab',(round(hx-126),round(hy-18),round(hx-100),round(hy+18)),.88)
            # Independent chat has smile/heart/GIF; merged chat may prepend search.
            # Prove the third glyph and border for each layout, never infer
            # a window offset from the desktop/taskbar or from its version.
            smile=self.hits(gray,'smile',(round(hx-70),round(hy-18),round(hx-42),round(hy+18)),.88)
            offsets=([140.5] if search else [])+([84.5] if smile and not search else [])
            if not gif or not offsets:continue
            left,top=round(hx-offsets[0]),round(hy-312)
            if left<0 or top<0 or left+450>w or top+337>h:continue
            # Long observed border and footer separator, not a naked heart.
            def edge(a,b):return float(np.mean(np.abs(a.astype(float)-b.astype(float))))
            a=gray[top+10:top+327,left];b=gray[top+10:top+327,left-1] if left else a
            footer=max(edge(gray[top+n,left+12:left+438],gray[top+n+1,left+12:left+438]) for n in (285,286,287,288))
            if edge(a,b)<2 or footer<2:continue
            panels.append((left,top,hx,hy))
        if len(panels)>1:raise StopAutomation('qq_visual_favorite_panel_ambiguous')
        if not panels:return state
        left,top,hx,hy=panels[0]
        # QQ can shorten the popup slightly in a smaller chat window. Measure
        # its top border in physical pixels instead of inheriting a fixed
        # height from the footer anchor (which would shift every media crop).
        raw=np.asarray(image.convert('L'),dtype=float)
        pl,pt,pr,pb=physical((left,top,left+450,top+337))
        lo,hi=max(1,pt-round(8*scale)),min(raw.shape[0]-1,pt+round(8*scale))
        xl,xr=pl+round(12*scale),pr-round(12*scale)
        edges=[(float(np.median(np.abs(raw[n,xl:xr]-raw[n-1,xl:xr]))),n) for n in range(lo,hi+1)]
        strength,measured=max(edges)
        if strength<2:raise StopAutomation('favorite_panel_geometry_changed')
        pt=measured
        if not 325*scale<=pb-pt<=340*scale:raise StopAutomation('favorite_panel_geometry_changed')
        # Footer boundary remains anchored by three independently matched tabs.
        grid_bottom=round((hy-25)*scale)
        state.update(panel_open=True,favorite_tab_ready=True,
                     panel_rect=[pl,pt,pr,pb],
                     grid_rect=[pl+round(scale),pt+round(scale),pr-round(scale),grid_bottom],
                     favorite_tab_rect=physical((hx-18,hy-18,hx+18,hy+18)))
        # The selected tab has a complete rounded backing, distinct from the
        # adjacent footer. An unselected outline heart proves no membership.
        inside=float(np.median(gray[round(hy)-12:round(hy)+12,round(hx)-15:round(hx)-12]))
        outside=float(np.median(gray[round(hy)-12:round(hy)+12,round(hx)-25:round(hx)-22]))
        if abs(inside-outside)<10:return state
        state['favorites_open']=True
        actual_top=pt/scale
        plus=self.hits(gray,'plus',(left+16,round(actual_top+18),left+86,round(actual_top+88)),.86)
        if len(plus)==1 and abs(plus[0][0]-(left+50))<3 and abs(plus[0][1]-(actual_top+54))<3:
            px,py,_=plus[0]
            state.update(import_ready=True,at_top=True,import_rect=physical((px-29,py-29,px+29,py+29)))
        # Pixel observations are not native runtime IDs or a cloud total.
        state['visual_grid_proven']=True
        if state['at_top']:
            from .client_geometry import qq_grid_rect
            from .paging import visual_observed_cells
            crop=qq_grid_rect(state['panel_rect'])
            cells=visual_observed_cells(image.crop(crop),0,max_bottom=grid_bottom-crop[1])
            state['cells']=[dict(rect=[v+crop[i%2] for i,v in enumerate(c['rect'])],
                                 fully_visible=True,runtime_id=[],membership='visual_candidate') for c in cells]
            state['fully_visible_cells']=len(cells)
        state['loaded_cells']=None  # no offscreen/native count exists in this mode
        return state


class VisualControls:
    def __init__(self,window,exe,cancel=None):
        self.window,self.exe,self.cancel=window,Path(exe),cancel
        self.reader=LayoutReader()

    def check(self):
        from .windows import guard,user
        import ctypes
        if self.cancel and Path(self.cancel).exists():raise StopAutomation('cancel_requested')
        guard(self.window,self.exe)
        title=ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(self.window.hwnd,title,512)
        if title.value.strip() in ('图片查看器','视频播放器','QQ图片查看器','屏幕共享','资料卡'):
            raise StopAutomation('qq_visual_chat_toolbar_not_unique')

    def unobscured(self,rect):
        from .windows import user,w
        self.check()
        for y in range(rect[1]+3,rect[3]-2,max(1,round(24*self.window.dpi/96))):
            for x in range(rect[0]+3,rect[2]-2,max(1,round(24*self.window.dpi/96))):
                if user.GetAncestor(user.WindowFromPoint(w.POINT(x,y)),2)!=self.window.hwnd:
                    raise StopAutomation('target_occluded')

    def read(self,action='snapshot',foreground=True,runtime_id=None):
        from .windows import capture,click
        self.check()
        state=self.reader.read(capture(self.window),self.window.dpi)
        for key in ('toolbar_rect','panel_rect','grid_rect','favorite_tab_rect','import_rect'):
            if key in state:state[key]=[v+self.window.rect[i%2] for i,v in enumerate(state[key])]
        for cell in state['cells']:
            cell['rect']=[v+self.window.rect[i%2] for i,v in enumerate(cell['rect'])]
        self.unobscured(state['toolbar_rect'])
        if state['panel_open']:self.unobscured(state['panel_rect'])
        if action in ('describe','panel','snapshot'):return state
        key=None
        if action=='open-panel' and not state['panel_open']:key='toolbar_rect'
        elif action=='close-panel' and state['panel_open']:key='toolbar_rect'
        elif action=='select-favorites' and not state['favorites_open']:
            if not state['favorite_tab_ready']:raise StopAutomation('qq_uia_favorite_tab_not_ready')
            key='favorite_tab_rect'
        elif action not in ('open-panel','close-panel','select-favorites'):
            raise StopAutomation('qq_visual_native_cell_unavailable')
        if key:
            box=state[key]
            click(self.window,self.exe,round((box[0]+box[2])/2-self.window.rect[0]),round((box[1]+box[3])/2-self.window.rect[1]))
            time.sleep(.12)
            state=self.read();state['performed']=True
        return state
