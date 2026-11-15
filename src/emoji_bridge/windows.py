"""Bounded Win32 access for QQ's normal visible windows, not its account files."""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
from dataclasses import dataclass
from pathlib import Path
import time

from PIL import ImageGrab


class StopAutomation(RuntimeError):
    pass


user = c.WinDLL("user32", use_last_error=True)
kernel = c.WinDLL("kernel32", use_last_error=True)
CALLBACK = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)


def api(dll, name, args, result):
    fn = getattr(dll, name)
    fn.argtypes, fn.restype = args, result
    return fn


api(user, "EnumWindows", [CALLBACK, w.LPARAM], w.BOOL)
api(user, "GetWindowThreadProcessId", [w.HWND, c.POINTER(w.DWORD)], w.DWORD)
api(user, "GetWindowRect", [w.HWND, c.POINTER(w.RECT)], w.BOOL)
api(user, "GetClassNameW", [w.HWND, w.LPWSTR, c.c_int], c.c_int)
api(user, "GetForegroundWindow", [], w.HWND)
api(user, "SetForegroundWindow", [w.HWND], w.BOOL)
api(user, "AttachThreadInput", [w.DWORD, w.DWORD, w.BOOL], w.BOOL)
api(kernel, "GetCurrentThreadId", [], w.DWORD)
api(user, "IsWindowVisible", [w.HWND], w.BOOL)
api(user, "IsIconic", [w.HWND], w.BOOL)
api(user, "IsZoomed", [w.HWND], w.BOOL)
api(user, "ShowWindowAsync", [w.HWND, c.c_int], w.BOOL)
api(user, "SetWindowPos", [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT], w.BOOL)
api(user, "GetDpiForWindow", [w.HWND], w.UINT)
api(user, "MonitorFromWindow", [w.HWND,w.DWORD], w.HANDLE)
api(user, "GetAncestor", [w.HWND, w.UINT], w.HWND)
api(user, "GetWindow", [w.HWND, w.UINT], w.HWND)
api(user, "EnumChildWindows", [w.HWND, CALLBACK, w.LPARAM], w.BOOL)
api(user, "GetDlgCtrlID", [w.HWND], c.c_int)
api(user, "IsWindowEnabled", [w.HWND], w.BOOL)
api(user, "GetWindowTextW", [w.HWND, w.LPWSTR, c.c_int], c.c_int)
api(user, "SendMessageTimeoutW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM,
    w.UINT, w.UINT, c.POINTER(c.c_size_t)], w.LPARAM)
api(user, "WindowFromPoint", [w.POINT], w.HWND)
api(user, "GetAsyncKeyState", [c.c_int], c.c_short)
api(user, "SetCursorPos", [c.c_int, c.c_int], w.BOOL)
api(user, "GetCursorPos", [c.POINTER(w.POINT)], w.BOOL)
api(user, "GetSystemMetrics", [c.c_int], c.c_int)
api(user, "SetProcessDpiAwarenessContext", [w.HANDLE], w.BOOL)
api(kernel, "OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)
api(kernel, "QueryFullProcessImageNameW", [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)], w.BOOL)
api(kernel, "CloseHandle", [w.HANDLE], w.BOOL)


