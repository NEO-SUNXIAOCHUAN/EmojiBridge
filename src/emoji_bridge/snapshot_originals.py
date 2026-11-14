"""A full original bound to a recorded favorite view; no live/playback claim."""
from datetime import datetime
from pathlib import Path
import hashlib
from .state import sha,save_json
from .originals import read
from .snapshot_matching import PROFILE,LEGACY_PROFILE,NATIVE_PROFILE,BACKGROUNDS,accepted


def validate(record, expected):
    r=record
    if (r.get('schema')!='qq-observed-original-v1' or r.get('client')!='qq'
            or r.get('source_kind')!='personal_favorites_snapshot'
            or r.get('sha256')!=expected or sha(r['file'])!=expected
            or not r.get('file_decode_complete') or r.get('complete') is not False
            or r.get('source_playback_verified') is not False or len(r.get('evidence',[]))<4):
        raise ValueError('invalid_observed_original')
    for e in r['evidence']:
        if sha(e['path'])!=e['sha256']:raise ValueError('observed_original_evidence_changed')
    s,c,m=(read(e['path']) for e in r['evidence'][:3])
    profile=m.get('profile')
    if profile is None:
        matching_ok=m.get('error',1)<.025
    else:
        lead=s.get('candidate_match',{})
        matching_ok=(profile in (PROFILE,LEGACY_PROFILE,NATIVE_PROFILE) and lead.get('profile')==profile
            and accepted(m.get('error',1),m.get('smoothed_error',1))
            and accepted(lead.get('error',1),lead.get('smoothed_error',1)))
        if profile in (PROFILE,NATIVE_PROFILE):
            matching_ok=matching_ok and tuple(m.get('background',())) in BACKGROUNDS and tuple(lead.get('background',())) in BACKGROUNDS
            matching_ok=matching_ok and s.get('candidate_scope')=='all_gif_frames_and_other_first_frames'
        if profile==NATIVE_PROFILE:
            matching_ok=matching_ok and s.get('native_raster_candidates_complete') is True
            matching_ok=matching_ok and m.get('resampler') in ('BOX','LANCZOS') and lead.get('resampler') in ('BOX','LANCZOS')
    if (s['item_id']!=r['selected_item_id'] or s.get('candidate_count')!=1
            or s.get('candidate_match',{}).get('kind')!='full_saved_cell'
            or s['scan_sha256']!=sha(s['scan']) or s['page_sha256']!=sha(s['page_image'])
            or c['sha256']!=expected or c['metadata']!=r['metadata']
            or not c.get('original_bytes_preserved') or not c.get('cache_stat_unchanged')
            or Path(c['file']).resolve()!=Path(r['file']).resolve()
            or hashlib.md5(Path(r['file']).read_bytes()).hexdigest()!=c['md5']
            or Path(s['candidate_name']).stem.lower()!=c['md5']
            or m.get('item_id')!=s['item_id'] or m.get('source_sha256')!=expected
            or m.get('match_count')!=1 or not matching_ok
            or m.get('scope')!='recorded_favorite_view_full_original'):
        raise ValueError('observed_original_binding_invalid')
    scan=read(s['scan']);items=[i for i in scan['items'] if i['id']==s['item_id']]
    if (scan.get('source_kind')!='personal_favorites_ui' or len(items)!=1
            or any(items[0][k]!=s['selected'][k] for k in ('page','position','rect'))
            ):raise ValueError('observed_favorite_identity_invalid')
    from PIL import Image
    from .paging import full_cell
    with Image.open(s['page_image']) as image:
        if not full_cell(image,items[0]['rect']):raise ValueError('observed_favorite_identity_invalid')
    return r


def register(selection, copy, matching, receipt):
    from .qq_cache import validate_copy
    s,c,m=read(selection),read(copy),read(matching);validate_copy(c)
    paths=[selection,copy,matching,s['scan'],s['page_image']]
    r={'schema':'qq-observed-original-v1','client':'qq','source_kind':'personal_favorites_snapshot',
       'selected_item_id':s['item_id'],'file':c['file'],'sha256':c['sha256'],'metadata':c['metadata'],
       'original_bytes_preserved':True,'file_decode_complete':True,'complete':False,
       'source_playback_verified':False,'current_membership_rechecked':False,'messages_sent':0,
       'scope':'one recorded favorite matched to complete Ori bytes; candidate scope: '+s.get('candidate_scope','first-frame cache leads'),
       'created':datetime.now().astimezone().isoformat(),
       'evidence':[{'path':str(Path(p).resolve()),'sha256':sha(p)} for p in paths]}
    validate(r,c['sha256']);save_json(receipt,r);return r
