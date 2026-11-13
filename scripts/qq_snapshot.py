"""Reuse proven originals from a dated QQ favorites snapshot, never live membership.

The saved receipt binds a particular observation to immutable original bytes.
Cache directory changes alone cannot grant this authority. Process-local proof
tokens are still new, cancellable and single-use on every queue run.
"""
from pathlib import Path
from emoji_bridge import catalog
from emoji_bridge.media import load_asset
from emoji_bridge.originals import origin_for_asset, validate_receipt, provenance_proofs
from emoji_bridge.state import sha, save_json
import qq_cache_acquire as acquire


def verification_valid(v, item, asset):
    if (v.get('target') != 'qq' or v.get('command') != 'verify'
            or v.get('status') != 'already_exists' or v.get('messages_sent') != 0
            or v.get('selected_item_id') != item['id']
            or v.get('source_sha256') != asset['source_sha256']
            or not v.get('collection_persisted') or len(v.get('favorite_match_after', [])) != 1):
        raise ValueError('snapshot_favorite_binding_invalid')
    if asset['original_metadata']['frames'] > 1 and not v.get('animation', {}).get('playback_confirmed'):
        raise ValueError('snapshot_source_animation_unproven')


def lookup(item):
    """Return a saved source proof or None when this observation is not bound.

    Invalid files/evidence raise; they never silently fall back to cache leads.
    A new scan ID needs a new binding, even if the ordinal happens to match.
    """
    if item.get('original_state') != 'ready' or not item.get('asset'):
        return None
    acquire.context(item)
    asset = load_asset(item['asset'])
    origin = origin_for_asset(asset)
    if asset['target'] != 'qq' or not origin.get('exported_from_client') or origin.get('export_source_client') != 'qq':
        return None
    receipt_path = origin['original_provenance']
    for proof in provenance_proofs(asset):
        candidate=catalog.read(proof['receipt'])
        if candidate.get('schema')=='qq-appearance-original-v1':
            from emoji_bridge.appearance_originals import POLICY
            if candidate.get('policy')!=POLICY:continue
        if candidate.get('client')=='qq' and candidate.get('selected_item_id')==item['id']:
            receipt_path=proof['receipt'];break
    receipt = validate_receipt(receipt_path, asset['source_sha256'])
    if receipt.get('schema')=='qq-appearance-original-v1':
        from emoji_bridge.appearance_originals import POLICY
        if receipt.get('policy')!=POLICY:return None
    binding = item.get('source_snapshot')
    if binding:
        if sha(binding['path']) != binding['sha256']:
            raise ValueError('snapshot_binding_changed')
        bound = catalog.read(binding['path'])
        if (bound.get('schema') != 'qq-saved-favorite-binding-v1'
                or bound.get('item_id') != item['id'] or bound.get('source_sha256') != asset['source_sha256']
                or Path(bound['scan']).resolve() != Path(item['scan']).resolve()
                or sha(item['scan']) != bound['scan_sha256']):
            raise ValueError('snapshot_selection_changed')
        if len(bound.get('evidence', [])) < 4:
            raise ValueError('snapshot_evidence_missing')
        for e in bound['evidence']:
            if sha(e['path']) != e['sha256']:
                raise ValueError('snapshot_evidence_changed')
        verification_valid(catalog.read(bound['verification']), item, asset)
        observed_at = bound['verified_at']
    else:
        # Existing cache-export receipts already contain the exact selected ID,
        # scan digest and two-view proof, so no migration scan is necessary.
        if receipt.get('schema') not in ('selected-personal-cache-export-v1','qq-observed-original-v1','qq-observed-variant-original-v1','qq-thumb-linked-original-v1','qq-appearance-original-v1') or receipt.get('selected_item_id') != item['id']:
            return None
        selected = catalog.read(receipt['evidence'][0]['path'])
        if receipt['schema']=='qq-thumb-linked-original-v1':
            selected={'scan':receipt['evidence'][6]['path'],'scan_sha256':receipt['evidence'][6]['sha256']}
        if (Path(selected['scan']).resolve() != Path(item['scan']).resolve()
                or selected['scan_sha256'] != sha(item['scan'])):
            raise ValueError('snapshot_selection_changed')
        observed_at = receipt['created']
    appearance=receipt.get('schema')=='qq-appearance-original-v1'
    return {'status': 'already_exists', 'target': 'qq', 'command': 'verify',
            'selected_item_id': item['id'], 'source_sha256': asset['source_sha256'],
            'asset': item['asset'], 'receipt': receipt_path,
            'membership_scope': 'saved_favorite_appearance_match' if appearance else 'saved_verified_favorite_snapshot', 'membership_verified_at': observed_at,
            'matching_basis':'appearance' if appearance else 'verified_correspondence',
            'current_membership_rechecked': False, 'current_account_binding': 'not_rechecked',
            'complete_collection_proven': False, 'messages_sent': 0, 'native_ui_calls': 0,
            'reason': '复用外观匹配结果；精确历史版本未证明' if appearance else '复用已核验收藏快照；未重新确认当前收藏成员'}


def reusable(item):
    try:
        return lookup(item) is not None
    except (OSError, ValueError, KeyError, TypeError):
        return False


def record(item, asset_path, receipt_path, verification, destination):
    """Bind a freshly reverified observation without overwriting its origins."""
    from datetime import datetime
    acquire.context(item)
    asset = load_asset(asset_path)
    validate_receipt(receipt_path, asset['source_sha256'])
    v = catalog.read(verification)
    verification_valid(v, item, asset)
    paths = [Path(verification), Path(receipt_path), Path(item['scan']),
             Path(v['evidence']) / 'favorites-before-reopen.png',
             Path(v['evidence']) / 'favorites-after-reopen.png']
    paths.extend(Path(w['path']) for w in v.get('animation', {}).get('visual_witnesses', []))
    result = {'schema': 'qq-saved-favorite-binding-v1', 'item_id': item['id'],
              'source_sha256': asset['source_sha256'], 'scan': item['scan'],
              'scan_sha256': sha(item['scan']), 'verification': str(Path(verification).resolve()),
              'verified_at': datetime.now().astimezone().isoformat(),
              'evidence': [{'path': str(p.resolve()), 'sha256': sha(p)} for p in paths]}
    save_json(destination, result)
    return {'path': str(Path(destination).resolve()), 'sha256': sha(destination)}
