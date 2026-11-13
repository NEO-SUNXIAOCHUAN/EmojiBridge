"""Shared desktop tokens; keep Tk/ttk and the existing layout."""
from ui_dpi import DpiStyle, px, spacing
from tkinter import ttk

BG = '#e9edf2'
SURFACE = '#ffffff'
INK = '#223047'
MUTED = '#64748b'
ACCENT = '#315ee8'
SELECTED = '#e7eeff'
BORDER = '#d6dee8'
FONT = 'Microsoft YaHei UI'
GAP = 12


def consent_checkbutton(parent,variable,text):
    """A normal ttk checkbox with a legible check mark, retaining Space/focus."""
    from PIL import Image,ImageDraw,ImageTk
    style=ttk.Style(parent)
    size=max(16,round(18*parent.winfo_fpixels('1i')/96))
    name=f'Consent{size}.indicator'
    if name not in style.element_names():
        images=[]
        for selected in (False,True):
            im=Image.new('RGBA',(size*4,size*4));d=ImageDraw.Draw(im)
            d.rounded_rectangle((2,2,size*4-3,size*4-3),radius=16,
                                fill=ACCENT if selected else SURFACE,outline=ACCENT if selected else MUTED,width=4)
            if selected:d.line([(size*.22*4,size*.5*4),(size*.43*4,size*.7*4),(size*.8*4,size*.28*4)],fill='white',width=7,joint='curve')
            images.append(ImageTk.PhotoImage(im.resize((size,size),Image.Resampling.LANCZOS),master=parent))
        style.element_create(name,'image',images[0],('selected',images[1]),width=size,sticky='')
        # Tcl style elements outlive this panel; keep their Tk images per root.
        parent._root().__dict__.setdefault('_consent_images',[]).extend(images)
    key=f'Consent{size}.TCheckbutton'
    style.layout(key,[('Checkbutton.padding',{'sticky':'nswe','children':[
        (name,{'side':'left','sticky':''}),('Checkbutton.focus',{'side':'left','sticky':'w','children':[
            ('Checkbutton.label',{'sticky':'nswe'})]})]})])
    style.configure(key,background=BG,foreground=INK,padding=(6,8),font=(FONT,10))
    style.map(key,background=[('active',HOVER)],foreground=[('disabled',DISABLED)])
    return ttk.Checkbutton(parent,variable=variable,text='  '+text,style=key,takefocus=True)

# Scope the transitional desktop palette to its owned editor process. The old
# entry and client workflows retain their existing styling and behavior.
import os
MIDNIGHT=os.environ.get('EMOJI_BRIDGE_DESKTOP_STYLE')=='midnight'
HOVER='#f5f7fb';PRIMARY=ACCENT;WORKSPACE='#d8e0e9';TIMELINE='#ffffff'
SUCCESS='#087c66';WARNING='#935b23';DUPLICATE='#7042a0';DISABLED='#96a2b3'
if os.environ.get('EMOJI_BRIDGE_DESKTOP_STYLE')=='apple':
    BG='#f5f5f7';INK='#1d1d1f';MUTED='#77777e';ACCENT='#007aff';SELECTED='#e8f2ff';BORDER='#e3e3e8'
    PRIMARY=ACCENT
if MIDNIGHT:
    import json
    from pathlib import Path
    _tokens=json.loads((Path(__file__).resolve().parents[1]/'assets/ui-midnight.json').read_text('utf-8'))
    BG=_tokens['background'];SURFACE=_tokens['surface'];INK=_tokens['ink'];MUTED=_tokens['muted']
    ACCENT=_tokens['accent'];SELECTED=_tokens['selected'];BORDER=_tokens['border']
    HOVER=_tokens['raised'];PRIMARY=_tokens['primary'];WORKSPACE=_tokens['workspace'];TIMELINE=SURFACE
    SUCCESS=_tokens.get('success','#8bd4b0');WARNING=_tokens.get('warning','#ffd27f')
    DUPLICATE=_tokens.get('duplicate','#c7b3ec');DISABLED=_tokens.get('disabled','#7a879c')


