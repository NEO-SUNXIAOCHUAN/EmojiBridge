"""Evidence receipts for selected client exports, never an all-favorites claim."""
import json
from datetime import datetime
from pathlib import Path
from .state import sha,save_json
from .paths import DATA_ROOT


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def register_save_as(file,client,selection,save_intent,verification,receipt):
    from .media import inspect
    file=Path(file).resolve();selection=Path(selection).resolve()
    save_intent=Path(save_intent).resolve();verification=Path(verification).resolve()
    selected=read(selection);saved=read(save_intent);verified=read(verification)
    metadata,_=inspect(file)
    if client not in ('qq','wechat') or selected.get('source_kind')!='personal_favorites_ui':
        raise ValueError('personal_favorite_selection_evidence_required')
    if Path(saved['destination']).resolve()!=file:
        raise ValueError('export_destination_mismatch')
    if saved.get('source_chain')!='selected_personal_favorite -> confirmed_self_chat_message -> Save As':
        raise ValueError('client_save_as_chain_required')
    if (verified.get('command')!='verify' or verified.get('target')!=client
            or verified.get('source_sha256')!=metadata['sha256']
            or verified.get('status') not in ('already_exists','desktop_confirmed')
            or not verified.get('collection_persisted')
            or len(verified.get('favorite_match_after',[]))!=1):
        raise ValueError('export_not_uniquely_verified_in_source_favorites')
    if metadata['frames']>1 and not verified.get('animation',{}).get('playback_confirmed'):
        raise ValueError('export_animation_not_verified_in_source')
    submit_path=selection.parent/'message-submit.json'
    submit=read(submit_path)
    binding=Path(submit['own_session_binding'])
    if not binding.is_absolute():binding=DATA_ROOT/binding
    evidence=[selection,save_intent,verification,selection.parent/'source-grid.png',selection.parent/'source-preview.png',
              selection.parent/'send-intent.json',submit_path,binding.resolve()]
    for path in evidence:
        if not path.is_file():raise ValueError('missing_source_evidence')
    result={'schema':'selected-client-export-v1','client':client,'client_version':verified['client_version'],
            'source_kind':'personal_favorites_ui','acquisition':'client_save_as_via_confirmed_self_chat',
            'file':str(file),'sha256':metadata['sha256'],'metadata':metadata,
            'complete':False,'scope':'one selected client-exported file; not the entire collection',
            'file_decode_complete':True,'upload_original_bytes_proven':False,
            'source_animation_sampling':verified.get('animation',{}).get('distinct_visual_frames',[]),
            'evidence':[{'path':str(path),'sha256':sha(path)} for path in evidence],
            'created':datetime.now().astimezone().isoformat()}
    save_json(receipt,result);return result


def validate_receipt(path,expected_sha):
    r=read(path)
    if r.get('schema')=='qq-appearance-original-v1':
        from .appearance_originals import validate
        return validate(r,expected_sha)
    if r.get('schema')=='qq-thumb-linked-original-v1':
        from .thumb_originals import validate
        return validate(r,expected_sha)
    if r.get('schema')=='qq-observed-variant-original-v1':
        from .variant_originals import validate
        return validate(r,expected_sha)
    if r.get('schema')=='qq-observed-original-v1':
        from .snapshot_originals import validate
        return validate(r,expected_sha)
    if r.get('schema')=='selected-personal-cache-export-v1':
        return validate_cache_receipt(r,expected_sha)
    if r.get('schema')=='authenticated-favorite-original-v1':
        return validate_authenticated_original(r,expected_sha)
    if r.get('schema')=='selected-favorite-index-export-v1':
        return validate_index_receipt(r,expected_sha)
    if (r.get('schema')!='selected-client-export-v1' or r.get('source_kind')!='personal_favorites_ui'
            or r.get('acquisition')!='client_save_as_via_confirmed_self_chat'
            or not r.get('file_decode_complete') or r.get('complete') is not False
            or r.get('sha256')!=expected_sha or sha(r['file'])!=expected_sha):
        raise ValueError('invalid_or_changed_client_export')
    if len(r.get('evidence',[]))<8:raise ValueError('missing_source_evidence')
    for evidence in r['evidence']:
        if sha(evidence['path'])!=evidence['sha256']:raise ValueError('export_evidence_changed')
    return r


