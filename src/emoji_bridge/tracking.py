"""Persisted canvas-space tracks; no tracker runs during preview or export."""
from copy import deepcopy
from functools import lru_cache

@lru_cache(maxsize=64)
def track_clock(starts,end):
    from .animated_edit import GifSource
    points=sorted({0,end,*starts});durations=tuple(b-a for a,b in zip(points,points[1:]) if b>a)
    return GifSource(b'',range(len(durations)),durations,0)

def lost_ranges(keys,duration):
    result=[];start=None
    for key in [*keys,{'ms':duration,'ok':True}]:
        if not key['ok'] and start is None:start=key['ms']
        if key['ok'] and start is not None:result.append([start,key['ms']]);start=None
    return result

def transform_track(track,fn):
    result=deepcopy(track)
    result['keys']=[{**k,'box':list(fn(*k['box']))} for k in track['keys']]
    result['reference']=list(fn(*track['reference']))
    return result

def tracked_layer(layer,elapsed):
    track=layer['tracking'];keys=track.get('keys',[])
    if not keys:return layer
    valid=[k for k in keys if k['ms']<=elapsed and k.get('ok',True)]
    if not valid:return layer
    box=valid[-1]['box'];reference=track['reference'];ratio=box[2]/max(1,reference[2])
    ratio_y=box[3]/max(1,reference[3]) if track.get('algorithm')=='Petpet declarative XYWH' else ratio
    old=layer['position'];x=box[0]+(old[0]-reference[0])*ratio;y=box[1]+(old[1]-reference[1])*ratio_y
    result={**layer,'position':(round(x),round(y))}
    if layer['kind']=='text':result['size']=max(1,round(layer['size']*ratio))
    else:result['size']=tuple(max(1,round(n*r)) for n,r in zip(layer['size'],(ratio,ratio_y)))
    return result
