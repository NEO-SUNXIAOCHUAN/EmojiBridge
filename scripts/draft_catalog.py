"""Draft visibility is separate from material records and immutable scene files."""
from pathlib import Path
import json
from emoji_bridge.state import save_json
import threading
import uuid

_covers=threading.BoundedSemaphore(2)

def directory(root,ident):
    if not isinstance(ident,str) or not ident or len(ident)>100 or any(c not in '0123456789abcdef-' for c in ident):
        raise ValueError('无效草稿标识')
    return Path(root)/'drafts'/ident

def listing(root):
    rows=[]
    for file in (Path(root)/'drafts').glob('*/scene.json'):
        if (file.parent/'deleted.json').exists():continue
        try:
            data=json.loads(file.read_text('utf-8'))
            rows.append({'id':file.parent.name,'name':data.get('name') or '创作草稿','updated':file.stat().st_mtime,
                         'animated':any(l.get('animation') for l in data.get('layers',[]))})
        except (OSError,ValueError):continue
    return sorted(rows,key=lambda r:(-r['updated'],r['id']))

def remove(root,ident):
    folder=directory(root,ident)
    if not (folder/'scene.json').is_file():raise ValueError('草稿不存在')
    # Scenes can be referenced by exported materials. Never delete their assets.
    save_json(folder/'deleted.json',{'deleted':True,'reason':'user_removed_from_drafts'})


def remove_many(root,idents):
    if not isinstance(idents,list):raise ValueError('请选择要删除的草稿')
    # Validate the entire selection before marking any draft as removed.
    for ident in idents:
        if not (directory(root,ident)/'scene.json').is_file():raise ValueError('草稿不存在')
    unique=list(dict.fromkeys(idents))
    for ident in unique:remove(root,ident)
    return unique

def resolve(root,ident):
    folder=directory(root,ident)
    if (folder/'deleted.json').exists() or not (folder/'scene.json').is_file():raise ValueError('草稿已删除或不存在')
    return folder

def cover(root,ident):
    """Only requested covers are rendered, off the UI, at most two at once."""
    from emoji_bridge.editing import load_scene
    from PIL import Image
    folder=resolve(root,ident);version=(folder/'scene.json').stat().st_mtime_ns
    target=Path(root)/'cache/draft-covers'/f'{ident}-{version}.png'
    with _covers:
        if not target.exists():
            doc,_=load_scene(folder)
            image=doc.render();image.thumbnail((480,260),Image.Resampling.LANCZOS)
            target.parent.mkdir(parents=True,exist_ok=True)
            temp=target.with_suffix('.'+uuid.uuid4().hex+'.tmp')
            try:image.save(temp,'PNG');temp.replace(target)
            finally:image.close();temp.unlink(missing_ok=True)
        return target.read_bytes()
