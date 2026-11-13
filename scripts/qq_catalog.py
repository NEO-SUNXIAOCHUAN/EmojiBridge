"""Read bounded QQ favorite pages and retain selectable, revalidated positions."""
from datetime import datetime
from pathlib import Path
import sys,time,json
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
from emoji_bridge.client_sources import qq_profile, executable
from qq_source_ui import SourceQQ as QQ
from local_bridge import handoff_to,read_json
from emoji_bridge.state import save_json,single_instance,sha
from emoji_bridge.client_geometry import qq_grid_rect,qq_panel_point,qq_panel_box,client_scale
from emoji_bridge.windows import scroll,guard,StopAutomation
from emoji_bridge.paging import align_scroll,native_observed_cells

MAX_SCAN_VIEWS=64


def visible_window():
    """Observe only an already foreground QQ; no restore/activation/input."""
    from emoji_bridge.windows import user,qq_windows
    config=qq_profile();foreground=user.GetForegroundWindow()
    windows=[w for w in qq_windows(Path(config['exe'])) if w.kind=='Chrome_WidgetWin_1' and w.rect[2]-w.rect[0]>=600 and w.rect[3]-w.rect[1]>=450]
    return config,windows[0] if len(windows)==1 and windows[0].hwnd==foreground else None


def scan_visible(cancel=None,previous_signature=None):
    from emoji_bridge.qq_controls import FavoriteControls
    from emoji_bridge.windows import file_version
    config,window=visible_window()
    if window is None:raise StopAutomation('qq_background_update_needs_visible_favorites')
    q=QQ(config,{},Path(cancel) if cancel else None);q.window=window
    if file_version(q.exe)!=config['version']:raise StopAutomation('client_version_changed')
    client_scale(window.dpi)
    try:
        with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
            q.controls=FavoriteControls(window,q.exe,Path(cancel) if cancel else None)
            native=q.controls.read();box=q.panel_box(native)
            if not native.get('at_top'):raise StopAutomation('qq_background_update_needs_first_view')
            # Runtime anchors identify this live view only. They are not used
            # as favorite IDs or cross-session duplicate/content proof.
            signature={'window':window.hwnd,'pid':window.pid,'loaded':native['loaded_cells'],
                       'anchors':[c['runtime_id'] for c in native.get('cells',[])]}
            if signature==previous_signature:return None,{'unchanged':True,'visible_signature':signature}
            guard(window,q.exe)
            image=q.frame().crop(qq_grid_rect(box))
            cells=native_observed_cells(image,0,native)
            if not cells:raise StopAutomation('qq_uia_favorites_loading_timeout')
            stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            folder=ROOT/'private/T005/qq-scans'/stamp;folder.mkdir(parents=True)
            page=folder/'page-0.png';image.save(page);items=[]
            for cell in cells:
                pos=cell['position'];thumb=folder/f'item-{pos}.png';image.crop(cell['rect']).save(thumb)
                items.append(dict(id=f'qq:{stamp}:{pos}',position=pos,page=0,rect=cell['rect'],preview=str(thumb),
                                  original_state='discovered',original_available=False,label=f'QQ 条目 {pos}',name_origin='generated',identity_scope='position in this scan only'))
            report={'schema':'qq-favorite-observations-v1','client':'qq','source_kind':'personal_favorites_ui',
                    'complete':False,'scope':'already visible first favorite viewport; no activation or input',
                    'pages':[dict(view=0,offset=0,image=str(page),sha256=sha(page),cells=cells,native_view=native)],
                    'items':items,'at':datetime.now().astimezone().isoformat(),'status':'partial_read',
                    'visible_signature':signature,'loaded_favorite_controls':native['loaded_cells'],'passive':True}
            guard(window,q.exe)
            path=ROOT/'reports/T005'/('qq-scan-'+stamp+'.json');save_json(path,report,compact=True)
            return path,report
    finally:q.close()


from emoji_bridge.timing import measured,stage

