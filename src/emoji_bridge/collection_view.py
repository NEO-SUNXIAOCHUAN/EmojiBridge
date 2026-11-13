"""Lossless grouping of observed favorites, not a claim of live/cloud membership."""
from datetime import datetime
import hashlib
from pathlib import Path
from .collection_overlap import keys
from .card_names import collection_name_origin, display_fields


def original_ready(item):
    # Cached successful original verification, not an identity/thumbnail match.
    # The acquisition pipeline revalidates bytes and provenance on execution.
    return (item.get('original_state') == 'ready' and item.get('original_available') is True
            and not item.get('transfer_block_reason') and bool((item.get('asset') or item.get('managed_original')) and item.get('source_sha256'))
            and any(Path(p).is_file() for p in (item.get('asset'),item.get('managed_original')) if p))


def original_label(item):
    if original_ready(item): return '完整文件已校验 · 外观关联' if item.get('matching_basis')=='appearance' else '原件已核验'
    if item.get('original_state')=='ready' and item.get('asset') and not Path(item['asset']).is_file():return '原件记录失效，执行时重新核对'
    if item.get('original_state') in ('failed','unavailable','unsupported'): return '原件获取失败 / 待处理'
    if item.get('original_available'): return '原件关联待核对'
    if item.get('original_state')=='downloaded' and item.get('asset'): return '已有完整文件 · 新视图关联待核对'
    return '待取得原件'


def retain_unseen(previous,current):
    """Reconcile observations, not media identity. Preserve prior provenance in place.

    QQ position + identical captured cover only links repeated observations. It
    must never promote an old original receipt or confirm an animated duplicate.
    """
    from .state import sha
    def observation(item):
        if item.get('observation_key'):return item['observation_key']
        if 'position' in item and item.get('preview'):
            try:item['observation_key']=str(item['position'])+':'+sha(item['preview'])
            except OSError:pass
        return item.get('observation_key')
    current_ids={i['id']:i for i in current.get('items',[])}
    observations={observation(i):i for i in current.get('items',[]) if observation(i)}
    def link(item):
        latest=current_ids.get(item['id'])
        if latest:
            prior=set(keys(item));new=set(keys(latest))
            if not prior or not new or prior&new:return latest
        latest=observations.get(observation(item)) if observation(item) else None
        if latest is not None:
            prior=set(keys(item));new=set(keys(latest))
            if prior and new and not prior&new:return None
        return latest
    historical={}
    records=[*previous.get('unseen_observations',[]),
             *({'item':i,'read_at':previous.get('snapshot_at'),'scope':previous.get('scope')} for i in previous.get('items',[]))]
    for record in records:
        item=record['item']
        if item.get('source_receipt_only') or item.get('receipt_only'):continue
        latest=link(item)
        if latest is not None:
            # Keep the full prior receipt without recursively nesting histories.
            if latest is item:continue
            older=list(item.get('observation_history',[]))
            if item['id']!=latest['id']:
                older.append(dict(record,item={k:v for k,v in item.items() if k!='observation_history'}))
            combined=[*latest.get('observation_history',[]),*older]
            if combined:latest['observation_history']=list({(r.get('read_at'),r['item']['id']):r for r in combined}.values())
            continue
        # An unchanged observation remains one historical record across scans.
        key=(observation(item) or item['id'],tuple(keys(item)))
        earlier=historical.get(key)
        if earlier and earlier['item']['id']!=item['id']:
            links=[*item.get('observation_history',[]),*earlier['item'].get('observation_history',[]),
                   dict(earlier,item={k:v for k,v in earlier['item'].items() if k!='observation_history'})]
            item['observation_history']=list({(r.get('read_at'),r['item']['id']):r for r in links}.values())
        historical[key]=record
    current['unseen_observations']=list(historical.values())


def extend_visible_qq(previous,visible):
    """Keep the previously read tail when a first viewport has shifted.

    Ordered, unique, unchanged covers locate the overlapping viewport ONLY.
    They do not prove a file, an animated duplicate or current tail membership.
    Original scan/position pairs remain intact on preserved tail observations.
    """
    from collections import Counter,defaultdict
    from .state import sha
    older=previous.get('items',[])
    if not older or not visible:return None
    def position(item):return item.get('display_position',item.get('position',0))
    def cover(item):
        try:return sha(item['preview'])
        except (KeyError,OSError):return None
    old_keys=defaultdict(list);new_keys=defaultdict(list)
    for item in older:
        key=cover(item)
        if key:old_keys[key].append(item)
    for item in visible:
        key=cover(item)
        if key:new_keys[key].append(item)
    anchors=[(a[0],new_keys[k][0]) for k,a in old_keys.items() if len(a)==1 and len(new_keys.get(k,[]))==1]
    if len(anchors)<3:return None
    shifts=Counter(position(b)-position(a) for a,b in anchors);shift,count=shifts.most_common(1)[0]
    if count<3 or count/len(anchors)<.75:return None
    end=max(position(i) for i in visible)
    # A non-prefix view must not silently displace the saved catalog.
    if min(position(i) for i in visible)!=1:return None
    for a,b in anchors:
        prior=set(keys(a));current=set(keys(b))
        if prior and current and not prior&current:continue
        if position(b)-position(a)==shift and a.get('observation_key'):
            b['observation_key']=a['observation_key']
    tail=[dict(i,display_position=position(i)+shift,preserved_from_previous_view=True,
               last_observed_at=i.get('last_observed_at',previous.get('snapshot_at')))
          for i in older if position(i)+shift>end]
    return sorted([*visible,*tail],key=position),dict(visible=len(visible),preserved=len(tail),offset=shift,anchors=count)


