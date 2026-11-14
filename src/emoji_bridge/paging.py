"""Conservative QQ viewport alignment. Observations are not original files."""
import numpy as np
from PIL import Image

# QQ 9.9.20 / calibrated 100% grid crops include part of the fixed footer.
# At y=279 the footer overlays the last six pixels of the fourth 58px tile.
# Those pixels aren't media. Only fully visible cells are new observations.
QQ_CONTENT_BOTTOM=279


def content_bottom(image):
    # Full viewports are 434 logical pixels wide. Legacy isolated saved cells
    # have no footer; the image boundary still excludes all out-of-image pixels.
    scale=max(1,image.width/434)
    return min(image.height,round(QQ_CONTENT_BOTTOM*scale))


def full_cell(image,rect):
    left,top,right,bottom=rect
    return 0<=left<right<=image.width and 0<=top<bottom<=content_bottom(image)


def difference(first,second):
    if first.size!=second.size:return 1.0
    return float(np.abs(np.asarray(first.convert('RGB'),dtype=float)-np.asarray(second.convert('RGB'),dtype=float)).mean()/255)


def align_scroll(before,after,allow_still=False):
    """Find a positive pixel shift using several independent unchanged patches.

    Animated patches may disagree. At least three spatially separated detailed
    patches must agree; blank backgrounds cannot establish a scroll offset.
    """
    if before.size!=after.size:raise ValueError('scroll_view_size_changed')
    # Convert once, rather than twice for every candidate patch. Short final
    # movements are real movements too. Zero is opt-in and means NO PROGRESS,
    # never proof that the entire collection has been read.
    first=np.asarray(before.convert('RGB'),dtype=np.float32)
    second=np.asarray(after.convert('RGB'),dtype=np.float32)
    scale=before.width/434
    px=lambda v:round(v*scale)
    bottom=min(px(QQ_CONTENT_BOTTOM),before.height)
    candidates=[];detailed={}
    for shift in range(0 if allow_still else 1,px(220)+1):
        errors=[]
        for x in [px(v) for v in (13,83,153,223,293,363)]:
            # QQ clips the leading/trailing strip; only compare interior
            # content. The measured wheel step is 200 px, leaving one full row.
            for y in range(shift+px(20),bottom-px(40)+1,max(1,px(16))):
                a=first[y:y+px(40),x:x+px(48)];b=second[y-shift:y-shift+px(40),x:x+px(48)]
                key=(x,y)
                if key not in detailed:detailed[key]=a.std()>=22
                if not detailed[key]:continue
                error=float(np.abs(a-b).mean()/255)
                if error<.025:errors.append((x,y,error))
        if len({x for x,y,e in errors})>=3:
            candidates.append((sum(e for x,y,e in errors)/len(errors),shift,len(errors)))
    if not candidates:raise ValueError('scroll_alignment_unproven')
    candidates.sort();best=candidates[0]
    if any(abs(s-best[1])>max(2,px(2)) and e<=best[0]+.003 for e,s,n in candidates[1:]):
        raise ValueError('scroll_alignment_ambiguous')
    return {'pixels':best[1],'matched_patches':best[2],'mean_error':best[0]}


def observed_cells(image,offset):
    """Only full calibrated cells with visible content; no empty-slot counting."""
    result=[]
    scale=image.width/434;px=lambda v:round(v*scale)
    background=np.median(np.asarray(image,dtype=float).reshape(-1,3),axis=0)
    for row in range(int((offset+image.height)/(70*scale))+1):
        y=px(17+70*row)-offset;bottom=px(17+70*row+58)-offset
        if y<0 or bottom>min(image.height,px(QQ_CONTENT_BOTTOM)):continue
        for col in range(6):
            if row==0 and col==0:continue
            x=px(13+70*col);right=px(13+70*col+58)
            crop=image.crop((x,y,right,bottom));arr=np.asarray(crop,dtype=float)
            coverage=float((np.max(np.abs(arr-background),axis=2)>18).mean())
            if coverage<.06:continue
            result.append({'position':row*6+col,'rect':[x,y,right,bottom],
                           'content_fraction':round(coverage,4)})
    return result


