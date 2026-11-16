"""Per-pixel Win32 stickers, adapted from supplied Pocket v2. Bounded decoding."""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
from concurrent.futures import Future
import os
import math
from pathlib import Path
import queue
import threading
import time

from PIL import Image,ImageDraw
from .material_preview import FrameStream


def display_stream(path, size=(384,384)):
    stream=FrameStream(path,size)
    try:
        frame,duration,index,count=stream.frames.get(timeout=15)
        if frame is None:raise ValueError(duration)
        with Image.open(path) as source:loops=source.info.get('loop',None)
        return stream,frame,duration,count,loops
    except Exception:
        stream.close();raise


class StickerManager:
    def __init__(self, on_context=None):
        self._queue = queue.Queue()
        self._ready = threading.Event()
        self._start_lock = threading.Lock()
        self._thread = None
        self._error = None
        self._startup_error = None
        self._windows = {}
        self._suspended = False
        self.on_context = on_context

    def start(self):
        if os.name != "nt":
            raise RuntimeError("桌面透明贴图仅支持 Windows，当前系统不能运行")
        with self._start_lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name="EmojiBridge-stickers", daemon=True)
                self._thread.start()
        # Every caller waits, including concurrent callers that find _thread
        # assigned before Win32 functions/message queue have been initialized.
        if not self._ready.wait(5):
            raise RuntimeError("贴图窗口线程未启动")
        if self._startup_error:
            raise self._startup_error
        if not self._thread.is_alive():
            raise RuntimeError("贴图线程已停止，请重新打开软件") from self._error

    def _submit(self, function):
        self.start()
        future = Future()
        self._queue.put((function, future))
        self.user32.PostThreadMessageW(self._thread_id, 0x8006, 0, 0)
        return future.result(timeout=10)

    def show(self, path, ident=None, placement=None):
        # Decoding is on the JS bridge worker, never the Win32/UI message thread.
        ident=ident or str(Path(path).resolve())
        decoded=display_stream(Path(path),(4096,4096) if placement else (384,384))
        try:
            result=self._submit(lambda:self._create(decoded,Path(path).stem,ident,Path(path)))
            if placement:
                def place():
                    handle=int(result['id']);state=self._windows[handle]
                    state.update(x=int(placement[0]),y=int(placement[1]),scale=96/state['dpi'])
                    self._recover(handle)
                self._submit(place)
            return result
        except Exception:decoded[0].close();raise

    def inspect(self, handle):
        def read():
            state=self._windows.get(int(handle))
            if not state:return None
            width,height=self._display_frame(state).size
            return {key:state[key] for key in ('x','y','paused','count','fixed','angle','path')} | {'width':width,'height':height}
        return self._submit(read)

    def play(self, handle):
        def toggle():
            state=self._windows.get(int(handle))
            if not state:raise ValueError('这张贴图已关闭')
            if state['count']>1:self._toggle_playback(state)
            return {'paused':state['paused'],'animated':state['count']>1}
        return self._submit(toggle)

    def replace(self, handle, path, expected):
        decoded=display_stream(path)
        def change():
            state=self._windows.get(int(handle))
            if not state or state['path']!=expected:decoded[0].close();return False
            stream,frame,duration,count,loops=decoded
            old=self._display_frame(state).size
            state['stream'].close()
            state.update(stream=stream,frame=frame,duration=duration,count=count,loops=loops,cycles=0,
                path=path,index=0,finished=False,due=time.monotonic()+duration/1000,dirty=True)
            new=self._display_frame(state).size
            state['x']+=round((old[0]-new[0])/2);state['y']+=round((old[1]-new[1])/2)
            self._recover(int(handle));return True
        try:return self._submit(change)
        except Exception:decoded[0].close();raise

    def recover_all(self):
        if not self._thread:return {'recovered':0}
        def recover():
            for handle in self._windows:self._recover(handle)
            return {'recovered':len(self._windows)}
        return self._submit(recover)

    def adjust_all(self):
        if not self._thread:return {'adjusting':0}
        def adjust():
            for handle in self._windows:self._fixed(handle,False);self._recover(handle)
            return {'adjusting':len(self._windows)}
        return self._submit(adjust)

    def _fixed(self,handle,value):
        state=self._windows[handle]
        style=self.user32.GetWindowLongPtrW(handle,-20)
        # Fixed locks placement, but the pin remains clickable to unlock it.
        self.user32.SetWindowLongPtrW(handle,-20,style&~0x20)
        self.user32.SetWindowPos(handle,None,0,0,0,0,0x37)
        state.update(fixed=bool(value),hover=True,dragging=None,dirty=True)
        self._draw(handle)

    def _workarea(self,x,y):
        class INFO(c.Structure):
            _fields_=[('size',w.DWORD),('monitor',w.RECT),('work',w.RECT),('flags',w.DWORD)]
        self.user32.MonitorFromPoint.argtypes=[w.POINT,w.DWORD];self.user32.MonitorFromPoint.restype=w.HANDLE
        self.user32.GetMonitorInfoW.argtypes=[w.HANDLE,c.POINTER(INFO)]
        info=INFO();info.size=c.sizeof(info)
        self.user32.GetMonitorInfoW(self.user32.MonitorFromPoint(w.POINT(x,y),2),c.byref(info))
        return info.work

    def _recover(self,handle):
        state=self._windows[handle];area=self._workarea(state['x'],state['y'])
        width,height=self._display_frame(state).size
        state['x']=max(area.left,min(state['x'],area.right-width))
        state['y']=max(area.top,min(state['y'],area.bottom-height))
        state['dirty']=True;self._draw(handle)
        if not self._suspended:self.user32.ShowWindow(handle,4)

    def close_all(self):
        if not self._thread or not self._thread.is_alive():
            return {"closed": 0}
        def close():
            handles = list(self._windows)
            for handle in handles:
                self.user32.DestroyWindow(handle)
            return {"closed": len(handles)}
        return self._submit(close)

    def suspend(self, value):
        if not self._thread:
            self._suspended = bool(value)
            return
        def change():
            self._suspended = bool(value)
            for handle in self._windows:
                self.user32.ShowWindow(handle, 0 if value else 4)  # SW_SHOWNOACTIVATE
                self._windows[handle]['due']=time.monotonic()+self._windows[handle]['duration']/1000
            return {"hidden": self._suspended}
        return self._submit(change)

    def shutdown(self):
        if self._thread and self._thread.is_alive():
            self.close_all()
            self.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
            self._thread.join(timeout=3)

    def _loop(self):
        try:
            self._init_win32()
            self._thread_id = self.kernel32.GetCurrentThreadId()
            message = w.MSG()
            self.user32.PeekMessageW(c.byref(message), None, 0, 0, 0)
            self._ready.set()
            while True:
                result = self.user32.GetMessageW(c.byref(message), None, 0, 0)
                if result <= 0:
                    break
                if message.message == 0x8006 and not message.hWnd:
                    while not self._queue.empty():
                        function, future = self._queue.get()
                        try:
                            future.set_result(function())
                        except Exception as exc:
                            future.set_exception(exc)
                else:
                    self.user32.TranslateMessage(c.byref(message))
                    self.user32.DispatchMessageW(c.byref(message))
        except Exception as exc:
            self._error = exc
            if not self._ready.is_set():
                self._startup_error = exc
            self._ready.set()

    def _init_win32(self):
        u = self.user32 = c.WinDLL("user32", use_last_error=True)
        g = self.gdi32 = c.WinDLL("gdi32", use_last_error=True)
        k = self.kernel32 = c.WinDLL("kernel32", use_last_error=True)
        if hasattr(u,'SetThreadDpiAwarenessContext'):
            u.SetThreadDpiAwarenessContext.argtypes=[c.c_void_p];u.SetThreadDpiAwarenessContext(c.c_void_p(-4))
        self._wndproc_type = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        self._wndproc = self._wndproc_type(self._procedure)
        class WNDCLASS(c.Structure):
            _fields_ = [("style", w.UINT), ("lpfnWndProc", self._wndproc_type),
                ("cbClsExtra", c.c_int), ("cbWndExtra", c.c_int), ("hInstance", w.HINSTANCE),
                ("hIcon", w.HICON), ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
                ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]
        class SIZE(c.Structure):
            _fields_ = [("cx", w.LONG), ("cy", w.LONG)]
        class BLEND(c.Structure):
            _fields_ = [("op", c.c_ubyte), ("flags", c.c_ubyte), ("alpha", c.c_ubyte), ("format", c.c_ubyte)]
        class BI(c.Structure):
            _fields_ = [("size", w.DWORD), ("width", w.LONG), ("height", w.LONG),
                ("planes", w.WORD), ("bitCount", w.WORD), ("compression", w.DWORD),
                ("sizeImage", w.DWORD), ("xPels", w.LONG), ("yPels", w.LONG),
                ("clrUsed", w.DWORD), ("clrImportant", w.DWORD), ("colors", w.DWORD * 3)]
        self.SIZE, self.BLEND, self.BI = SIZE, BLEND, BI
        def bind(dll, name, args, restype):
            function = getattr(dll, name)
            function.argtypes, function.restype = args, restype
        bind(k, "GetModuleHandleW", [w.LPCWSTR], w.HMODULE)
        bind(k, "GetCurrentThreadId", [], w.DWORD)
        bind(u, "RegisterClassW", [c.POINTER(WNDCLASS)], w.ATOM)
        bind(u, "CreateWindowExW", [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
            c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p], w.HWND)
        bind(u, "DefWindowProcW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM], c.c_ssize_t)
        bind(u, "LoadCursorW", [w.HINSTANCE, c.c_void_p], w.HANDLE)
        bind(u, "ShowWindow", [w.HWND, c.c_int], w.BOOL)
        bind(u, "DestroyWindow", [w.HWND], w.BOOL)
        bind(u, "SetTimer", [w.HWND, c.c_size_t, w.UINT, c.c_void_p], c.c_size_t)
        bind(u, "KillTimer", [w.HWND, c.c_size_t], w.BOOL)
        bind(u, "GetMessageW", [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT], c.c_int)
        bind(u, "PeekMessageW", [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT], w.BOOL)
        bind(u, "TranslateMessage", [c.POINTER(w.MSG)], w.BOOL)
        bind(u, "DispatchMessageW", [c.POINTER(w.MSG)], c.c_ssize_t)
        bind(u, "PostThreadMessageW", [w.DWORD, w.UINT, w.WPARAM, w.LPARAM], w.BOOL)
        bind(u, "SetWindowPos", [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT], w.BOOL)
        bind(u, "SetCapture", [w.HWND], w.HWND)
        bind(u, "ReleaseCapture", [], w.BOOL)
        bind(u, "GetCursorPos", [c.POINTER(w.POINT)], w.BOOL)
        bind(u, "GetWindowRect", [w.HWND,c.POINTER(w.RECT)], w.BOOL)
        bind(u, 'GetWindowLongPtrW',[w.HWND,c.c_int],c.c_ssize_t)
        bind(u, 'SetWindowLongPtrW',[w.HWND,c.c_int,c.c_ssize_t],c.c_ssize_t)
        bind(u, 'SetCursor',[w.HANDLE],w.HANDLE)
        bind(u, "GetDC", [w.HWND], w.HDC)
        bind(u, "ReleaseDC", [w.HWND, w.HDC], c.c_int)
        bind(u, "UpdateLayeredWindow", [w.HWND, w.HDC, c.POINTER(w.POINT), c.POINTER(SIZE),
            w.HDC, c.POINTER(w.POINT), w.DWORD, c.POINTER(BLEND), w.DWORD], w.BOOL)
        bind(g, "CreateCompatibleDC", [w.HDC], w.HDC)
        bind(g, "CreateDIBSection", [w.HDC, c.POINTER(BI), w.UINT, c.POINTER(c.c_void_p), w.HANDLE, w.DWORD], w.HBITMAP)
        bind(g, "SelectObject", [w.HDC, w.HGDIOBJ], w.HGDIOBJ)
        bind(g, "DeleteObject", [w.HGDIOBJ], w.BOOL)
        bind(g, "DeleteDC", [w.HDC], w.BOOL)
        bind(u, "CreatePopupMenu", [], w.HMENU)
        bind(u, "AppendMenuW", [w.HMENU, w.UINT, c.c_size_t, w.LPCWSTR], w.BOOL)
        bind(u, "TrackPopupMenu", [w.HMENU, w.UINT, c.c_int, c.c_int, c.c_int, w.HWND, c.c_void_p], w.UINT)
        bind(u, "DestroyMenu", [w.HMENU], w.BOOL)
        if hasattr(u,'GetDpiForWindow'):bind(u,'GetDpiForWindow',[w.HWND],w.UINT)
        self.instance = k.GetModuleHandleW(None)
        self.class_name = "EmojiBridgeAlphaSticker_" + str(os.getpid()) + '_' + str(id(self))
        wc = WNDCLASS(0x0008, self._wndproc, 0, 0, self.instance, None,
                      u.LoadCursorW(None, c.c_void_p(32512)), None, None, self.class_name)
        if not u.RegisterClassW(c.byref(wc)):
            raise c.WinError(c.get_last_error())

    def _create(self, decoded, title, ident, path):
        stream,frame,duration,count,loops=decoded
        if len(self._windows) >= 16:
            raise ValueError("最多同时显示 16 张贴图，请先收回部分贴图；库内原件不受影响")
        width, height = frame.size
        offset = len(self._windows) * 28
        cursor=w.POINT();self.user32.GetCursorPos(c.byref(cursor));area=self._workarea(cursor.x,cursor.y)
        x,y=area.left+(area.right-area.left-width)//2+offset,area.top+80+offset
        # WS_EX_LAYERED | TOPMOST | TOOLWINDOW | NOACTIVATE; WS_POPUP.
        handle = self.user32.CreateWindowExW(0x08080088, self.class_name, title,
            0x80000000, x, y, width, height, None, None, self.instance, None)
        if not handle:
            raise c.WinError(c.get_last_error())
        self._windows[handle] = dict(stream=stream,frame=frame,duration=duration,count=count,loops=loops,cycles=0,ident=ident,x=x,y=y,dpi=self.user32.GetDpiForWindow(handle) if hasattr(self.user32,'GetDpiForWindow') else 96,due=time.monotonic()+duration/1000,
            scale=1.0, angle=0, paused=False,finished=False,path=path,pin_press=None,
            dragging=None, index=0, dirty=True,fixed=False,hover=True)
        try:
            self._draw(handle)
            self.user32.SetTimer(handle, 1, 16, None)
            if not self._suspended:
                self.user32.ShowWindow(handle, 4)
        except Exception:
            self.user32.DestroyWindow(handle)
            raise
        return {"ok": True, "id": str(handle), "count": len(self._windows)}

    @staticmethod
    def _display_frame(state):
        image = state['frame']
        scale=state['scale']*state.get('dpi',96)/96
        if scale != 1:
            image = image.resize((max(24, round(image.width * scale)),
                                  max(24, round(image.height * scale))), Image.Resampling.LANCZOS)
        if state.get('angle',0):image=image.rotate(state['angle'],Image.Resampling.BICUBIC,expand=True)
        return image

    def _rotate(self,handle,angle,explicit=False):
        state=self._windows[handle]
        if state.get('fixed') and not explicit:return
        old=self._display_frame(state).size;state['angle']=angle%360
        new=self._display_frame(state).size
        state['x']+=round((old[0]-new[0])/2);state['y']+=round((old[1]-new[1])/2)
        self._recover(handle)

    def _draw(self, handle):
        state = self._windows[handle]
        image = self._display_frame(state)
        width, height = image.size
        # Near-transparent hit surface permits grabbing transparent corners;
        # this is display-only and never changes the managed PNG/GIF.
        surface=Image.new('RGBA',image.size,(0,0,0,1));surface.alpha_composite(image);image=surface
        if state.get('hover'):
            d=ImageDraw.Draw(image);r=max(12,round(18*state.get('dpi',96)/96));state['control_size']=r
            d.rounded_rectangle((0,0,width-1,height-1),radius=5,outline='#94bafa',width=1)
            d.rectangle((0,0,r,r),fill='#587299' if state.get('fixed') else '#25344bee')
            d.line((r//2,4,r//2,r-3),fill='white',width=2)
            d.line((4,6,r-4,6),fill='white',width=2)
            d.rectangle((width-r,0,width, r),fill='#25344bee');d.line((width-r+5,5,width-5,r-5),fill='white',width=2);d.line((width-5,5,width-r+5,r-5),fill='white',width=2)
            if not state.get('fixed'):d.rectangle((width-r,height-r,width-1,height-1),fill='#94bafa')
        pixels = image.convert("RGBa").tobytes("raw", "BGRa")
        screen = self.user32.GetDC(None)
        memory = self.gdi32.CreateCompatibleDC(screen)
        info = self.BI()
        info.size, info.width, info.height = 40, width, -height
        info.planes, info.bitCount, info.sizeImage = 1, 32, len(pixels)
        bits = c.c_void_p()
        bitmap = self.gdi32.CreateDIBSection(memory, c.byref(info), 0, c.byref(bits), None, 0)
        old = None
        try:
            if not bitmap or not bits.value:
                raise c.WinError(c.get_last_error())
            old = self.gdi32.SelectObject(memory, bitmap)
            c.memmove(bits, pixels, len(pixels))
            destination, source = w.POINT(state["x"], state["y"]), w.POINT(0, 0)
            size, blend = self.SIZE(width, height), self.BLEND(0, 0, 255, 1)
            if not self.user32.UpdateLayeredWindow(handle, screen, c.byref(destination),
                c.byref(size), memory, c.byref(source), 0, c.byref(blend), 2):
                raise c.WinError(c.get_last_error())
            state["dirty"] = False
        finally:
            if old:
                self.gdi32.SelectObject(memory, old)
            if bitmap:
                self.gdi32.DeleteObject(bitmap)
            self.gdi32.DeleteDC(memory)
            self.user32.ReleaseDC(None, screen)

    def _procedure(self, handle, message, wp, lp):
        try:
            state = self._windows.get(handle)
            if message == 0x0021:  # WM_MOUSEACTIVATE -> MA_NOACTIVATE
                return 3
            if not state:
                return self.user32.DefWindowProcW(handle, message, wp, lp)
            if message == 0x0003:  # OS placement must agree with subsequent pointer dragging.
                rect=w.RECT()
                if self.user32.GetWindowRect(handle,c.byref(rect)):
                    state.update(x=rect.left,y=rect.top)
                return 0
            if message == 0x0113:  # WM_TIMER
                press=state.get('pin_press')
                if press and time.monotonic()-press['at']>=.35:press['rotate']=True
                if not state.get('dragging'):
                    p=w.POINT();self.user32.GetCursorPos(c.byref(p));rect=w.RECT();self.user32.GetWindowRect(handle,c.byref(rect))
                    inside=rect.left<=p.x<rect.right and rect.top<=p.y<rect.bottom
                    if inside!=state.get('hover'):state.update(hover=inside,dirty=True)
                if not self._suspended and not state['paused'] and state['count']>1 and time.monotonic()>=state['due']:
                    try:frame,duration,index,count=state['stream'].frames.get_nowait()
                    except queue.Empty:frame=None;duration=None
                    if duration is not None:
                        if frame is None:
                            state['paused']=True;self._error=ValueError(duration)
                        elif index==0 and state['loops']!=0 and state['cycles']>=int(state['loops'] or 0):
                            state['paused']=True;state['finished']=True;state['stream'].close()
                        else:
                            if index==0:state['cycles']+=1
                            state.update(frame=frame,duration=duration,index=index,dirty=True,due=max(state['due']+duration/1000,time.monotonic()))
                if state["dirty"] and not self._suspended:
                    self._draw(handle)
                return 0
            if message in (0x0201,0x0203):  # down / double-click followed by dragging
                point = w.POINT()
                self.user32.GetCursorPos(c.byref(point))
                rect=w.RECT();self.user32.GetWindowRect(handle,c.byref(rect));r=state.get('control_size',18)
                x,y=point.x-rect.left,point.y-rect.top
                if y<r and x<r:
                    cx=rect.left+(rect.right-rect.left)/2;cy=rect.top+(rect.bottom-rect.top)/2
                    state['pin_press']={'at':time.monotonic(),'rotate':False,'cx':cx,'cy':cy,
                        'pointer':math.atan2(point.y-cy,point.x-cx),'angle':state.get('angle',0)}
                    self.user32.SetCapture(handle);return 0
                if y<r and x>=rect.right-rect.left-r:self.user32.DestroyWindow(handle);return 0
                if state.get('fixed'):return 0
                corner=x>=rect.right-rect.left-r and y>=rect.bottom-rect.top-r
                state["dragging"] = ('resize' if corner else 'move',point.x,point.y,state['x'],state['y'],state['scale'],rect.right-rect.left,rect.bottom-rect.top)
                self.user32.SetCapture(handle)
                return 0
            if message==0x0200 and state.get('pin_press'):
                press=state['pin_press']
                if time.monotonic()-press['at']>=.35:
                    press['rotate']=True;p=w.POINT();self.user32.GetCursorPos(c.byref(p))
                    delta=math.atan2(p.y-press['cy'],p.x-press['cx'])-press['pointer']
                    self._rotate(handle,press['angle']-math.degrees(delta),explicit=True)
                return 0
            if message == 0x0200 and state["dragging"]:
                point = w.POINT()
                self.user32.GetCursorPos(c.byref(point))
                mode,x,y,ox,oy,scale,width,height=state['dragging']
                if mode=='resize':
                    ratio=max((width+point.x-x)/width,(height+point.y-y)/height)
                    state.update(scale=max(.25,min(2.5,scale*ratio)),dirty=True)
                    return 0
                state["x"], state["y"] = ox+point.x-x,oy+point.y-y
                self.user32.SetWindowPos(handle, None, state["x"], state["y"], 0, 0, 0x0015)
                return 0
            if message==0x0020 and not state.get('fixed'):
                p=w.POINT();self.user32.GetCursorPos(c.byref(p));rect=w.RECT();self.user32.GetWindowRect(handle,c.byref(rect));r=state.get('control_size',18)
                cursor=32642 if p.x>=rect.right-r and p.y>=rect.bottom-r else 32646
                self.user32.SetCursor(self.user32.LoadCursorW(None,c.c_void_p(cursor)));return 1
            if message == 0x0202:
                press=state.get('pin_press');state['pin_press']=None
                if press and not press['rotate'] and time.monotonic()-press['at']<.35:
                    self._fixed(handle,not state.get('fixed'))
                state["dragging"] = None
                self.user32.ReleaseCapture()
                return 0
            if message==0x0215:state['dragging']=None;state['pin_press']=None;return 0
            if message==0x007E:self._recover(handle);return 0
            if message==0x02E0:
                rect=c.cast(lp,c.POINTER(w.RECT)).contents
                state.update(x=rect.left,y=rect.top,dpi=int(wp)&0xffff,dirty=True)
                self._recover(handle);return 0
            if message == 0x020A:  # wheel
                if state.get('fixed'):return 0
                delta = c.c_short((wp >> 16) & 0xffff).value
                state["scale"] = max(.25, min(2.5, state["scale"] * (1.1 if delta > 0 else 1 / 1.1)))
                state["dirty"] = True
                return 0
            if message == 0x0205:  # right up
                if self.on_context:
                    threading.Thread(target=self.on_context,args=(handle,),daemon=True,name='sticker-actions').start()
                    return 0
                point = w.POINT()
                self.user32.GetCursorPos(c.byref(point))
                menu = self.user32.CreatePopupMenu()
                try:
                    self.user32.AppendMenuW(menu, 0, 1, "继续播放" if state["paused"] else "暂停动画")
                    self.user32.AppendMenuW(menu, 0, 2, "关闭这张贴图")
                    self.user32.AppendMenuW(menu, 0, 3, "放大")
                    self.user32.AppendMenuW(menu, 0, 4, "缩小")
                    self.user32.AppendMenuW(menu, 0, 5, "找回到屏幕内")
                    self.user32.AppendMenuW(menu, 0, 6, "取消固定" if state.get('fixed') else "固定位置 · 再点左上角取消")
                    for key,label in ((7,'向左旋转 15°'),(8,'向右旋转 15°'),(9,'恢复原角度')):
                        self.user32.AppendMenuW(menu, 1 if state.get('fixed') else 0, key, label)
                    action = self.user32.TrackPopupMenu(menu, 0x0100 | 0x0002, point.x, point.y, 0, handle, None)
                    if action == 1:
                        self._toggle_playback(state)
                    elif action == 2:
                        self.user32.DestroyWindow(handle)
                    elif action in (3,4):state['scale']=max(.25,min(2.5,state['scale']*(1.1 if action==3 else 1/1.1)));state['dirty']=True
                    elif action==5:self._recover(handle)
                    elif action==6:self._fixed(handle,not state.get('fixed'))
                    elif action in (7,8,9):self._rotate(handle,0 if action==9 else state.get('angle',0)+(15 if action==7 else -15))
                finally:
                    self.user32.DestroyMenu(menu)
                return 0
            if message == 0x0002:  # destroy
                self.user32.KillTimer(handle, 1)
                self._windows.pop(handle, None)
                state['stream'].close()
                return 0
        except Exception as exc:
            # Keep the message callback alive; a failed sticker must not kill
            # the parent material window. Save diagnostic for host integration.
            self._error = exc
        return self.user32.DefWindowProcW(handle, message, wp, lp)

    def _toggle_playback(self,state):
        if state['finished']:
            state.update(stream=FrameStream(state['path'],(384,384)),cycles=-1,finished=False)
        state['paused']=not state['paused']
        state['due']=time.monotonic()+state['duration']/1000
