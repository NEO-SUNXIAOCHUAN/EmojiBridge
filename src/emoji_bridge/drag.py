"""One guarded drag to our registered local receiver, never to another chat."""
import ctypes as c
import time
from .windows import (INPUT,Window,user,w,guard,bounds,pid_of,process_path,StopAutomation)


def drag_to_receiver(source,exe,x,y,receiver,receiver_exe,allowed_foregrounds=()):
    guard(source,exe);guard(receiver,receiver_exe,foreground=False)
    for key in (1,2,0x10,0x11,0x12,0x1b,0x5b,0x5c):
        if user.GetAsyncKeyState(key)&0x8000:raise StopAutomation('user_input_in_progress')
    start=(source.rect[0]+x,source.rect[1]+y)
    dest=((receiver.rect[0]+receiver.rect[2])//2,(receiver.rect[1]+receiver.rect[3])//2)
    if not (source.rect[0]<start[0]<source.rect[2] and source.rect[1]<start[1]<source.rect[3]):raise StopAutomation('source_outside_window')
    if user.GetAncestor(user.WindowFromPoint(w.POINT(*start)),2)!=source.hwnd:raise StopAutomation('source_occluded')
    if user.GetAncestor(user.WindowFromPoint(w.POINT(*dest)),2)!=receiver.hwnd:raise StopAutomation('receiver_occluded')
    before=w.POINT();user.GetCursorPos(c.byref(before));last=start;pressed=False
    def mouse(flag):
        event=INPUT();event.type=0;event.mi.dwFlags=flag
        if user.SendInput(1,c.byref(event),c.sizeof(INPUT))!=1:raise StopAutomation('drag_input_failed')
    def cancel():
        events=(INPUT*2)()
        for event in events:event.type=1;event.ki.wVk=0x1b
        events[1].ki.dwFlags=2;user.SendInput(2,events,c.sizeof(INPUT))
    try:
        user.SetCursorPos(*start);guard(source,exe);mouse(2);pressed=True
        for step in range(1,25):
            now=w.POINT();user.GetCursorPos(c.byref(now))
            if (now.x,now.y)!=last:raise StopAutomation('user_moved_pointer')
            if user.GetAsyncKeyState(0x1b)&0x8000:raise StopAutomation('cancelled_escape')
            if pid_of(source.hwnd)!=source.pid or process_path(source.pid)!=exe:raise StopAutomation('drag_source_changed')
            guard(receiver,receiver_exe,foreground=False)
            if user.GetForegroundWindow() not in (source.hwnd,receiver.hwnd,*allowed_foregrounds):raise StopAutomation('drag_foreground_changed')
            last=tuple(round(a+(b-a)*step/24) for a,b in zip(start,dest))
            user.SetCursorPos(*last);time.sleep(.04)
        if user.GetAncestor(user.WindowFromPoint(w.POINT(*dest)),2)!=receiver.hwnd:raise StopAutomation('receiver_occluded')
        mouse(4);pressed=False
    except Exception:
        cancel();raise
    finally:
        if pressed:mouse(4)
        now=w.POINT();user.GetCursorPos(c.byref(now))
        if (now.x,now.y)==last:user.SetCursorPos(before.x,before.y)
