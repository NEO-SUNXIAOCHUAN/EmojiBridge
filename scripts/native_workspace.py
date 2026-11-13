"""Host the existing Tk process inside the Windows desktop content rectangle.

WinForms owns placement; Tk still owns its widgets, focus, history and event loop.
Only HWNDs belonging to the child process may be attached. No client HWND is used.
API contracts: https://pywebview.flowrl.com/api/#window-native and
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setparent
"""
import ctypes
from ctypes import wintypes
import os
import threading


def _user32():
    if os.name != 'nt':
        raise RuntimeError('内嵌工作区当前仅支持 Windows')
    user = ctypes.WinDLL('user32', use_last_error=True)
    signatures = {
        'IsWindow': ([wintypes.HWND], wintypes.BOOL),
        'GetParent': ([wintypes.HWND], wintypes.HWND),
        'SetParent': ([wintypes.HWND, wintypes.HWND], wintypes.HWND),
        'GetWindowThreadProcessId': ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        'GetWindowLongPtrW': ([wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t),
        'SetWindowLongPtrW': ([wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t),
        'ShowWindow': ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        'ShowWindowAsync': ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        'SetWindowPos': ([wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
        'SendMessageW': ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.LPARAM),
        'PostMessageW': ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
        'RedrawWindow': ([wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT], wintypes.BOOL),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(user, name); fn.argtypes = args; fn.restype = result
    return user


def pixel_bounds(rect, width, height):
    """Map CSS viewport coordinates to the actual WinForms client size."""
    sx = width / max(1., float(rect.get('viewportWidth', width)))
    sy = height / max(1., float(rect.get('viewportHeight', height)))
    x = max(0, min(width, round(float(rect.get('x', 0)) * sx)))
    y = max(0, min(height, round(float(rect.get('y', 0)) * sy)))
    w = max(1, min(width - x, round(float(rect.get('width', width)) * sx)))
    h = max(1, min(height - y, round(float(rect.get('height', height)) * sy)))
    return x, y, w, h


class NativeWorkspace:
    """A single WinForms Panel over the WebView, never a second editor engine."""
    def __init__(self, window):
        self.window = window
        self.panel = None
        self.hwnd = 0
        self.pid = 0
        self.original = None
        self.rect = {'visible': False}
        self.user = _user32()
        self._resize_handler = None
        self._placement = None
        self.presentation_rect = None

    def _invoke(self, callback):
        from System import Action
        form = self.window.native
        if form is None or form.IsDisposed:
            raise RuntimeError('桌面工作区尚未就绪')
        result, errors = [], []
        def call():
            try: result.append(callback(form))
            except Exception as exc: errors.append(exc)
        if form.InvokeRequired: form.Invoke(Action(call))
        else: call()
        if errors: raise errors[0]
        return result[0] if result else None

    def _ensure_panel(self, form):
        if self.panel is not None: return
        from System.Windows.Forms import Panel
        from System.Drawing import Color
        self.panel = Panel()
        import json
        from pathlib import Path
        color=json.loads((Path(__file__).resolve().parents[1]/'assets/ui-midnight.json').read_text('utf-8'))['background']
        self.panel.BackColor = Color.FromArgb(*(int(color[n:n+2],16) for n in (1,3,5)))
        self.panel.TabStop = False
        self.panel.Visible = False
        form.Controls.Add(self.panel)
        self._resize_handler = lambda sender, event: self._place(form)
        form.ClientSizeChanged += self._resize_handler

    def attach(self, hwnd, pid):
        hwnd, pid = int(hwnd), int(pid)
        owner = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if not hwnd or not self.user.IsWindow(hwnd) or not pid or owner.value != pid:
            raise ValueError('工作区窗口与当前编辑进程不一致')
        def mount(form):
            self._ensure_panel(form)
            if self.hwnd == hwnd:
                self._place(form)
                return self._state()
            if self.hwnd: self._detach(False)
            style = self.user.GetWindowLongPtrW(hwnd, -16)
            exstyle = self.user.GetWindowLongPtrW(hwnd, -20)
            self.original = (style, exstyle, self.user.GetParent(hwnd))
            self.user.ShowWindow(hwnd, 0)
            # SetParent does not change WS_CHILD/WS_POPUP; do it explicitly.
            child_style = (style & ~(0x80000000 | 0x00CF0000)) | 0x40000000 | 0x02000000
            self.user.SetWindowLongPtrW(hwnd, -16, child_style)
            self.user.SetWindowLongPtrW(hwnd, -20, exstyle & ~(0x00040000 | 0x00000301))
            ctypes.set_last_error(0)
            previous = self.user.SetParent(hwnd, int(self.panel.Handle.ToInt64()))
            error = ctypes.get_last_error()
            if not previous and error:
                self.user.SetWindowLongPtrW(hwnd, -16, style)
                self.user.SetWindowLongPtrW(hwnd, -20, exstyle)
                self.original = None
                raise ctypes.WinError(error)
            self.hwnd, self.pid = hwnd, pid
            self._placement = None
            # Clear hidden focus cues only; retain each toolkit's focus handling.
            self.user.PostMessageW(hwnd, 0x0128, 0x00030002, 0)
            self._place(form)
            return self._state()
        return self._invoke(mount)

    def _state(self):
        return {'attached': bool(self.hwnd), 'hwnd': self.hwnd, 'pid': self.pid,
                'visible': bool(self.panel and self.panel.Visible)}

    def _place(self, form):
        if self.panel is None: return
        from System.Drawing import Rectangle
        x, y, width, height = pixel_bounds(self.rect, form.ClientSize.Width, form.ClientSize.Height)
        self.panel.Bounds = Rectangle(x, y, width, height)
        self._presentation_region(width,height)
        visible = bool(self.rect.get('visible', False) and self.hwnd)
        self.panel.Visible = visible
        placement=(self.hwnd,width,height,visible)
        if placement!=self._placement and self.hwnd and self.user.IsWindow(self.hwnd):
            # Tk owns a different input thread. Resize/visibility must not make
            # the desktop UI wait for a frame currently being drawn by Tk.
            # Tk repaints child surfaces at their new geometry. Copying old client
            # bits during an asynchronous resize produces stale panel fragments.
            self.user.SetWindowPos(self.hwnd, 0, 0, 0, width, height, 0x0014 | 0x0020 | 0x4000 | 0x0100)
            self.user.ShowWindowAsync(self.hwnd, 8 if visible else 0)
            if visible:self.user.RedrawWindow(self.hwnd,None,None,0x0001 | 0x0004 | 0x0080)
            self._placement=placement
        if visible: self.panel.BringToFront()

    def layout(self, rect):
        self.rect = dict(rect)
        return self._invoke(lambda form: (self._place(form), self._state())[1])

    def _presentation_region(self,width,height):
        from System.Drawing import Rectangle,Region
        r=self.presentation_rect
        key=(width,height,str(r))
        if key==getattr(self,'_region_key',None):return
        self._region_key=key
        old=self.panel.Region
        if r and r.get('width',0)>1:
            sx=width/max(1,r['rootWidth']);sy=height/max(1,r['rootHeight'])
            region=Region(Rectangle(0,0,width,height))
            region.Exclude(Rectangle(round(r['x']*sx),round(r['y']*sy),round(r['width']*sx),round(r['height']*sy)))
            self.panel.Region=region
        else:self.panel.Region=None
        if old:old.Dispose()

    def presentation_region(self,rect):
        self.presentation_rect=rect
        return self._invoke(lambda form:self._presentation_region(self.panel.Width,self.panel.Height) if self.panel else None)

    def _detach(self, show):
        hwnd = self.hwnd
        if hwnd and self.user.IsWindow(hwnd) and self.original:
            style, exstyle, old_parent = self.original
            self.user.ShowWindow(hwnd, 0)
            self.user.SetParent(hwnd, old_parent)
            self.user.SetWindowLongPtrW(hwnd, -16, style)
            self.user.SetWindowLongPtrW(hwnd, -20, exstyle)
            self.user.SetWindowPos(hwnd, 0, 100, 100, 1200, 850, 0x0014 | 0x0020)
            if show: self.user.ShowWindow(hwnd, 8)
        self.hwnd = self.pid = 0
        self._placement = None
        self.original = None
        if self.panel is not None: self.panel.Visible = False

    def detach(self, show=True):
        """Call before the Form is destroyed, so unsaved Tk content survives."""
        return self._invoke(lambda form: self._detach(show))

    def detach_async(self,done,show=True):
        """Cross-process window messages may wait for Tk; never wait on host UI."""
        def begin(form):
            hwnd,original=self.hwnd,self.original
            self.hwnd=self.pid=0;self.original=None;self._placement=None
            if self.panel is not None:self.panel.Visible=False
            def detach_child():
                try:
                    if hwnd and original and self.user.IsWindow(hwnd):
                        style,exstyle,parent=original
                        self.user.ShowWindowAsync(hwnd,0)
                        self.user.SetParent(hwnd,parent)
                        if self.user.IsWindow(hwnd):
                            self.user.SetWindowLongPtrW(hwnd,-16,style)
                            self.user.SetWindowLongPtrW(hwnd,-20,exstyle)
                            self.user.SetWindowPos(hwnd,0,100,100,1200,850,0x0014|0x0020|0x4000)
                            if show:self.user.ShowWindowAsync(hwnd,8)
                finally:done()
            threading.Thread(target=detach_child,daemon=True,name='workspace-detach').start()
        self._invoke(begin)
