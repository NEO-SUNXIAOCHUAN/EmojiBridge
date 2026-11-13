"""Cancellable, atomic copies for managed media and explicit exports."""
from pathlib import Path
from uuid import uuid4
from concurrent.futures import CancelledError
import os


def native_path(path):
    path=Path(path).resolve()
    value=str(path)
    if os.name=='nt' and not value.startswith('\\\\?\\'):
        return Path('\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value)
    return path


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise CancelledError('已取消文件处理，原件和已完成文件保留')


def copy_file(source,destination,*,cancel=None):
    source=Path(source);destination=Path(destination)
    check_cancel(cancel)
    temporary=native_path(destination.with_name(destination.name+'.'+uuid4().hex+'.partial'))
    try:
        with native_path(source).open('rb') as src,temporary.open('wb') as dst:
            while chunk:=src.read(1024*1024):
                check_cancel(cancel);dst.write(chunk)
        check_cancel(cancel);temporary.replace(native_path(destination))
        return destination
    finally:temporary.unlink(missing_ok=True)