def native_titlebar(root):
    if not MIDNIGHT or os.name!='nt':return
    import ctypes
    from ctypes import wintypes as w
    hwnd=ctypes.windll.user32.GetParent
    hwnd.argtypes=[w.HWND];hwnd.restype=w.HWND
    dwm=ctypes.windll.dwmapi.DwmSetWindowAttribute
    dwm.argtypes=[w.HWND,w.DWORD,ctypes.c_void_p,w.DWORD]
    enabled=ctypes.c_int(1)
    dwm(hwnd(root.winfo_id()),20,ctypes.byref(enabled),ctypes.sizeof(enabled))
    corners=ctypes.c_int(2)  # Windows 11 DWM default rounded owned window frame.
    dwm(hwnd(root.winfo_id()),33,ctypes.byref(corners),ctypes.sizeof(corners))


def disclosure(parent,title):
    """Keep optional parameters reachable without filling the everyday panel."""
    box=ttk.Frame(parent);box.pack(fill='x',pady=6)
    body=ttk.Frame(box)
    def toggle():
        opened=bool(body.winfo_manager())
        if opened:body.pack_forget()
        else:body.pack(fill='x',pady=6)
        button.configure(text=('▸ ' if opened else '▾ ')+title)
    button=ttk.Button(box,text='▸ '+title,command=toggle);button.pack(fill='x')
    return body


def editor_style(root):
    style=DpiStyle(root)
    style.configure('Editor.Tool.TButton',padding=(5,5),background=SURFACE,foreground=MUTED,borderwidth=0,font=(FONT,10),anchor='center')
    style.map('Editor.Tool.TButton',background=[('selected',SELECTED),('active',HOVER if MIDNIGHT else '#f0f4fa')],foreground=[('selected',ACCENT)])
    style.configure('Editor.Rail.TButton',padding=(8,6),background=SURFACE,foreground=INK,borderwidth=0,font=(FONT,10),anchor='w')
    style.map('Editor.Rail.TButton',background=[('selected',SELECTED),('pressed',SELECTED),('active',HOVER)],foreground=[('selected',ACCENT)])
    # Native Toolbutton inherits the Windows grey segmented surface. Reuse the
    # existing button element, retaining real radio keyboard/focus semantics.
    style.layout('Editor.Segment.TRadiobutton',style.layout('TButton'))
    style.configure('Editor.Segment.TRadiobutton',padding=(6,6),background=BG,foreground=MUTED,font=(FONT,10),anchor='center',borderwidth=0)
    style.map('Editor.Segment.TRadiobutton',background=[('selected',SELECTED),('pressed',SELECTED),('active',HOVER)],foreground=[('selected',INK),('active',INK)])
    style.configure('Editor.Primary.TButton',padding=(16,7),background=PRIMARY,foreground='#17181e' if MIDNIGHT else '#ffffff',font=(FONT,10,'bold'))
    style.map('Editor.Primary.TButton',background=[('disabled',HOVER if MIDNIGHT else '#aebccc'),('pressed','#c8c8d1'),('active','#f7f7fa')],foreground=[('disabled',MUTED)])
    style.configure('Editor.TNotebook',background=SURFACE,borderwidth=0)
    style.configure('Editor.TNotebook.Tab',padding=(12,8),font=(FONT,10))
    style.map('Editor.TNotebook.Tab',background=[('selected',SELECTED if MIDNIGHT else '#ffffff'),('!selected',BG if MIDNIGHT else '#e4eaf0')],foreground=[('selected',ACCENT)])
    style.configure('Editor.Property.TNotebook.Tab',padding=(5,5),font=(FONT,9))
    style.configure('Editor.Property.TNotebook',background=SURFACE,borderwidth=0,bordercolor=SURFACE,lightcolor=SURFACE,darkcolor=SURFACE)
    style.layout('Editor.Property.TNotebook.Tab',[])
    style.configure('Layers.Treeview',background=SURFACE,fieldbackground=SURFACE,foreground=INK,borderwidth=0,font=(FONT,9),rowheight=54)
    if MIDNIGHT:style.layout('Layers.Treeview',[('Treeview.treearea',{'sticky':'nswe'})])
    style.map('Layers.Treeview',background=[('selected',SELECTED)],foreground=[('selected',INK if MIDNIGHT else ACCENT)])
    return style


