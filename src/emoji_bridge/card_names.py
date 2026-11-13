"""Presentation provenance, separate from media identity and searchable names."""

def collection_name_origin(item, client):
    if item.get('name_origin'):
        return item['name_origin']
    # Compatibility for records created by our old, known catalog producers.
    # A matching title alone is NOT evidence (a user can name a work identically).
    label = item.get('label')
    if client == 'wechat':
        md5 = (item.get('member') or {}).get('md5')
        if md5 and item.get('id') == 'wechat:' + md5 and label == '微信收藏 ' + md5[:8]:
            return 'generated'
    if client == 'qq' and item.get('identity_scope') == 'position in this scan only':
        if 'position' in item and label == f"QQ 条目 {item['position']}":
            return 'generated'
    return 'unknown'


def display_fields(name, origin):
    return dict(name=name, name_origin=origin, display_name='' if origin == 'generated' else name)
