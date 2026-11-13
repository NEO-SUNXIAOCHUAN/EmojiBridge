"""Owned Tk dialogs using the desktop palette; native file pickers stay native.

Explicit imports only: this module never patches tkinter globally. Light/legacy
launchers keep their original platform dialogs and return-value contracts.
"""
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox as native_messagebox, simpledialog as native_simpledialog
from tkinter import colorchooser as native_colorchooser
from ui_style import MIDNIGHT, BG, SURFACE, INK, MUTED, ACCENT, BORDER, FONT, native_titlebar


def prepare_window(window, parent=None):
    """Theme an existing owned window without changing its task/lifetime."""
    if not MIDNIGHT:
        return window
    window.configure(background=BG)
    if parent is not None:
        owner = parent.winfo_toplevel()
        if owner.winfo_viewable():
            window.transient(owner)
    window.after_idle(lambda: native_titlebar(window) if window.winfo_exists() else None)
    window.bind('<Map>', lambda event: native_titlebar(window) if event.widget is window else None, add='+')
    return window


def details_window(parent, title, content):
    """Non-modal, selectable detail text; closing it never cancels a task."""
    window = tk.Toplevel(parent); window.title(title); window.geometry('760x460')
    prepare_window(window, parent)
    area = ttk.Frame(window, padding=20); area.pack(fill='both', expand=True)
    ttk.Label(area, text=title, font=(FONT, 14, 'bold')).pack(anchor='w', pady=(0, 14))
    body = ttk.Frame(area); body.pack(fill='both', expand=True)
    from ui_style import text_field
    field,text=text_field(body,wrap='word')
    from ui_scroll import OverlayScrollbar
    bar=OverlayScrollbar(text);field.pack(fill='both', expand=True)
    text.insert('1.0', content); text.configure(state='disabled')
    ttk.Button(area, text='关闭详情', command=window.destroy).pack(anchor='e', pady=(14, 0))
    window.bind('<Escape>', lambda _event: window.destroy())
    return window


def unsaved_choice(parent):
    """An owned in-workspace sheet; never a second editor or blocking worker wait."""
    focus=parent.focus_get();grab=parent.grab_current();answer=tk.StringVar(parent,value='')
    overlay=ttk.Frame(parent,padding=24,style='TFrame');overlay.place(relx=.5,rely=.5,anchor='center');overlay.lift()
    ttk.Label(overlay,text='保存这次修改？',font=(FONT,15,'bold')).pack(anchor='w',pady=(0,12))
    ttk.Label(overlay,text='原素材不会被覆盖。保存会另存一个可继续编辑的作品。',wraplength=440).pack(anchor='w')
    row=ttk.Frame(overlay);row.pack(fill='x',pady=(24,0))
    first=None
    for label,value in [('保存并返回','save'),('不保存','discard'),('继续编辑','edit')]:
        button=ttk.Button(row,text=label,command=lambda v=value:answer.set(v));button.pack(side='left',padx=4)
        if first is None:first=button
    overlay.bind('<Escape>',lambda _e:answer.set('edit'));overlay.grab_set();first.focus_set()
    try:parent.wait_variable(answer);return answer.get()
    finally:
        overlay.destroy()
        if grab is not None and grab.winfo_exists():grab.grab_set()
        if focus is not None and focus.winfo_exists():focus.focus_set()


