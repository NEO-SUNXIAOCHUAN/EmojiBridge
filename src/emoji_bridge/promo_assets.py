"""Versioned, opt-in bundle content over the existing material/draft services."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from .paths import APP_ROOT
from .state import save_json, sha, single_instance
from .frame_store import cancelled

COLLECTION = '宣传片同款'


def bundle_root():
    return APP_ROOT / '宣传片同款表情'


def metadata(root=None):
    file = (Path(root) if root else bundle_root()) / 'bundle-index.json'
    return json.loads(file.read_text('utf-8')) if file.is_file() else None


def pending(store, root=None):
    info = metadata(root)
    if not info:return False
    receipt = store.root / 'promo-assets.json'
    if not receipt.exists():return True
    try:return json.loads(receipt.read_text('utf-8')).get('completed') != info['manifest_sha256']
    except (OSError,ValueError):return True  # Surface the specific failure in the cancellable task, not during GUI startup.


def local(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('随包素材缺失或路径无效，请完整解压候选包')
    return path


def media_sources(root=None):
    root = Path(root) if root else bundle_root()
    info = metadata(root)
    if not info:return {}
    manifest = json.loads(local(root, 'manifest.json').read_text('utf-8'))
    return {row['sha256']: local(root, row['path']) for row in manifest['assets'] if row['seed_default']}


def install(store, *, root=None, restore=False, editable=False, cancel=None, progress=None):
    root = Path(root) if root else bundle_root()
    info = metadata(root)
    if not info:return {'added':0, 'existing':0, 'drafts':0, 'templates':0, 'errors':[]}
    manifest_file = local(root, 'manifest.json')
    if sha(manifest_file) != info['manifest_sha256']:raise ValueError('随包素材清单校验未通过')
    manifest = json.loads(manifest_file.read_text('utf-8'))
    result = {'added':0, 'existing':0, 'drafts':0, 'templates':0, 'errors':[]}
    receipt = store.root / 'promo-assets.json'
    # OS-owned lock survives interrupted seeding without deleting a lock or a library.
    with single_instance(store.root / 'promo-seed.lock'):
        seen = json.loads(receipt.read_text('utf-8')) if receipt.exists() else {'media':{}, 'editable':{}}
        rows = [r for r in manifest['assets'] if r['seed_default']]
        store.collection(COLLECTION)
        for index, row in enumerate(rows):
            cancelled(cancel)
            ident = row['sha256']
            if ident in seen['media'] and not restore:continue
            try:
                with store.connect() as conn:
                    old = conn.execute('SELECT id FROM materials WHERE id=?',(ident,)).fetchone()
                    deleted = conn.execute('SELECT deleted FROM material_flags WHERE material_id=?',(ident,)).fetchone()
                # Even a new pack version cannot resurrect a previously deleted original.
                if deleted and deleted[0] and not restore:
                    seen['media'][ident] = ident;save_json(receipt,seen);continue
                if old and not restore:
                    item = store.get(ident);duplicate = True
                    with store.connect() as conn:
                        from .materials import now
                        conn.execute('INSERT OR IGNORE INTO sources VALUES (?,?,?,?)',
                                     (ident,'builtin',f'宣传片同款 {manifest["version"]} · {row["path"]}',now()))
                else:
                    item, duplicate = store.import_file(local(root,row['path']),kind='builtin',name=row['name'],
                        name_origin='user',source=f'宣传片同款 {manifest["version"]} · {row["path"]}',
                        expected_sha=ident,cancel=cancel)
                category = row['category'].split('_',1)[-1]
                store.organize([item['id']],add_collections=[COLLECTION],add_tags=[category])
                seen['media'][ident] = item['id'];save_json(receipt,seen)
                result['existing' if duplicate else 'added'] += 1
            except (OSError,ValueError) as exc:
                from .material_diagnostics import record
                record(store.root,'promo_seed',root/row['path'],exc,ident=ident)
                result['errors'].append(row['name']+'：未能准备，请检查完整解压及文件访问后重试')
            if progress:progress(index+1,len(rows),'准备宣传片同款')
        if not result['errors']:seen['completed']=info['manifest_sha256'];save_json(receipt,seen)
        if editable:
            for index,row in enumerate(manifest['editable']):
                cancelled(cancel)
                file = local(root,row['path']);key = sha(file)
                if key in seen['editable']:continue
                if row['kind']=='native_scene':
                    ident = hashlib.sha256(('promo-scene:'+key).encode()).hexdigest()[:32]
                    target = store.root/'drafts'/ident
                    if not (target/'scene.json').exists():
                        target.parent.mkdir(parents=True,exist_ok=True)
                        with tempfile.TemporaryDirectory(prefix='promo-scene-',dir=target.parent) as temporary:
                            stage=Path(temporary)/'scene';shutil.copytree(file.parent,stage)
                            data=json.loads((stage/'scene.json').read_text('utf-8'))
                            # Author-side IDs are provenance, not records on another computer.
                            parents=data.get('source_ids',[])
                            with store.connect() as conn:
                                valid={r[0] for r in conn.execute('SELECT id FROM materials')}
                            data['source_ids']=[v for v in parents if v in valid]
                            for layer in data['layers']:
                                if layer.get('source_id') not in valid:layer['source_id']=None
                            data.setdefault('extra',{})['promo_origin']={'version':manifest['version'],'path':row['path'],'source_ids':parents}
                            save_json(stage/'scene.json',data)
                            from .editing import load_scene
                            load_scene(stage,cancel=cancel)
                            cancelled(cancel);stage.rename(target)
                    seen['editable'][key]=ident;result['drafts']+=1
                elif row['kind']=='native_template':
                    from .template_packs import import_pack
                    target=store.root/'templates'/key[:32]
                    if not (target/'template.json').exists():
                        imported,pack=import_pack(file,store.root)
                        pack['installed_id']=key[:32];pack['promo_sha256']=key
                        save_json(imported/'template.json',pack);imported.rename(target)
                    seen['editable'][key]=target.name;result['templates']+=1
                save_json(receipt,seen)
                if progress:progress(index+1,len(manifest['editable']),'准备可编辑示例')
    return result
