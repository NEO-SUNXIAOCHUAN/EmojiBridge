"""Practical appearance matching, explicitly not exact historical identity."""
from datetime import datetime
from pathlib import Path
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
import json,math
from PIL import Image
from .paging import full_cell
from .state import sha,save_json
from .originals import read
from .qq_cache import validate_copy

POLICY='appearance-representative-v2'
LEGACY_POLICY='appearance-representative-v1'
SCHEMA='qq-appearance-original-v1'
_evidence_cache=ContextVar('appearance_evidence_cache',default=None)


@contextmanager
def evidence_session():
    """Only reuse parsed JSON within one preparation, never file validation."""
    if _evidence_cache.get() is not None:
        yield
        return
    token=_evidence_cache.set(OrderedDict())
    try:yield
    finally:_evidence_cache.reset(token)


def _read_verified_evidence(evidence):
    # validate() has just hashed every evidence file, including cache hits.
    # Consumers below only read these objects; mutable manifests use read().
    cache=_evidence_cache.get();key=evidence['sha256']
    if cache is not None and key in cache:
        cache.move_to_end(key);return cache[key][0]
    raw=Path(evidence['path']).read_bytes()
    import hashlib
    if hashlib.sha256(raw).hexdigest()!=key:raise ValueError('appearance_evidence_changed')
    value=json.loads(raw)
    if cache is not None and len(raw)<=8*1024*1024:
        cache[key]=(value,len(raw))
        while len(cache)>16 or sum(v[1] for v in cache.values())>16*1024*1024:
            cache.popitem(last=False)
    return value


def read_snapshot(path):
    """Read-only reuse; no cached parse without hashing current file bytes."""
    if _evidence_cache.get() is None:return read(path)
    return _read_verified_evidence({'path':str(path),'sha256':sha(path)})


def shortlist(hits):
    ranked=sorted(hits,key=lambda name:(hits[name]['error'],name))
    if not ranked:raise ValueError('appearance_no_candidate')
    for h in hits.values():
        if (not math.isfinite(h['error']) or not math.isfinite(h['smoothed_error'])
                or not 0<=h['error']<.10 or not 0<=h['smoothed_error']<.075
                or h.get('profile')!='qq-appearance-v1'):
            raise ValueError('appearance_invalid_score')
    best=hits[ranked[0]]['error']
    group=[name for name in ranked if hits[name]['error']<=best+.012]
    other=[name for name in ranked if name not in group]
    if other and hits[other[0]]['error']-hits[group[-1]]['error']<.015:
        raise ValueError('appearance_candidates_too_close')
    return group


def choose(hits,copies,comparison,*,legacy=False):
    group=shortlist(hits)
    if set(copies)!=set(group):raise ValueError('appearance_candidate_metadata_missing')
    if len(group)>1:
        if set(comparison)!=set(group) or any(not math.isfinite(v) or not 0<=v<.04 for v in comparison.values()):
            raise ValueError('appearance_candidates_visibly_different')
        animated={copies[name]['metadata']['frames']>1 for name in group}
        if not legacy and len(animated)>1:raise ValueError('appearance_static_animation_ambiguous')
    # Size is a representative preference, never evidence of byte equivalence.
    def key(name):
        m=copies[name]['metadata'];w,h=m['oriented_size']
        return (m['frames']>1,w*h,m['bytes'],name)
    return max(group,key=key)