def grouped(library,owned=(),history=None,owned_content=()):
    history=history or {};owned=set(owned);owned_content=set(owned_content);entries=[];parent=[];lookup={}
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for client in ('qq','wechat'):
        side=library.get('clients',{}).get(client,{})
        observed=[(i,side) for i in side.get('items',[])]
        observed += [(dict(r['item'],unseen=True),dict(side,snapshot_at=r.get('read_at'),scope=r.get('scope'))) for r in side.get('unseen_observations',[])]
        seen=set()
        for item,read_side in observed:
            if item.get('receipt_only') or item.get('source_receipt_only'):continue
            observation=(item['id'],tuple(keys(item))) if item.get('unseen') else item['id']
            if observation in seen:continue
            if item.get('unseen') and item['id'] in seen and not keys(item):continue
            seen.add(observation)
            n=len(entries);entries.append((client,item,read_side));parent.append(n)
            for key in keys(item):
                if key in lookup:parent[root(n)]=root(lookup[key])
                else:lookup[key]=n
    groups={}
    for n,entry in enumerate(entries):groups.setdefault(root(n),[]).append(entry)
    output=[]
    for entries in groups.values():
        members=[];sources=[];trusted=False;imported=False;historical=False;current_sources=set()
        for client,item,side in entries:
            sources.append(client);trusted|=bool(keys(item));imported|=item.get('source_sha256') in owned or any(k=='content_key' and v in owned_content for k,v in keys(item))
            if not item.get('unseen'):current_sources.add(client)
            historical|=history.get((client,item['id']),{}).get('state')=='confirmed'
            members.append({'client':client,'id':item['id'],'source_sha256':item.get('source_sha256'),
                'name':item.get('label','收藏表情'),'name_origin':collection_name_origin(item,client),
                'observation_key':item.get('observation_key',item['id']),
                'content_key':item.get('content_key'),'read_at':item.get('last_observed_at',side.get('snapshot_at')),'scope':side.get('scope'),
                'matching_basis':item.get('matching_basis'),
                'prior_observations':len(item.get('observation_history',[])),
                'original_state':item.get('original_state'),'original_available':bool(item.get('original_available')),
                'original_ready':original_ready(item),'original_label':original_label(item),
                'enrichment_state':item.get('enrichment_state'),'enrichment_error':item.get('enrichment_error'),'enrichment_at':item.get('enrichment_at'),
                'last_read_failure':side.get('last_read_failure'),'asset':item.get('asset'),'managed_original':item.get('managed_original'),'unseen':bool(item.get('unseen'))})
        item=next((i for _,i,_ in entries if i.get('clear_preview') and Path(i['clear_preview']).is_file()),None) or next((i for _,i,_ in entries if i.get('preview')),entries[0][1])
        # Adding another source must not change the content card identity.
        identities=sorted({str(k)+':'+v for _,i,_ in entries for k,v in keys(i)}) or sorted(c+':'+i['id'] for c,i,_ in entries)
        identities=identities[:1]
        key=hashlib.sha256('\0'.join(identities).encode()).hexdigest()
        states=[]
        if len(current_sources)==2 and trusted:states.append('两端都有')
        if any(m['unseen'] for m in members):states.append('部分来源本次未读到')
        if imported:states.append('已入素材库')
        if historical:states.append('曾添加')
        if not trusted:states.append('待核对')
        counts={c:sum(m['client']==c and not m['unseen'] for m in members) for c in ('qq','wechat')}
        duplicate=trusted and sum(counts.values())>1
        labels=[]
        if trusted:
            if all(counts.values()):labels.append('QQ、微信都有')
            labels.extend(('QQ' if c=='qq' else '微信')+f'内有 {n} 份' for c,n in counts.items() if n>1)
        comparison='confirmed' if duplicate else 'exact' if trusted else 'pending'
        if comparison=='pending':states=[s for s in states if s!='待核对']+['待比对 · 原件或精确关联未齐']
        named=next((m for m in members if m['name_origin']!='generated'),members[0])
        clear=item.get('clear_preview') if item.get('clear_preview') and Path(item['clear_preview']).is_file() else None
        output.append({'id':key,**display_fields(named['name'],named['name_origin']),'preview':clear or item.get('preview'),
                       'preview_quality':'original_cover' if clear else 'cover',
                       'has_preview':bool(item.get('preview')),
                       'clients':list(dict.fromkeys(sources)),'members':members,'states':states,
                       'source_counts':counts,'source_count':sum(counts.values()),'duplicate':duplicate,
                       'historical_only':not any(counts.values()),
                       'duplicate_labels':labels,'comparison':comparison,
                       'frames':max(i.get('frames',1) for _,i,_ in entries),'identity_verified':trusted,
                       'ready':any(m['original_ready'] and not m['unseen'] for m in members),
                       'original_label':next((m['original_label'] for m in members if m['original_ready'] and not m['unseen']),
                                             '本次未读到，请更新来源' if all(m['unseen'] for m in members) else '待取得原件 / 核对关联')})
    candidates={}
    for row in output:
        for m in row['members']:
            if m['unseen'] or m['original_state']!='ready' or not m['original_available']:continue
            for name in ('source_sha256','content_key'):
                if m.get(name):candidates.setdefault((name,m[name]),set()).add(row['id'])
    for row in output:
        related={other for m in row['members'] for name in ('source_sha256','content_key')
                 for other in candidates.get((name,m.get(name)),()) if other!=row['id']}
        row['suspected_with']=sorted(related)
        if related and not row['identity_verified']:
            row['comparison']='suspected'
            row['states']=[s for s in row['states'] if not s.startswith('待比对')]+[f'疑似与 {len(related)} 组相同 · 外观关联未精确确认']
    return output
