"""Resolve collection metadata to original media, never its compatibility copy."""
import json
from pathlib import Path
from collections import OrderedDict
from threading import Lock
from .media import sha

_verified=OrderedDict()
_guard=Lock()

def original_for_preview(member):
    managed=member.get('managed_original')
    value=managed if managed and Path(managed).is_file() else member.get('asset')
    if not value:return None
    path=Path(value)
    if not path.is_file():return None
    if path.suffix.lower()!='.json':return path  # legacy direct media records
    manifest=json.loads(path.read_text('utf8'))
    if manifest.get('schema')!='local-asset-v1':raise ValueError('invalid_asset_manifest')
    original=Path(manifest['original_copy'])
    if not original.is_absolute():original=path.parent/original
    stat=original.stat();key=(str(original),stat.st_size,stat.st_mtime_ns,manifest['source_sha256'])
    with _guard:known=key in _verified
    if not known:
        if sha(original)!=manifest['source_sha256']:raise ValueError('original_digest_mismatch')
        with _guard:
            _verified[key]=True
            while len(_verified)>64:_verified.popitem(last=False)
    return original
