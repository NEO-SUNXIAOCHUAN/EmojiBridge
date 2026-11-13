"""Relocate a cache-bound favorite by content; scan ordinals are only history.

Only reads the personal favorite panel. Never clicks a favorite or sends one.
The retained view is a hint and must pass fresh anchor and original matching.
"""
import time
from emoji_bridge.paging import observed_cells,align_scroll,page_anchors_match
from emoji_bridge.recognition import find_in_cells
from emoji_bridge.client_geometry import qq_grid_rect,qq_panel_point,qq_panel_box,client_scale
from emoji_bridge.windows import StopAutomation,scroll
from qq_export import first_panel,check_cancel,close_selected_panel,current_panel_box,open_retained_panel

_hint=None


def clear_hint():
    global _hint
    _hint=None


def snapshot(q,box):
    if current_panel_box(q)!=box:
        raise StopAutomation('favorite_panel_anchor_changed')
    return q.frame().crop(qq_grid_rect(box))


def matched_page(grid,cells,refs,matcher,offset):
    hits=find_in_cells(grid,refs,[c['rect'] for c in cells],matcher)
    if len(hits)>1:raise StopAutomation('current_favorite_content_ambiguous')
    if not hits:return None
    x,y=hits[0].center
    chosen=[c for c in cells if c['rect'][0]<=x<c['rect'][2] and c['rect'][1]<=y<c['rect'][3]]
    if len(chosen)!=1:raise StopAutomation('current_favorite_cell_ambiguous')
    return {'offset':offset,'cells':cells,'selected_rect':chosen[0]['rect'],
            'current_position':chosen[0]['position'],'locator':'original_content',
            'complete_collection_proven':False}


def remember(q,grid,box,page):
    global _hint
    _hint=(q.window.hwnd,q.window.pid,grid.copy(),box,dict(page))
    return grid,box,page


def locate(q,refs,matcher,folder,cancel=None,max_views=24):
    """Bounded relocation. A missing match never means deletion or all read."""
    check_cancel(cancel)
    if _hint and _hint[:2]==(q.window.hwnd,q.window.pid):
        _,_,old,box,prior=_hint
        # Open the remembered view without seeking the top unnecessarily.
        try:current_panel_box(q)
        except StopAutomation as exc:
            if str(exc) not in ('heart_not_uniquely_identified','qq_uia_personal_favorites_not_open'):raise
            open_retained_panel(q)
        fresh=snapshot(q,box)
        if page_anchors_match(old,fresh,prior['cells'],-1)[0]:
            page=matched_page(fresh,prior['cells'],refs,matcher,prior['offset'])
            if page:
                page.update(search_views=0,retained_view=True)
                return remember(q,fresh,box,page)
    _,box,_=first_panel(q,cancel=cancel)
    grid=snapshot(q,box);offset=0
    for n in range(max_views):
        check_cancel(cancel)
        cells=observed_cells(grid,offset)
        page=matched_page(grid,cells,refs,matcher,offset)
        if page:
            page.update(search_views=n+1,retained_view=False)
            return remember(q,grid,box,page)
        # Diagnostics are limited to the favorite grid, not the chat window.
        grid.save(folder/f'search-{n}.png')
        if n+1==max_views:break
        previous=grid
        scroll(q.window,q.exe,*qq_panel_point(box,410,160),-1);time.sleep(.65)
        grid=snapshot(q,box)
        movement=align_scroll(previous,grid,allow_still=True)
        if movement['pixels']==0:
            time.sleep(.2);check_cancel(cancel);grid=snapshot(q,box)
            movement=align_scroll(previous,grid,allow_still=True)
        if movement['pixels']==0:
            raise StopAutomation('selected_original_not_found_before_scroll_stalled')
        offset+=movement['pixels']
    raise StopAutomation('selected_original_not_found_in_bounded_current_favorites')


def reopen(q,grid,box,page,refs,matcher,folder,cancel=None):
    close_selected_panel(q,box,cancel)
    open_retained_panel(q)
    check_cancel(cancel);fresh=snapshot(q,box)
    if page_anchors_match(grid,fresh,page['cells'],-1)[0]:
        current=matched_page(fresh,page['cells'],refs,matcher,page['offset'])
        if current:
            current.update(search_views=0,retained_view=True)
            return remember(q,fresh,box,current)
    # QQ may reset the scroll offset on reopen. Establish a NEW offset from
    # shared detailed cells in either direction, without returning to the top.
    for before,after,direction in ((grid,fresh,1),(fresh,grid,-1)):
        try:offset=page['offset']+direction*align_scroll(before,after)['pixels']
        except ValueError:continue
        if offset<0:continue
        current=matched_page(fresh,observed_cells(fresh,offset),refs,matcher,offset)
        if current:
            current.update(search_views=0,retained_view=True,realigned_on_reopen=True)
            return remember(q,fresh,box,current)
    # A fresh reorder is allowed, but the original must be found again.
    clear_hint()
    return locate(q,refs,matcher,folder,cancel)
