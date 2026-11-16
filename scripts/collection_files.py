"""Selected source files for copying/transfer. This module never imports materials."""
from pathlib import Path
from emoji_bridge import catalog
from emoji_bridge.state import sha


def local_original(client, item, profile, cancel):
    """Return verified local bytes without client locks or catalog writes."""
    profile=Path(profile)
    if item.get('cache_file'):
        from emoji_bridge.cache_listing import snapshot
        file=snapshot(item,profile/'runtime-data/collection-files',cancel.exists)
        return file,item['source_sha256'],{'schema':'cache-file-source-v1','client':client,
            'path':item['cache_file'],'sha256':item['source_sha256'],'scope':'selected_cache_file'}
    if item.get('managed_original') and item.get('source_sha256'):
        file=Path(item['managed_original'])
        if file.is_file() and sha(file)==item['source_sha256']:
            return file,item['source_sha256'],{'client':client,'scope':'previously_saved_original'}
    from client_material_import import verified_original
    if client=='wechat' and item.get('asset'):
        try:return verified_original(client,item)
        except (OSError,ValueError,KeyError):pass
    return None


def original(client, item, library, profile, cancel):
    available=local_original(client,item,profile,cancel)
    if available:return available
    if client!='wechat':
        raise ValueError('旧 QQ 面板记录请重新读取本地缓存；不会打开来源窗口')
    from client_material_import import verified_original
    from wechat_acquire import acquire_selected
    result=acquire_selected(item,library['clients']['wechat'].get('source_report'),cancel)
    catalog.apply_acquisition(item,result)
    if item.get('original_state')!='ready':
        raise ValueError(result.get('reason') or '完整原件尚未取得')
    return verified_original(client,item)
