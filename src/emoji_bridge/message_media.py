"""Read-only image location inside freshly identified File Transfer Assistant rows.

Connected foreground components propose actual rendered rectangles. Only full
original-frame pixels accept a proposal; rectangles or movement aren't identity.
"""
import time
from collections import OrderedDict
import numpy as np
from PIL import Image
from .vision import Match
from .recognition import FrameMatcher,find_media,distinguish_candidates
from .windows import StopAutomation
from .client_geometry import client_scale


class WeChatFrameMatcher(FrameMatcher):
    """WeChat paints transparent GIF previews on a light media surface.

    Original bytes/alpha remain intact. Try only the observed native surfaces,
    still checking every source pixel/frame at the normal error threshold.
    """
    def __init__(self,refs,native_path=None):
        super().__init__(refs)
        self.has_alpha=any(ref.convert('RGBA').getchannel('A').getextrema()[0]<255 for ref in refs)
        self.native_path=native_path;self.native_cache=OrderedDict();self.native_bytes=0
        self.batch_geometry_only=False
        self.native_size=refs[0].size
        if native_path:
            with Image.open(native_path) as image:self.native_size=image.size

    def __call__(self,crop,background=(34,34,34)):
        plain=super().__call__(crop,background)
        if plain[1]<.04:return plain
        backgrounds=[background]
        if self.has_alpha:
            backgrounds.append((240,240,240))
            light=super().__call__(crop,backgrounds[-1])
            if light[1]<plain[1]:plain=light
        # The native Qt preview uses a different reduction filter. Repeated
        # spatial searches cannot fix that mismatch. Compare intact source
        # frames reduced directly with bilinear filtering; retain the .04 gate.
        if self.native_path and .04<=plain[1]<.09:
            for bg in backgrounds:
                native=self.native_match(crop,bg)
                if native[1]<plain[1]:plain=native
        return plain

    def native_match(self,crop,background):
        from .recognition import rgb
        key=(crop.size,background);expected=self.native_cache.get(key)
        if expected is None:
            frames=[]
            with Image.open(self.native_path) as image:
                if getattr(image,'n_frames',1)!=len(self.refs):raise StopAutomation('asset_changed')
                for index in range(len(self.refs)):
                    image.seek(index)
                    scaled=rgb(image,background).resize(crop.size,Image.Resampling.BILINEAR)
                    frames.append(np.asarray(scaled,dtype=np.uint8)[1:-1,1:-1])
            expected=np.asarray(frames)
            while self.native_cache and self.native_bytes+expected.nbytes>32*1024*1024:
                _,old=self.native_cache.popitem(last=False);self.native_bytes-=old.nbytes
            if expected.nbytes<=32*1024*1024:
                self.native_cache[key]=expected;self.native_bytes+=expected.nbytes
        else:self.native_cache.move_to_end(key)
        actual=np.asarray(crop.convert('RGB'),dtype=np.int16)[1:-1,1:-1];errors=[]
        for start in range(0,len(expected),32):
            errors.extend(np.abs(expected[start:start+32].astype(np.int16)-actual).mean(axis=(1,2,3))/255)
        index=int(np.argmin(errors));return (index if errors[index]<.04 else None),float(errors[index])


def staged_matches(image,refs,matcher):
    # Components only propose bounds. Full original frames prove the staged
    # object; disconnected transparent content must not be accepted by itself.
    hits=match_rows(image,[(('composer',),(0,0,*image.size))],refs,matcher)
    found=[hit for _,hit in hits] if hits else find_media(image,refs,(120,118,122,100,80,72,60,48))
    found,proof=distinguish_candidates(image,refs,found,((34,34,34),(240,240,240)))
    if proof:matcher.last_spatial_check=proof
    return found


def component_rects(image,scale=1):
    a=np.asarray(image.convert('RGB'),dtype=np.int16)
    background=np.median(a[:, :max(1,min(8,image.width))],axis=(0,1))
    mask=np.max(np.abs(a-background),axis=2)>6
    # Row runs + union-find avoids an O(pixels) Python flood-fill on each frame.
    parent=[];boxes=[];previous=[]
    def root(n):
        while parent[n]!=n:
            parent[n]=parent[parent[n]];n=parent[n]
        return n
    for y,line in enumerate(mask):
        edges=np.flatnonzero(np.diff(np.r_[False,line,False].astype(np.int8)))
        current=[]
        for x,right in zip(edges[::2],edges[1::2]):
            overlaps={root(n) for left,end,n in previous if left<right and end>x}
            if overlaps:
                n=min(overlaps);b=boxes[n]
                for other in overlaps-{n}:
                    c=boxes[other];parent[other]=n
                    b[:]=[min(b[0],c[0]),min(b[1],c[1]),max(b[2],c[2]),max(b[3],c[3])]
                b[:]=[min(b[0],int(x)),min(b[1],y),max(b[2],int(right)),y+1]
            else:
                n=len(parent);parent.append(n);boxes.append([int(x),y,int(right),y+1])
            current.append((x,right,n))
        previous=current
    low,high=round(24*scale),round(240*scale)
    return [b for n,b in enumerate(boxes) if root(n)==n and low<=b[2]-b[0]<=high and low<=b[3]-b[1]<=high]


def row_regions(meta,window,size):
    def local(rect):return tuple(round(v-o) for v,o in zip(rect,window.rect[:2]*2))
    area=local(meta['list'])
    if not (0<=area[0]<area[2]<=size[0] and 0<=area[1]<area[3]<=size[1]):
        raise StopAutomation('message_list_outside_window')
    rows=[];identities=set()
    for row in meta['rows']:
        ident=tuple(row['identity']);r=local(row['rect'])
        if ident in identities:raise StopAutomation('message_row_identity_ambiguous')
        identities.add(ident)
        rect=(max(area[0],r[0]),max(area[1],r[1]),min(area[2],r[2]),min(area[3],r[3]))
        if rect[0]<rect[2] and rect[1]<rect[3]:rows.append((ident,rect))
    return area,rows


