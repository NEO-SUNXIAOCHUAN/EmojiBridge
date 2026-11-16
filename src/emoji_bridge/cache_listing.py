"""Read a user-selected cache into a presentation index, never MaterialStore.

Names/extensions and current QQ favorites membership are not content identity.
The index owns thumbnails only. A use operation takes a validated temporary copy.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from concurrent.futures import CancelledError

from PIL import Image, ImageOps
from .media import inspect
from .frame_store import MAX_INPUT_BYTES
from .state import save_json, sha

EXTENSIONS = {'PNG': '.png', 'JPEG': '.jpg', 'GIF': '.gif', 'WEBP': '.webp', 'BMP': '.bmp'}

class Cancellation:
    def __init__(self,callback):self.callback=callback
    def is_set(self):return self.callback()


def signature(path):
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text('utf-8'))
    except FileNotFoundError:
        return default


def enumerate_files(root):
    """Bound discovery to the selected directory; never traverse linked trees."""
    def unavailable(error):raise OSError('目录暂不可读，未将原列表当作删除：'+str(error))
    for base, dirs, files in os.walk(root, followlinks=False,onerror=unavailable):
        dirs[:] = sorted(d for d in dirs if not Path(base, d).is_symlink()
                         and not (Path(base, d).stat().st_file_attributes & 0x400 if os.name == 'nt' else False))
        for name in sorted(files):
            file = Path(base, name)
            if not file.is_symlink() and file.is_file():
                yield file


def scan(root, index_path, *, cancel=lambda: False, progress=None):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('请选择个人表情缓存目录')
    index_path = Path(index_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index = read_json(index_path, {'schema': 'cache-read-v1', 'root': str(root), 'files': {}})
    if index.get('root') != str(root) or index.get('schema') != 'cache-read-v1':
        index = {'schema': 'cache-read-v1', 'root': str(root), 'files': {}}
    files = list(enumerate_files(root))
    current = {str(f.relative_to(root)) for f in files}
    index['files'] = {k: v for k, v in index['files'].items() if k in current}
    counts = dict(discovered=len(files), ready=0, unchanged=0, failed=0, waiting=0, remaining=len(files))
    index.update(state='reading', counts=counts)
    save_json(index_path, index)
    for n, file in enumerate(files):
        if cancel():
            break
        key = str(file.relative_to(root))
        old = index['files'].get(key, {})
        try:
            before = signature(file)
            if before == old.get('signature') and old.get('state') == 'ready' and Path(old['preview']).is_file():
                counts['unchanged'] += 1
            else:
                if not 0 < before[0] <= MAX_INPUT_BYTES:
                    raise ValueError('文件为空或超过本地媒体大小限制')
                # A writer may still hold a valid partial GIF. Recent writes
                # wait for a later enumeration instead of accepting first-frame success.
                if time.time_ns() - before[1] < 200_000_000:
                    raise BlockingIOError('文件仍在写入，请稍后点击更新重试')
                with tempfile.TemporaryDirectory(prefix='read-', dir=index_path.parent) as temp:
                    copy = Path(temp) / 'media'
                    digest = hashlib.sha256()
                    with file.open('rb') as src, copy.open('wb') as dst:
                        total = 0
                        while chunk := src.read(1024 * 1024):
                            if cancel():
                                raise InterruptedError('读取已取消')
                            total += len(chunk)
                            if total > MAX_INPUT_BYTES:
                                raise ValueError('文件超过本地媒体大小限制')
                            digest.update(chunk); dst.write(chunk)
                    if before != signature(file):
                        raise BlockingIOError('文件变化，稍后重试')
                    metadata, _ = inspect(copy,cancel=Cancellation(cancel))
                    if metadata['format'] not in EXTENSIONS:
                        raise ValueError('暂不支持此图片格式')
                    ident = digest.hexdigest()
                    cover = index_path.parent / 'previews' / (ident + '.png')
                    if not cover.exists():
                        cover.parent.mkdir(parents=True, exist_ok=True)
                        with Image.open(copy) as image:
                            image = ImageOps.exif_transpose(image).convert('RGBA')
                            image.thumbnail((384, 384), Image.Resampling.LANCZOS)
                            output = Path(temp) / 'preview.png'; image.save(output)
                            os.replace(output, cover)
                index['files'][key] = dict(state='ready', signature=before, path=str(file),
                    sha256=ident, metadata=metadata, preview=str(cover), discovered_at=old.get('discovered_at') or time.time())
            counts['ready'] += 1
        except (InterruptedError,CancelledError):
            break
        except (OSError, ValueError) as exc:
            waiting = isinstance(exc, BlockingIOError)
            counts['waiting' if waiting else 'failed'] += 1
            index['files'][key] = dict(state='waiting' if waiting else 'failed', path=str(file), reason=str(exc))
        counts['remaining'] = len(files) - n - 1
        if n % 16 == 0:
            save_json(index_path, index)
        if progress:
            progress(n + 1, len(files), dict(counts))
    index.update(state='cancelled' if cancel() else 'complete', updated_at=time.time())
    save_json(index_path, index)
    return index


def catalog_side(index):
    items = []
    for key, value in index['files'].items():
        if value['state'] != 'ready':
            continue
        item_id = hashlib.sha256((index['root'] + '\0' + key).encode()).hexdigest()
        items.append(dict(id=item_id, label=Path(key).stem, name_origin='filename',
            cache_file=value['path'], cache_signature=value['signature'],
            source_sha256=value['sha256'], original_state='ready', original_available=True,
            frames=value['metadata'].get('frames', 1), metadata=value['metadata'],
            preview=value['preview'], clear_preview=value['preview'],
            source_kind='personal_cache_file', first_discovered_at=value['discovered_at']))
    return dict(items=items, scope='所选个人表情缓存目录的完整可读文件；不代表当前收藏',
        source_kind='personal_cache_directory', source=index['root'], snapshot_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        complete=index['state']=='complete', counts=index['counts'])


def snapshot(item, destination, cancel=lambda: False):
    """Freeze only the selected content for copy/transfer/import, not library entry."""
    file = Path(item['cache_file']); digest = item['source_sha256']
    destination = Path(destination) / digest
    destination.mkdir(parents=True, exist_ok=True)
    result = destination / ('original' + EXTENSIONS[item['metadata']['format']])
    if signature(file)!=item['cache_signature']:
        raise ValueError('缓存文件已变化，请重新读取；已准备的互通任务仍保留自己的副本')
    if result.is_file() and sha(result) == digest:
        os.utime(result,None)
        return result
    with tempfile.TemporaryDirectory(prefix='snapshot-', dir=destination) as temp:
        staged = Path(temp) / 'media'
        with file.open('rb') as src, staged.open('wb') as dst:
            size = 0
            while chunk := src.read(1024 * 1024):
                if cancel():
                    raise InterruptedError('已取消')
                size += len(chunk)
                if size > MAX_INPUT_BYTES:
                    raise ValueError('文件超过本地媒体大小限制')
                dst.write(chunk)
        if sha(staged) != digest:
            raise ValueError('缓存文件已变化，请重新读取；未使用其他内容代替')
        inspect(staged,cancel=Cancellation(cancel))
        os.replace(staged, result)
    return result
