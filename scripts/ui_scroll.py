"""Shared, layout-neutral scroll affordance; never used for task progress/sliders."""
import tkinter as tk
from tkinter import ttk
import time
from ui_dpi import px

HIT=16; THIN=4; HOVER=6; IDLE=1000; FADE=180


def system_preferences():
    always=reduce=contrast=False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Control Panel\Accessibility') as key:
            always=not bool(winreg.QueryValueEx(key,'DynamicScrollbars')[0])
    except (ImportError,OSError):pass
    try:
        import ctypes as c
        enabled=c.c_int(1);c.windll.user32.SystemParametersInfoW(0x1042,0,c.byref(enabled),0)
        reduce=not bool(enabled.value)
        class HC(c.Structure):_fields_=[('size',c.c_uint),('flags',c.c_uint),('scheme',c.c_void_p)]
        hc=HC(c.sizeof(HC),0,None);c.windll.user32.SystemParametersInfoW(0x42,hc.size,c.byref(hc),0)
        contrast=bool(hc.flags&1)
    except (ImportError,OSError,AttributeError):pass
    return {'always_scrollbars':always,'reduce_motion':reduce,'high_contrast':contrast}


class ScrollCoordinator:
    def __init__(self,root):
        self.root=root;self.bars={};self.preferences=system_preferences()
        root.bind_all('<Motion>',self.motion,add='+')
        root.bind_all('<KeyPress>',self.key,add='+')
        root.bind_all('<Map>',self.map,add='+')
    def map(self,event):
        widget=event.widget
        if not isinstance(widget,(tk.Text,tk.Listbox,ttk.Treeview)):return
        if not widget.cget('yscrollcommand'):OverlayScrollbar(widget)
        if isinstance(widget,(tk.Listbox,ttk.Treeview)) and not widget.cget('xscrollcommand'):OverlayScrollbar(widget,orient='horizontal')
    def owners(self,widget):
        while widget is not None:
            for bar in self.bars.get(str(widget),()):yield bar
            widget=getattr(widget,'master',None)
    def motion(self,event):
        if not hasattr(event.widget,'winfo_rootx'):return
        for bar in self.owners(event.widget):
            target=bar.target
            near=(event.x_root>=target.winfo_rootx()+target.winfo_width()-px(target,HIT) if bar.vertical else event.y_root>=target.winfo_rooty()+target.winfo_height()-px(target,HIT))
            if near:bar.show()
    def key(self,event):
        if event.keysym in ('Up','Down','Left','Right','Prior','Next','Home','End'):
            for bar in self.owners(event.widget):bar.show()