class MOUSEINPUT(c.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", c.c_size_t)]


class KEYBDINPUT(c.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", c.c_size_t)]


class INPUTUNION(c.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(c.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", w.DWORD), ("data", INPUTUNION)]


api(user, "SendInput", [w.UINT, c.POINTER(INPUT), c.c_int], w.UINT)
user.SetProcessDpiAwarenessContext(c.c_void_p(-4))


def process_path(pid):
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        buf, size = c.create_unicode_buffer(32768), w.DWORD(32768)
        if kernel.QueryFullProcessImageNameW(handle, 0, buf, c.byref(size)):
            return Path(buf.value)
    finally:
        kernel.CloseHandle(handle)
    return None


def class_name(hwnd):
    buf = c.create_unicode_buffer(256)
    user.GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def pid_of(hwnd):
    pid = w.DWORD()
    user.GetWindowThreadProcessId(hwnd, c.byref(pid))
    return pid.value


def bounds(hwnd):
    rect = w.RECT()
    if not user.GetWindowRect(hwnd, c.byref(rect)):
        raise StopAutomation("window_unavailable")
    return (rect.left, rect.top, rect.right, rect.bottom)


@dataclass
class Window:
    hwnd: int
    pid: int
    kind: str
    rect: tuple[int, int, int, int]
    dpi: int


class MONITORINFO(c.Structure):
    _fields_=[('cbSize',w.DWORD),('rcMonitor',w.RECT),('rcWork',w.RECT),('dwFlags',w.DWORD)]


api(user,'GetMonitorInfoW',[w.HANDLE,c.POINTER(MONITORINFO)],w.BOOL)


def monitor_work_area(hwnd):
    monitor=user.MonitorFromWindow(hwnd,2)
    info=MONITORINFO();info.cbSize=c.sizeof(info)
    if not monitor or not user.GetMonitorInfoW(monitor,c.byref(info)):
        raise StopAutomation('display_work_area_unavailable')
    r=info.rcWork;return (r.left,r.top,r.right,r.bottom)


def fitted_window_rect(rect,area):
    width,height=rect[2]-rect[0],rect[3]-rect[1]
    if width>area[2]-area[0] or height>area[3]-area[1]:
        raise StopAutomation('display_too_small_for_calibrated_window')
    x=min(max(rect[0],area[0]),area[2]-width);y=min(max(rect[1],area[1]),area[3]-height)
    return (x,y,x+width,y+height)


def visual_window_rect(rect,area,dpi):
    """At a visual task boundary keep all four edges inside the work area.

    Win32 outer rectangles include invisible resize borders. A small inset also
    leaves room for Qt popup shadows; no primary-screen/absolute-origin guess.
    """
    scale=dpi/96;gap=max(8,round(12*scale))
    safe=(area[0]+gap,area[1]+gap,area[2]-gap,area[3]-gap)
    width=min(max(rect[2]-rect[0],round(760*scale)),safe[2]-safe[0])
    height=min(max(rect[3]-rect[1],round(550*scale)),safe[3]-safe[1])
    if width<700*scale or height<500*scale:
        raise StopAutomation('display_too_small_for_calibrated_window')
    return fitted_window_rect((rect[0],rect[1],rect[0]+width,rect[1]+height),safe)


def ensure_window_on_screen(window,exe):
    """Task-boundary placement only; retain tested size, identity and DPI."""
    guard(window,exe,foreground=False)
    desired=fitted_window_rect(window.rect,monitor_work_area(window.hwnd))
    if desired==window.rect:return window
    if user.IsZoomed(window.hwnd):raise StopAutomation('calibrated_window_placement_failed')
    if not user.SetWindowPos(window.hwnd,0,desired[0],desired[1],0,0,0x15):
        raise StopAutomation('calibrated_window_placement_failed')
    time.sleep(.3)
    updated=Window(window.hwnd,window.pid,window.kind,bounds(window.hwnd),int(user.GetDpiForWindow(window.hwnd)))
    guard(updated,exe,foreground=False)
    if updated.rect!=desired or updated.dpi!=window.dpi:
        raise StopAutomation('calibrated_window_placement_unconfirmed')
    return updated


def qq_windows(exe: Path, include_inactive=False) -> list[Window]:
    found, paths = [], {}

    @CALLBACK
    def callback(hwnd, _):
        if not include_inactive and (not user.IsWindowVisible(hwnd) or user.IsIconic(hwnd)):
            return True
        pid = pid_of(hwnd)
        if pid not in paths:
            paths[pid] = process_path(pid)
        if paths[pid] == exe:
            found.append(Window(int(hwnd), pid, class_name(hwnd), bounds(hwnd),
                                int(user.GetDpiForWindow(hwnd))))
        return True

    user.EnumWindows(callback, 0)
    return found


class WINDOWPLACEMENT(c.Structure):
    _fields_=[('length',w.UINT),('flags',w.UINT),('showCmd',w.UINT),
              ('ptMinPosition',w.POINT),('ptMaxPosition',w.POINT),('rcNormalPosition',w.RECT)]


api(user,'GetWindowPlacement',[w.HWND,c.POINTER(WINDOWPLACEMENT)],w.BOOL)


def normal_bounds(window):
    if not user.IsIconic(window.hwnd):return window.rect
    placement=WINDOWPLACEMENT();placement.length=c.sizeof(placement)
    if not user.GetWindowPlacement(window.hwnd,c.byref(placement)):
        raise StopAutomation('window_unavailable')
    r=placement.rcNormalPosition
    return (r.left,r.top,r.right,r.bottom)


def restorable_main(exe,kind,min_size,dpi,hidden_size=None):
    """Restore only one identified main window, including a tray/minimized one.

    No launch/login, guessed tray clicks, focus forcing, or dismissal of dialogs.
    Called at a task boundary, never as a reaction to a mid-click guard failure.
    """
    candidates=[]
    for window in qq_windows(exe,include_inactive=True):
        if window.kind!=kind or (window.dpi!=dpi if dpi is not None else window.dpi not in (96,120,144)):continue
        rect=window.rect
        if user.IsIconic(window.hwnd):
            placement=WINDOWPLACEMENT();placement.length=c.sizeof(placement)
            if not user.GetWindowPlacement(window.hwnd,c.byref(placement)):continue
            r=placement.rcNormalPosition;rect=(r.left,r.top,r.right,r.bottom)
        size=(rect[2]-rect[0],rect[3]-rect[1])
        if hidden_size and not user.IsWindowVisible(window.hwnd) and size!=tuple(hidden_size):continue
        if size[0]>=min_size[0] and size[1]>=min_size[1]:candidates.append(window)
    # A minimized visible main window takes precedence over dormant auxiliary
    # windows (QQ keeps several hidden Chrome windows of ordinary size).
    visible=[v for v in candidates if user.IsWindowVisible(v.hwnd)]
    if visible:candidates=visible
    if len(candidates)!=1:raise StopAutomation('client_main_window_missing_or_ambiguous')
    window=candidates[0]
    if pid_of(window.hwnd)!=window.pid or process_path(window.pid)!=exe:raise StopAutomation('process_identity_changed')
    if not user.IsWindowVisible(window.hwnd) or user.IsIconic(window.hwnd):
        if not user.ShowWindowAsync(window.hwnd,9):raise StopAutomation('client_restore_failed')
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if user.IsWindowVisible(window.hwnd) and not user.IsIconic(window.hwnd):break
            time.sleep(.05)
        # Re-enumerate geometry after restore. Never reuse minimized coordinates.
        found=[v for v in qq_windows(exe) if v.hwnd==window.hwnd and v.pid==window.pid]
        if len(found)!=1:raise StopAutomation('client_restore_unconfirmed')
        window=found[0]
    return window


def guard(window: Window, exe: Path, foreground=True, owner=None):
    if user.GetAsyncKeyState(0x1B) & 0x8000:
        raise StopAutomation("cancelled_escape")
    if pid_of(window.hwnd) != window.pid or process_path(window.pid) != exe:
        raise StopAutomation("process_identity_changed")
    if not user.IsWindowVisible(window.hwnd) or user.IsIconic(window.hwnd):
        raise StopAutomation("window_not_visible")
    if int(user.GetDpiForWindow(window.hwnd)) != window.dpi:
        raise StopAutomation('client_display_scale_changed')
    if bounds(window.hwnd) != window.rect:
        raise StopAutomation("window_moved_or_resized")
    if foreground and user.GetForegroundWindow() != window.hwnd:
        if owner is None or owner.pid!=window.pid or (user.GetAncestor(window.hwnd,3)!=owner.hwnd and user.GetWindow(window.hwnd,4)!=owner.hwnd):
            raise StopAutomation("foreground_changed")
        guard(owner,exe)


def activate(window: Window, exe: Path, cancel_check=None, accessible_fallback=False,observe=None):
    """One bounded handoff at bind time, never a retry around a failed click.

    Never attach this thread's input queue. A short-lived, bounded helper shares
    the same handoff for source reads and transfers. If denied, use a proven
    native caption or explicitly enabled root SetFocus.
    An intervening foreground switch cancels the handoff.
    """
    if cancel_check:cancel_check()
    guard(window, exe, foreground=False)
    previous = user.GetForegroundWindow()
    note=observe or (lambda stage:None)
    if previous != window.hwnd:
        note('set_foreground_begin')
        user.SetForegroundWindow(window.hwnd)
        note('set_foreground_end')
        time.sleep(0.3)
        if cancel_check:cancel_check()
        foreground = user.GetForegroundWindow()
        if foreground != window.hwnd:
            if foreground != previous:raise StopAutomation('foreground_changed')
            for key in (0x01,0x02,0x10,0x11,0x12,0x5B,0x5C):
                if user.GetAsyncKeyState(key) & 0x8000:raise StopAutomation('user_input_in_progress')
            guard(window,exe,foreground=False)
            if accessible_fallback and user.GetForegroundWindow()==previous:
                from .window_handoff import handoff
                note('bounded_handoff_begin')
                try:handoff(window,exe,previous,cancel_check)
                except StopAutomation as exc:
                    if str(exc) not in ('foreground_switch_denied','foreground_handoff_unavailable'):raise
                note('bounded_handoff_end')
            if user.GetForegroundWindow()==previous:
                note('caption_begin')
                activate_caption(window,exe,previous)
                note('caption_end')
            if accessible_fallback and user.GetForegroundWindow()==previous:
                note('accessible_focus_begin')
                activate_accessible(window,exe,previous,cancel_check)
                note('accessible_focus_end')
    if cancel_check:cancel_check()
    if previous!=window.hwnd and user.GetForegroundWindow()==previous:
        guard(window,exe,foreground=False)
        raise StopAutomation('foreground_switch_denied')
    guard(window, exe)


def activate_accessible(window,exe,previous,cancel_check=None):
    """Activate via a proven navigation edit, never a guessed chat point."""
    from .uia_worker import UIAWorker
    from .paths import APP_ROOT
    def check():
        if cancel_check:cancel_check()
        guard(window,exe,foreground=False)
        current=user.GetForegroundWindow()
        if current not in (previous,window.hwnd):
            raise StopAutomation('foreground_changed')
        for key in (1,2,16,17,18,91,92):
            if user.GetAsyncKeyState(key)&0x8000:raise StopAutomation('user_input_in_progress')
    check()
    helper=UIAWorker(APP_ROOT/'scripts/window_focus.ps1')
    try:
        payload=dict(window=window.hwnd,pid=window.pid,exe=str(exe),kind=window.kind,
                     rect=list(window.rect),dpi=window.dpi,previous=previous)
        if window.kind=='Chrome_WidgetWin_1':
            prepared=helper.request(cancel_check=check,timeout_seconds=4,action='prepare',**payload)
            if not prepared.get('ok'):raise StopAutomation(prepared.get('reason','foreground_switch_denied'))
            if user.GetForegroundWindow()==window.hwnd:return
            rect=prepared.get('focus_rect',())
            if len(rect)!=4 or not (window.rect[0]<=rect[0]<rect[2]<=window.rect[2]
                                  and window.rect[1]<=rect[1]<rect[3]<=window.rect[3]):
                raise StopAutomation('foreground_focus_geometry_changed')
            # QQ SetFocus can activate an invisible Chromium parking window.
            # Click the unique current navigation search edit instead. No text,
            # conversation choice or message submission is involved.
            check();user.SetWindowPos(window.hwnd,0,0,0,0,0,0x13)
            fresh=helper.request(cancel_check=check,timeout_seconds=4,action='prepare',**payload)
            if fresh.get('ok') and user.GetForegroundWindow()==window.hwnd:return
            if not fresh.get('ok') or fresh.get('focus_rect')!=rect or fresh.get('focus_runtime')!=prepared.get('focus_runtime'):
                raise StopAutomation('foreground_focus_geometry_changed')
            x,y=round((rect[0]+rect[2])/2),round((rect[1]+rect[3])/2)
            if user.GetAncestor(user.WindowFromPoint(w.POINT(x,y)),2)!=window.hwnd:
                raise StopAutomation('target_occluded')
            check();old=w.POINT();user.GetCursorPos(c.byref(old))
            try:
                pointer_click(x,y)
                deadline=time.monotonic()+.8
                while user.GetForegroundWindow()!=window.hwnd and time.monotonic()<deadline:
                    check();time.sleep(.03)
            finally:restore_pointer((old.x,old.y),(x,y))
        else:
            result=helper.request(cancel_check=check,timeout_seconds=4,**payload)
            if not result.get('ok'):raise StopAutomation(result.get('reason','foreground_switch_denied'))
    finally:helper.close()
    check()


def pointer_click(x,y,right=False):
    """Position and click in one SendInput batch; never block physical input."""
    left,top,width,height=(user.GetSystemMetrics(n) for n in (76,77,78,79))
    if width<=0 or height<=0 or not(left<=x<left+width and top<=y<top+height):
        raise StopAutomation('point_outside_desktop')
    events=(INPUT*3)()
    # Pixel centres, including negative coordinates on secondary monitors.
    events[0].mi.dx=min(65535,int((x-left+.5)*65536/width))
    events[0].mi.dy=min(65535,int((y-top+.5)*65536/height))
    events[0].mi.dwFlags=0x0001|0x8000|0x4000
    events[1].mi.dwFlags,events[2].mi.dwFlags=(8,16) if right else (2,4)
    if user.SendInput(3,events,c.sizeof(INPUT))!=3:
        raise StopAutomation('input_not_delivered')


def activate_caption(window: Window,exe: Path,previous):
    """Last task-start fallback: one click on a proven native title bar.

    Never click guessed client content to gain focus. NCHITTEST must explicitly
    identify HTCAPTION, and the point must belong to this visible target.
    """
    guard(window,exe,foreground=False)
    if user.GetForegroundWindow()!=previous:raise StopAutomation('foreground_changed')
    for key in (0x01,0x02,0x10,0x11,0x12,0x5B,0x5C):
        if user.GetAsyncKeyState(key)&0x8000:raise StopAutomation('user_input_in_progress')
    left,top,right,bottom=window.rect;x=(left+right)//2;y=top+12
    result=c.c_size_t()
    packed=((y&0xffff)<<16)|(x&0xffff)
    # WM_NCHITTEST; HTCAPTION=2. Custom title bars that do not prove it stop.
    if not user.SendMessageTimeoutW(window.hwnd,0x84,0,packed,0x2,200,c.byref(result)) or result.value!=2:return
    user.SetWindowPos(window.hwnd,0,0,0,0,0,0x13)  # TOP, no move/resize/activation
    time.sleep(.05)
    at=user.WindowFromPoint(w.POINT(x,y))
    if user.GetAncestor(at,2)!=window.hwnd:return
    guard(window,exe,foreground=False)
    if user.GetForegroundWindow()!=previous:raise StopAutomation('foreground_changed')
    old=w.POINT();user.GetCursorPos(c.byref(old))
    try:
        guard(window,exe,foreground=False)
        if user.GetForegroundWindow()!=previous:raise StopAutomation('foreground_changed')
        pointer_click(x,y)
        time.sleep(.15)
    finally:
        restore_pointer((old.x,old.y),(x,y))


def capture(window: Window):
    # QQ's GPU surface was black through PrintWindow on the tested version.
    # Screen capture is allowed only while this exact QQ window is foreground.
    if user.GetForegroundWindow() != window.hwnd:
        raise StopAutomation("capture_requires_foreground")
    picture = ImageGrab.grab(bbox=window.rect, all_screens=True)
    if picture.size != (window.rect[2] - window.rect[0], window.rect[3] - window.rect[1]):
        raise StopAutomation("capture_dimensions_mismatch")
    return picture.convert("RGB")


def click(window: Window, exe: Path, x: int, y: int, right=False, owner=None):
    guard(window, exe,owner=owner)
    if not (0 <= x < window.rect[2]-window.rect[0] and 0 <= y < window.rect[3]-window.rect[1]):
        raise StopAutomation("point_outside_window")
    for key in (0x01, 0x02, 0x10, 0x11, 0x12, 0x5B, 0x5C):
        if user.GetAsyncKeyState(key) & 0x8000:
            raise StopAutomation("user_input_in_progress")
    sx, sy = window.rect[0]+x, window.rect[1]+y
    at = user.WindowFromPoint(w.POINT(sx, sy))
    if user.GetAncestor(at, 2) != window.hwnd:
        raise StopAutomation("target_occluded")
    previous = w.POINT()
    user.GetCursorPos(c.byref(previous))
    guard(window, exe,owner=owner)
    pointer_click(sx,sy,right)
    # Restore only if the user has not moved the pointer meanwhile.
    now = w.POINT()
    user.GetCursorPos(c.byref(now))
    if (now.x, now.y) == (sx, sy):
        user.SetCursorPos(previous.x, previous.y)


def escape(window,exe,owner=None):
    guard(window,exe,owner=owner)
    for key in (0x01,0x02,0x10,0x11,0x12,0x5B,0x5C):
        if user.GetAsyncKeyState(key)&0x8000:raise StopAutomation('user_input_in_progress')
    events=(INPUT*2)()
    for event in events:event.type=1;event.ki.wVk=0x1B
    events[1].ki.dwFlags=2
    if user.SendInput(2,events,c.sizeof(INPUT))!=2:raise StopAutomation('input_not_delivered')
    time.sleep(.3)


def hover(window: Window, exe: Path, x: int, y: int):
    """Preview an identified sticker without clicking/sending it."""
    guard(window,exe)
    for key in (0x01,0x02,0x10,0x11,0x12,0x5B,0x5C):
        if user.GetAsyncKeyState(key)&0x8000:raise StopAutomation('user_input_in_progress')
    sx,sy=window.rect[0]+x,window.rect[1]+y
    if not (window.rect[0]<=sx<window.rect[2] and window.rect[1]<=sy<window.rect[3]):
        raise StopAutomation('point_outside_window')
    if user.GetAncestor(user.WindowFromPoint(w.POINT(sx,sy)),2)!=window.hwnd:
        raise StopAutomation('target_occluded')
    previous=w.POINT();user.GetCursorPos(c.byref(previous))
    if not user.SetCursorPos(sx,sy):
        raise StopAutomation('cursor_unavailable')
    return (previous.x,previous.y),(sx,sy)


def restore_pointer(previous, expected):
    now=w.POINT();user.GetCursorPos(c.byref(now))
    if (now.x,now.y)==expected:user.SetCursorPos(*previous)


def pointer_scroll(x,y,notches):
    """Move and wheel atomically so physical pointer motion cannot retarget it."""
    left,top,width,height=(user.GetSystemMetrics(n) for n in (76,77,78,79))
    if width<=0 or height<=0 or not(left<=x<left+width and top<=y<top+height):
        raise StopAutomation('point_outside_desktop')
    events=(INPUT*2)()
    events[0].mi.dx=min(65535,int((x-left+.5)*65536/width))
    events[0].mi.dy=min(65535,int((y-top+.5)*65536/height))
    events[0].mi.dwFlags=0x0001|0x8000|0x4000
    events[1].mi.dwFlags=0x0800;events[1].mi.mouseData=c.c_uint32(notches*120).value
    if user.SendInput(2,events,c.sizeof(INPUT))!=2:raise StopAutomation('scroll_input_not_delivered')


def scroll(window,exe,x,y,notches):
    """Bounded wheel gesture inside an already identified client panel."""
    if not isinstance(notches,int) or not 1<=abs(notches)<=3:
        raise StopAutomation('invalid_scroll_distance')
    previous,expected=hover(window,exe,x,y)
    try:
        guard(window,exe)
        pointer_scroll(*expected,notches)
    finally:restore_pointer(previous,expected)


def dialog_controls(dialog):
    found = []

    @CALLBACK
    def callback(hwnd, _):
        kind, ident = class_name(hwnd), user.GetDlgCtrlID(hwnd)
        if (kind, ident) in (('Edit', 1148), ('Edit', 1001), ('Button', 1), ('Button', 2)):
            found.append({'hwnd':int(hwnd),'class':kind,'id':ident})
        return True

    user.EnumChildWindows(dialog.hwnd, callback, 0)
    return found


def dialog_owned_by(dialog, owner):
    parent = user.GetWindow(dialog.hwnd, 4)
    return (dialog.pid == owner.pid and bool(parent)
            and (parent == owner.hwnd or user.GetAncestor(parent, 2) == owner.hwnd))


def foreground_dialog(owner, exe):
    """Inspect a foreground picker even before it has WS_VISIBLE.

    This is transition evidence only. Never permits input into a hidden shell.
    """
    hwnd = user.GetForegroundWindow()
    if not hwnd or hwnd == owner.hwnd:
        return None
    if pid_of(hwnd) != owner.pid or process_path(owner.pid) != exe:
        return None
    if class_name(hwnd) != '#32770':
        return None
    dialog = Window(hwnd, owner.pid, '#32770', bounds(hwnd), int(user.GetDpiForWindow(hwnd)))
    return dialog if dialog_owned_by(dialog, owner) else None


def filename_is_empty(dialog, exe):
    """Read only the native filename edit; never expose its contents."""
    guard(dialog, exe)
    edits = [v['hwnd'] for v in dialog_controls(dialog) if (v['class'], v['id']) == ('Edit', 1148)]
    if len(edits) != 1:
        raise StopAutomation('file_name_control_unavailable')
    edit = edits[0]
    if pid_of(edit) != dialog.pid or user.GetAncestor(edit, 2) != dialog.hwnd:
        raise StopAutomation('native_control_identity_changed')
    value = c.create_unicode_buffer(32768); result = c.c_size_t()
    if not user.SendMessageTimeoutW(edit, 0x000D, len(value), c.addressof(value), 2, 2000, c.byref(result)):
        raise StopAutomation('native_message_timeout')
    return not value.value


def selection_text(files,batch_limit=None):
    """Native open-dialog selection, independent of its starting directory."""
    files=list(files)
    from .limits import QQ_BATCH_LIMIT
    limit=QQ_BATCH_LIMIT if batch_limit is None else batch_limit
    if not files or len(files)>limit:raise StopAutomation('batch_selection_limit')
    paths=[Path(p) for p in files]
    if any(not p.is_absolute() or not p.is_file() or '"' in str(p) for p in paths):
        raise StopAutomation('absolute_existing_file_required')
    if len({str(p.resolve()).casefold() for p in paths})!=len(paths):
        raise StopAutomation('duplicate_file_selection')
    value=' '.join('"'+str(p)+'"' for p in paths)
    if len(value)>=30000:raise StopAutomation('batch_path_length_limit')
    return value


def dialog_action(dialog, owner, exe, action, file=None, before_submit=None, output_root=None,batch_limit=None):
    guard(dialog, exe)
    if not dialog_owned_by(dialog, owner):
        raise StopAutomation('wrong_dialog_owner')
    controls = dialog_controls(dialog)

    def control(kind, ident):
        targets = [x['hwnd'] for x in controls if x['class']==kind and x['id']==ident]
        if len(targets)!=1 or not user.IsWindowEnabled(targets[0]):
            raise StopAutomation('native_dialog_control_not_unique_or_disabled')
        return targets[0]

    def send(hwnd, message, value=0, parameter=0):
        guard(dialog, exe)
        if pid_of(hwnd) != owner.pid or user.GetAncestor(hwnd,2) != dialog.hwnd:
            raise StopAutomation('native_control_identity_changed')
        result = c.c_size_t()
        if not user.SendMessageTimeoutW(hwnd,message,parameter,value,2,5000,c.byref(result)):
            raise StopAutomation('native_message_timeout')
        return result.value

    if action=='Probe':
        return {'ok':True,'controls':controls}
    if action=='Cancel':
        send(control('Button',2),0x00F5)
        return {'ok':True,'action':action}
    def validate_file():
        if action=='ChooseMany':
            selection_text(file,batch_limit)
        elif action=='Choose':
            if file is None or not file.is_absolute() or not file.is_file():
                raise StopAutomation('absolute_existing_file_required')
        elif action=='SaveNew':
            if (file is None or not file.is_absolute() or output_root is None
                    or not Path(output_root).is_absolute() or not Path(output_root).is_dir()
                    or not file.resolve().is_relative_to(Path(output_root).resolve())
                    or not file.parent.is_dir() or file.exists()):
                raise StopAutomation('new_file_inside_output_root_required')
        else:
            raise StopAutomation('unsupported_dialog_action')
    validate_file()
    if action=='SaveNew' and not any(x['class']=='Edit' and x['id']==1148 for x in controls):
        edit=control('Edit',1001)
        if class_name(user.GetParent(edit))!='ComboBox' or bounds(edit)[1]<dialog.rect[1]+(dialog.rect[3]-dialog.rect[1])//2:
            raise StopAutomation('save_filename_control_not_identified')
    else:
        edit = control('Edit',1148)
    text=selection_text(file,batch_limit) if action=='ChooseMany' else str(file)
    value = c.create_unicode_buffer(text)
    if not send(edit,0x000C,c.addressof(value)):
        raise StopAutomation('file_path_set_failed')
    actual = c.create_unicode_buffer(32768)
    # GetWindowText does not retrieve another process's edit text. WM_GETTEXT does.
    send(edit,0x000D,c.addressof(actual),len(actual))
    if actual.value != text:
        raise StopAutomation('file_path_readback_mismatch')
    button = control('Button',1)
    if action=='SaveNew':
        label=c.create_unicode_buffer(256)
        send(button,0x000D,c.addressof(label),len(label))
        if not any(word in label.value for word in ('保存','另存为','Save','save')):
            raise StopAutomation('save_button_not_identified')
    if before_submit is not None:
        before_submit()
    validate_file()
    send(button,0x00F5)
    return {'ok':True,'action':action,'absolutePathVerified':True,
            'selected_count':len(file) if action=='ChooseMany' else 1}


def file_version(path):
    version = c.WinDLL('version', use_last_error=True)
    api(version,'GetFileVersionInfoSizeW',[w.LPCWSTR,c.POINTER(w.DWORD)],w.DWORD)
    api(version,'GetFileVersionInfoW',[w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p],w.BOOL)
    api(version,'VerQueryValueW',[c.c_void_p,w.LPCWSTR,c.POINTER(c.c_void_p),c.POINTER(w.UINT)],w.BOOL)
    unused = w.DWORD()
    size = version.GetFileVersionInfoSizeW(str(path),c.byref(unused))
    if not size:
        raise StopAutomation('file_version_unavailable')
    data = c.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path),0,size,data):
        raise StopAutomation('file_version_unavailable')
    pointer,length = c.c_void_p(),w.UINT()
    if not version.VerQueryValueW(data,'\\',c.byref(pointer),c.byref(length)) or length.value<16:
        raise StopAutomation('file_version_unavailable')
    fields = c.cast(pointer,c.POINTER(w.DWORD))
    if fields[0] != 0xFEEF04BD:
        raise StopAutomation('invalid_version_signature')
    return '.'.join(str(x) for x in (fields[2]>>16,fields[2]&65535,fields[3]>>16,fields[3]&65535))
