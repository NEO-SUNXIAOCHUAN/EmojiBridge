"""Fixed layouts change placements, never replace animated sources or layer IDs."""
from PIL import Image
from .editing import _size, _rgba, _layer_size

LAYOUTS={'双图横排':(2,1),'双图竖排':(1,2),'三图横排':(3,1),'四宫格':(2,2),'九宫格':(3,3),'纵向长图':None}


def plan(document, layout, cell=512, gap=12, background=(0,0,0,0)):
    """Calculate placements without allocating a base or changing the work."""
    pictures=[layer for layer in document.layers if layer['kind']=='sticker']
    if len(pictures)<2:raise ValueError('请先添加至少两张图片或动图。')
    grid=LAYOUTS[layout];cell=int(cell);gap=int(gap)
    if not 32<=cell<=8000 or not 0<=gap<=200:raise ValueError('格子宽度应为32～8000像素，间距为0～200像素。')
    if grid and len(pictures)>grid[0]*grid[1]:raise ValueError(f'这个模板最多放 {grid[0]*grid[1]} 张图，请选择更大的模板。')
    placements={};top=0
    for i,layer in enumerate(pictures):
        width,height=_layer_size(layer)
        ratio=min(cell/width,cell/height) if grid else cell/width
        size=tuple(max(1,round(n*ratio)) for n in layer['size'])
        updated={**layer,'size':size,'role':'collage'}
        w,h=_layer_size(updated)
        if grid:
            x=(i%grid[0])*(cell+gap)+(cell-w)//2;y=(i//grid[0])*(cell+gap)+(cell-h)//2
        else:x=0;y=top;top+=h+gap
        updated['position']=(x,y);placements[layer['id']]=updated
    dimensions=(grid[0]*cell+(grid[0]-1)*gap,grid[1]*cell+(grid[1]-1)*gap) if grid else (cell,top-gap)
    # Overlays belong to the complete work too. A smaller layout must not leave
    # captions or decorations outside the new export bounds. Keep their size,
    # expand for oversized overlays, and bring their full bounds into view.
    overlays=[l for l in document.layers if l['id'] not in placements]
    dimensions=tuple(max([dimensions[axis],*[_layer_size(l)[axis] for l in overlays]]) for axis in (0,1))
    for layer in overlays:
        extent=_layer_size(layer)
        position=tuple(max(0,min(layer['position'][axis],dimensions[axis]-extent[axis])) for axis in (0,1))
        placements[layer['id']]={**layer,'position':position}
    return _size(dimensions),[placements.get(l['id'],l) for l in document.layers],_rgba(background)


def arrange(document, layout, cell=512, gap=12, background=(0,0,0,0)):
    dimensions,layers,background=plan(document,layout,cell,gap,background)
    document.replace_scene(Image.new('RGBA',dimensions,background),layers,document.source_ids,'套用拼图模板')