class OverlayScrollbar(tk.Canvas):
    def __init__(self,target,orient='vertical',command=None):
        from ui_style import SURFACE,MUTED
        self.target=target;self.vertical=orient=='vertical';self.command=command or (target.yview if self.vertical else target.xview)
        try:bg=target.cget('background')
        except tk.TclError:bg=ttk.Style(target).lookup(target.cget('style') or target.winfo_class(),'background') or SURFACE
        super().__init__(target.master,bg=bg,width=px(self.target,HIT),height=px(self.target,HIT),highlightthickness=0,takefocus=True,cursor='arrow')
        root=target._root()
        if not hasattr(root,'_scroll_coordinator'):root._scroll_coordinator=ScrollCoordinator(root)
        self.coordinator=root._scroll_coordinator;self.coordinator.bars.setdefault(str(target),[]).append(self)
        self.first=0.;self.last=1.;self.hover=False;self.drag=None;self.opacity=0.;self.timer=None;self.closed=False
        self.color=MUTED;self.thumb=self.create_line(0,0,0,0,width=px(self.target,THIN),capstyle='round',fill=bg)
        self.bind('<Configure>',lambda _:self.draw());self.bind('<Enter>',self.enter);self.bind('<Leave>',self.leave)
        self.bind('<ButtonPress-1>',self.press);self.bind('<B1-Motion>',self.motion);self.bind('<ButtonRelease-1>',self.release)
        self.bind('<FocusIn>',lambda _:self.show());self.bind('<FocusOut>',lambda _:self.arm())
        self.bind('<KeyPress>',self.key);self.bind('<MouseWheel>',self.wheel)
        target.bind('<Configure>',lambda _:self.draw(),add='+')
        target.bind('<Destroy>',self.destroy_target,add='+')
        target.configure(**{('yscrollcommand' if self.vertical else 'xscrollcommand'):self.set})
    def prefs(self):return {**self.coordinator.preferences,**getattr(self.target._root(),'_scroll_preferences',{})}
    def set(self,first,last):
        old=(self.first,self.last);self.first=max(0.,float(first));self.last=min(1.,float(last))
        if self.closed:return
        if self.last-self.first>=.9999:self.cancel_timer();self.place_forget();self.opacity=0.;return
        if old!=(self.first,self.last):self.show()
        elif self.prefs().get('always_scrollbars') or self.prefs().get('high_contrast'):self.show()
        else:self.draw()
    def geometry(self):
        length=self.target.winfo_height() if self.vertical else self.target.winfo_width()
        size=min(length,max(px(self.target,28),length*(self.last-self.first)))
        start=self.first/max(.00001,1-(self.last-self.first))*(length-size)
        return length,size,start
    def draw(self):
        if self.closed or not self.winfo_manager():return
        length,size,start=self.geometry();width=px(self.target,HOVER) if self.hover or self.drag is not None or self.focus_get()==self else px(self.target,THIN)
        bg=self.winfo_rgb(self.cget('background'));fg=self.winfo_rgb('SystemWindowText' if self.prefs().get('high_contrast') else self.color)
        color='#'+''.join(f'{round((b+(f-b)*self.opacity)/257):02x}' for b,f in zip(bg,fg))
        coords=(px(self.target,HIT)/2,start+width/2,px(self.target,HIT)/2,max(start+width/2,start+size-width/2)) if self.vertical else (start+width/2,px(self.target,HIT)/2,max(start+width/2,start+size-width/2),px(self.target,HIT)/2)
        self.coords(self.thumb,*coords);self.itemconfigure(self.thumb,fill=color,width=width)
    def show(self):
        if self.closed or self.last-self.first>=.9999:return
        self.cancel_timer();self.opacity=1.
        if not self.winfo_manager():
            if self.vertical:self.place(in_=self.target,relx=1,x=-px(self.target,HIT),y=0,width=px(self.target,HIT),relheight=1)
            else:self.place(in_=self.target,rely=1,y=-px(self.target,HIT),x=0,height=px(self.target,HIT),relwidth=1)
            self.tk.call('raise',self._w)
        self.draw();self.arm()
    def cancel_timer(self):
        if self.timer is not None:self.after_cancel(self.timer);self.timer=None
    def held(self):return self.hover or self.drag is not None or self.focus_get()==self or self.prefs().get('always_scrollbars') or self.prefs().get('high_contrast')
    def arm(self):
        self.cancel_timer()
        if not self.held():self.timer=self.after(IDLE,self.fade)
    def fade(self):
        self.timer=None
        if self.closed or self.held():return
        if self.prefs().get('reduce_motion'):self.opacity=0
        else:self.opacity=max(0,self.opacity-16/FADE)
        if not self.opacity:self.place_forget()
        else:self.draw();self.timer=self.after(16,self.fade)
    def enter(self,_):self.hover=True;self.show()
    def leave(self,_):self.hover=False;self.arm();self.draw()
    def press(self,event):
        length,size,start=self.geometry();pos=event.y if self.vertical else event.x
        self.focus_set();self.grab_set();self.drag=(pos,self.first)
        if not start<=pos<=start+size:
            fraction=max(0,min(1-(self.last-self.first),(pos-size/2)/max(1,length-size)*(1-(self.last-self.first))))
            self.command('moveto',fraction);self.drag=(pos,fraction)
        self.show();return 'break'
    def motion(self,event):
        if self.drag is not None:
            length,size,_=self.geometry();pos=event.y if self.vertical else event.x
            self.command('moveto',self.drag[1]+(pos-self.drag[0])/max(1,length-size)*(1-(self.last-self.first)))
        return 'break'
    def release(self,event):
        self.motion(event);self.drag=None
        if self.grab_current()==self:self.grab_release()
        self.target.focus_set();self.arm();return 'break'
    def key(self,event):
        moves={'Up':-1,'Left':-1,'Down':1,'Right':1,'Prior':-1,'Next':1}
        if event.keysym in moves:self.command('scroll',moves[event.keysym],'pages' if event.keysym in ('Prior','Next') else 'units')
        elif event.keysym in ('Home','End'):self.command('moveto',0 if event.keysym=='Home' else 1)
        else:return
        self.show();return 'break'
    def wheel(self,event):
        if event.delta:self.command('scroll',-int(event.delta/120) or (-1 if event.delta>0 else 1),'units');self.show()
        return 'break'
    def destroy_target(self,event):
        if event.widget is self.target:self.destroy()
    def destroy(self):
        if self.closed:return
        self.closed=True;self.cancel_timer()
        if self.grab_current()==self:self.grab_release()
        bars=self.coordinator.bars.get(str(self.target),[])
        if self in bars:bars.remove(self)
        if not bars:self.coordinator.bars.pop(str(self.target),None)
        super().destroy()


def configure(root,preferences=None):
    if not hasattr(root,'_scroll_coordinator'):root._scroll_coordinator=ScrollCoordinator(root)
    if preferences is not None:
        root._scroll_preferences={key:bool(preferences[key]) for key in ('always_scrollbars','reduce_motion') if key in preferences}
        for bars in list(root._scroll_coordinator.bars.values()):
            for bar in bars:bar.show()
