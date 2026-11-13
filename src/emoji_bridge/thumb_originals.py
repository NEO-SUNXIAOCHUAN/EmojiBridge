"""Evidence for a static favorite -> actual personal Thumb -> intact Ori chain."""
from pathlib import Path
from datetime import datetime
from PIL import Image
from .originals import read
from .state import sha,save_json
from .snapshot_matching import CellMatcher
from .qq_thumbnails import static_correspondence,frames
from .qq_cache import validate_copy


def validate(r,expected):
    if (r.get('schema')!='qq-thumb-linked-original-v1' or r.get('sha256')!=expected
            or sha(r['file'])!=expected or r.get('client')!='qq' or r.get('complete') is not False
            or not r.get('file_decode_complete') or r.get('messages_sent')!=0):
        raise ValueError('thumbnail_receipt_invalid')
    evidence=r.get('evidence',[])
    for e in evidence:
        if sha(e['path'])!=e['sha256']:raise ValueError('thumbnail_evidence_changed')
    if len(evidence)!=8:raise ValueError('thumbnail_evidence_incomplete')
    selection,copy,search,prior,inventory=(read(e['path']) for e in evidence[:5])
    thumb=Path(evidence[5]['path']);scan=read(evidence[6]['path']);page_image=Path(evidence[7]['path'])
    validate_copy(copy)
    ident=r['selected_item_id'];hits=search.get('candidates',{}).get(ident,{})
    found=[i for i in scan['items'] if i['id']==ident]
    if (scan.get('schema')!='qq-favorite-observations-v1' or scan.get('source_kind')!='personal_favorites_ui'
            or len(found)!=1 or prior.get('item_id')!=ident or selection.get('item_id')!=ident
            or prior.get('candidates')!={} or not prior.get('native_raster_candidates_complete')
            or prior.get('candidate_scope') not in ('all_gif_frames_and_other_first_frames','all_native_frames_at_observed_hover')
            or prior.get('scan_sha256')!=evidence[6]['sha256'] or prior.get('inventory_sha256')!=evidence[4]['sha256']
            or Path(prior['scan']).resolve()!=Path(evidence[6]['path']).resolve()
            or Path(prior['inventory']).resolve()!=Path(evidence[4]['path']).resolve()
            or len(hits)!=1 or not search.get('complete_candidates') or search.get('failures')
            or search.get('scope')!='all_immediate_personal_emoji_Thumb_full_frames'
            or search.get('candidate_count',0)<1 or inventory.get('failures')
            or copy['sha256']!=expected or copy['metadata']!=r['metadata']
            or Path(copy['file']).resolve()!=Path(r['file']).resolve()):
        raise ValueError('thumbnail_binding_invalid')
    name=next(iter(hits));md5=Path(name).stem.lower()
    candidates=[i for i in inventory['items'] if Path(i['name']).stem.lower()==md5]
    if (len(candidates)!=1 or candidates[0]['name']!=Path(copy['cache_source']).name or md5!=copy['md5']
            or selection.get('thumbnail_name')!=name or hits[name]['thumbnail_sha256']!=sha(thumb)
            or Path(search['root']).resolve()!=Path(copy['cache_source']).resolve().parent.parent/'Thumb'
            or Path(inventory['root']).resolve()!=Path(copy['cache_source']).resolve().parent):
        raise ValueError('thumbnail_file_identity_mismatch')
    item=found[0];page=scan['pages'][item['page']]
    if (item['rect'][3]>279 or Path(page['image']).resolve()!=page_image.resolve()
            or page['sha256']!=sha(page_image)):
        raise ValueError('thumbnail_observation_changed')
    with Image.open(page_image) as image:cell=image.crop(item['rect'])
    matched=CellMatcher(frames(thumb.read_bytes()),native=True).match(cell)
    frame=hits[name]['frame']
    if frame not in matched or any(matched[frame][k]!=hits[name].get(k) for k in matched[frame]):
        raise ValueError('thumbnail_observation_mismatch')
    static_correspondence(copy['file'],thumb)
    return r


def register(selection,copy,search,prior,inventory,thumbnail,scan,page,receipt):
    c=read(copy);s=read(selection)
    paths=[selection,copy,search,prior,inventory,thumbnail,scan,page]
    r=dict(schema='qq-thumb-linked-original-v1',client='qq',source_kind='personal_favorites_snapshot',
           selected_item_id=s['item_id'],file=c['file'],sha256=c['sha256'],metadata=c['metadata'],
           original_bytes_preserved=True,file_decode_complete=True,complete=False,messages_sent=0,
           source_playback_verified=False,current_membership_rechecked=False,
           scope='one static observed favorite; complete Ori retained, Thumb used only for correspondence',
           created=datetime.now().astimezone().isoformat(),
           evidence=[dict(path=str(Path(p).resolve()),sha256=sha(p)) for p in paths])
    validate(r,c['sha256']);save_json(receipt,r);return r
