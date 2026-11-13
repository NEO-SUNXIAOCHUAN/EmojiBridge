"""Native CF_HDROP with a real owner HWND; reused from Pocket v2. """
import os
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path

def _publish_file_handle(user, kernel, owner_hwnd, handle):
    """Transfer a prepared HGLOBAL; OpenClipboard needs an actual owner window."""
    if not owner_hwnd or not user.IsWindow(owner_hwnd):
        kernel.GlobalFree(handle)
        raise RuntimeError('素材窗尚未就绪，无法复制文件')
    if not user.OpenClipboard(owner_hwnd):
        kernel.GlobalFree(handle)
        raise RuntimeError('剪贴板正在被占用，请稍后重试')
    transferred = False
    try:
        if not user.EmptyClipboard():
            raise RuntimeError('无法清空剪贴板，请稍后重试')
        if not user.SetClipboardData(15, handle):
            raise RuntimeError('无法把原文件写入剪贴板')
        transferred = True
    finally:
        if not transferred:
            kernel.GlobalFree(handle)
        user.CloseClipboard()


def copy_file_to_clipboard(path: Path, owner_hwnd: int):
    if os.name != 'nt':
        raise RuntimeError('文件剪贴板原型仅支持 Windows')
    class DROPFILES(c.Structure):
        _fields_ = [('pFiles', w.DWORD), ('pt', w.POINT), ('fNC', w.BOOL), ('fWide', w.BOOL)]
    user = c.WinDLL('user32', use_last_error=True)
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.GlobalAlloc.argtypes, kernel.GlobalAlloc.restype = [w.UINT, c.c_size_t], w.HGLOBAL
    kernel.GlobalLock.argtypes, kernel.GlobalLock.restype = [w.HGLOBAL], c.c_void_p
    kernel.GlobalUnlock.argtypes = [w.HGLOBAL]
    kernel.GlobalFree.argtypes, kernel.GlobalFree.restype = [w.HGLOBAL], w.HGLOBAL
    user.IsWindow.argtypes, user.IsWindow.restype = [w.HWND], w.BOOL
    user.OpenClipboard.argtypes, user.OpenClipboard.restype = [w.HWND], w.BOOL
    user.SetClipboardData.argtypes, user.SetClipboardData.restype = [w.UINT, w.HANDLE], w.HANDLE
    user.EmptyClipboard.argtypes, user.EmptyClipboard.restype = [], w.BOOL
    user.CloseClipboard.argtypes, user.CloseClipboard.restype = [], w.BOOL
    header = DROPFILES(c.sizeof(DROPFILES), w.POINT(0, 0), False, True)
    payload = bytes(header) + (str(path) + '\0\0').encode('utf-16-le')
    handle = kernel.GlobalAlloc(0x42, len(payload))
    if not handle:
        raise c.WinError(c.get_last_error())
    pointer = kernel.GlobalLock(handle)
    if not pointer:
        kernel.GlobalFree(handle)
        raise c.WinError(c.get_last_error())
    c.memmove(pointer, payload, len(payload))
    kernel.GlobalUnlock(handle)
    _publish_file_handle(user, kernel, owner_hwnd, handle)
    return {'ok': True, 'kind': 'file', 'message': '已复制原文件，可粘贴到支持文件的目标'}
