"""Configure this application's temporary files, never the user's global TEMP.

The small local settings file can point at another disk. Existing launchers and
workers inherit the resolved directory; models and permanent media keep their
existing stores. Invalid explicit locations fail instead of silently filling C.
"""
import json
import os
from pathlib import Path
import tempfile


def configure():
    local = os.environ.get('LOCALAPPDATA')
    config = Path(local)/'EmojiBridge/storage-location.json' if local else None
    location = os.environ.get('EMOJI_BRIDGE_TEMP')
    if not location and config and config.is_file():
        try:
            settings = json.loads(config.read_text('utf-8-sig'))
            location = settings.get('temporary_root')
        except (ValueError, AttributeError) as exc:
            raise ValueError('EmojiBridge 本地保存设置无法读取，请检查临时目录设置') from exc
    if not location:
        # resolve() follows a migrated data directory's junction as well.
        location = Path(local)/'EmojiBridge/temporary' if local else Path(tempfile.gettempdir())/'EmojiBridge'
    root = Path(location).expanduser()
    if not root.is_absolute():
        raise ValueError('EmojiBridge 临时目录必须是绝对路径，请检查本地保存设置')
    root = root.resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=root) as probe:
            probe.write(b'EmojiBridge'); probe.flush()
    except OSError as exc:
        raise OSError('EmojiBridge 临时目录不可写，请恢复目标磁盘或修改本地保存位置') from exc
    os.environ['EMOJI_BRIDGE_TEMP'] = str(root)
    os.environ['TEMP'] = os.environ['TMP'] = str(root)
    # A library may have cached gettempdir() before the desktop entry started.
    tempfile.tempdir = str(root)
    return root
