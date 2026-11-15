"""Release-pinned optional components: streamed verification and atomic activation."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import shutil
import stat
import tempfile
import threading
import uuid

APP = Path(__file__).resolve().parents[2]
LOCK = threading.Lock()
IDS = ('anime', 'fine', 'speech', 'templates')


def catalog(app=None):
    file = Path(app or APP) / 'RELEASE_COMPONENTS.json'
    if not file.is_file(): return None
    data = json.loads(file.read_text('utf-8'))
    if data.get('schema') != 'emojibridge-components-v1': raise ValueError('组件目录版本无效，请重新解压软件')
    return data


def root():
    return Path(os.environ.get('EMOJI_BRIDGE_COMPONENTS',
                str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'EmojiBridge/components')))


def check(cancel):
    if cancel is not None and cancel.is_set(): raise InterruptedError('已取消组件导入，原组件保留')


def digest(path, cancel=None):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            check(cancel); value.update(block)
    return value.hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name or '\x00' in name or path.is_absolute()
            or any(p in ('', '.', '..') or p.rstrip(' .') != p or p.split('.')[0].upper() in
                      {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(10)],*[f'LPT{i}' for i in range(10)]}
                   for p in name.split('/'))):
        raise ValueError('组件包包含不安全路径')
    return name


def bundle(component, app=None):
    data = catalog(app)
    if not data or component not in data['components']: return None
    spec = data['components'][component]
    base = Path(app or APP)
    if all((base / entry['path']).is_file() for entry in spec['files']): return base
    pointer = root() / component / 'current.json'
    try:
        saved = json.loads(pointer.read_text('utf-8'))
        if saved.get('abi') != data['abi'] or saved.get('sha256') != spec['sha256']: return None
        folder = root() / component / 'bundles' / spec['sha256']
        if folder.is_dir(): return folder
    except (OSError, ValueError): pass
    return None


def resolve(component, relative, app=None):
    folder = bundle(component, app)
    return folder / safe_name(relative) if folder else None


def require(component):
    data = catalog()
    if not data: return
    spec = data['components'][component]
    raise RuntimeError(f'需要安装“{spec["title"]}”（下载约 {spec["bytes"]/1024/1024:.0f} MB）。请打开“设置 → 可选组件”，下载后点“导入组件包”；作品已保留。')


def status(app=None, verify=False, cancel=None):
    data = catalog(app)
    if not data: return []
    rows = []
    for ident, spec in data['components'].items():
        folder = bundle(ident, app); state = 'missing'
        if folder:
            state = 'installed'
            for entry in spec['files']:
                check(cancel); file = folder / safe_name(entry['path'])
                try:
                    if file.stat().st_size != entry['size'] or (verify and digest(file, cancel) != entry['sha256']):
                        state = 'corrupt'; break
                except OSError: state = 'corrupt'; break
        elif (root() / ident / 'current.json').is_file(): state = 'incompatible'
        rows.append({k: spec[k] for k in ('title','purpose','bytes','unpacked_bytes','url','filename')} |
                    {'id':ident, 'state':state, 'version':data['abi']})
    return rows


def install(archive, component, app=None, cancel=None, progress=None):
    import zipfile
    data = catalog(app)
    if not data or component not in data['components']: raise ValueError('组件未列入当前版本')
    spec = data['components'][component]; archive = Path(archive)
    if not LOCK.acquire(blocking=False): raise RuntimeError('另一个组件正在导入，请等待完成')
    try:
        check(cancel)
        if archive.stat().st_size != spec['bytes'] or digest(archive, cancel) != spec['sha256']:
            raise ValueError('组件包校验失败或版本不符；请下载当前版本对应的组件，原组件保留')
        destination = root() / component; destination.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(destination).free < spec['unpacked_bytes'] + 64 * 1024 * 1024:
            raise OSError('磁盘空间不足，未开始安装；请释放空间后重试')
        expected = {safe_name(e['path']):e for e in spec['files']}
        with zipfile.ZipFile(archive) as z:
            names = set(); entries = z.infolist()
            if len(entries) != len(expected) + 1: raise ValueError('组件包文件清单不符')
            for entry in entries:
                name = safe_name(entry.filename); key = name.casefold()
                if key in names or entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                    raise ValueError('组件包包含重复文件、链接或不支持的成员')
                names.add(key)
                if name != 'component.json' and (name not in expected or entry.file_size != expected[name]['size']):
                    raise ValueError('组件包文件大小或清单不符')
            if z.getinfo('component.json').file_size > 8 * 1024 * 1024: raise ValueError('组件清单过大')
            manifest = json.loads(z.read('component.json'))
            if manifest != {'schema':'emojibridge-component-v1','id':component,'abi':data['abi'],'files':spec['files']}:
                raise ValueError('组件包版本或内容清单不符')
            with tempfile.TemporaryDirectory(prefix='import-', dir=destination) as staging:
                stage = Path(staging); done = 0
                for name, entry in expected.items():
                    check(cancel); target = stage / name; target.parent.mkdir(parents=True, exist_ok=True)
                    value = hashlib.sha256(); size = 0
                    with z.open(name) as src, target.open('xb') as out:
                        while block := src.read(1024 * 1024):
                            check(cancel); size += len(block)
                            if size > entry['size']: raise ValueError('组件文件超出清单大小')
                            out.write(block); value.update(block); done += len(block)
                            if progress: progress('校验并导入组件', done, spec['unpacked_bytes'])
                    if size != entry['size'] or value.hexdigest() != entry['sha256']: raise ValueError('组件文件校验失败')
                check(cancel)
                bundles = destination / 'bundles'; bundles.mkdir(exist_ok=True)
                # Use immutable validated contents. Reimport may repair a bad old
                # directory without replacing it while workers still use it.
                final = bundles / spec['sha256']
                if final.exists():
                    if any(not (final/n).is_file() or digest(final/n,cancel)!=e['sha256'] for n,e in expected.items()):
                        raise ValueError('现有组件文件损坏，请关闭软件并保留目录后重新安装完整包')
                else:
                    # TemporaryDirectory remains solely for cleanup of this stage.
                    os.replace(stage, final)
                check(cancel)
                pointer = destination / ('current-'+uuid.uuid4().hex+'.tmp')
                try:
                    pointer.write_text(json.dumps({'abi':data['abi'],'sha256':spec['sha256']}), 'utf-8')
                    os.replace(pointer, destination/'current.json')
                finally: pointer.unlink(missing_ok=True)
        return {'text':'组件已导入；重新打开对应工具即可使用。若工具已加载旧组件，请重启软件。'}
    finally: LOCK.release()