@measured("index")
def scan(max_views=5,cancel=None,progress=None):
    if not 1<=max_views<=MAX_SCAN_VIEWS:raise ValueError('views_out_of_range')
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder=ROOT/'private/T005/qq-scans'/stamp;folder.mkdir(parents=True)
    path=ROOT/'reports/T005'/('qq-scan-'+stamp+'.json')
    r={'schema':'qq-favorite-observations-v1','client':'qq','source_kind':'personal_favorites_ui',
       'complete':False,'scope':'bounded aligned viewports; observations, not global favorite IDs',
       'pages':[],'items':[],'status':'reading','at':datetime.now().astimezone().isoformat()}
    q=QQ(qq_profile(),r,Path(cancel) if cancel else None);known={};offset=0;scrolled=0;opened=False
    try:
        with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
            from qq_export import first_panel
            handoff_to('qq');q.bind();panel,box,_=first_panel(q);opened=True
            for number in range(max_views):
                if cancel and Path(cancel).exists():raise StopAutomation('cancel_requested')
                guard(q.window,q.exe)
                with stage('qq_scan_capture'):
                    q.assert_panel(box)
                    image=q.frame().crop(qq_grid_rect(box))
                img=folder/f'page-{number}.png';image.save(img)
                alignment=None
                if number:
                    alignment=align_scroll(previous,image,allow_still=True)
                    if alignment['pixels']==0:
                        # QQ loads the list in chunks. A still viewport at the
                        # loaded tail must not immediately terminate a scan.
                        with stage('qq_scan_loading_wait'):
                            settled=q.wait_for_favorite_growth(native)
                        if settled['loaded_cells']==native['loaded_cells']:
                            r['stop_reason']='loaded_tail_quiet_cloud_total_unproven';break
                        with stage('qq_scan_advance'):q.advance_favorites()
                        q.assert_panel(box)
                        image=q.frame().crop(qq_grid_rect(box))
                        alignment=align_scroll(previous,image,allow_still=True)
                        if alignment['pixels']==0:raise StopAutomation('qq_favorite_scroll_no_progress')
                        image.save(img)
                    offset+=alignment['pixels']
                with stage('qq_scan_controls'):native=q.controls.read()
                cells=native_observed_cells(image,offset,native)
                page={'view':number,'offset':offset,'image':str(img),'sha256':sha(img),'alignment':alignment,'cells':cells}
                r['pages'].append(page)
                page['native_view'] = native
                for cell in cells:
                    position=cell['position']
                    if position in known:continue
                    thumb=folder/f'item-{position}.png';image.crop(cell['rect']).save(thumb)
                    item={'id':f'qq:{stamp}:{position}','position':position,'page':number,'rect':cell['rect'],
                          'preview':str(thumb),'original_state':'discovered','original_available':False,'selected':False,
                          'label':f'QQ 条目 {position}','name_origin':'generated','identity_scope':'position in this scan only'}
                    known[position]=item;r['items'].append(item)
                with stage('qq_scan_save'):save_json(path,r,compact=True)
                previous=image
                if progress:
                    with stage('qq_scan_publish'):progress(path,r)
                if number+1<max_views:
                    with stage('qq_scan_advance'):q.advance_favorites()
                    scrolled+=1
            else:
                r['stop_reason']='view_budget_reached'
                r['reason']='qq_scan_view_limit_reached'
            r['status']='partial_read'
            if r['pages']:
                r['loaded_favorite_controls']=r['pages'][-1]['native_view']['loaded_cells']
                r['observed_count_matches_loaded_controls']=len(known)==r['loaded_favorite_controls']
            # A stopped viewport and all loaded controls are not a server total.
            q.close_panel();opened=False
            r['returned_to_first_view']=False
    except Exception as exc:
        r['status']='partial_read';r['reason']=str(exc)
        if opened:
            try:
                q.close_panel()
                r['returned_to_first_view']=False
            except Exception:r['returned_to_first_view']=False
    finally:q.close()
    r['observed_count']=len(r['items']);r['finished_at']=datetime.now().astimezone().isoformat();save_json(path,r,compact=True)
    return path,r


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--views',type=int,default=5);a=p.parse_args()
    path,r=scan(a.views);print(json.dumps({'report':str(path),'pages':len(r['pages']),'items':len(r['items']),'reason':r.get('reason'),'complete':False},ensure_ascii=False))
