"""Disambiguate saved QQ observations using their read-only hover samples."""
from datetime import datetime
from pathlib import Path
from PIL import Image
from emoji_bridge import catalog
from emoji_bridge.state import sha,save_json
from emoji_bridge.recognition import rgb
from emoji_bridge.snapshot_matching import CellMatcher
from emoji_bridge.variant_originals import winner,register
from emoji_bridge.originals import attach_receipt
import qq_cache_acquire as acquire
from qq_offline_index import native_frames,target_readiness


def hover_frames(path,cancel=None):
    for n,frame in native_frames(path,cancel):
        yield (n,'plain'),rgb(frame,(54,54,54))
        yield (n,'painted'),Image.blend(rgb(frame),Image.new('RGB',frame.size,'white'),20/255)


def discover_from_hover(library_path,probe_path,position,cancel=None):
    return discover_from_hovers(library_path,probe_path,[position],cancel)[position]


def discover_from_hovers(library_path,probe_path,positions,cancel=None):
    """A full, freshly observed larger pose can fix a thumbnail-render miss.

    Search every allowed original, not just the closest idle thumbnail. This
    is source acquisition only and never opens or submits to either client.
    """
    # Decode every cache file once for this bounded group, not once per item.
    # Retain ALL matches for each selection; sharing decoding never resolves
    # ambiguity or changes the acceptance thresholds.
    positions=list(positions)
    if not 1<=len(positions)<=6 or len(set(positions))!=len(positions):
        raise ValueError('bounded_existing_selection_required')
    library=catalog.read(library_path);probe=catalog.read(probe_path);selected={};cells={}
    for position in positions:
        observations=[i for i in probe['items'] if i['position']==position]
        if len(observations)!=1:raise ValueError('variant_selection_changed')
        observed=observations[0]
        items=[i for i in library['clients']['qq']['items'] if i['id']==observed['id']]
        if len(items)!=1 or items[0]['position']!=position:raise ValueError('variant_selection_changed')
        item=items[0]
        if sha(item['scan'])!=probe['scan_sha256']:raise ValueError('variant_scan_changed')
        sample=observed['samples'][0]
        if sha(sample['path'])!=sample['sha256']:raise ValueError('variant_sample_changed')
        with Image.open(sample['path']) as im:
            if im.size!=(68,68):raise ValueError('complete_hover_sample_required')
            cells[position]=im.crop((2,2,66,66)).convert('RGB')
        selected[position]=(item,sample)
    inventory,inventory_path=acquire.current_inventory(cancel)
    if inventory.get('failures'):raise ValueError('cache_candidates_incomplete')
    if len({e['name'] for e in inventory['items']})!=len(inventory['items']):raise ValueError('cache_candidates_incomplete')
    candidates={position:{} for position in positions}
    for entry in inventory['items']:
        acquire.cancelled(cancel);path=acquire.cache.candidate_path(inventory['root'],entry['name']);before=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(entry['size'],entry['mtime_ns']):raise ValueError('cache_candidate_changed')
        matcher=CellMatcher(hover_frames(path,cancel),edge=64,native=True)
        for position,cell in cells.items():
            acquire.cancelled(cancel);hits=matcher.match(cell)
            if hits:
                key=min(hits,key=lambda key:hits[key]['error'])
                candidates[position][entry['name']]=dict(hits[key],frame=key[0],paint=key[1])
        after=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('cache_candidate_changed')
    current,_=acquire.current_inventory(cancel)
    if current.get('directory_fingerprint')!=inventory.get('directory_fingerprint'):raise ValueError('cache_inventory_changed')
    acquire.cancelled(cancel)
    # No evidence is published for an interrupted search or changed source.
    for item,sample in selected.values():
        if sha(item['scan'])!=probe['scan_sha256']:raise ValueError('variant_scan_changed')
        if sha(sample['path'])!=sample['sha256']:raise ValueError('variant_sample_changed')
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f');evidence_by_position={}
    for position,(item,sample) in selected.items():
        path=acquire.ROOT/'private/T006/hover-candidates'/f'{stamp}-{position}.json'
        evidence={'item_id':item['id'],'scan':item['scan'],'scan_sha256':probe['scan_sha256'],
              'candidate_scope':'all_native_frames_at_observed_hover','native_raster_candidates_complete':True,
              'inventory':str(inventory_path),'inventory_sha256':sha(inventory_path),'candidates':candidates[position],
              'probe_sample':sample['path'],'probe_sample_sha256':sample['sha256']}
        save_json(path,evidence);item['candidate_evidence']=str(path);evidence_by_position[position]=evidence
    catalog.save(library,library_path)
    return evidence_by_position


