"""Bounded two-pass current-favorite proof shared by a selected group.

No sticker click, message, chat read, or target import. Old ordinals are not
used for location. Every receipt still has its own original/content proof.
"""
import time
from dataclasses import asdict
from pathlib import Path
from emoji_bridge.media import load_asset,references
from emoji_bridge.recognition import FrameMatcher,find_in_cells
from emoji_bridge.paging import observed_cells,align_scroll,page_anchors_match
from emoji_bridge.state import save_json
from emoji_bridge.client_geometry import qq_grid_rect,qq_panel_point,qq_panel_box,client_scale
from emoji_bridge.windows import scroll,StopAutomation
from qq_export import first_panel,close_selected_panel,check_cancel,verify_animation,SourceAnimationPending,QQCellMatcher,open_retained_panel
from qq_source_locator import snapshot,clear_hint


def reopened_view(q,grid,box,offset,cancel,history=None,selected_offset=None):
    """Prove a retained view after closing/reopening, otherwise seek afresh.

    Three detailed neighbors establish geometry only. Each selected original
    must still match its own full frames in this new pass.
    """
    check_cancel(cancel)
    open_retained_panel(q)
    fresh=snapshot(q,box)
    if page_anchors_match(grid,fresh,observed_cells(grid,offset),-1)[0]:return fresh,offset,1
    # QQ often resets to the top. Reuse first-pass snapshots only as anchors
    # for a bounded seek, never as proof of current selected-item membership.
    # Intermediate pages need not be matched against every original again.
    if not history or selected_offset is None:return None
    def position(current):
        found=[at for at,old in history.items() if page_anchors_match(old,current,observed_cells(old,at),-1)[0]]
        return found[0] if len(found)==1 else None
    current=position(fresh)
    if current!=0:return None
    for _ in range(8):
        if current>=selected_offset:return fresh,current,-1
        # A notch has produced at most 200px in the calibrated layout. Every
        # new landing must independently match a saved detailed view; a wheel
        # count or estimated position alone can never be trusted.
        notches=max(1,min(3,(selected_offset-current)//200))
        scroll(q.window,q.exe,*qq_panel_point(box,410,160),-notches);time.sleep(.35)
        check_cancel(cancel);fresh=snapshot(q,box);located=position(fresh)
        if located is None or located<=current:return None
        current=located
    return None


def verify_many(q,requests,folder,cancel=None,max_views=24,progress=None):
    if not requests or len(requests)>8:raise ValueError('source_group_limit_8')
    if len({r['id'] for r in requests})!=len(requests):raise ValueError('duplicate_source_selection')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter();entries=[];clear_hint()
    for n,request in enumerate(requests):
        check_cancel(cancel);asset=load_asset(request['asset']);refs=references(asset)
        evidence=folder/str(n);evidence.mkdir()
        entries.append(dict(request,asset_data=asset,refs=refs,matcher=QQCellMatcher(refs),folder=evidence,
            result={'command':'verify','target':'qq','status':'pending_confirmation',
                    'source_sha256':asset['source_sha256'],'selected_item_id':request['id'],
                    'client_version':q.report['client_version'],'messages_sent':0,'evidence':str(evidence),
                    'source_group':str(folder),'complete_collection_proven':False}))
    metrics={'items':len(entries),'passes':[],'messages_sent':0,'complete_collection_proven':False};history={}
    try:
        for pass_index in range(2):
            if all(e['result'].get('reason') for e in entries):break
            check_cancel(cancel)
            selected_offsets=[e['result']['content_locations'][0]['offset'] for e in entries if not e['result'].get('reason') and e['result'].get('content_locations')]
            retained=reopened_view(q,grid,box,offset,cancel,history,min(selected_offsets) if selected_offsets else None) if pass_index else None
            if retained is not None:
                grid,offset,direction=retained
            else:
                _,box,_=first_panel(q,cancel=cancel)
                grid=snapshot(q,box);offset=0;direction=-1
            seen={};positions={}
            for view in range(max_views):
                check_cancel(cancel);cells=observed_cells(grid,offset);occupied={}
                if not pass_index:history[offset]=grid.copy()
                for e in entries:
                    if e['result'].get('reason'):continue
                    hits=find_in_cells(grid,e['refs'],[c['rect'] for c in cells],e['matcher'])
                    if len(hits)>1:
                        e['result']['ambiguous_hits']=[asdict(hit) for hit in hits]
                        grid.save(e['folder']/'ambiguous-current-view.png')
                        e['result']['reason']='current_favorite_content_ambiguous';continue
                    if not hits:continue
                    hit=hits[0];matching=[c for c in cells if c['rect'][0]<=hit.center[0]<c['rect'][2] and c['rect'][1]<=hit.center[1]<c['rect'][3]]
                    if len(matching)!=1:raise StopAutomation('current_favorite_cell_ambiguous')
                    position=matching[0]['position'];digest=e['asset_data']['source_sha256']
                    if position in occupied and occupied[position]!=digest:raise StopAutomation('different_originals_match_same_favorite')
                    occupied[position]=digest
                    if e['id'] in positions and positions[e['id']]!=position:
                        e['result']['reason']='current_favorite_content_ambiguous';continue
                    positions[e['id']]=position
                    if e['id'] in seen:continue
                    seen[e['id']]=True
                    name='favorites-after-reopen.png' if pass_index else 'favorites-before-reopen.png'
                    grid.save(e['folder']/name)
                    e['result'].setdefault('content_locations',[]).append({'offset':offset,'current_position':position,'search_view':view+1})
                    if pass_index:
                        e['result'].update(favorite_match_after=[asdict(hit)],collection_persisted=True)
                        try:
                            verify_animation(q,e['asset_data'],e['refs'],e['matcher'],hit,box,e['folder'],e['result'],cancel)
                        except SourceAnimationPending as exc:
                            # The exact selected item stays pending; other originals
                            # still finish both passes. Focus/cancel/identity errors
                            # are intentionally not swallowed here.
                            e['result']['reason']=str(exc)
                    if progress:progress(pass_index+1,len(seen),len(entries))
                if all(e['id'] in seen or e['result'].get('reason') for e in entries):break
                if view+1==max_views:
                    for e in entries:
                        if e['id'] not in seen and not e['result'].get('reason'):
                            e['result']['reason']='selected_original_not_found_in_bounded_current_favorites'
                    break
                previous=grid;scroll(q.window,q.exe,*qq_panel_point(box,410,160),direction);time.sleep(.65)
                grid=snapshot(q,box)
                try:
                    movement=align_scroll(previous,grid,allow_still=True) if direction<0 else align_scroll(grid,previous,allow_still=True)
                    if movement['pixels']==0:
                        # One bounded, read-only resample rules out a delayed
                        # wheel paint. Do not send another wheel or claim EOF.
                        time.sleep(.2);check_cancel(cancel);grid=snapshot(q,box)
                        movement=align_scroll(previous,grid,allow_still=True) if direction<0 else align_scroll(grid,previous,allow_still=True)
                    metrics.setdefault('scrolls',[]).append(dict(movement,pass_index=pass_index,view=view+1,direction=direction))
                    if movement['pixels']==0:
                        for e in entries:
                            if e['id'] not in seen and not e['result'].get('reason'):
                                e['result']['reason']='selected_original_not_found_before_scroll_stalled'
                        break
                    offset-=direction*movement['pixels']
                    if offset<0:raise ValueError('scroll_alignment_outside_collection')
                except ValueError:
                    previous.save(folder/f'scroll-before-{pass_index}-{view}.png')
                    grid.save(folder/f'scroll-after-{pass_index}-{view}.png')
                    raise
            metrics['passes'].append({'views':view+1,'matched':len(seen),'retained_reopen':retained is not None})
            close_selected_panel(q,box,cancel)
        check_cancel(cancel)
        paths={}
        for e in entries:
            e['result']['status']='pending_confirmation' if e['result'].get('reason') else 'already_exists'
            path=e['folder']/'source-verification.json';save_json(path,e['result']);paths[e['id']]=path
        metrics['pending_items']=[e['id'] for e in entries if e['result']['status']!='already_exists']
        metrics['status']='partial' if metrics['pending_items'] else 'verified';return paths
    except Exception as exc:
        metrics.update(status='pending_confirmation',reason=str(exc))
        for e in entries:
            save_json(e['folder']/'interrupted-verification.json',dict(e['result'],status='pending_confirmation',interruption=str(exc)))
        raise
    finally:
        metrics['seconds']=round(time.perf_counter()-started,3)
        save_json(folder/'group.json',metrics);clear_hint()
