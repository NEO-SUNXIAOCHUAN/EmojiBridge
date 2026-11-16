"""Keep the system caption controls while matching our dark work surface."""
import ctypes as c
import os


def apply_titlebar(native, palette='midnight'):
    if os.name != 'nt':
        return {}
    color = '#101112' if palette == 'neutral' else '#111214'
    from System.Drawing import Color
    native.BackColor = Color.FromArgb(*[int(color[i:i+2],16) for i in (1,3,5)])
    handle = c.c_void_p(int(native.Handle.ToInt64()))
    dwm = c.WinDLL('dwmapi').DwmSetWindowAttribute
    dwm.argtypes = [c.c_void_p,c.c_uint,c.c_void_p,c.c_uint]
    dwm.restype = c.c_long
    def set_value(attribute, value):
        data=c.c_uint(value)
        return int(dwm(handle,attribute,c.byref(data),c.sizeof(data)))
    dark=set_value(20,1)
    if dark:dark=set_value(19,1)  # Older Windows 10 caption implementation.
    def rgb(value):
        return sum(int(value[i:i+2],16) << (8*n) for n,i in enumerate((1,3,5)))
    return {'dark':dark,'caption':set_value(35,rgb(color)),
            'text':set_value(36,rgb('#eef2fa')),'border':set_value(34,rgb(color))}
