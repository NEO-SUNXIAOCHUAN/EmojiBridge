"""Offline starter originals, with a durable per-entry receipt (including deletion)."""
import json
import hashlib
from pathlib import Path
from PIL import Image
from .paths import APP_ROOT
from .state import save_json


def needs_preparation(store):
    """Cheap startup check; never reimport deleted or optional media."""
    receipt=store.root/'builtin-examples.json'
    try:seen=json.loads(receipt.read_text('utf8'))
    except (OSError,ValueError):return True
    if not seen.get('__complete_v1'):return True
    manifest=json.loads((APP_ROOT/'assets/examples/manifest.json').read_text('utf8'))
    if any(entry.get('id',entry['file']) not in seen for entry in manifest):return True
    active_keys={entry.get('id',entry['file']) for entry in manifest}|{'editable-v1'}
    live=set(store.matching_ids())
    for key,ident in seen.items():
        if key not in active_keys or ident not in live:continue
        item=store.get(ident)
        try:
            if not item['path'].is_file() or not item['thumbnail'].is_file():return True
        except OSError:return True
    return False


def install(store,*,restore=False,cancel=None,progress=None):
    root=APP_ROOT/'assets/examples';manifest=json.loads((root/'manifest.json').read_text('utf-8'))
    receipt=store.root/'builtin-examples.json'
    seen=json.loads(receipt.read_text('utf-8')) if receipt.exists() else {}
    added=0
    for index,entry in enumerate(manifest):
        if cancel and cancel.is_set():break
        key=entry.get('id',entry['file'])
        if key in seen and not restore:continue
        original=root/entry['file']
        digest=hashlib.sha256(original.read_bytes()).hexdigest()
        if entry.get('sha256') and entry['sha256']!=digest:raise ValueError('builtin_source_digest_changed')
        # A manually imported/deleted identical original must not be resurrected
        # or have its user collections changed by an automatic upgrade.
        if not restore:
            with store.connect() as conn:
                exists=conn.execute('SELECT id FROM materials WHERE id=?',(digest,)).fetchone()
            if exists:
                seen[key]=digest;save_json(receipt,seen);continue
        provenance=entry.get('source_note')
        source=('内置素材 · '+provenance+' · '+entry.get('source_url','')) if provenance else (
            '内置示例 · Twemoji v16.0.1 / CC BY 4.0 · '+entry.get('modification','透明 PNG'))
        item,duplicate=store.import_file(original,kind='builtin',name=entry['name'],
            source=source,cancel=cancel,expected_sha=digest)
        store.organize([item['id']],add_collections=entry['collections'])
        seen[key]=item['id'];save_json(receipt,seen);added+=not duplicate
        if progress:progress(index+1,len(manifest),'准备离线示例')
    if restore and 'editable-v1' in seen:
        store.organize([seen['editable-v1']],deleted=False,add_collections=['创作素材'])
    if not (cancel and cancel.is_set()) and 'editable-v1' not in seen:
        from .editing import EditDocument
        from .scene_save import SceneSave
        ident=seen['1f438.png']
        doc=EditDocument(Image.new('RGBA',(512,384)),[ident])
        with Image.open(store.original(ident)) as source:doc.add_sticker(source.convert('RGBA'),(136,64),size=(240,240),source_id=ident)
        doc.add_text('今天也要开心',36,'#eaf4ff',(122,315))
        job=SceneSave.capture(doc,'开心 · 可编辑示例',(512,384),{},'builtin-editable-v1')
        if cancel:job.cancel=cancel
        item=job.run(store,lambda *args:None);store.organize([item['id']],add_collections=['创作素材'])
        with store.connect() as conn:conn.execute('INSERT OR IGNORE INTO sources VALUES (?,?,?,?)',(item['id'],'builtin','内置可编辑示例 · Twemoji / CC BY 4.0',item['created']))
        seen['editable-v1']=item['id'];save_json(receipt,seen);added+=1
    if not (cancel and cancel.is_set()):seen['__complete_v1']=True;save_json(receipt,seen)
    return added
