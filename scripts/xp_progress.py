"""Opt-in right-side progress for a foreground operation's actual wait.

Only the explicit worker owning this widget may start XP. Layout, hover and
the application's general activity bus never grant presentation eligibility.
The original V9 renderer/audio stays in the desktop WebView; a small region in
the native host exposes it at this widget's actual bounds.
"""
import tkinter as tk
from tkinter import ttk
from emoji_bridge.task_activity import begin, finish, snapshot


class XPProgress(ttk.Frame):
    def __init__(self, parent, editor, **options):
        super().__init__(parent, height=68,style='Panel.TFrame')
        self.editor=editor;self.activity={}
        self.fallback=ttk.Progressbar(self, **options)
        if not editor.embedded:self.fallback.pack(fill='x',expand=True)
        self.pack_propagate(False);self.grid_propagate(False)
        editor.xp_slots=getattr(editor,'xp_slots',[])+[self]

    def begin(self, label):
        self.activity=begin(label);self.activity['xp_eligible']=True
        return self.activity

    def finish(self,error=None,cancel=None,activity=None):
        value=self.activity if activity is None else activity
        if value.get('active'):finish(value,error,cancel)

    def start(self,*args):
        if not self.editor.embedded:self.fallback.start(*args)
    def stop(self):self.fallback.stop()
    def configure(self,**kw):
        if hasattr(self,'fallback'):return self.fallback.configure(**kw)
        return super().configure(**kw)

    def presentation(self,root):
        if not self.winfo_viewable():return None
        # Display eligibility belongs to this original progress slot. Running
        # eligibility is granted only by begin(), after worker admission.
        from ui_style import SURFACE
        return {'eligible':True,'slot':str(self),'background':SURFACE,'task':snapshot(self.activity),'rect':{
            'x':self.winfo_rootx()-root.winfo_rootx(),'y':self.winfo_rooty()-root.winfo_rooty(),
            'width':self.winfo_width(),'height':self.winfo_height(),
            'rootWidth':root.winfo_width(),'rootHeight':root.winfo_height()}}