def visual_observed_cells(image,offset,max_bottom=None):
    """Conservative outer bounds at fractional DPI; never truncate a pixel.

    Native Chromium bounds can enclose a fractional edge. Rounding both edges
    to nearest can make a 58 logical-pixel square 86 rather than 87 pixels at
    150%. Preserve the whole cell; existing full-image matching handles <=2px.
    """
    import math
    scale=min((1,1.25,1.5),key=lambda s:abs(image.width-434*s))
    background=np.median(np.asarray(image,dtype=float).reshape(-1,3),axis=0)
    result=[]
    for row in range(int((offset+image.height)/(70*scale))+1):
        y=math.floor((17+70*row)*scale)-offset
        bottom=math.ceil((75+70*row)*scale)-offset
        if y<0 or bottom>min(content_bottom(image),max_bottom if max_bottom is not None else image.height):continue
        for col in range(6):
            if (row,col)==(0,0):continue
            x=math.floor((13+70*col)*scale);right=math.ceil((71+70*col)*scale)
            arr=np.asarray(image.crop((x,y,right,bottom)),dtype=float)
            coverage=float((np.max(np.abs(arr-background),axis=2)>18).mean())
            if coverage<.06:continue
            result.append(dict(position=row*6+col,rect=[x,y,right,bottom],content_fraction=round(coverage,4),
                               membership='visual_candidate_not_native_identity'))
    return result


def native_observed_cells(image, offset, state):
    """Only actual personal-favorite controls, excluding built-in game tiles.

    UIA bounds identify membership of this observed viewport, not the original
    file. Keep blank/unloaded favorites too; missing previews are not omissions.
    """
    if not state.get('favorites_open'):
        raise ValueError('qq_uia_personal_favorites_not_open')
    if state.get('backend')=='visual':
        if not state.get('visual_grid_proven'):raise ValueError('favorite_panel_geometry_changed')
        return visual_observed_cells(image,offset,max_bottom=state['grid_rect'][3]-round(state['panel_rect'][1]+8*(state['panel_rect'][2]-state['panel_rect'][0])/450))
    panel=state['panel_rect'];scale=(panel[2]-panel[0])/450
    origin = (round(panel[0]+8*scale),round(panel[1]+8*scale))
    result = []; known = set()
    background = np.median(np.asarray(image, dtype=float).reshape(-1, 3), axis=0)
    for cell in state.get('cells', ()):
        if not cell['fully_visible']: continue
        box = [round(v-origin[i % 2]) for i, v in enumerate(cell['rect'])]
        x, y, right, bottom = box
        # The current raster reader has a stricter footer exclusion than UIA.
        if y < 0 or bottom > min(image.height,round(QQ_CONTENT_BOTTOM*scale)): continue
        # Two observed native layouts; never infer membership from dimensions.
        # The alternate renderer exposes 64px cells in the named favorite grid.
        alternate=cell.get('class_name')=='sticker-list-item'
        left,top,edge,pitch=(10,10,64,64) if alternate else (13,17,58,70)
        col=round((x/scale-left)/70);row=round(((y+offset)/scale-top)/pitch)
        expected=(round((left+70*col)*scale),round((top+pitch*row)*scale)-offset,
                  round((left+70*col+edge)*scale),round((top+pitch*row+edge)*scale)-offset)
        if any(abs(a-b)>2 for a,b in zip(box,expected)):
            raise ValueError('qq_uia_cell_grid_mismatch')
        if not 0 <= col < 6 or row < 0:
            raise ValueError('qq_uia_cell_grid_mismatch')
        position = row*6+col
        if position == 0 or position in known:
            raise ValueError('qq_uia_cell_grid_mismatch')
        known.add(position)
        arr = np.asarray(image.crop(box), dtype=float)
        coverage = float((np.max(np.abs(arr-background), axis=2)>18).mean())
        result.append({'position':position, 'rect':box, 'content_fraction':round(coverage,4),
                       'membership':'native_collection_sticker'})
    return result


def page_anchors_match(saved,current,cells,excluded):
    if saved.size!=current.size:return False,0
    count=0
    for cell in cells:
        if cell['position']==excluded:continue
        box=cell['rect'];a=saved.crop(box)
        if np.asarray(a,dtype=float).std()<22:continue
        if difference(a,current.crop(box))<.025:count+=1
    return count>=3,count
