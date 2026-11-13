"""Task-start foreground handoff, never a mid-operation retry.

The two-thread attachment route is adapted from CursorTouch/Windows-MCP
b74c507d9e709223a0904cf08019edf55f2a75bb (MIT). See THIRD_PARTY_NOTICES.md.
No global foreground permission change, simulated key or guessed mouse click.
"""
from pathlib import Path
import ctypes
import time
from .windows import user, kernel, guard, StopAutomation


def activate_source(window, exe, cancel=None):
    """Source and destination use the same bounded task-start activation."""
    from .windows import activate
    def cancelled():
        if cancel and Path(cancel).exists():raise StopAutomation('cancel_requested')
    return activate(window,exe,cancel_check=cancelled,accessible_fallback=True)


def _activate_linked(window, exe, cancel=None,previous=None):
    """Only invoked in the disposable window_handoff process."""
    if previous is None:previous=user.GetForegroundWindow()

    def check():
        if cancel and Path(cancel).exists():raise StopAutomation('cancel_requested')
        guard(window,exe,foreground=False)
        for key in (1,2,16,17,18,27,91,92):
            if user.GetAsyncKeyState(key)&0x8000:raise StopAutomation('user_input_in_progress')
        if user.GetForegroundWindow() not in (previous,window.hwnd):
            raise StopAutomation('foreground_changed')

    check()
    if previous==window.hwnd:return
    user.SetForegroundWindow(window.hwnd)
    time.sleep(.04);check()
    if user.GetForegroundWindow()!=window.hwnd:
        current=kernel.GetCurrentThreadId()
        threads=[]
        for handle in (previous,window.hwnd):
            tid=user.GetWindowThreadProcessId(handle,None) if handle else 0
            if tid and tid!=current and tid not in threads:threads.append(tid)
        attached=[];access_denied=False
        try:
            for tid in threads:
                check()
                ctypes.set_last_error(0)
                if user.AttachThreadInput(current,tid,True):attached.append(tid)
                elif ctypes.get_last_error()==5:access_denied=True
            check();user.SetForegroundWindow(window.hwnd)
            check()
            # Raise only the identified window, without move/size/topmost state.
            user.SetWindowPos(window.hwnd,0,0,0,0,0,0x43)
        finally:
            failed=False
            for tid in reversed(attached):
                if not user.AttachThreadInput(current,tid,False):failed=True
            if failed:raise StopAutomation('input_thread_detach_failed')
        time.sleep(.04);check()
        if user.GetForegroundWindow()!=window.hwnd and access_denied:
            raise StopAutomation('foreground_handoff_access_denied')
    if user.GetForegroundWindow()!=window.hwnd:
        raise StopAutomation('foreground_switch_denied')
    guard(window,exe)
