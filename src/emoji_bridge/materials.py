"""User-owned local originals. Reuse media validation; never treat files as client favorites."""
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

from PIL import Image, ImageOps
from .frame_store import inspect_local as inspect, MAX_INPUT_BYTES
from .state import sha

EXTENSIONS = {'PNG': '.png', 'JPEG': '.jpg', 'GIF': '.gif', 'WEBP': '.webp'}


def is_dynamic(metadata):
    return metadata.get('format') == 'GIF' or bool(metadata.get('animated')) or metadata.get('frames',1)>1


def _generated_recipe(recipe):
    """Generators and owned video clips retain real provenance, not fake parents."""
    if not isinstance(recipe,dict):return False
    if recipe.get('type')=='template':
        return bool(recipe.get('template_key')) and bool(recipe.get('template_version'))
    if recipe.get('type')=='editor-scene' and recipe.get('recipe_version')==1:
        return all(bool(re.fullmatch(r'[a-f0-9]{32}',str(recipe.get(key,''))))
                   for key in ('draft_id','work_id','document_revision'))
    if recipe.get('type')=='video-clip' and recipe.get('recipe_version')==1:
        span=recipe.get('source_range_ms',[])
        return (bool(re.fullmatch(r'[a-f0-9]{64}',str(recipe.get('source_sha256',''))))
                and len(span)==2 and all(isinstance(t,int) for t in span)
                and 0<=span[0]<span[1])
    return False


def now():
    return datetime.now().astimezone().isoformat()


def default_root():
    from .client_sources import known_folder
    return known_folder('local_app_data') / 'EmojiBridgePilot' / 'material-library'


def tags_from(text):
    values = re.split(r'[,，;；\n]+', text) if isinstance(text, str) else text
    return list(dict.fromkeys(v.strip() for v in values if v.strip()))


class MaterialStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'materials.db'
        existed=self.db.exists()
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS materials (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, tags TEXT NOT NULL,
                    category TEXT NOT NULL, search_text TEXT NOT NULL,
                    relative_file TEXT NOT NULL, metadata TEXT NOT NULL,
                    created TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sources (
                    material_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
                    imported TEXT NOT NULL, UNIQUE(material_id, kind, value));
                CREATE INDEX IF NOT EXISTS materials_category ON materials(category);
                CREATE TABLE IF NOT EXISTS material_usage (
                    material_id TEXT PRIMARY KEY, used TEXT NOT NULL);
            ''')
        self._migrate(existed)

    def _migrate(self, existed):
        with self.connect() as conn:
            if conn.execute('PRAGMA user_version').fetchone()[0]>=2:return
            if existed:
                backup=self.root/'materials-before-S0098.db'
                if not backup.exists():
                    pending=backup.with_suffix('.pending.db')
                    destination=sqlite3.connect(pending)
                    try:conn.backup(destination)
                    finally:destination.close()
                    os.replace(pending,backup)
            conn.executescript('''BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS collections(name TEXT PRIMARY KEY, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS memberships(material_id TEXT NOT NULL, name TEXT NOT NULL,
                    PRIMARY KEY(material_id,name));
                CREATE INDEX IF NOT EXISTS memberships_name ON memberships(name,material_id);
                CREATE TABLE IF NOT EXISTS material_flags(material_id TEXT PRIMARY KEY,
                    favorite INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS flags_views ON material_flags(deleted,favorite,material_id);
                CREATE INDEX IF NOT EXISTS sources_kind ON sources(kind,material_id);
                CREATE INDEX IF NOT EXISTS materials_created ON materials(created DESC,id);
                CREATE INDEX IF NOT EXISTS usage_recent ON material_usage(used DESC,material_id);
                CREATE TABLE IF NOT EXISTS library_revision(value INTEGER NOT NULL);
                INSERT INTO library_revision SELECT 0 WHERE NOT EXISTS(SELECT 1 FROM library_revision);
                INSERT OR IGNORE INTO collections SELECT category,MIN(created) FROM materials WHERE category!='' GROUP BY category;
                INSERT OR IGNORE INTO memberships SELECT id,category FROM materials WHERE category!='';
            ''')
            for table in ('materials','sources','material_usage','collections','memberships','material_flags'):
                for action in ('INSERT','UPDATE','DELETE'):
                    conn.execute(f'CREATE TRIGGER IF NOT EXISTS revision_{table}_{action} AFTER {action} ON {table} BEGIN UPDATE library_revision SET value=value+1; END')
            conn.execute('PRAGMA user_version=2')

    def revision(self):
        # GUI watchers may skip one tick while a writer commits; never wait ten
        # seconds for SQLite on Tk's thread. The next tick retries the read.
        try:
            with self.connect(timeout=.01) as conn:return conn.execute('SELECT value FROM library_revision').fetchone()[0]
        except sqlite3.OperationalError as exc:
            if 'locked' in str(exc).lower() or 'busy' in str(exc).lower():return None
            raise

    @contextmanager
    def connect(self,*,timeout=10):
        # A connection per operation: background imports never share GUI connections.
        conn = sqlite3.connect(self.db, timeout=timeout)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _row(self, row):
        if row is None:
            raise ValueError('material_not_found')
        result = dict(row)
        result['tags'] = json.loads(result['tags'])
        result['metadata'] = json.loads(result['metadata'])
        from .card_names import display_fields
        result.update(display_fields(result['name'],result['metadata'].get('name_origin','unknown')))
        result['collections']=(result.pop('collection_names',None) or '').split('\x1f')
        result['collections']=[v for v in result['collections'] if v]
        result['source_kinds']=(result.pop('source_kinds',None) or '').split(',')
        result['favorite']=bool(result.get('favorite',False))
        result['path'] = self.root / result['relative_file']
        result['thumbnail'] = result['path'].parent / 'thumbnail.png'
        return result

    def get(self, ident):
        with self.connect() as conn:
            return self._row(conn.execute(self._select()+' WHERE id=?', (ident,)).fetchone())

    @staticmethod
    def _select():
        return '''SELECT materials.*,
            (SELECT group_concat(name,char(31)) FROM memberships WHERE material_id=id) AS collection_names,
            (SELECT group_concat(DISTINCT kind) FROM sources WHERE material_id=id) AS source_kinds,
            COALESCE((SELECT favorite FROM material_flags WHERE material_id=id),0) AS favorite
            FROM materials'''

    def _filter(self,text='',category='',recent=False,source='',media='',view=''):
        conditions=['instr(search_text,?)>0' for _ in text.casefold().split()];params=text.casefold().split()
        if category:conditions.append('id IN (SELECT material_id FROM memberships WHERE name=?)');params.append(category)
        if recent or view=='recent':conditions.append('id IN (SELECT material_id FROM material_usage)')
        conditions.append('id IN (SELECT material_id FROM material_flags WHERE deleted=1)' if view=='trash' else 'id NOT IN (SELECT material_id FROM material_flags WHERE deleted=1)')
        if view=='favorite':conditions.append('id IN (SELECT material_id FROM material_flags WHERE favorite=1)')
        if view=='unclassified':conditions.append('id NOT IN (SELECT material_id FROM memberships)')
        kinds={'qq':('qq',),'wechat':('wechat',),'edited':('edited',),'local':('file','drop','clipboard_files','clipboard_bitmap')}
        if source:
            values=kinds[source];conditions.append('id IN (SELECT material_id FROM sources WHERE kind IN ('+','.join('?' for _ in values)+'))');params.extend(values)
        if media:conditions.append("CAST(json_extract(metadata,'$.frames') AS INTEGER)"+('>1' if media=='animated' else '=1'))
        return ' WHERE '+' AND '.join(conditions),params

    def search(self, text='', category='', offset=0, limit=60, *, recent=False, source='', media='', view=''):
        where,params=self._filter(text,category,recent,source,media,view)
        with self.connect() as conn:
            total = conn.execute('SELECT COUNT(*) FROM materials' + where, params).fetchone()[0]
            order = '(SELECT used FROM material_usage WHERE material_id=id) DESC, id' if recent or view=='recent' else 'created DESC, id'
            rows = conn.execute(self._select() + where +
                                ' ORDER BY ' + order + ' LIMIT ? OFFSET ?',
                                params + [limit, offset]).fetchall()
        return [self._row(row) for row in rows], total

    def matching_ids(self,text='',category='',**filters):
        where,params=self._filter(text,category,**filters)
        with self.connect() as conn:return [r[0] for r in conn.execute('SELECT id FROM materials'+where+' ORDER BY created DESC,id',params)]

    def mark_used(self, ids):
        with self.connect() as conn:
            conn.executemany('INSERT OR REPLACE INTO material_usage(material_id,used) '
                             'SELECT id,? FROM materials WHERE id=?', [(now(), ident) for ident in ids])

    def categories(self):
        with self.connect() as conn:
            return [r[0] for r in conn.execute('SELECT name FROM collections ORDER BY name')]

    def collection(self,name,rename=None):
        name=name.strip();new=name if rename is None else rename.strip()
        if not name or not new or max(len(name),len(new))>100 or '\x1f' in name+new:raise ValueError('合集名须为1～100个字符')
        with self.connect() as conn:
            if rename is None:conn.execute('INSERT OR IGNORE INTO collections VALUES (?,?)',(name,now()))
            elif new!=name:
                if conn.execute('SELECT 1 FROM collections WHERE name=?',(new,)).fetchone():raise ValueError('新合集名称已经存在')
                conn.execute('UPDATE collections SET name=? WHERE name=?',(new,name))
                conn.execute('UPDATE memberships SET name=? WHERE name=?',(new,name))
                conn.execute('UPDATE materials SET category=? WHERE category=?',(new,name))

    def organize(self,ids,*,add_tags=(),remove_tags=(),add_collections=(),remove_collections=(),favorite=None,deleted=None):
        additions=tags_from(add_tags);removals=set(tags_from(remove_tags))
        groups=tags_from(add_collections);remove_groups=tags_from(remove_collections)
        for group in groups:self.collection(group)
        with self.connect() as conn:
            for ident in dict.fromkeys(ids):
                row=conn.execute('SELECT name,tags,category,metadata FROM materials WHERE id=?',(ident,)).fetchone()
                if not row:raise ValueError('material_not_found')
                labels=[v for v in dict.fromkeys([*json.loads(row['tags']),*additions]) if v not in removals]
                original_name=json.loads(row['metadata']).get('original_name','')
                conn.execute('UPDATE materials SET tags=?,search_text=?,updated=? WHERE id=?',(json.dumps(labels,ensure_ascii=False),' '.join([row['name'],original_name,row['category'],*labels]).casefold(),now(),ident))
                conn.executemany('INSERT OR IGNORE INTO memberships VALUES (?,?)',[(ident,g) for g in groups])
                conn.executemany('DELETE FROM memberships WHERE material_id=? AND name=?',[(ident,g) for g in remove_groups])
                if favorite is not None or deleted is not None:
                    conn.execute('INSERT OR IGNORE INTO material_flags(material_id) VALUES (?)',(ident,))
                    for field,value in [('favorite',favorite),('deleted',deleted)]:
                        if value is not None:conn.execute(f'UPDATE material_flags SET {field}=? WHERE material_id=?',(int(value),ident))

    def sources(self, ident):
        with self.connect() as conn:
            # Several editable drafts can produce byte-identical GIFs. Keep all
            # provenance, but reopen the most recently saved draft, not the
            # lexicographically greatest random draft id from the UNIQUE index.
            return [dict(r) for r in conn.execute('SELECT kind,value,imported FROM sources WHERE material_id=? ORDER BY imported,rowid', (ident,))]

    def import_file(self, path, *, kind='file', name=None, source=None, cancel=None, expected_sha=None, name_origin=None):
        """Copy first, then fully validate the owned snapshot, then commit metadata."""
        if kind not in ('file', 'drop', 'clipboard_files', 'clipboard_bitmap', 'edited','qq','wechat','builtin'):
            raise ValueError('unknown_material_source')
        path = Path(path).resolve()
        if not path.is_file():
            raise ValueError('请选择图片文件，不支持直接导入文件夹')
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError('local_decode_size_limit')
        with tempfile.TemporaryDirectory(prefix='import-', dir=self.root) as folder:
            snapshot = Path(folder) / 'source'
            with path.open('rb') as src, snapshot.open('wb') as dst:
                total = 0
                while chunk := src.read(1024 * 1024):
                    if cancel and cancel.is_set():
                        raise InterruptedError('导入已取消，已完成项保留')
                    total += len(chunk)
                    if total > MAX_INPUT_BYTES:
                        raise ValueError('local_decode_size_limit')
                    dst.write(chunk)
                dst.flush(); os.fsync(dst.fileno())
            ident = sha(snapshot)
            if expected_sha and ident!=expected_sha:raise ValueError('所选原件内容已变化，未入库')
            with self.connect() as conn:
                row = conn.execute('SELECT * FROM materials WHERE id=?', (ident,)).fetchone()
            duplicate = row is not None
            if duplicate:
                item = self._row(row)
                info = item['metadata']
                destination = item['path']
            else:
                info, _ = inspect(snapshot,cancel=cancel)
                destination = self.root / 'objects' / ident[:2] / ident / ('original' + EXTENSIONS[info['format']])
            if cancel and cancel.is_set():
                raise InterruptedError('导入已取消，已完成项保留')
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if sha(destination) != ident:
                    raise ValueError('库内原件发生变化，未覆盖；请保留数据并检查')
            else:
                os.replace(snapshot, destination)
            thumbnail = destination.parent / 'thumbnail.png'
            if not thumbnail.exists():
                with Image.open(destination) as im:
                    frame = ImageOps.exif_transpose(im).convert('RGBA')
                    frame.thumbnail((180, 140), Image.Resampling.LANCZOS)
                    temp = Path(folder) / 'thumbnail.png'
                    frame.save(temp, 'PNG'); os.replace(temp, thumbnail)
            title = (name or path.stem).strip() or '未命名素材'
            if not duplicate:
                info=dict(info,name_origin=name_origin or ('user' if kind=='edited' else 'filename' if kind in ('file','drop','clipboard_files') else 'unknown'),original_name=title)
            stamp = now()
            # Clipboard bitmap temp paths are implementation details, not provenance.
            value = source if source is not None else (str(path) if kind != 'clipboard_bitmap' else '剪贴板仅提供静态图像')
            with self.connect() as conn:
                inserted=conn.execute('INSERT OR IGNORE INTO materials VALUES (?,?,?,?,?,?,?,?,?)',
                             (ident, title, '[]', '', title.casefold(), str(destination.relative_to(self.root)),
                              json.dumps(info, separators=(',', ':')), stamp, stamp))
                duplicate=inserted.rowcount==0
                conn.execute('INSERT OR IGNORE INTO sources VALUES (?,?,?,?)', (ident, kind, value, stamp))
                conn.execute('UPDATE material_flags SET deleted=0 WHERE material_id=?',(ident,))
            return self.get(ident), duplicate

    def import_bitmap(self, image, cancel=None):
        """The clipboard did not supply an original/GIF; record a new static PNG."""
        with tempfile.TemporaryDirectory(prefix='clipboard-', dir=self.root) as folder:
            file = Path(folder) / '剪贴板图片.png'
            image.save(file, 'PNG')
            return self.import_file(file, kind='clipboard_bitmap', name='剪贴板 ' + datetime.now().strftime('%m-%d %H%M%S'), cancel=cancel)

    def update(self, ids, *, name=None, tags=None, category=None):
        with self.connect() as conn:
            for ident in ids:
                item = self._row(conn.execute('SELECT * FROM materials WHERE id=?', (ident,)).fetchone())
                title = (name.strip() or item['name']) if name is not None else item['name']
                labels = tags_from(tags) if tags is not None else item['tags']
                group = category.strip() if category is not None else item['category']
                metadata=dict(item['metadata'])
                if name is not None:metadata['name_origin']='user'
                searchable = ' '.join([title,metadata.get('original_name',''), group, *labels]).casefold()
                conn.execute('UPDATE materials SET name=?,tags=?,category=?,search_text=?,metadata=?,updated=? WHERE id=?',
                             (title, json.dumps(labels, ensure_ascii=False), group, searchable,json.dumps(metadata,ensure_ascii=False), now(), ident))
                if category is not None:
                    if item['category'] and item['category']!=group:conn.execute('DELETE FROM memberships WHERE material_id=? AND name=?',(ident,item['category']))
                    if group:
                        conn.execute('INSERT OR IGNORE INTO collections VALUES (?,?)',(group,now()))
                        conn.execute('INSERT OR IGNORE INTO memberships VALUES (?,?)',(ident,group))

    def original(self, ident):
        item = self.get(ident)
        try:digest=sha(item['path'])
        except OSError as exc:
            from .material_diagnostics import record
            record(self.root,'original_read',item['path'],exc,ident=ident)
            raise
        if digest != ident:
            raise ValueError('库内原件校验失败')
        return item['path']

    def thumbnail_bytes(self,ident):
        """Retryable derived cover; an inaccessible cover never invalidates media."""
        from io import BytesIO
        from .material_diagnostics import record
        item=self.get(ident);file=item['thumbnail']
        try:
            data=file.read_bytes()
            # A readable truncated/HTML/empty cover is not a usable image.
            with Image.open(BytesIO(data)) as cover:cover.verify()
            return data
        except (OSError,ValueError,SyntaxError) as exc:record(self.root,'thumbnail_read',file,exc,ident=ident)
        try:
            with Image.open(item['path']) as source:
                frame=ImageOps.exif_transpose(source).convert('RGBA');frame.thumbnail((180,140),Image.Resampling.LANCZOS)
                output=BytesIO();frame.save(output,'PNG');data=output.getvalue()
        except OSError as exc:
            record(self.root,'thumbnail_source_read',item['path'],exc,ident=ident);raise
        temp=None
        try:
            with tempfile.NamedTemporaryFile(dir=file.parent,suffix='.tmp',delete=False) as stream:
                temp=Path(stream.name);stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,file)
        except OSError as exc:record(self.root,'thumbnail_cache_write',file,exc,mode='wb/replace',ident=ident)
        finally:
            if temp and temp.exists():
                try:temp.unlink()
                except OSError:pass
        return data

    def export(self, ids, directory, cancel=None):
        directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=True)
        output = []
        for ident in dict.fromkeys(ids):
            if cancel and cancel.is_set():
                break
            item = self.get(ident); source = self.original(ident)
            stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', item['name']).rstrip(' .')[:70] or '素材'
            # Prefix also avoids reserved DOS names, preserves the actual detected suffix.
            destination = directory / (ident[:8] + '-' + stem + source.suffix)
            n = 1
            while destination.exists() and sha(destination) != ident:
                destination = directory / (ident[:8] + '-' + stem + f'-{n}' + source.suffix); n += 1
            if not destination.exists():
                # Create exclusively; never overwrite the user's existing file.
                stream = destination.open('xb')
                try:
                    with stream, source.open('rb') as original:
                        while chunk := original.read(1024 * 1024):
                            if cancel and cancel.is_set():
                                raise InterruptedError('导出已取消；已完成文件保留')
                            stream.write(chunk)
                        if cancel and cancel.is_set():
                            raise InterruptedError('导出已取消；已完成文件保留')
                except InterruptedError:
                    destination.unlink(missing_ok=True)
                    break
                except Exception:
                    destination.unlink(missing_ok=True)
                    raise
                if sha(destination) != ident:
                    raise ValueError('export_copy_mismatch')
            output.append(destination)
        return output

    def editing_input(self, ident):
        """Future editor seam: read this original, import the result as a new asset."""
        return {'material_id': ident, 'original': self.original(ident), 'metadata': self.get(ident)['metadata']}

    def save_work(self, image, *, name, source_ids, recipe, cancel=None):
        """Lossless new PNG plus durable parent relationships; originals stay immutable."""
        from PIL.PngImagePlugin import PngInfo
        parents = list(dict.fromkeys(source_ids))
        if not parents and not _generated_recipe(recipe):
            raise ValueError('作品需要至少一个素材来源')
        for ident in parents:
            if cancel and cancel.is_set():raise InterruptedError('保存已取消，原素材保留')
            self.original(ident)
        provenance = {'schema': 'static-work-v1', 'parents': parents, 'recipe': recipe}
        encoded = json.dumps(provenance, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        metadata = PngInfo(); metadata.add_itxt('EmojiBridge-source', encoded)
        with tempfile.TemporaryDirectory(prefix='work-', dir=self.root) as folder:
            file = Path(folder) / 'work.png'
            image.convert('RGBA').save(file, 'PNG', pnginfo=metadata)
            return self.import_file(file, kind='edited', name=name or '新作品', source=encoded,cancel=cancel)

    def save_animated_work(self, file, *, name, source_ids, recipe, cancel=None):
        """Import an already validated animated result, preserving owned originals."""
        parents=list(dict.fromkeys(source_ids))
        if not parents and not _generated_recipe(recipe):raise ValueError('作品需要素材来源或有版本的生成配方')
        for ident in parents:
            if cancel and cancel.is_set():raise InterruptedError('保存已取消，原素材保留')
            self.original(ident)
        # import_file validates every frame of its immutable owned copy once.
        with Image.open(file) as image:
            if image.format not in ('GIF','PNG','WEBP') or not (image.format=='GIF' or getattr(image,'is_animated',False)):raise ValueError('动态作品须为 GIF、APNG 或动态 WebP')
            schema='single-gif-work-v1' if image.format=='GIF' else 'animated-work-v1'
        encoded=json.dumps({'schema':schema,'parents':parents,'recipe':recipe},ensure_ascii=False,sort_keys=True)
        return self.import_file(file,kind='edited',name=name or '动态作品',source=encoded,cancel=cancel)