def cache_evidence(selection,copy,verification):
    """Bind selected observation, exact cache bytes, and fresh favorites proof."""
    s=read(selection);c=read(copy);v=read(verification)
    if (s.get('source_kind')!='personal_favorites_ui' or s.get('candidate_count')!=1
            or s.get('item_id')!=s.get('selected',{}).get('id')
            or sha(s['scan'])!=s['scan_sha256'] or sha(s['page_image'])!=s['page_sha256']):
        raise ValueError('cache_selection_evidence_invalid')
    scan=read(s['scan']);matches=[i for i in scan.get('items',[]) if i['id']==s['item_id']]
    if (scan.get('schema')!='qq-favorite-observations-v1' or scan.get('source_kind')!='personal_favorites_ui'
            or len(matches)!=1 or any(matches[0][k]!=s['selected'][k] for k in ('page','position','rect'))
            or scan['pages'][matches[0]['page']]['sha256']!=s['page_sha256']):
        raise ValueError('cache_source_scan_changed')
    import hashlib
    if (c.get('schema')!='qq-personal-cache-original-v1' or not c.get('original_bytes_preserved')
            or c.get('complete_collection_proven') is not False or c.get('messages_sent')!=0
            or Path(c['cache_source']).name!=s['candidate_name'] or Path(s['candidate_name']).stem.lower()!=c['md5']
            or sha(c['file'])!=c['sha256'] or c['metadata']['sha256']!=c['sha256']
            or hashlib.md5(Path(c['file']).read_bytes()).hexdigest()!=c['md5']):
        raise ValueError('cache_original_evidence_invalid')
    if (v.get('command')!='verify' or v.get('target')!='qq' or v.get('status')!='already_exists'
            or v.get('source_sha256')!=c['sha256'] or v.get('selected_item_id')!=s['item_id']
            or not v.get('collection_persisted') or len(v.get('favorite_match_after',[]))!=1
            or v.get('messages_sent')!=0):raise ValueError('cache_source_favorite_not_verified')
    if c['metadata']['frames']>1 and not v.get('animation',{}).get('playback_confirmed'):
        raise ValueError('cache_animation_not_verified')
    return s,c,v


def register_cache_export(selection,copy,verification,receipt):
    from .qq_cache import validate_copy
    s,c,v=cache_evidence(selection,copy,verification);validate_copy(c)
    paths=[Path(selection),Path(copy),Path(verification),Path(s['scan']),Path(s['page_image']),
           Path(v['evidence'])/'favorites-before-reopen.png',Path(v['evidence'])/'favorites-after-reopen.png']
    paths.extend(Path(w['path']) for w in v.get('animation',{}).get('visual_witnesses',[]))
    r={'schema':'selected-personal-cache-export-v1','client':'qq','client_version':v['client_version'],
       'source_kind':'personal_favorites_ui','acquisition':'personal_ori_and_selected_favorite_ui',
       'file':c['file'],'sha256':c['sha256'],'metadata':c['metadata'],'selected_item_id':s['item_id'],
       'original_bytes_preserved':True,'file_decode_complete':True,'complete':False,'messages_sent':0,
       'scope':'one uniquely matched current UI favorite; cache directory is not a complete collection',
       'target_collection_verified':False,'evidence':[{'path':str(p.resolve()),'sha256':sha(p)} for p in paths],
       'created':datetime.now().astimezone().isoformat()}
    save_json(receipt,r);return r


def validate_cache_receipt(r,expected_sha):
    if (r.get('client')!='qq' or r.get('source_kind')!='personal_favorites_ui'
            or r.get('acquisition')!='personal_ori_and_selected_favorite_ui'
            or not r.get('original_bytes_preserved') or not r.get('file_decode_complete')
            or r.get('complete') is not False or r.get('messages_sent')!=0
            or r.get('sha256')!=expected_sha or sha(r['file'])!=expected_sha or len(r.get('evidence',[]))<7):
        raise ValueError('invalid_cache_export_receipt')
    for e in r['evidence']:
        if sha(e['path'])!=e['sha256']:raise ValueError('cache_export_evidence_changed')
    s,c,v=cache_evidence(*(e['path'] for e in r['evidence'][:3]))
    if (c['sha256']!=expected_sha or c['metadata']!=r['metadata'] or s['item_id']!=r['selected_item_id']
            or Path(c['file']).resolve()!=Path(r['file']).resolve()):raise ValueError('cache_receipt_binding_changed')
    return r