def panel_surface(widget):
    """Scope property surfaces to the editor; image pixels are never themed."""
    if isinstance(widget,ttk.Frame) and str(widget.cget('style'))!='Input.TFrame':widget.configure(style='Panel.TFrame')
    elif isinstance(widget,ttk.Label):
        current=str(widget.cget('style'))
        widget.configure(style='Panel.Muted.TLabel' if 'Muted' in current else 'Panel.TLabel')
    elif MIDNIGHT and isinstance(widget,ttk.Button) and str(widget.cget('style')) in ('','TButton'):
        widget.configure(style='Panel.TButton')
    for child in widget.winfo_children():panel_surface(child)


def text_field(parent,**options):
    """Rounded chrome around a real Tk Text; keep native IME and selection."""
    import tkinter as tk
    frame=ttk.Frame(parent,style='Input.TFrame' if MIDNIGHT else 'TFrame',padding=px(parent,10))
    text=tk.Text(frame,**options)
    text.configure(highlightthickness=0,padx=0,pady=0)
    text.pack(fill='both',expand=True)
    text.bind('<FocusIn>',lambda ev:frame.state(['focus']),add='+')
    text.bind('<FocusOut>',lambda ev:frame.state(['!focus']),add='+')
    return frame,text


def entry_hint(entry,variable,text):
    """A visual hint over an empty native entry; never changes its input value."""
    import tkinter as tk
    label=tk.Label(entry,text=text,bg=SURFACE,fg=MUTED,font=(FONT,9),anchor='w',cursor='xterm')
    def update(*_):
        if not variable.get() and entry.focus_get()!=entry:label.place(x=9,rely=.5,anchor='w')
        else:label.place_forget()
    label.bind('<Button-1>',lambda _:entry.focus_set())
    entry.bind('<FocusIn>',update,add='+');entry.bind('<FocusOut>',update,add='+')
    trace=variable.trace_add('write',update)
    entry.bind('<Destroy>',lambda event:variable.trace_remove('write',trace) if event.widget is entry else None,add='+')
    update()