def validate(r,expected):
    if (r.get('schema')!=SCHEMA or r.get('policy') not in (POLICY,LEGACY_POLICY) or r.get('client')!='qq'
            or r.get('sha256')!=expected or sha(r['file'])!=expected
            or r.get('exact_original_identity_proven') is not False
            or r.get('matching_basis')!='appearance' or r.get('complete') is not False
            or r.get('messages_sent')!=0 or not r.get('file_decode_complete')):
        raise ValueError('appearance_receipt_invalid')
    evidence=r.get('evidence',[])
    if len(evidence)!=6:raise ValueError('appearance_evidence_incomplete')
    for e in evidence:
        if sha(e['path'])!=e['sha256']:raise ValueError('appearance_evidence_changed')
    s,copies,search,scan,inventory=(_read_verified_evidence(evidence[n]) for n in (0,1,2,3,5))
    unreadable=len(inventory.get('failures',[]))
    if (r.get('unreadable_cache_candidates',0)!=unreadable
            or (unreadable and r.get('candidate_inventory_complete') is not False)):
        raise ValueError('appearance_inventory_scope_changed')
    if (s.get('item_id')!=r.get('selected_item_id') or s.get('policy')!=r['policy']
            or s['scan_sha256']!=evidence[3]['sha256'] or s['page_sha256']!=evidence[4]['sha256']
            or Path(s['scan']).resolve()!=Path(evidence[3]['path']).resolve()
            or scan.get('schema')!='qq-favorite-observations-v1' or scan.get('source_kind')!='personal_favorites_ui'
            or search.get('inventory_sha256')!=evidence[5]['sha256']
            or search.get('policy')!=r['policy'] or search.get('scope')!='cached_first_frame_appearance_candidates'):
        raise ValueError('appearance_source_binding_invalid')
    found=[i for i in scan['items'] if i['id']==s['item_id']]
    if len(found)!=1 or any(found[0][k]!=s['selected'][k] for k in ('page','position','rect')):
        raise ValueError('appearance_selection_changed')
    page=scan['pages'][found[0]['page']]
    if (page['sha256']!=evidence[4]['sha256']
            or Path(page['image']).resolve()!=Path(evidence[4]['path']).resolve()):
        raise ValueError('appearance_observation_changed')
    with Image.open(page['image']) as image:
        if not full_cell(image,found[0]['rect']):raise ValueError('appearance_observation_changed')
    hits=search['candidates'][s['item_id']]
    if r['policy']==POLICY and any(not 0<=h.get('max_patch_error',float('inf'))<=.12 for h in hits.values()):
        raise ValueError('appearance_local_difference_unchecked')
    name=choose(hits,copies,s['comparison'],legacy=r['policy']==LEGACY_POLICY)
    if name!=s['candidate_name']:raise ValueError('appearance_selection_policy_changed')
    chosen=copies[name];validate_copy(chosen)
    entry=next((i for i in inventory['items'] if i['name']==name),None)
    if (not entry or Path(chosen['cache_source']).resolve().parent!=Path(inventory['root']).resolve()
            or Path(chosen['cache_source']).name!=name or chosen['sha256']!=expected
            or chosen['metadata']!=r['metadata'] or Path(chosen['file']).resolve()!=Path(r['file']).resolve()):
        raise ValueError('appearance_original_changed')
    return r


def register(selection,copies,search,inventory,receipt):
    s=read(selection);c=read(copies)[s['candidate_name']]
    unreadable=len(read_snapshot(inventory).get('failures',[]))
    paths=[selection,copies,search,s['scan'],s['page_image'],inventory]
    r=dict(schema=SCHEMA,policy=POLICY,client='qq',source_kind='personal_favorites_snapshot',
           selected_item_id=s['item_id'],file=c['file'],sha256=c['sha256'],metadata=c['metadata'],
           matching_basis='appearance',exact_original_identity_proven=False,
           original_bytes_preserved=True,file_decode_complete=True,complete=False,messages_sent=0,
           source_playback_verified=False,current_membership_rechecked=False,
           unreadable_cache_candidates=unreadable,candidate_inventory_complete=not unreadable,
           scope='appearance-selected intact Ori representative; exact historic variant not proven',
           created=datetime.now().astimezone().isoformat(),
           evidence=[dict(path=str(Path(p).resolve()),sha256=sha(p)) for p in paths])
    validate(r,c['sha256']);save_json(receipt,r);return r
