"""Workspace-local transport keys, before ttk's button class bindings."""
import os
import tkinter as tk


def composing(widget):
    """Read only this widget's Windows IME context; never change IME settings."""
    if os.name != 'nt':
        return False
    import ctypes as c
    from ctypes import wintypes as w
    imm = c.WinDLL('imm32')
    imm.ImmGetContext.argtypes = [w.HWND]; imm.ImmGetContext.restype = w.HANDLE
    imm.ImmGetCompositionStringW.argtypes = [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD]
    imm.ImmReleaseContext.argtypes = [w.HWND, w.HANDLE]
    hwnd = widget.winfo_id(); context = imm.ImmGetContext(hwnd)
    if not context:
        return False
    try:
        return imm.ImmGetCompositionStringW(context, 8, None, 0) > 0  # GCS_COMPSTR
    finally:
        imm.ImmReleaseContext(hwnd, context)


class PlaybackKeys:
    def __init__(self, workspace, play_button, toggle, available):
        self.workspace = workspace; self.play_button = play_button
        self.toggle = toggle; self.available = available
        self.active = True; self.held = False; self.widgets = []
        self.tag = 'Playback' + str(id(self))
        workspace.bind_class(self.tag, '<KeyPress-space>', self.press)
        workspace.bind_class(self.tag, '<KeyRelease-space>', self.release)
        workspace.bind_class(self.tag, '<FocusOut>', self.blur)
        self.attach(workspace)

    def attach(self, widget):
        self.widgets.append(widget)
        widget.bindtags((self.tag,) + widget.bindtags())
        if widget.winfo_class() in ('Frame', 'TFrame', 'Label', 'TLabel', 'Canvas'):
            widget.bind('<Button-1>', lambda e: e.widget.focus_set(), add='+')
        for child in widget.winfo_children():
            self.attach(child)

    def eligible(self, event):
        widget = event.widget
        if not self.active or not self.available() or not self.workspace.winfo_ismapped():
            return False
        # Tk/Windows Mod1 (8) is NumLock, not Alt. Do not disable Space just
        # because the number pad is enabled. ALT_MASK is the Windows extension.
        modifiers=1|4|(0x20000 if os.name=='nt' else 8)
        if event.state & modifiers:
            return False
        grab=self.workspace.grab_current()
        if grab is not None and grab is not self.workspace:
            return False
        if widget is not self.play_button and widget.winfo_class() not in ('Frame', 'TFrame', 'Label', 'TLabel', 'Canvas'):
            return False
        return not composing(widget)

    def press(self, event):
        # Once a key-down was consumed, repeated downs belong to that same
        # physical press even while the next frame is briefly being prepared.
        if self.held:return 'break'
        if not self.eligible(event):
            return
        if not self.held:
            self.held = True
            self.toggle()
        return 'break'

    def release(self, event):
        consumed = self.held
        self.held = False
        return 'break' if consumed else None

    def blur(self, event=None):
        self.held = False

    def set_active(self, active):
        self.active = bool(active); self.held = False

    def close(self):
        self.set_active(False)
        for widget in self.widgets:
            if widget.winfo_exists():
                widget.bindtags(tuple(t for t in widget.bindtags() if t != self.tag))
        for event in ('<KeyPress-space>', '<KeyRelease-space>', '<FocusOut>'):
            self.workspace.unbind_class(self.tag, event)
