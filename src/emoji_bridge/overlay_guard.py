"""Optional desktop-host handshake at the existing foreground lock boundary."""
from contextlib import contextmanager
import json,os
from urllib.request import Request,urlopen

def process_alive(pid):
    import ctypes as c
    from ctypes import wintypes as w
    k=c.WinDLL('kernel32',use_last_error=True);k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
    k.GetExitCodeProcess.argtypes=[w.HANDLE,c.POINTER(w.DWORD)];k.CloseHandle.argtypes=[w.HANDLE]
    handle=k.OpenProcess(0x1000,False,int(pid))
    if not handle:return c.get_last_error()!=87
    code=w.DWORD()
    try:return not k.GetExitCodeProcess(handle,c.byref(code)) or code.value==259
    finally:k.CloseHandle(handle)

@contextmanager
def hidden_overlays(token):
    endpoint=os.environ.get('EMOJI_BRIDGE_OVERLAY_ENDPOINT')
    def change(value):
        payload=json.dumps({'token':token,'hide':value,'pid':os.getpid()}).encode()
        with urlopen(Request(endpoint,data=payload,headers={'Content-Type':'application/json'}),timeout=5) as reply:
            return json.load(reply)
    if not endpoint:
        yield;return
    try:
        try:change(True)
        except OSError as exc:
            pid=os.environ.get('EMOJI_BRIDGE_OVERLAY_HOST_PID')
            if pid and not process_alive(pid):
                yield;return
            raise RuntimeError('素材小窗未能收起，本次未开始操作客户端；请关闭小窗后重试。') from exc
        yield
    finally:
        # No retries of client work. Restoration is independent of task outcome.
        try:change(False)
        except OSError:pass
