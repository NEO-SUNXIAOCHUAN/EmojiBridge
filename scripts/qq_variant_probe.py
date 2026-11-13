"""Read ambiguous selected favorites once in ascending order. Never send.

This collects small favorite-only observations, not original images or source
receipts. A later candidate comparison must still prove the exact variant.
"""
from emoji_bridge.client_sources import qq_profile, executable
from datetime import datetime
from pathlib import Path
import time
from qq_source_ui import SourceQQ as QQ
from qq_export import first_panel,check_cancel
from qq_cache_acquire import ROOT,read
from emoji_bridge.state import save_json,single_instance,sha
from emoji_bridge.windows import scroll,hover,restore_pointer,StopAutomation
from emoji_bridge.paging import align_scroll,page_anchors_match,difference


def seek_visible(item,recorded,offset,current,grid,move,cancel,progress,limit=48):
    """Bounded observed movement, including a check AFTER the final wheel step."""
    deadline=time.monotonic()+60
    for step in range(limit+1):
        check_cancel(cancel)
        delta=recorded['offset']-offset
        rect=[item['rect'][0],item['rect'][1]+delta,item['rect'][2],item['rect'][3]+delta]
        progress.update(position=item['position'],offset=offset,steps=step,target_rect=rect)
        if 0<=rect[1] and rect[3]<=279:return offset,current,delta,rect
        if rect[1]<0:raise StopAutomation('selected_cell_scroll_overshoot')
        if step==limit or time.monotonic()>=deadline:raise StopAutomation('selected_cell_scan_limit')
        move();following=grid();pixels=align_scroll(current,following,allow_still=True)['pixels']
        progress.setdefault('measured_steps',[]).append(pixels)
        if pixels==0:raise StopAutomation('qq_favorite_scroll_no_progress')
        offset+=pixels;current=following


def observe(scan_path,positions,cancel=None,seconds=3):
    scan=read(scan_path);selected=[i for i in scan['items'] if i['position'] in positions]
    if len(selected)!=len(set(positions)) or not 1<=len(selected)<=6:raise ValueError('bounded_existing_selection_required')
    folder=ROOT/'private/T006/variant-probe'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder.mkdir(parents=True)
    result={'scan':str(scan_path),'scan_sha256':sha(scan_path),'items':[], 'messages_sent':0,'additions':0,'navigation':[]}
    q=QQ(qq_profile(),{},Path(cancel) if cancel else None)
    try:
        with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
            check_cancel(cancel)
            q.bind();_,box,_=first_panel(q,cancel=cancel);offset=0
            def grid():
                q.assert_panel(box)
                return q.frame().crop((box[0]+8,box[1]+8,box[0]+442,box[1]+298))
            current=grid()
            for item in sorted(selected,key=lambda i:i['position']):
                check_cancel(cancel);recorded=scan['pages'][item['page']]
                if sha(recorded['image'])!=recorded['sha256']:raise ValueError('scan_image_changed')
                def move():
                    check_cancel(cancel);q.advance_favorites()
                navigation={};result['navigation'].append(navigation)
                offset,current,delta,rect=seek_visible(item,recorded,offset,current,grid,move,cancel,navigation)
                from PIL import Image
                with Image.open(recorded['image']) as saved:
                    shifted=Image.new('RGB',current.size);shifted.paste(saved,(0,delta))
                cells=[dict(c,rect=[c['rect'][0],c['rect'][1]+delta,c['rect'][2],c['rect'][3]+delta])
                       for c in recorded['cells'] if 0<=c['rect'][1]+delta and c['rect'][3]+delta<=279]
                if not page_anchors_match(shifted,current,cells,item['position'])[0]:
                    raise StopAutomation('selected_neighbors_changed')
                if difference(shifted.crop(rect),current.crop(rect))>.025:
                    raise StopAutomation('selected_idle_content_changed')
                target=folder/str(item['position']);target.mkdir()
                idle=target/'idle.png';current.crop(rect).save(idle)
                entry={'id':item['id'],'position':item['position'],'idle':str(idle),'samples':[],'offset':offset,'rect':rect}
                x=box[0]+8+(rect[0]+rect[2])//2;y=box[1]+8+(rect[1]+rect[3])//2
                previous,pointer=hover(q.window,q.exe,x,y)
                try:
                    time.sleep(.3);started=time.monotonic()
                    while time.monotonic()-started<seconds:
                        check_cancel(cancel);path=target/f'sample-{len(entry["samples"])}.png'
                        q.frame().crop((x-34,y-34,x+34,y+34)).save(path)
                        entry['samples'].append({'path':str(path),'sha256':sha(path),'elapsed':time.monotonic()-started})
                        time.sleep(.15)
                finally:restore_pointer(previous,pointer)
                time.sleep(.3);current=grid();result['items'].append(entry)
                save_json(folder/'result.json',result)
            q.close_panel()
            result['status']='observed_only'
    except Exception as exc:result.update(status='stopped',reason=str(exc))
    finally:q.close()
    save_json(folder/'result.json',result)
    return dict(result,report=str(folder/'result.json'))
