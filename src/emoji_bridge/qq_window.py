"""Shared QQ task boundary: native main identity, restore, fit, activate."""
from pathlib import Path
import time
from . import windows as win
from .client_geometry import client_scale
from .qq_controls import discover_main


def bind_window(exe,version,report,cancel=None,prior=None):
    exe=Path(exe)
    def check(window=None):
        if cancel and Path(cancel).exists():raise win.StopAutomation('cancel_requested')
        if win.file_version(exe)!=version:raise win.StopAutomation('client_version_changed')
        if any(win.user.GetAsyncKeyState(k)&0x8000 for k in (1,2,16,17,18,27,91,92)):
            raise win.StopAutomation('user_input_in_progress')
        if window:
            if (win.pid_of(window.hwnd)!=window.pid or win.process_path(window.pid)!=exe
                    or win.class_name(window.hwnd)!='Chrome_WidgetWin_1'):
                raise win.StopAutomation('process_identity_changed')
            if win.user.GetDpiForWindow(window.hwnd)!=window.dpi:
                raise win.StopAutomation('client_display_scale_changed')
    check()
    if (prior and win.pid_of(prior.hwnd)==prior.pid and win.process_path(prior.pid)==exe
            and (not win.user.IsWindowVisible(prior.hwnd) or win.user.IsIconic(prior.hwnd))):
        window=prior
    else:
        window=discover_main(exe,win.qq_windows(exe,include_inactive=True),cancel,restore_hidden=True)
    check(window);client_scale(window.dpi)
    if not win.user.IsWindowVisible(window.hwnd) or win.user.IsIconic(window.hwnd) or win.user.IsZoomed(window.hwnd):
        win.user.ShowWindowAsync(window.hwnd,9)
        deadline=time.monotonic()+3
        while not win.user.IsWindowVisible(window.hwnd) or win.user.IsIconic(window.hwnd) or win.user.IsZoomed(window.hwnd):
            check(window)
            if time.monotonic()>=deadline:raise win.StopAutomation('client_restore_unconfirmed')
            time.sleep(.05)
        report['window_restored']=True
    def fresh():
        check(window)
        found=[w for w in win.qq_windows(exe) if (w.hwnd,w.pid)==(window.hwnd,window.pid)]
        if len(found)!=1:raise win.StopAutomation('client_restore_unconfirmed')
        return found[0]
    window=fresh()
    identified=discover_main(exe,[window],cancel)
    if (identified.hwnd,identified.pid)!=(window.hwnd,window.pid):raise win.StopAutomation('process_identity_changed')
    # Native controls define the layout. Retain the user's size; only fit an
    # oversized/offscreen window at this task boundary, then re-read geometry.
    area=win.monitor_work_area(window.hwnd)
    width,height=window.rect[2]-window.rect[0],window.rect[3]-window.rect[1]
    target=(min(width,area[2]-area[0]),min(height,area[3]-area[1]))
    scale=client_scale(window.dpi)
    if target[0]<round(600*scale) or target[1]<round(450*scale):
        raise win.StopAutomation('display_too_small_for_calibrated_window')
    if target!=(width,height):
        check(window)
        if not win.user.SetWindowPos(window.hwnd,0,area[0],area[1],*target,0x14):
            raise win.StopAutomation('calibrated_window_resize_failed')
        deadline=time.monotonic()+2
        while True:
            window=fresh()
            if (window.rect[2]-window.rect[0],window.rect[3]-window.rect[1])==target:break
            if time.monotonic()>=deadline:raise win.StopAutomation('calibrated_window_resize_failed')
            time.sleep(.05)
        report['layout_adjustment']={'from_size':[width,height],'to_size':target}
    window=win.ensure_window_on_screen(window,exe)
    began=time.monotonic()
    def observe(stage):
        current=win.user.GetForegroundWindow()
        report.setdefault('activation',[]).append({'stage':stage,'seconds':round(time.monotonic()-began,3),
            'expected_hwnd':window.hwnd,'actual_hwnd':current,'target_visible':bool(win.user.IsWindowVisible(window.hwnd))})
    observe('before_activation')
    try:win.activate(window,exe,cancel_check=lambda:check(window),accessible_fallback=True,observe=observe)
    except win.StopAutomation:observe('activation_stopped');raise
    observe('activated')
    report.update(client_version=version,window=vars(window),window_locator='shared_native_main')
    return window