def resolve(library_path,probe_path,cancel=None):
    library=catalog.read(library_path);probe=catalog.read(probe_path)
    observed={i['id']:i for i in probe['items']};results=[]
    folder=acquire.ROOT/'private/T006/variant-bindings'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    for item in library['clients']['qq']['items']:
        if item['id'] not in observed or not item.get('candidate_evidence'):continue
        acquire.cancelled(cancel);out={'id':item['id'],'status':'pending_confirmation'}
        try:
            evidence=catalog.read(item['candidate_evidence']);samples=observed[item['id']]['samples']
            if evidence['scan_sha256']!=probe['scan_sha256']:raise ValueError('variant_scan_changed')
            if not 1<=len(evidence['candidates'])<=12:raise ValueError('bounded_candidates_required')
            if len(evidence['candidates'])==1 and evidence['candidate_scope']!='all_native_frames_at_observed_hover':
                raise ValueError('single_candidate_requires_complete_hover_search')
            inventory=catalog.read(evidence['inventory'])
            entries={i['name']:i for i in inventory['items']}
            comparison={'item_id':item['id'],'candidates':list(evidence['candidates']),
                        'observations':[{'path':s['path'],'matches':{}} for s in samples]}
            for name in evidence['candidates']:
                entry=entries[name];path=acquire.cache.candidate_path(inventory['root'],name);before=path.stat()
                if (before.st_size,before.st_mtime_ns)!=(entry['size'],entry['mtime_ns']):raise ValueError('cache_candidate_changed')
                matcher=CellMatcher(hover_frames(path,cancel),edge=64,native=True)
                for sample,o in zip(samples,comparison['observations']):
                    if sha(sample['path'])!=sample['sha256']:raise ValueError('variant_sample_changed')
                    with Image.open(sample['path']) as image:hits=matcher.match(image.crop((2,2,66,66)))
                    if hits:
                        key=min(hits,key=lambda key:hits[key]['error'])
                        o['matches'][name]=dict(hits[key],frame=key[0],paint=key[1])
                after=path.stat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('cache_candidate_changed')
            target=folder/str(item['position']);target.mkdir(parents=True)
            try:name=winner(comparison)
            except ValueError as ambiguity:
                if str(ambiguity) not in ('animation_variant_not_unique','animation_variant_distinct_poses_missing') or len(evidence['candidates'])<2:raise
                # Preserve both originals as evidence. Never choose a static
                # first frame in place of a different animated candidate.
                comparison['equivalent_originals']={}
                for candidate in sorted(evidence['candidates']):
                    acquire.cancelled(cancel)
                    comparison['equivalent_originals'][candidate]=acquire.cache.copied_original(
                        inventory['root'],entries[candidate],target/'equivalent-candidates')
                name=winner(comparison)
            copied=acquire.cache.copied_original(inventory['root'],entries[name],target/'original')
            selection={'item_id':item['id'],'scan':item['scan'],'scan_sha256':sha(item['scan']),
                       'candidate_evidence':item['candidate_evidence'],'candidate_name':name,'probe':str(Path(probe_path).resolve())}
            save_json(target/'selection.json',selection);save_json(target/'copy.json',copied);save_json(target/'comparison.json',comparison)
            receipt=target/'receipt.json';register(target/'selection.json',target/'copy.json',target/'comparison.json',receipt)
            asset,_=acquire.prepare_asset(Path(copied['file']),'qq',acquire.ROOT/'private/T006/assets',native=True)
            attach_receipt(asset,receipt);catalog.attach_original(item,asset);target_readiness(item)
            if comparison.get('equivalent_originals'):item['content_equivalent_variants']=len(comparison['equivalent_originals'])
            item.pop('source_snapshot',None);item.pop('index_reason',None)
            out.update(status='ready',receipt=str(receipt),candidate=name)
        except Exception as exc:
            if str(exc)=='cancel_requested':raise
            out['reason']=str(exc)
            item['index_reason']=str(exc)
            item['reason']={'bounded_candidates_required':'预览与本地原件显示有差异，正在等待更明确的对应证据。',
                            'animation_variant_not_unique':'多个候选画面相近，尚未区分具体版本；其他项目可继续准备。',
                            'original_contents_not_equivalent':'相似候选的完整内容不同，不能当作重复合并。',
                            'animation_variant_distinct_poses_missing':'需要更多不同画面才能区分静态版与动图版。'}.get(str(exc),str(exc))
        results.append(out);catalog.save(library,library_path)
    save_json(folder/'result.json',{'results':results,'native_ui_calls':0,'messages_sent':0})
    return results