def register_authenticated_original(acquisition,receipt):
    """Index membership + digest-confirmed original, no invented source UI test."""
    from .media import inspect
    import hashlib
    acquisition=Path(acquisition).resolve();report=read(acquisition)
    entries=report.get('acquisitions',[])
    if len(entries)!=1:raise ValueError('one_index_original_required')
    item=entries[0];member=item.get('member',{});digest=member.get('md5')
    if (report.get('status')!='index_decrypted_and_integrity_verified' or not report.get('snapshot_current_consistent')
            or member.get('membership_table')!='kFavEmoticonOrderTable'
            or sum(m.get('md5')==digest and m.get('membership_table')=='kFavEmoticonOrderTable' for m in report.get('index_members',[]))!=1):
        raise ValueError('authenticated_current_favorite_membership_required')
    if item.get('status')!='original_verified' or not item.get('md5_matches_favorite') or item.get('url_field')!='cdn_url':
        raise ValueError('digest_verified_original_required')
    metadata,_=inspect(Path(item['path']))
    if metadata['sha256']!=item['metadata']['sha256'] or hashlib.md5(Path(item['path']).read_bytes()).hexdigest()!=digest:
        raise ValueError('favorite_original_changed')
    r={'schema':'authenticated-favorite-original-v1','client':'wechat','client_version':report['client_version'],
       'source_kind':'authenticated_local_personal_favorite_index','acquisition':'favorite_index_cdn_md5_verified',
       'file':item['path'],'sha256':metadata['sha256'],'metadata':metadata,'member':member,
       'file_decode_complete':True,'md5_matches_favorite':True,'complete':False,
       'scope':'one current authenticated local favorite member, not cloud completeness',
       'source_ui_verified':False,'source_playback_verified':False,'target_collection_verified':False,
       'evidence':[{'path':str(acquisition),'sha256':sha(acquisition)}],
       'created':datetime.now().astimezone().isoformat()}
    save_json(receipt,r);return r


def validate_authenticated_original(r,expected_sha):
    import hashlib
    if (r.get('client')!='wechat' or r.get('source_kind')!='authenticated_local_personal_favorite_index'
            or r.get('acquisition')!='favorite_index_cdn_md5_verified' or r.get('sha256')!=expected_sha
            or not r.get('file_decode_complete') or not r.get('md5_matches_favorite') or r.get('complete') is not False
            or r.get('member',{}).get('membership_table')!='kFavEmoticonOrderTable'
            or sha(r['file'])!=expected_sha or hashlib.md5(Path(r['file']).read_bytes()).hexdigest()!=r['member']['md5']):
        raise ValueError('invalid_authenticated_favorite_original')
    if len(r.get('evidence',[]))!=1:raise ValueError('missing_index_evidence')
    proof=r['evidence'][0]
    if sha(proof['path'])!=proof['sha256']:raise ValueError('index_evidence_changed')
    report=read(proof['path'])
    if (report.get('status')!='index_decrypted_and_integrity_verified' or not report.get('snapshot_current_consistent')
            or sum(m.get('md5')==r['member']['md5'] and m.get('membership_table')=='kFavEmoticonOrderTable' for m in report.get('index_members',[]))!=1):
        raise ValueError('authenticated_current_favorite_membership_required')
    return r


