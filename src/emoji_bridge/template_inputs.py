"""Immutable edited-scene inputs, owned by the project rather than the library."""
from copy import copy
from pathlib import Path
from uuid import uuid4
from PIL import Image
from .editing import EditDocument


def capture(document, ids=None):
    if ids is None:
        result=copy(document);result._undo=[];result._redo=[]
        return result
    layers=[l for l in document.layers if l['id'] in ids]
    if not layers:raise ValueError('请先选择当前作品中的图层')
    bounds=[document.layer_bounds(l['id']) for l in layers]
    left=min(b[0] for b in bounds);top=min(b[1] for b in bounds)
    right=max(b[2] for b in bounds);bottom=max(b[3] for b in bounds)
    result=EditDocument(Image.new('RGBA',(right-left,bottom-top)))
    for layer in layers:layer['position']=(layer['position'][0]-left,layer['position'][1]-top)
    result.replace_scene(result._state.base,layers,[l['source_id'] for l in layers if l.get('source_id')],'模板输入快照')
    # A selected subject retains its complete animation; full-work input uses
    # the document output range. Neither includes future generated layers.
    return result


def persist(document, root, *, revision, label, frame=None, cancel=None):
    from .animation_formats import export_animation
    from .state import save_json
    folder=Path(root)/uuid4().hex;folder.mkdir(parents=True)
    path=folder/'input.png';thumb=folder/'preview.png'
    if document.animation and frame is None:export_animation(document,path,cancel=cancel)
    else:document.render(animation_frame=frame or 0).save(path,'PNG')
    image=document.render(animation_frame=frame or 0);image.thumbnail((160,120));image.save(thumb)
    value={'snapshot':str(path.resolve()),'thumbnail':str(thumb.resolve()),'revision':revision,
           'label':label,'source_ids':document.source_ids,'frame':None,'animated':bool(document.animation and frame is None)}
    save_json(folder/'input.json',value)
    return value


def return_to_canvas(document, ids):
    """One translation / history entry; never scale or unlock a selected group."""
    layers=document.layers;chosen=[l for l in layers if l['id'] in ids]
    if not chosen:return False
    if any(l.get('locked') for l in chosen):raise ValueError('所选图层已锁定；请明确解锁后移动')
    boxes=[document.layer_bounds(l['id']) for l in chosen]
    a=min(b[0] for b in boxes);b=min(b[1] for b in boxes);c=max(b[2] for b in boxes);d=max(b[3] for b in boxes)
    w,h=document.size
    dx=round((w-(c-a))/2-a);dy=round((h-(d-b))/2-b)
    if not (dx or dy):return False
    for layer in chosen:layer['position']=(layer['position'][0]+dx,layer['position'][1]+dy)
    document.replace_scene(document._state.base,layers,document.source_ids,'移回画布')
    return True
