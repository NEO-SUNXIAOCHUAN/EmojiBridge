"""Same-document, canvas-first geometry. Catalogues are views, never loaders."""
from ui_dpi import px, spacing, factor
import tkinter as tk
from tkinter import ttk
from ui_style import BG


class WorkspaceLayout:
    def __init__(self, factory):
        self.f=factory; self.e=e=factory.e; self.opened=False; self.expanded=False
        self.width=px(self.e.window,304); self.drawer=False
        # Keep original Tk parents and native canvas stacking intact.
        self.inspector=tk.PanedWindow(e.editor_tabs,orient='vertical',bg=BG,sashwidth=px(self.e.window,8),borderwidth=0)
        from ui_sash import SashMotion
        self.sash_motion=SashMotion(e.panes);self.inspector_motion=SashMotion(self.inspector)
        e.editor_tabs.forget(e.properties_host);e.editor_tabs.forget(e.layers_host)
        e.editor_tabs.add(self.inspector,text='属性与图层')
        self.inspector.add(e.properties_host,minsize=px(self.e.window,150),stretch='always')
        self.inspector.add(e.layers_host,minsize=px(self.e.window,100),height=px(e.window,128),stretch='never')
        self.inspector_ratio=None;self.inspector_pending=None;self.inspector_drag=False
        self.inspector.bind('<Configure>',self.arrange_inspector,add='+')
        self.inspector.bind('<ButtonPress-1>',self.inspector_press,add='+')
        self.inspector.bind('<ButtonRelease-1>',self.inspector_release,add='+')
        e.properties_host.lift(self.inspector);e.layers_host.lift(e.properties_host)
        controls=ttk.Frame(e.browser_host,padding=px(self.e.window,5));controls.pack(fill='x',before=e.browser_tabs)
        self.expand=ttk.Button(controls,text='展开浏览',command=self.toggle_expand);self.expand.pack(side='left')
        ttk.Button(controls,text='收起目录',command=self.hide).pack(side='right')
        e.panes.forget(e.browser_host)
        e.panes.paneconfigure(e.canvas_host,minsize=px(self.e.window,250),stretch='always')
        e.panes.paneconfigure(e.tools,minsize=px(self.e.window,264),width=px(e.window,286),stretch='never')
        e.panes.bind('<Configure>',lambda _:self.arrange(),add='+')
        e.panes.bind('<ButtonRelease-1>',lambda _:self.remember(),add='+')
        ttk.Button(factory.rail.winfo_children()[0],text='恢复默认布局',command=self.reset).pack(fill='x',pady=px(self.e.window,3))
        factory.enlarge.configure(text='展开目录',command=lambda:self.hide() if self.opened else self.show(e.effects_host))

    def remember(self):
        if self.opened and not self.drawer:self.width=max(px(self.e.window,280),self.e.browser_host.winfo_width())
        self.arrange()

    def inspector_press(self,event):
        self.inspector_drag=bool(self.inspector.identify(event.x,event.y))

    def inspector_release(self,event):
        if self.inspector_drag:
            height=self.inspector.winfo_height()
            self.inspector_ratio=(height-self.inspector.sash_coord(0)[1]-px(self.e.window,8))/max(1,height)
        self.inspector_drag=False

    def arrange_inspector(self,event=None):
        if event is not None and event.widget is not self.inspector:return
        if self.inspector_pending is not None:self.inspector.after_cancel(self.inspector_pending)
        def apply():
            self.inspector_pending=None
            height=self.inspector.winfo_height()
            if height<px(self.e.window,260) or self.inspector_drag:return
            layers=(height*self.inspector_ratio if self.inspector_ratio is not None
                    else min(px(self.e.window,160),height*.22))
            layers=max(px(self.e.window,100),min(layers,height-px(self.e.window,150)))
            y=round(height-layers-px(self.e.window,8))
            if self.inspector.sash_coord(0)[1]!=y:self.inspector.sash_place(0,0,y)
        self.inspector_pending=self.inspector.after_idle(apply)

    def show(self,page):
        self.opened=True;self.e.browser_tabs.select(page);self.arrange()
        self.f.enlarge.configure(text='返回编辑')

    def hide(self):
        e=self.e
        if e.browser_host.winfo_manager()=='panedwindow':e.panes.forget(e.browser_host)
        e.browser_host.place_forget();self.opened=False
        self.f.enlarge.configure(text='展开目录');e.resized()

    def arrange(self):
        if not self.opened:return
        e=self.e;total=e.panes.winfo_width()
        if total<px(e.window,300):return
        drawer=total<px(e.window,1160)
        available=max(px(e.window,280),total-px(e.window,766))
        width=min(available,px(e.window,520) if self.expanded else self.width)
        manager=e.browser_host.winfo_manager()
        if drawer:
            if manager=='panedwindow':e.panes.forget(e.browser_host)
            e.browser_host.place(x=self.f.rail.winfo_width()+px(e.window,8),y=0,width=min(px(e.window,380 if self.expanded else 304),total-px(e.window,170)),relheight=1)
            e.browser_host.lift()
        else:
            if manager=='place':e.browser_host.place_forget()
            if manager!='panedwindow':e.panes.add(e.browser_host,before=e.canvas_host,minsize=px(self.e.window,280),width=width,stretch='never')
            elif e.browser_host.winfo_width()>available or self.drawer:e.panes.paneconfigure(e.browser_host,width=width)
        self.drawer=drawer

    def toggle_expand(self):
        self.expanded=not self.expanded;self.width=px(self.e.window,520 if self.expanded else 304)
        self.expand.configure(text='两列浏览' if self.expanded else '展开浏览')
        if self.e.browser_host.winfo_manager()=='panedwindow':self.e.panes.paneconfigure(self.e.browser_host,width=self.width)
        self.arrange()

    def reset(self):
        self.hide();self.expanded=False;self.width=px(self.e.window,304)
        self.expand.configure(text='展开浏览')
        if not self.e.tools.winfo_manager():self.e.toggle_tools()
        self.e.panes.paneconfigure(self.e.tools,width=px(self.e.window,286))
        self.inspector_ratio=None;self.arrange_inspector()
        self.e.zoom_by(None)