def register_index_export(acquisition,ordinal,verification,receipt):
    from .media import inspect
    acquisition=Path(acquisition).resolve();verification=Path(verification).resolve()
    acquired=read(acquisition);verified=read(verification)
    matches=[a for a in acquired.get('acquisitions',[]) if a['member']['ordinal']==ordinal]
    if len(matches)!=1 or acquired.get('status')!='index_decrypted_and_integrity_verified' or not acquired.get('snapshot_current_consistent'):
        raise ValueError('verified_favorite_index_snapshot_required')
    item=matches[0]
    if item.get('status')!='original_verified' or not item.get('md5_matches_favorite') or item.get('url_field')!='cdn_url':
        raise ValueError('original_matching_favorite_digest_required')
    metadata,_=inspect(Path(item['path']))
    if metadata['sha256']!=item['metadata']['sha256']:raise ValueError('original_changed')
    if (verified.get('command')!='verify' or verified.get('target')!='wechat'
            or verified.get('source_sha256')!=metadata['sha256']
            or verified.get('status') not in ('already_exists','desktop_confirmed')
            or not verified.get('collection_persisted') or len(verified.get('favorite_match_after',[]))!=1):
        raise ValueError('export_not_uniquely_verified_in_source_favorites')
    if metadata['frames']>1 and not verified.get('animation',{}).get('playback_confirmed'):
        raise ValueError('export_animation_not_verified_in_source')
    evidence=[acquisition,verification,Path(verified['evidence'])/'favorites-after-reopen.png']
    result={'schema':'selected-favorite-index-export-v1','client':'wechat','client_version':verified['client_version'],
            'source_kind':'personal_favorite_index_and_ui','acquisition':'favorite_index_cdn_md5_verified',
            'file':item['path'],'sha256':metadata['sha256'],'metadata':metadata,'member':item['member'],
            'complete':False,'scope':'one indexed and UI-verified favorite, not full-library originals',
            'file_decode_complete':True,'upload_original_bytes_proven':False,'md5_matches_favorite':True,
            'evidence':[{'path':str(p),'sha256':sha(p)} for p in evidence],
            'created':datetime.now().astimezone().isoformat()}
    save_json(receipt,result);return result


def validate_index_receipt(r,expected_sha):
    import hashlib
    if (r.get('client')!='wechat' or r.get('source_kind')!='personal_favorite_index_and_ui'
            or r.get('acquisition')!='favorite_index_cdn_md5_verified' or not r.get('md5_matches_favorite')
            or r.get('member',{}).get('membership_table')!='kFavEmoticonOrderTable'
            or not r.get('file_decode_complete') or r.get('complete') is not False
            or r.get('sha256')!=expected_sha or sha(r['file'])!=expected_sha):
        raise ValueError('invalid_or_changed_index_export')
    if hashlib.md5(Path(r['file']).read_bytes()).hexdigest()!=r['member']['md5']:
        raise ValueError('favorite_md5_changed')
    if len(r.get('evidence',[]))!=3:raise ValueError('missing_source_evidence')
    for evidence in r['evidence']:
        if sha(evidence['path'])!=evidence['sha256']:raise ValueError('export_evidence_changed')
    return r


def attach_receipt(asset_path,receipt_path):
    from .media import load_asset
    a=load_asset(asset_path);path=Path(receipt_path).resolve()
    validate_receipt(path,a['source_sha256'])
    proof={'receipt':str(path),'sha256':sha(path)}
    proofs=provenance_proofs(a)
    if proof in proofs:return
    # Same bytes may have independently verified native origins in both
    # clients. Retain every receipt; crossing back must not replace the native
    # collection's credential with the other client's credential.
    if not proofs:a['source_provenance']=proof
    else:a['source_provenances']=[*proofs,proof]
    save_json(asset_path,a)


def provenance_proofs(a):
    proofs=[]
    for proof in [a.get('source_provenance'),*a.get('source_provenances',[])]:
        if proof and proof not in proofs:proofs.append(proof)
    return proofs


def origin_for_asset(a):
    proofs=provenance_proofs(a)
    if not proofs:return {'original_origin':'retained_user_import_asset; visually bound to this personal-favorites view','exported_from_client':False}
    validated=[]
    for proof in proofs:
        if sha(proof['receipt'])!=proof['sha256']:raise ValueError('export_receipt_changed')
        validated.append((proof,validate_receipt(proof['receipt'],a['source_sha256'])))
    # Validate all receipts before choosing one; a broken proof never silently
    # falls back to another provenance.
    proof,r=next((p,r) for p,r in validated if r['client']==a['target']) if any(r['client']==a['target'] for _,r in validated) else validated[0]
    same=r['client']==a['target']
    method='favorite_index_original_from_this_collection' if r['schema'] in ('selected-favorite-index-export-v1','authenticated-favorite-original-v1') else 'client_save_as_from_this_collection'
    if r['schema'] in ('selected-personal-cache-export-v1','qq-observed-original-v1','qq-observed-variant-original-v1','qq-thumb-linked-original-v1'):method='personal_cache_original_from_this_collection'
    if r['schema']=='qq-appearance-original-v1':method='personal_cache_appearance_representative'
    return {'original_origin':method if same else 'retained_export_from_other_client',
            'exported_from_client':same,'export_source_client':r['client'],'original_provenance':proof['receipt'],
            'matching_basis':r.get('matching_basis','verified_correspondence')}
