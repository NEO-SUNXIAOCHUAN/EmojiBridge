"""Current-schema portable backups of owned data, never the QQ cache inventory."""
from pathlib import Path,PurePosixPath
from contextlib import closing
import hashlib,json,os,shutil,sqlite3,stat,tempfile,time,uuid,zipfile
from .library_gate import hold
from .state import save_json,sha

DIRECTORIES=('objects','drafts','video-sources','tasks','templates','template-inputs')
SETTINGS=('desktop-ui.json','drawer.json','pocket-position.json','compatibility-copy.json',
          'builtin-examples.json','last-task.json','work-output.json')

def check(cancel):
    if cancel and cancel.is_set():raise InterruptedError('备份操作已取消，原库保留')

def safe(name):
    from .release_components import safe_name
    return safe_name(name)

def strings(value):
    if isinstance(value,str):yield value
    elif isinstance(value,dict):
        for v in value.values():yield from strings(v)
    elif isinstance(value,list):
        for v in value:yield from strings(v)

def remap(value,mapping):
    if isinstance(value,str):return mapping.get(value,value)
    if isinstance(value,dict):return {k:remap(v,mapping) for k,v in value.items()}
    if isinstance(value,list):return [remap(v,mapping) for v in value]
    return value

def create(store,archive,cancel=None,progress=None):
    archive=Path(archive).resolve()
    if archive.exists():raise ValueError('备份文件已存在，请另选名称')
    archive.parent.mkdir(parents=True,exist_ok=True)
    pending=archive.with_name(archive.name+'.'+uuid.uuid4().hex+'.pending')
    try:
        with hold(store.root,cancel),tempfile.TemporaryDirectory(prefix='backup-',dir=archive.parent) as temp:
            temp=Path(temp);database=temp/'materials.db'
            with store.connect() as conn:
                schema=conn.execute('PRAGMA user_version').fetchone()[0]
                if schema!=3:raise ValueError('此备份版本不支持当前素材库结构')
                with closing(sqlite3.connect(database)) as out:conn.backup(out)
                source_values=[r[0] for r in conn.execute('SELECT value FROM sources')]
                originals=[r[0] for r in conn.execute('SELECT relative_file FROM materials')]
            files={'materials.db':database}
            from .cache_listing import enumerate_files
            for directory in DIRECTORIES:
                base=store.root/directory
                if base.is_dir():
                    for file in enumerate_files(base):files[file.relative_to(store.root).as_posix()]=file
            for name in SETTINGS:
                file=store.root/name
                if file.is_file():files[name]=file
            for name in originals:
                if not (store.root/name).is_file():raise ValueError('受管原件缺失，未生成不完整备份：'+name)
            # Include owned generated files only when a persisted JSON/recipe
            # actually references them. Ordinary transient outputs stay out.
            pending_json=[p for p in files.values() if p.suffix=='.json'];visited=set()
            values=[]
            for source in source_values:
                try:values.append(json.loads(source))
                except ValueError:pass
            while pending_json or values:
                check(cancel)
                if pending_json:
                    file=pending_json.pop()
                    if file in visited:continue
                    visited.add(file);value=json.loads(file.read_text('utf8'))
                else:value=values.pop()
                for text in strings(value):
                    path=Path(text)
                    if not path.is_absolute():continue
                    path=path.resolve()
                    if not path.is_relative_to(store.root):continue
                    relative=path.relative_to(store.root).as_posix()
                    if relative in files:continue
                    if relative.split('/')[0] not in ('video-output','factory','video-sources','drafts','objects'):continue
                    if path.is_dir():continue
                    if not path.is_file():raise ValueError('作品引用的持久文件缺失：'+relative)
                    files[relative]=path
                    if path.suffix=='.json':pending_json.append(path)
            entries=[]
            with zipfile.ZipFile(pending,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as z:
                for n,(name,file) in enumerate(sorted(files.items())):
                    check(cancel);digest=hashlib.sha256();size=0
                    before=file.stat()
                    with file.open('rb') as src,z.open(safe(name),'w',force_zip64=True) as dst:
                        while block:=src.read(1024*1024):
                            check(cancel);dst.write(block);digest.update(block);size+=len(block)
                    after=file.stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('保存内容在备份时变化，请重试')
                    entries.append({'path':name,'size':size,'sha256':digest.hexdigest()})
                    if progress:progress(n+1,len(files))
                z.writestr('backup.json',json.dumps({'schema':'emojibridge-backup-v1','db_schema':schema,'app_build':'S0176',
                    'original_root':str(store.root),'files':entries},ensure_ascii=False))
            check(cancel);os.replace(pending,archive)
        return {'archive':str(archive),'files':len(entries),'bytes':archive.stat().st_size}
    finally:pending.unlink(missing_ok=True)

def restore(archive,destination,cancel=None,progress=None):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('恢复必须使用尚不存在的新目录，原库不覆盖')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        if z.getinfo('backup.json').file_size>32*1024*1024:raise ValueError('备份清单过大')
        manifest=json.loads(z.read('backup.json'))
        if manifest.get('schema')!='emojibridge-backup-v1' or manifest.get('db_schema')!=3:raise ValueError('不支持的备份版本')
        entries={safe(e['path']):e for e in manifest['files']}
        if len(entries)!=len(manifest['files']) or 'materials.db' not in entries:raise ValueError('备份清单重复或缺失')
        names=set()
        for info in z.infolist():
            name=safe(info.filename)
            if name.casefold() in names or info.is_dir() or stat.S_ISLNK(info.external_attr>>16) or info.flag_bits&1:raise ValueError('归档包含重复、加密或链接成员')
            names.add(name.casefold())
            if name!='backup.json' and (name not in entries or entries[name]['size']!=info.file_size):raise ValueError('备份文件清单不符')
        if len(names)!=len(entries)+1:raise ValueError('备份缺少成员')
        if shutil.disk_usage(destination.parent).free<sum(e['size'] for e in entries.values())+64*1024*1024:raise OSError('恢复空间不足，原库保留')
        with tempfile.TemporaryDirectory(prefix='restore-',dir=destination.parent) as temp:
            stage=Path(temp)/'library';stage.mkdir()
            for n,(name,entry) in enumerate(entries.items()):
                check(cancel);file=stage/name;file.parent.mkdir(parents=True,exist_ok=True);digest=hashlib.sha256()
                with z.open(name) as src,file.open('xb') as out:
                    while block:=src.read(1024*1024):check(cancel);out.write(block);digest.update(block)
                if digest.hexdigest()!=entry['sha256']:raise ValueError('备份内容损坏：'+name)
                if progress:progress(n+1,len(entries))
            old=Path(manifest['original_root'])
            mapping={str(old/name):str(destination/name) for name in entries}
            for name in entries:
                for parent in Path(name).parents:
                    mapping[str(old/parent)]=str(destination/parent)
            mapping[str(old)]=str(destination)
            for name in entries:
                if name.endswith('.json'):
                    file=stage/name;save_json(file,remap(json.loads(file.read_text('utf8')),mapping))
            with closing(sqlite3.connect(stage/'materials.db')) as conn,conn:
                if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('备份数据库损坏')
                if conn.execute('PRAGMA user_version').fetchone()[0]!=3:raise ValueError('备份数据库结构不符')
                for rowid,value in conn.execute('SELECT rowid,value FROM sources').fetchall():
                    try:updated=json.dumps(remap(json.loads(value),mapping),ensure_ascii=False)
                    except ValueError:updated=mapping.get(value,value)
                    conn.execute('UPDATE sources SET value=? WHERE rowid=?',(updated,rowid))
                for (name,) in conn.execute('SELECT relative_file FROM materials'):
                    name=safe(name.replace('\\','/'))
                    if name not in entries or not (stage/name).is_file():raise ValueError('备份缺少受管原件')
            save_json(stage/'restored-backup.json',{'source':str(Path(archive).resolve()),'history_only':True,'note':'重新配置来源目录；任务历史不自动执行'})
            # Windows indexers/AV can briefly hold freshly extracted media.
            # Keep the old library untouched and retry only the atomic publish.
            for attempt in range(20):
                check(cancel)
                if destination.exists():raise ValueError('恢复目标已存在，未覆盖')
                try:os.rename(stage,destination);break
                except PermissionError:
                    if attempt==19:raise
                    time.sleep(.1)
    return {'root':str(destination),'files':len(entries)}
