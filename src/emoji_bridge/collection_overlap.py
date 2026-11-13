"""Exact complete-media overlap in two saved favorite snapshots, not raw cache."""
import re
from . import catalog


def keys(item):
    if (item.get('original_state')!='ready' or item.get('original_available') is not True
            or item.get('transfer_block_reason') or item.get('source_receipt_only')
            or item.get('matching_basis')=='appearance'):
        return []
    # content_key includes all decoded frames, timing, loop and color data.
    # Never compare a thumbnail, first frame, name, ordinal or file size.
    return [(name,value) for name in ('source_sha256','content_key')
            if isinstance(value:=item.get(name),str) and re.fullmatch('[0-9a-f]{64}',value)]


def collect(library):
    indexes={}
    for client in ('wechat','qq'):
        side=library['clients'].get(client,{'items':[]})
        index={}
        for item in catalog.display_items(side):
            for key in keys(item):index.setdefault(key,[]).append(item['id'])
        indexes[client]=index
    facts={}
    for client,target in (('wechat','qq'),('qq','wechat')):
        side=library['clients'].get(client,{'items':[]})
        for item in catalog.display_items(side):
            for key in keys(item):
                if key not in indexes[target]:continue
                facts[(client,item['id'])]={'target':target,'matched_ids':indexes[target][key],
                    'basis':key[0],'source_at':side.get('snapshot_at'),
                    'target_at':library['clients'][target].get('snapshot_at'),
                    'scope':'exact complete originals in saved favorite snapshots; not live membership'}
                break
    return facts
