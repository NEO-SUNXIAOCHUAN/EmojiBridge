"""Scribbles are prompts, never painted into the source or treated as a cutout.

Coordinates are normalized to the untransformed source. Each brush stores two
source-space basis vectors, retaining circular screen strokes under rotation,
reflection and non-uniform scaling. No inference is performed in this module.
"""
import hashlib
import json
import math
from PIL import Image, ImageDraw

ADAPTER = 'scribble-alpha-flow-v3'


def digest(prompt):
    return hashlib.sha256(json.dumps(prompt, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def rasterize(strokes, size):
    """0 unknown, 1 keep, 2 exclude; erase restores unknown, not background."""
    result = Image.new('L', size); draw = ImageDraw.Draw(result)
    w, h = size
    for stroke in strokes:
        points = stroke['points']; u, v = stroke['basis']
        u = (u[0]*w, u[1]*h); v = (v[0]*w, v[1]*h)
        polygon = [(math.cos(a)*u[0]+math.sin(a)*v[0], math.cos(a)*u[1]+math.sin(a)*v[1]) for a in [i*math.tau/16 for i in range(16)]]
        fill = {'keep': 1, 'exclude': 2, 'erase': 0}[stroke['mode']]
        previous = None
        for point in points:
            p = (point[0]*w, point[1]*h)
            draw.polygon([(p[0]+x, p[1]+y) for x,y in polygon], fill=fill)
            if previous:
                # Connect corresponding circular rims: a swept ellipse capsule.
                for i in range(16):
                    a,b = polygon[i],polygon[(i+1)%16]
                    draw.polygon([(previous[0]+a[0],previous[1]+a[1]),(p[0]+a[0],p[1]+a[1]),(p[0]+b[0],p[1]+b[1]),(previous[0]+b[0],previous[1]+b[1])],fill=fill)
            previous=p
    return result


def document_points(layer, points):
    """Forward counterpart of subject_selection.source_points."""
    from .editing import _layer_size
    iw,ih=layer['image'].size;lw,lh=layer['size'];dw,dh=_layer_size(layer);px,py=layer['position']
    angle=math.radians(layer.get('rotation',0));out=[]
    for x,y in points:
        x*=iw;y*=ih
        if layer.get('fit')=='cover':
            ratio=max(lw/iw,lh/ih);x=(x-(iw-lw/ratio)/2)*ratio;y=(y-(ih-lh/ratio)/2)*ratio
        else:x=x*lw/iw;y=y*lh/ih
        if layer.get('flip_h'):x=lw-x
        if layer.get('flip_v'):y=lh-y
        dx,dy=x-lw/2,y-lh/2
        out.append((px+dw/2+math.cos(angle)*dx+math.sin(angle)*dy,py+dh/2-math.sin(angle)*dx+math.cos(angle)*dy))
    return out
