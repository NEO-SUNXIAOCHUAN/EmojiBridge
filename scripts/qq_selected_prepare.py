"""Prepare only explicit transfer selections, without refreshing the catalog."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import time

from emoji_bridge import catalog
from emoji_bridge.state import single_instance
from client_material_import import binding


def complete_selected(library_path, ids, cancel, progress=None):
    from qq_appearance_prepare import prepare
    from qq_offline_index import build
    from qq_cache_acquire import current_inventory, cancelled
    library_path=Path(library_path)
    library=catalog.read(library_path)
    chosen=[i for i in library['clients']['qq']['items'] if i['id'] in ids and not i.get('source_receipt_only')]
    if len(chosen)!=len(set(ids)):raise ValueError('selected_original_binding_changed')
    identities={i['id']:binding(i) for i in chosen}
    # Keep this subset's expensive animation search independent of unselected
    # rows. The enclosing transfer owns the account's collection writer lock.
    folder=library_path.parent/'selected-originals'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    work=folder/'library.json'
    catalog.save({'clients':{'qq':dict(library['clients']['qq'],items=deepcopy(chosen)),
                             'wechat':{'items':[]}}},work)
    def merge():
        current=catalog.read(library_path)
        updates={i['id']:i for i in catalog.read(work)['clients']['qq']['items']}
        for item in current['clients']['qq']['items']:
            if item['id'] in updates:
                if binding(item)!=identities[item['id']]:raise ValueError('selected_original_binding_changed')
                item.update(updates[item['id']])
        catalog.save(current,library_path)
    try:
        prepare(work,cancel,ids=ids)
        cancelled(cancel)
        pending=[i for i in catalog.read(work)['clients']['qq']['items'] if not i.get('original_available')]
        if not pending:return
        if progress:progress('只补所选 QQ 原件；其他条目稍后继续')
        build(work,cancel)
        pending=[i for i in catalog.read(work)['clients']['qq']['items'] if not i.get('original_available')]
        if not pending:return
        before,_=current_inventory(cancel)
        # A source visit is reserved for selected originals absent locally.
        # No QQ chat click, send, or favorite addition is performed.
        from qq_source_ui import SourceQQ
        from emoji_bridge.client_sources import qq_profile
        from qq_export import selected_page,close_selected_panel
        from emoji_bridge.client_geometry import qq_grid_rect
        from emoji_bridge.windows import hover,restore_pointer
        from local_bridge import handoff_to
        root=library_path.parents[2]
        q=SourceQQ(qq_profile(),{},Path(cancel))
        try:
            with single_instance(root/'runtime-data/T003/client-ui.lock'):
                handoff_to('qq');q.bind()
                for item in pending:
                    cancelled(cancel)
                    scan=catalog.read(item['scan'])
                    _,box,page=selected_page(q,scan,item,cancel)
                    grid=qq_grid_rect(box);l,t,r,b=page['selected_rect']
                    old,pointer=hover(q.window,q.exe,grid[0]+(l+r)//2,grid[1]+(t+b)//2)
                    try:
                        for _ in range(6):
                            cancelled(cancel);q.frame();time.sleep(.15)
                    finally:restore_pointer(old,pointer)
                    close_selected_panel(q,box,cancel)
        finally:q.close()
        # Only a changed local inventory warrants decoding again. An unloaded
        # or ambiguous item stays pending, never becomes a thumbnail export.
        for _ in range(6):
            cancelled(cancel);after,_=current_inventory(cancel)
            if after.get('directory_fingerprint')!=before.get('directory_fingerprint'):
                prepare(work,cancel,ids=ids)
                build(work,cancel)
                break
            time.sleep(.25)
    finally:merge()
