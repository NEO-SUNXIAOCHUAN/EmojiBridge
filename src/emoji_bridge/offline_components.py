"""Install an exact release sidecar without network or touching user media."""
from pathlib import Path,PurePosixPath
import hashlib,json,tempfile,zipfile
from .background_remove import check_cancel

def specification(app,name):
    manifest=Path(app)/'BUILD.json'
    if not manifest.is_file():return None
    return json.loads(manifest.read_text('utf8')).get('optional_components',{}).get(name)

def install(app,cache,name,spec,cancel=None,progress=None):
    filename=spec['filename'];digest=spec['sha256']
    if Path(filename).name!=filename or any(v in filename for v in ('/','\\',':')):
        raise ValueError('invalid_component_filename')
    if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise ValueError('invalid_component_digest')
    app=Path(app).resolve();base=Path(cache).resolve()/name/'bundles';target=base/digest[:16]
    def ready():
        marker=target/'complete.json'
        return marker.is_file() and json.loads(marker.read_text('utf8')).get('sha256')==digest and (target/'packages/ready.json').is_file() and (target/'packages/meme_generator/__init__.py').is_file()
    check_cancel(cancel)
    if ready():return target/'packages'
    choices=[app/filename,app.parent/filename]
    archive=next((p for p in choices if p.is_file()),None)
    if archive is None:
        raise RuntimeError('此包的模板引擎需安装扩展：将同版“模板扩展 ZIP”放在程序文件夹内或旁边，再点击生成；也可改用完整包。作品保留')
    if progress:progress('校验本地模板扩展',0,spec['bytes'])
    sha=hashlib.sha256();done=0
    with archive.open('rb') as source:
        while block:=source.read(1024*1024):
            check_cancel(cancel);sha.update(block);done+=len(block)
            if progress:progress('校验本地模板扩展',done,spec['bytes'])
    if done!=spec['bytes'] or sha.hexdigest()!=digest:raise RuntimeError('模板扩展校验失败；请重新取得同版本扩展，未安装未知文件')
    base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='preparing-',dir=base) as folder:
        stage=Path(folder)/'bundle';packages=stage/'packages';packages.mkdir(parents=True)
        prefix=f'EB/runtime/{name}/';seen=set();total=0
        with zipfile.ZipFile(archive) as z:
            files=[f for f in z.infolist() if not f.is_dir()]
            if len(files)!=spec['file_count']:raise ValueError('component_file_count_changed')
            for index,entry in enumerate(files):
                check_cancel(cancel)
                if not entry.filename.startswith(prefix):raise ValueError('component_path_outside_runtime')
                relative=entry.filename[len(prefix):];parts=PurePosixPath(relative).parts
                if not parts or any(p in ('.','..') or ':' in p or '\\' in p or p.endswith((' ','.')) for p in parts):raise ValueError('invalid_component_path')
                folded=relative.casefold()
                if folded in seen:raise ValueError('duplicate_component_path')
                seen.add(folded);total+=entry.file_size
                if total>spec['unpacked_bytes']:raise ValueError('component_size_changed')
                dest=packages.joinpath(*parts).resolve()
                if not dest.is_relative_to(packages.resolve()):raise ValueError('component_path_outside_runtime')
                dest.parent.mkdir(parents=True,exist_ok=True)
                with z.open(entry) as source,dest.open('xb') as output:
                    while block:=source.read(1024*1024):check_cancel(cancel);output.write(block)
                if progress:progress('安装本地模板扩展',index+1,len(files))
        if total!=spec['unpacked_bytes'] or not (packages/'ready.json').is_file() or not (packages/'meme_generator/__init__.py').is_file():raise ValueError('component_incomplete')
        check_cancel(cancel);(stage/'complete.json').write_text(json.dumps({'sha256':digest}),'utf8')
        try:stage.rename(target)
        except OSError:
            # Another instance may have published the same immutable bundle.
            if not ready():raise
    return target/'packages'
