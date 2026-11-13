"""Native UI dimensions in logical pixels; document/image coordinates stay untouched."""
import sys
from tkinter import ttk


def initialize_process():
    """Match the WinForms host before Tk creates/caches any fonts or HWNDs.

    Changing awareness after font creation leaves Tk's cached fonts at 96 DPI.
    Cross-process embedding also requires the same awareness as the host.
    This is scoped to native UI entry points, never client automation workers.
    """
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()


def initialize_tk(root):
    if sys.platform == 'win32':
        import ctypes
        user = ctypes.windll.user32
        user.GetDpiForWindow.argtypes = [ctypes.c_void_p]
        dpi = user.GetDpiForWindow(root.winfo_id())
        if dpi:
            root.tk.call('tk', 'scaling', dpi / 72.0)


def factor(widget):
    # Tk scaling is pixels per point (72 points/inch), UI constants use 96/inch.
    value = float(widget.tk.call('tk', 'scaling')) * 72 / 96
    return round(value * 96) / 96


def px(widget, value):
    return round(value * factor(widget))


def spacing(widget, values):
    return tuple(px(widget, value) for value in values)


class DpiStyle(ttk.Style):
    """Scale only explicit style geometry. Positive font sizes already use points."""
    def __init__(self, master=None):
        super().__init__(master)
        self.scale = factor(self.master)

    def configure(self, style, query_opt=None, **kw):
        for key in ('rowheight', 'arrowsize', 'sliderlength', 'thickness', 'borderwidth'):
            if key in kw and isinstance(kw[key], (int, float)):
                kw[key] = round(kw[key] * self.scale)
        if 'padding' in kw:
            value = kw['padding']
            kw['padding'] = (tuple(round(v * self.scale) for v in value)
                             if isinstance(value, (tuple, list)) else round(value * self.scale))
        return super().configure(style, query_opt, **kw)
