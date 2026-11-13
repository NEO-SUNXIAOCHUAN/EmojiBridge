"""Original identity narrowed by multiple recorded poses of one QQ favorite."""
from pathlib import Path
from datetime import datetime
import numpy as np
from PIL import Image
from .state import sha,save_json
from .originals import read
from .snapshot_matching import accepted


def equivalent_winner(comparison):
    """Different encodings may represent exactly the same full media.

    Small preview similarity is never enough: re-decode every copied candidate,
    including ALL frames, timing, orientation and embedded colour profile.
    Return a deterministic intact encoding, not a synthesized first frame.
    """
    from .media import inspect
    from .qq_cache import validate_copy
    copies=comparison.get('equivalent_originals',{})
    names=set(comparison['candidates'])
    if not 2<=len(names)<=12 or set(copies)!=names:raise ValueError('content_equivalence_incomplete')
    signatures=[]
    for name in sorted(names):
        record=copies[name];validate_copy(record)
        if Path(record['cache_source']).name!=name:raise ValueError('content_equivalence_wrong_candidate')
        meta,_=inspect(Path(record['file']))
        if meta!=record['metadata']:raise ValueError('content_equivalence_metadata_changed')
        with Image.open(record['file']) as image:
            colour=(image.info.get('icc_profile'),image.info.get('gamma'),image.info.get('srgb'))
        signatures.append((meta['oriented_size'],meta['frame_pixel_hashes'],
                           meta['durations_ms'] if meta['frames']>1 else [],
                           meta['loop'] if meta['frames']>1 else None,colour))
    if any(s!=signatures[0] for s in signatures[1:]):raise ValueError('original_contents_not_equivalent')
    return sorted(names)[0]


def winner(comparison):
    observations=comparison['observations'];candidates=set(comparison['candidates'])
    possible=set(candidates);used=[]
    for o in observations:
        passing={name for name,hit in o['matches'].items()
                 if name in candidates and accepted(hit['error'],hit['smoothed_error'])}
        if passing:possible.intersection_update(passing);used.append(o)
    if len(used)<3:raise ValueError('animation_variant_not_unique')
    if possible==candidates and len(possible)>1 and comparison.get('equivalent_originals'):
        return equivalent_winner(comparison)
    if len(possible)!=1:raise ValueError('animation_variant_not_unique')
    # Several encodings of the same pose, or repeated idle samples, cannot
    # establish animation identity. Require actual visible change as well.
    arrays=[np.asarray(Image.open(o['path']).convert('RGB'),dtype=np.float32) for o in used]
    if len(candidates)>1 and not any(np.abs(a-b).mean()/255>.018 for n,a in enumerate(arrays) for b in arrays[n+1:]):
        raise ValueError('animation_variant_distinct_poses_missing')
    return next(iter(possible))


def validate(record,expected):
    r=record
    if (r.get('schema')!='qq-observed-variant-original-v1' or r.get('client')!='qq'
            or r.get('sha256')!=expected or sha(r['file'])!=expected or r.get('complete') is not False
            or not r.get('file_decode_complete') or r.get('messages_sent')!=0 or len(r.get('evidence',[]))<7):
        raise ValueError('variant_receipt_invalid')
    for e in r['evidence']:
        if sha(e['path'])!=e['sha256']:raise ValueError('variant_evidence_changed')
    selection,copied,comparison=(read(e['path']) for e in r['evidence'][:3])
    from .qq_cache import validate_copy
    validate_copy(copied)
    candidates=read(selection['candidate_evidence']);scan=read(selection['scan']);probe=read(selection['probe'])
    ident=r['selected_item_id'];observed=[i for i in probe['items'] if i['id']==ident]
    original=[i for i in scan['items'] if i['id']==ident]
    if (selection['item_id']!=ident or len(observed)!=1 or len(original)!=1
            or candidates['item_id']!=ident or candidates['scan_sha256']!=sha(selection['scan'])
            or probe['scan_sha256']!=sha(selection['scan'])
            or candidates.get('candidate_scope') not in ('all_gif_frames_and_other_first_frames','all_native_frames_at_observed_hover')
            or not candidates.get('native_raster_candidates_complete')
            or candidates['inventory_sha256']!=sha(candidates['inventory'])
            or set(candidates['candidates'])!=set(comparison['candidates'])
            or comparison['item_id']!=ident or winner(comparison)!=selection['candidate_name']
            or copied['sha256']!=expected or copied['metadata']!=r['metadata']
            or Path(copied['cache_source']).name!=selection['candidate_name']
            or Path(copied['file']).resolve()!=Path(r['file']).resolve()):
        raise ValueError('variant_binding_invalid')
    observed=observed[0];original=original[0]
    if observed['position']!=original['position']:raise ValueError('variant_selection_changed')
    samples={str(Path(o['path']).resolve()):o['sha256'] for o in observed['samples']}
    if candidates.get('candidate_scope')=='all_native_frames_at_observed_hover':
        if samples.get(str(Path(candidates['probe_sample']).resolve()))!=candidates.get('probe_sample_sha256'):
            raise ValueError('variant_candidate_sample_unbound')
    if (len(comparison['observations'])!=len(samples)
            or {str(Path(o['path']).resolve()) for o in comparison['observations']}!=set(samples)):
        raise ValueError('variant_samples_incomplete')
    for o in comparison['observations']:
        if samples.get(str(Path(o['path']).resolve()))!=sha(o['path']):raise ValueError('variant_sample_changed')
    from .paging import difference
    page=scan['pages'][original['page']]
    if sha(page['image'])!=page['sha256']:raise ValueError('variant_scan_changed')
    with Image.open(page['image']) as saved,Image.open(observed['idle']) as idle:
        if difference(saved.crop(original['rect']),idle)>.025:raise ValueError('variant_idle_not_same_favorite')
    return r


def register(selection,copy,comparison,destination):
    s,c,m=read(selection),read(copy),read(comparison);probe=read(s['probe'])
    observed=next(i for i in probe['items'] if i['id']==s['item_id'])
    paths=[selection,copy,comparison,s['candidate_evidence'],s['scan'],s['probe'],observed['idle']]
    paths.extend(o['path'] for o in observed['samples'])
    r={'schema':'qq-observed-variant-original-v1','client':'qq','source_kind':'personal_favorites_snapshot',
       'selected_item_id':s['item_id'],'file':c['file'],'sha256':c['sha256'],'metadata':c['metadata'],
       'complete':False,'file_decode_complete':True,'original_bytes_preserved':True,'messages_sent':0,
       'scope':'one observed favorite variant; not collection completeness or timing verification',
       'created':datetime.now().astimezone().isoformat(),
       'evidence':[{'path':str(Path(p).resolve()),'sha256':sha(p)} for p in paths]}
    if m.get('equivalent_originals'):
        r['content_identity']='all_candidate_pixels_and_animation_timing_exactly_equivalent'
        r['encoding_identity']='deterministic_intact_candidate; exact originally-favorited encoding unknown'
    validate(r,c['sha256']);save_json(destination,r);return r