def prepare_rows(frame,rows,scale=1):
    """Geometry is shared only within one captured frame, never across scrolls."""
    return [(ident,rect,crop,component_rects(crop,scale)) for ident,rect in rows
            for crop in [frame.crop(rect)]]


def match_rows(frame,rows,refs,matcher,fallback=False,prepared_rows=None,scale=1):
    hits=[];ratio=refs[0].width/refs[0].height
    for ident,rect,crop,components in (prepared_rows if prepared_rows is not None else prepare_rows(frame,rows,scale)):
        found=[]
        for x,y,right,bottom in components:
            width,height=right-x,bottom-y
            if abs(width/height-ratio)>max(.025,2/height):continue
            index,error=matcher(crop.crop((x,y,right,bottom)))
            if index is not None and error<.04:found.append(Match(x,y,width,height,error))
        if not found and isinstance(matcher,WeChatFrameMatcher) and matcher.native_path:
            # Outgoing image rows in the supported WeChat layout have
            # a native avatar next to the media. Its current component + row
            # bounds propose the FULL transparent canvas, not just opaque ink.
            # This is only a proposal: every source pixel still has to match.
            # UIA rows and captures are physical pixels. Scale the native
            # layout proposals together; never change the full-pixel gate.
            px=lambda value:round(value*scale)
            avatars=[b for b in components if px(30)<=b[2]-b[0]<=px(42)
                     and abs((b[2]-b[0])-(b[3]-b[1]))<=px(2)
                     and b[0]>crop.width-px(90) and b[1]<=px(12)]
            native_ratio=matcher.native_size[0]/matcher.native_size[1]
            for avatar in avatars:
                for delta in (0,-1,1):
                    height=crop.height-px(20)+delta;width=round(height*native_ratio)
                    x=avatar[0]-px(14)-width;y=px(8)
                    if not (px(24)<=width<=px(240) and px(24)<=height<=px(240) and 0<=x<x+width<=crop.width and y+height<=crop.height):continue
                    index,error=matcher(crop.crop((x,y,x+width,y+height)))
                    if index is not None and error<.04:found.append(Match(x,y,width,height,error))
                if found:break
            if found:found=[min(found,key=lambda h:h.error)]
        if fallback and not found and getattr(matcher,'batch_geometry_only',False) is not True:
            found=find_media(crop,refs,tuple(e for e in (200,180,160,144,140,136,132,128,120,100,80,72) if e<=max(crop.size)))
        for h in found:
            absolute=Match(h.x+rect[0],h.y+rect[1],h.width,h.height,h.error)
            if not any(abs(absolute.center[0]-old[1].center[0])<8 and abs(absolute.center[1]-old[1].center[1])<8 for old in hits):
                hits.append((ident,absolute))
    if len(hits)>1:
        kept,proof=distinguish_candidates(frame,refs,[h for _,h in hits],((34,34,34),(240,240,240)))
        accepted={id(h) for h in kept};hits=[(i,h) for i,h in hits if id(h) in accepted]
        matcher.last_spatial_check=proof
    return hits


def locate(q,refs,cancelled,report,evidence,timeout=3,matcher=None,exclude_ids=()):
    started=time.monotonic();matcher=matcher or FrameMatcher(refs);attempts=[];fallback=False
    while True:
        cancelled();meta=q.uia('message-rows');frame=q.frame()
        area,rows=row_regions(meta,q.window,frame.size)
        rows=[(ident,rect) for ident,rect in rows if ident not in exclude_ids]
        # Disconnected transparent artwork often has no enclosing foreground
        # component. Try the bounded full-frame fallback immediately once,
        # rather than spending the entire loading timeout on impossible bounds.
        probe_fallback=fallback or (not attempts and bool(getattr(matcher,'has_alpha',False)))
        hits=match_rows(frame,rows,refs,matcher,probe_fallback,scale=client_scale(q.window.dpi))
        attempts.append({'rows':len(rows),'candidates':len(hits),'fallback':probe_fallback,
                         'elapsed':round(time.monotonic()-started,4)})
        report['message_location']={'method':'uia_rows_full_frames','attempts':attempts}
        if len(hits)==1:
            ident,hit=hits[0]
            fresh_meta=q.uia('message-rows');fresh=q.frame()
            _,fresh_rows=row_regions(fresh_meta,q.window,fresh.size)
            old_rect=next(r for i,r in rows if i==ident)
            current=[r for i,r in fresh_rows if i==ident]
            index,error=matcher(fresh.crop((hit.x,hit.y,hit.x+hit.width,hit.y+hit.height)))
            if current==[old_rect] and index is not None and error<.04:
                report['message_location'].update(seconds=round(time.monotonic()-started,4),row_identity=list(ident))
                fresh.crop((hit.x,hit.y,hit.x+hit.width,hit.y+hit.height)).save(evidence/'sent-media.png')
                return hit,ident,old_rect
            # Read-only relocation if loading shifted an existing row. Never send.
        elif len(hits)>1:
            report['message_location']['failure']='multiple_matching_messages';break
        if fallback:
            report['message_location']['failure']='no_stable_unique_match';break
        if time.monotonic()-started>=timeout:fallback=True
        else:time.sleep(.2)
    frame.crop(area).save(evidence/'unconfirmed-sent-media-area.png')
    raise StopAutomation('sent_media_not_unique_no_resend')
