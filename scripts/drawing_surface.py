"""Live desktop plane. WebView supplies only drawing pixels, never a screenshot.

The small WebView regions keep native text/IME and the toolbar; the per-pixel
Win32 plane composites over the live desktop and owns empty-area mouse input.
This avoids relying on version-dependent WebView2 window transparency.
"""
import base64
import ctypes as c
from ctypes import wintypes as w
from io import BytesIO
import json
import logging
import math
import queue
import threading

from PIL import Image
from emoji_bridge.desktop_stickers import StickerManager
from pocket_service import on_window


class DrawingSurface(StickerManager):
    def __init__(self, window, bounds):
        super().__init__()
        self.window=window;self.bounds=bounds;self.events=queue.Queue();self.closed=False
        self.handle=None;self.last_regions=None
        self.start()
        self.handle=self._submit(self._create_plane)
        self.event_thread=threading.Thread(target=self._events,daemon=True,name='drawing-input')
        self.event_thread.start()

    def _create_plane(self):
        x,y,width,height=self.bounds
        handle=self.user32.CreateWindowExW(0x08080088,self.class_name,'EmojiBridge · 实时绘制层',
            0x80000000,x,y,width,height,None,None,self.instance,None)
        if not handle:raise c.WinError(c.get_last_error())
        self._windows[handle]=dict(x=x,y=y,frame=Image.new('RGBA',(width,height)),scale=1,dpi=96,hover=False)
        return handle

    def update(self, encoded, regions, css_width, css_height):
        if self.closed:return False
        if not isinstance(encoded,str) or len(encoded)>48*1024*1024:raise ValueError('绘制预览过大')
        _,_,width,height=self.bounds
        with Image.open(BytesIO(base64.b64decode(encoded.split(',',1)[1],validate=True))) as im:
            if im.size!=(width,height):raise ValueError('绘制预览尺寸不符')
            frame=im.convert('RGBA')
        if not all(math.isfinite(n) and n>0 for n in (css_width,css_height)) or len(regions)>8:raise ValueError('绘制界面尺寸无效')
        scale_x,scale_y=width/css_width,height/css_height
        rectangles=tuple(tuple(round(v*(scale_x if i%2==0 else scale_y)) for i,v in enumerate(rect)) for rect in regions)
        if rectangles!=self.last_regions:
            def region():
                from System.Drawing import Region,Rectangle
                shape=Region();shape.MakeEmpty()
                for x,y,rw,rh in rectangles:shape.Union(Rectangle(x,y,max(1,rw),max(1,rh)))
                old=self.window.native.Region;self.window.native.Region=shape
                if old:old.Dispose()
            on_window(self.window,region);self.last_regions=rectangles
        owner=int(self.window.native.Handle.ToInt64())
        def paint():
            if self.handle not in self._windows:return False
            self._windows[self.handle]['frame']=frame;self._draw(self.handle)
            self.user32.SetWindowPos(self.handle,owner,0,0,0,0,0x0013)  # below visible controls, no activation
            self.user32.ShowWindow(self.handle,4)
            return True
        return self._submit(paint)

    def _procedure(self, handle, message, wp, lp):
        if message==0x0021:return 3  # controls keep focus for shortcuts / IME
        if message in (0x0200,0x0201,0x0202,0x0203) and handle in self._windows:
            x=c.c_short(lp&0xffff).value;y=c.c_short((lp>>16)&0xffff).value
            kind={0x0200:'move',0x0201:'down',0x0202:'up',0x0203:'double'}[message]
            if kind in ('down','double'):self.user32.SetCapture(handle)
            if kind=='up':self.user32.ReleaseCapture()
            self.events.put(dict(kind=kind,x=x,y=y,shiftKey=bool(wp&4),ctrlKey=bool(wp&8)))
            return 0
        if message==0x0215 and handle in self._windows:
            self.events.put(dict(kind='cancel',x=0,y=0));return 0
        if message==0x0002:self._windows.pop(handle,None);return 0
        return self.user32.DefWindowProcW(handle,message,wp,lp)

    def _events(self):
        pending=None
        while not self.closed:
            event=pending or self.events.get();pending=None
            if event is None:return
            if event['kind']=='move':
                while not self.events.empty():
                    following=self.events.get()
                    if following is None:return
                    if following['kind']!='move':pending=following;break
                    event=following
            try:
                if event['kind'] in ('down','double'):
                    on_window(self.window,lambda:self.window.native.webview.Focus())
                self.window.evaluate_js('window.desktopPointer?.('+json.dumps(event)+')')
            except Exception:
                if self.closed:return
                logging.exception('Drawing input delivery failed')

    def shutdown(self):
        self.closed=True;self.events.put(None)
        super().shutdown()
        self.user32.UnregisterClassW.argtypes=[w.LPCWSTR,w.HINSTANCE]
        self.user32.UnregisterClassW(self.class_name,self.instance)