class ScrollBody(ttk.Frame):
    """Local property scrolling; wheel never binds to another page/window."""
    def __init__(self,parent):
        import tkinter as tk
        super().__init__(parent)
        self.canvas=tk.Canvas(self,background=SURFACE,highlightthickness=0,width=px(parent,240))
        from ui_scroll import OverlayScrollbar
        self.bar=OverlayScrollbar(self.canvas)
        self.canvas.pack(side='left',fill='both',expand=True)
        self.body=ttk.Frame(self.canvas,style='Panel.TFrame')
        self.item=self.canvas.create_window(0,0,anchor='nw',window=self.body)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.bind('<Configure>',self.resize)
        self.body.bind('<Configure>',lambda ev:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
    def resize(self,event):
        if int(float(self.canvas.itemcget(self.item,'width')))!=event.width:self.canvas.itemconfigure(self.item,width=event.width)
    def attach(self):
        def bind(widget):
            if widget.winfo_class() in ('Label','TLabel') and float(widget.cget('wraplength') or 0)>0:
                if not getattr(widget,'_scroll_body_wrap',False):
                    def wrap(event,w=widget):
                        width=max(1,event.width-2)
                        if float(w.cget('wraplength'))!=width:w.configure(wraplength=width)
                    widget.bind('<Configure>',wrap,add='+');widget._scroll_body_wrap=True
            if widget.winfo_class() not in ('Text','Entry','TEntry','TCombobox','TSpinbox'):
                if not getattr(widget,'_scroll_body_wheel',False):
                    widget.bind('<MouseWheel>',self.wheel,add='+');widget._scroll_body_wheel=True
            for child in widget.winfo_children():bind(child)
        bind(self)
    def wheel(self,event):
        if self.body.winfo_height()>self.canvas.winfo_height():self.canvas.yview_scroll(-int(event.delta/120),'units')
        return 'break'


def video_style(root):
    """Scoped tokens for the clip workspace; leave all other pages unchanged."""
    style=DpiStyle(root)
    style.configure('Video.TFrame',background=BG)
    style.configure('Video.Title.TLabel',font=(FONT,16,'bold'),foreground=INK)
    style.configure('Video.Muted.TLabel',font=(FONT,9),foreground=MUTED)
    style.configure('Video.Primary.TButton',background=PRIMARY,foreground='#17181e' if MIDNIGHT else 'white',padding=(24,10),font=(FONT,11,'bold'))
    style.map('Video.Primary.TButton',background=[('disabled',HOVER if MIDNIGHT else '#aebccc'),('pressed','#c8cad6' if MIDNIGHT else '#214e98'),('active','#f2f2f5' if MIDNIGHT else '#346fce')],foreground=[('disabled',MUTED if MIDNIGHT else '#f1f4f7')])
    style.configure('Video.Tool.TButton',padding=(10,7),font=(FONT,10))
    return style


def apply(root):
    from ui_scroll import configure
    configure(root._root())
    style = DpiStyle(root)
    style.theme_use('clam')
    style.configure('TFrame', background=BG)
    style.configure('TLabel', background=BG, foreground=INK, font=(FONT, 10))
    # A global *Font also becomes an explicit ttk.Label/ttk.Button option and
    # overrides the title/tool styles. Set raw Tk widget defaults narrowly.
    for kind in ('Text','Listbox','Menu','Entry'):
        root.option_add('*'+kind+'.Font',(FONT,10))
    style.configure('TButton', padding=(12,7), font=(FONT,10),background=SURFACE,foreground=INK,borderwidth=0,bordercolor=BORDER,lightcolor=SURFACE,darkcolor=SURFACE,relief='flat')
    style.map('TButton',background=[('pressed',SELECTED),('active',HOVER)],bordercolor=[('focus',ACCENT),('active',BORDER if MIDNIGHT else '#b9c8dd')],foreground=[('disabled','#7a879c' if MIDNIGHT else '#96a2b3')])
    style.configure('TMenubutton',padding=(10,6),background=SURFACE,foreground=INK,bordercolor=BORDER,
                    lightcolor=SURFACE,darkcolor=SURFACE,arrowcolor=MUTED,relief='flat')
    style.configure('TEntry',padding=6,fieldbackground=SURFACE,bordercolor=BORDER,lightcolor=SURFACE,darkcolor=SURFACE)
    style.configure('TCombobox',padding=5,fieldbackground=SURFACE,background=SURFACE,bordercolor=BORDER,arrowcolor=MUTED)
    style.map('TCombobox',fieldbackground=[('readonly',SURFACE)],selectbackground=[('readonly',SURFACE)],selectforeground=[('readonly',INK)])
    style.configure('TSpinbox',padding=5,fieldbackground=SURFACE,background=SURFACE,bordercolor=BORDER,arrowcolor=MUTED)
    style.configure('TNotebook',background=BG,borderwidth=0)
    style.configure('TNotebook.Tab',background=BG,padding=(12,8),font=(FONT,10))
    style.map('TNotebook.Tab',background=[('selected',SURFACE)],foreground=[('selected',ACCENT)])
    style.configure('TScrollbar',background='#cad4e1',troughcolor=BG,borderwidth=0,arrowsize=12)
    style.configure('Title.TLabel', font=(FONT, 21, 'bold'), foreground=INK)
    style.configure('LibraryTitle.TLabel', font=(FONT, 18, 'bold'), foreground=INK)
    style.configure('Nav.TButton', anchor='w', padding=(12,12), font=(FONT,10),borderwidth=0,background=BG)
    style.map('Nav.TButton',background=[('selected',SELECTED),('active','#f5f7fb')],foreground=[('selected',ACCENT)])
    style.configure('Muted.TLabel',foreground=MUTED,font=(FONT,9))
    style.configure('Panel.TFrame',background=SURFACE)
    style.configure('Panel.TLabel',background=SURFACE,foreground=INK)
    style.configure('Panel.Muted.TLabel',background=SURFACE,foreground=MUTED,font=(FONT,9))
    style.configure('Treeview',background=SURFACE,fieldbackground=SURFACE,foreground=INK,
                    font=(FONT,10),rowheight=36,borderwidth=0,bordercolor=BORDER)
    style.configure('Treeview.Heading',background=HOVER,foreground=MUTED,font=(FONT,9),padding=(10,8),relief='flat')
    style.map('Treeview',background=[('selected',SELECTED)],foreground=[('selected',INK)])
    style.configure('TLabelframe',background=BG,bordercolor=BORDER,relief='flat')
    style.configure('TLabelframe.Label',background=BG,foreground=MUTED,font=(FONT,9))
    style.configure('TSeparator',background=BORDER)
    style.configure('Horizontal.TProgressbar',background=ACCENT,troughcolor=SURFACE,bordercolor=SURFACE,
                    lightcolor=ACCENT,darkcolor=ACCENT,thickness=5)
    if MIDNIGHT:
        root.configure(background=BG)
        style.configure('TNotebook.Tab',foreground=MUTED)
        for name in ('TNotebook','TNotebook.Tab','Editor.TNotebook','Editor.TNotebook.Tab','Editor.Property.TNotebook'):
            style.configure(name,bordercolor=BORDER,lightcolor=SURFACE,darkcolor=SURFACE)
        for name in ('TEntry','TCombobox','TSpinbox'):
            style.configure(name,foreground=INK,insertcolor=INK,selectbackground=SELECTED,selectforeground=INK,lightcolor=BORDER,darkcolor=BORDER)
            style.map(name,bordercolor=[('focus',ACCENT)],lightcolor=[('focus',ACCENT)],darkcolor=[('focus',ACCENT)])
        for name in ('TCheckbutton','TRadiobutton'):
            style.configure(name,background=BG,foreground=INK,indicatorbackground=SURFACE,indicatorforeground=ACCENT)
            style.map(name,background=[('active',HOVER)],indicatorbackground=[('selected',PRIMARY)],foreground=[('disabled',DISABLED)])
        for name in ('TScrollbar','Horizontal.TScrollbar','Vertical.TScrollbar'):
            style.configure(name,background=BORDER,troughcolor=BG,arrowcolor=MUTED,gripcount=0,arrowsize=14,
                            borderwidth=0,bordercolor=BG,lightcolor=BORDER,darkcolor=BORDER)
            style.map(name,background=[('pressed',MUTED),('active',MUTED)])
        for name in ('TScale','Horizontal.TScale','Vertical.TScale'):
            style.configure(name,background=ACCENT,troughcolor=BORDER,bordercolor=ACCENT,
                            lightcolor=ACCENT,darkcolor=ACCENT,borderwidth=1,sliderlength=14)
            style.map(name,background=[('pressed',INK),('active',INK)])
        style.map('Treeview.Heading',background=[('active',SELECTED)])
        style.map('Nav.TButton',background=[('selected',SELECTED),('active',HOVER)],foreground=[('selected',ACCENT)])
        style.map('TMenubutton',background=[('active',HOVER)],foreground=[('active',INK)])
        for kind in ('Text','Listbox','Menu'):
            for key,value in {'background':SURFACE,'foreground':INK,'selectBackground':SELECTED,'selectForeground':INK,'insertBackground':INK,'highlightBackground':BORDER,'highlightColor':ACCENT}.items():
                root.option_add('*'+kind+'.'+key,value)
        root.option_add('*Menu.activeBackground',SELECTED)
        root.option_add('*Menu.activeForeground',INK)
        root.option_add('*Menu.disabledForeground',DISABLED)
        root.option_add('*Menu.relief','flat')
        root.option_add('*Menu.borderWidth',0)
        root.option_add('*Menu.activeBorderWidth',0)
        root.option_add('*Text.relief','flat')
        root.option_add('*Text.borderWidth',0)
        root.option_add('*Text.highlightThickness',1)
        root.option_add('*Text.padX',10)
        root.option_add('*Text.padY',8)
        root.option_add('*Listbox.relief','flat')
        root.option_add('*Listbox.borderWidth',0)
        root.option_add('*Listbox.highlightThickness',1)
        root.option_add('*TCombobox*Listbox.background',SURFACE)
        root.option_add('*TCombobox*Listbox.foreground',INK)
        root.after_idle(lambda:native_titlebar(root) if root.winfo_exists() else None)
    editor_style(root)
    if MIDNIGHT:
        style.configure('Editor.TNotebook',bordercolor=BORDER,lightcolor=SURFACE,darkcolor=SURFACE)
        style.configure('Editor.TNotebook.Tab',foreground=MUTED,bordercolor=BORDER,lightcolor=SURFACE,darkcolor=SURFACE)
        style.configure('Muted.TLabel',font=(FONT,10))
        style.configure('Panel.Muted.TLabel',font=(FONT,10))
        from ui_elements import rounded_elements
        rounded_elements(root,style,_tokens)