class Dialog:
    def __init__(self, parent, title, *, width=480):
        self.parent = parent or tk._default_root
        self.owner = self.parent.winfo_toplevel()
        self.focus = self.owner.focus_get()
        self.grab = self.owner.grab_current()
        self.result = None
        self.window = tk.Toplevel(self.owner)
        self.window.withdraw()
        self.window.title(title)
        prepare_window(self.window, self.owner)
        self.window.resizable(False, False)
        self.body = ttk.Frame(self.window, padding=24)
        self.body.pack(fill='both', expand=True)
        ttk.Label(self.body, text=title, font=(FONT, 14, 'bold'), wraplength=width-48).pack(anchor='w', pady=(0, 16))
        self.buttons = ttk.Frame(self.body)
        self.width = width
        self.window.bind('<Escape>', lambda _event: self.finish(None))
        self.window.protocol('WM_DELETE_WINDOW', lambda: self.finish(None))

    def finish(self, value):
        self.result = value
        self.window.destroy()

    def run(self, initial=None):
        self.buttons.pack(fill='x', pady=(22, 0))
        self.window.update_idletasks()
        width = max(self.width, self.window.winfo_reqwidth())
        height = self.window.winfo_reqheight()
        x = self.owner.winfo_rootx() + (self.owner.winfo_width()-width)//2
        y = self.owner.winfo_rooty() + max(20, (self.owner.winfo_height()-height)//2)
        self.window.geometry(f'{width}x{height}+{max(0,x)}+{max(0,y)}')
        self.window.deiconify()
        self.window.grab_set()
        (initial or self.window).focus_set()
        try:
            self.owner.wait_window(self.window)
        finally:
            try:
                if self.grab is not None and self.grab.winfo_exists():
                    self.grab.grab_set()
                if self.focus is not None and self.focus.winfo_exists():
                    self.focus.focus_set()
            except tk.TclError:
                pass  # The owning application may have closed while a dialog was open.
        return self.result


def _message(title, message, options, choices):
    dialog = Dialog(options.get('parent'), title)
    content = str(message or '')
    detail = options.get('detail')
    if detail:
        content += '\n\n' + str(detail)
    if len(content) > 420 or content.count('\n') > 8:
        area = ttk.Frame(dialog.body); area.pack(fill='both', expand=True)
        text = tk.Text(area, width=56, height=min(16, max(7, content.count('\n')+2)), wrap='word',
                       background=SURFACE, foreground=INK, relief='flat', padx=12, pady=12,
                       highlightthickness=1, highlightbackground=BORDER)
        from ui_scroll import OverlayScrollbar
        scroll=OverlayScrollbar(text);text.pack(fill='both', expand=True)
        text.insert('1.0', content); text.configure(state='disabled')
    else:
        ttk.Label(dialog.body, text=content, wraplength=432, justify='left').pack(anchor='w')
    first = None
    for label, value in reversed(choices):
        button = ttk.Button(dialog.buttons, text=label, command=lambda v=value: dialog.finish(v))
        button.pack(side='right', padx=(8, 0))
        button.bind('<Return>', lambda _event, v=value: dialog.finish(v))
        first = button
    if len(choices) == 1:
        dialog.window.bind('<Return>', lambda _event: dialog.finish(choices[0][1]))
    return dialog.run(first)


class MessageBox:
    def _show(self, method, title, message, options, choices):
        if not MIDNIGHT:
            return getattr(native_messagebox, method)(title, message, **options)
        return _message(title, message, options, choices)

    def showinfo(self, title=None, message=None, **options):
        return self._show('showinfo', title or '提示', message, options, [('知道了', 'ok')])

    def showwarning(self, title=None, message=None, **options):
        return self._show('showwarning', title or '请留意', message, options, [('知道了', 'ok')])

    def showerror(self, title=None, message=None, **options):
        return self._show('showerror', title or '操作未完成', message, options, [('关闭', 'ok')])

    def askyesno(self, title=None, message=None, **options):
        return bool(self._show('askyesno', title or '确认', message, options, [('是', True), ('否', False)]))

    def askokcancel(self, title=None, message=None, **options):
        return bool(self._show('askokcancel', title or '确认', message, options, [('确定', True), ('取消', False)]))

    def askyesnocancel(self, title=None, message=None, **options):
        return self._show('askyesnocancel', title or '确认', message, options, [('是', True), ('否', False), ('取消', None)])


class SimpleDialog:
    def _ask(self, method, title, prompt, options, convert=None):
        if not MIDNIGHT:
            return getattr(native_simpledialog, method)(title, prompt, **options)
        dialog = Dialog(options.get('parent'), title)
        ttk.Label(dialog.body, text=prompt, wraplength=432, justify='left').pack(anchor='w', pady=(0, 10))
        value = tk.StringVar(value=options.get('initialvalue', ''))
        entry = ttk.Entry(dialog.body, textvariable=value, show=options.get('show', ''))
        entry.pack(fill='x'); entry.select_range(0, 'end')
        note = tk.StringVar()
        ttk.Label(dialog.body, textvariable=note, foreground=ACCENT, wraplength=432).pack(anchor='w', pady=(8, 0))

        def accept():
            try:
                result = convert(value.get()) if convert else value.get()
                low, high = options.get('minvalue'), options.get('maxvalue')
                if low is not None and result < low:
                    raise ValueError(f'请输入不小于 {low} 的数值')
                if high is not None and result > high:
                    raise ValueError(f'请输入不大于 {high} 的数值')
            except ValueError as exc:
                note.set(str(exc) if str(exc).startswith('请输入') else '请输入有效数值'); return
            dialog.finish(result)

        ttk.Button(dialog.buttons, text='确定', command=accept, style='Editor.Primary.TButton').pack(side='right')
        ttk.Button(dialog.buttons, text='取消', command=lambda: dialog.finish(None)).pack(side='right', padx=8)
        entry.bind('<Return>', lambda _event: accept())
        return dialog.run(entry)

    def askstring(self, title, prompt, **options):
        return self._ask('askstring', title, prompt, options)

    def askinteger(self, title, prompt, **options):
        return self._ask('askinteger', title, prompt, options, int)

    def askfloat(self, title, prompt, **options):
        return self._ask('askfloat', title, prompt, options, float)


class ColorChooser:
    def askcolor(self, color=None, **options):
        if not MIDNIGHT:
            return native_colorchooser.askcolor(color, **options)
        dialog = Dialog(options.get('parent'), options.get('title', '选择颜色'))
        if isinstance(color, (tuple, list)):
            color = '#%02x%02x%02x' % tuple(round(v) for v in color[:3])
        color = color or '#ffffff'
        initial = tuple(v//257 for v in dialog.window.winfo_rgb(color))
        preview = tk.Canvas(dialog.body, height=52, highlightthickness=1, highlightbackground=BORDER)
        preview.pack(fill='x', pady=(0, 12))
        values = [tk.IntVar(value=v) for v in initial]
        hex_value = tk.StringVar(value='#%02x%02x%02x' % initial)
        note = tk.StringVar()

        def refresh(*_args):
            rgb = tuple(v.get() for v in values)
            hex_value.set('#%02x%02x%02x' % rgb); preview.configure(background=hex_value.get()); note.set('')

        def select(value):
            try:
                rgb = tuple(v//257 for v in dialog.window.winfo_rgb(value))
            except tk.TclError:
                note.set('请输入 #RRGGBB，例如 #91BAFF'); return False
            for var, channel in zip(values, rgb): var.set(channel)
            refresh(); return True

        swatches = ttk.Frame(dialog.body); swatches.pack(fill='x', pady=(0, 12))
        for index, value in enumerate(('#ffffff','#000000','#91baff','#285fbd','#8bd4b0','#ffb6b4','#ffd27f','#bfafff')):
            swatch = tk.Canvas(swatches, width=38, height=28, background=value, highlightthickness=1,
                               highlightbackground=BORDER, takefocus=True, cursor='hand2')
            swatch.grid(row=0, column=index, padx=(0, 6))
            swatch.bind('<Button-1>', lambda _event, v=value: select(v))
            swatch.bind('<space>', lambda _event, v=value: select(v))
            swatch.bind('<FocusIn>', lambda _event, w=swatch: w.configure(highlightbackground=ACCENT))
            swatch.bind('<FocusOut>', lambda _event, w=swatch: w.configure(highlightbackground=BORDER))
        for name, var in zip(('红','绿','蓝'), values):
            row = ttk.Frame(dialog.body); row.pack(fill='x', pady=4)
            ttk.Label(row, text=name, width=3).pack(side='left')
            def adjust(value, channel=var):
                channel.set(round(float(value))); refresh()
            ttk.Scale(row, from_=0, to=255, variable=var, command=adjust).pack(side='left', fill='x', expand=True, padx=8)
            ttk.Label(row, textvariable=var, width=4, anchor='e').pack(side='right')
        entry = ttk.Entry(dialog.body, textvariable=hex_value); entry.pack(fill='x', pady=(12, 0))
        ttk.Label(dialog.body, textvariable=note, foreground=ACCENT).pack(anchor='w', pady=(6, 0))

        def accept():
            if select(hex_value.get()): dialog.finish((tuple(v.get() for v in values), hex_value.get()))

        entry.bind('<Return>', lambda _event: accept())
        ttk.Button(dialog.buttons, text='使用颜色', command=accept, style='Editor.Primary.TButton').pack(side='right')
        ttk.Button(dialog.buttons, text='取消', command=lambda: dialog.finish(None)).pack(side='right', padx=8)
        refresh()
        return dialog.run(entry) or (None, None)


messagebox = MessageBox()
simpledialog = SimpleDialog()
colorchooser = ColorChooser()
