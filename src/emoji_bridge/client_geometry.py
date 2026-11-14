"""Physical client coordinates, independently of the editor's UI scaling."""
from .windows import StopAutomation

SUPPORTED_DPI = (96, 120, 144)


def client_scale(dpi):
    if dpi not in SUPPORTED_DPI:
        raise StopAutomation('client_display_scale_unsupported')
    return dpi / 96


def qq_panel_box(window, state):
    if not state.get('favorites_open'):
        raise StopAutomation('qq_uia_personal_favorites_not_open')
    scale = client_scale(window.dpi)
    panel, grid = state['panel_rect'], state['grid_rect']
    local = tuple(round(v - window.rect[i % 2]) for i, v in enumerate(panel))
    # Chromium can round each edge independently by a physical pixel.
    size = (panel[2]-panel[0], panel[3]-panel[1])
    inset = tuple(grid[i]-panel[i % 2] for i in range(4))
    visual=state.get('backend')=='visual' and state.get('visual_grid_proven')
    if visual:
        if abs(size[0]-450*scale)>2 or not 325*scale<=size[1]<=340*scale:
            raise StopAutomation('favorite_panel_geometry_changed')
        if (any(abs(inset[i]-v*scale)>2 for i,v in enumerate((1,1,449)))
                or abs((size[1]-inset[3])-50*scale)>4):
            raise StopAutomation('favorite_grid_geometry_changed')
    elif abs(size[0]-450*scale)>2 or abs(size[1]-337*scale)>4:
        raise StopAutomation('favorite_panel_geometry_changed')
    if not visual and any(abs(a-b*scale)>(4 if i==3 else 2) for i,(a,b) in enumerate(zip(inset,(1,1,449,287)))):
        raise StopAutomation('favorite_grid_geometry_changed')
    if not (0<=local[0]<local[2]<=window.rect[2]-window.rect[0]
            and 0<=local[1]<local[3]<=window.rect[3]-window.rect[1]):
        raise StopAutomation('favorite_panel_geometry_changed')
    return local


def qq_grid_rect(box):
    """One physical crop shared by source scans and destination verification."""
    scale = (box[2]-box[0])/450
    return tuple(round(box[i % 2]+v*scale) for i,v in enumerate((8,8,442,298)))


def qq_grid_crop(panel,box):
    rect=qq_grid_rect(box)
    return panel.crop(tuple(v-box[i % 2] for i,v in enumerate(rect))),rect


def qq_grid_cells(image):
    """Full tiles of the proven first viewport, in physical crop coordinates."""
    from .paging import content_bottom
    # 125% has a half-pixel width; do not reinterpret its rounded raster width
    # as a slightly smaller display scale and drift the last columns.
    scale=min(SUPPORTED_DPI,key=lambda dpi:abs(image.width-434*dpi/96))/96
    cells=[]
    for row in range(4):
        for col in range(6):
            if (row,col)==(0,0):continue
            rect=tuple(round(v*scale) for v in (13+70*col,17+70*row,71+70*col,75+70*row))
            if rect[2]<=image.width and rect[3]<=content_bottom(image):cells.append(rect)
    return cells


def qq_native_grid_cells(state):
    """Current native favorites only; game tiles and clipped rows are excluded."""
    rect=qq_grid_rect(state['panel_rect']);scale=(state['panel_rect'][2]-state['panel_rect'][0])/450
    result=[]
    for cell in state.get('cells',()):
        if not cell['fully_visible']:continue
        box=tuple(round(v-rect[i % 2]) for i,v in enumerate(cell['rect']))
        if (0<=box[0]<box[2]<=rect[2]-rect[0] and 0<=box[1]<box[3]<=round(279*scale)):
            result.append(box)
    return result


def qq_panel_point(box,x,y):
    scale=(box[2]-box[0])/450
    return round(box[0]+x*scale),round(box[1]+y*scale)
