"""Shared labelled horizontal controls for editor parameters."""
import math
import tkinter as tk
from tkinter import ttk
from ui_dpi import px, spacing


class ParameterBar(ttk.Frame):
    def __init__(self, parent, title, variable, low, high, *, step=1, suffix='', input_high=None):
        super().__init__(parent)
        self.variable=variable;self.step=step;self.low=low;self.high=high
        self.position=tk.DoubleVar(value=variable.get());self.syncing=False
        head=ttk.Frame(self);head.pack(fill='x')
        ttk.Label(head,text=title).pack(side='left')
        self.value=tk.StringVar()
        ttk.Label(head,text=suffix.strip(),style='Muted.TLabel').pack(side='right',padx=spacing(self,(4,0)))
        self.number=tk.StringVar(value=f'{float(variable.get()):g}')
        self.input_high=high if input_high is None else input_high
        self.label=ttk.Spinbox(head,textvariable=self.number,from_=low,to=self.input_high,increment=step,width=7,justify='right',command=self.enter_number)
        self.label.pack(side='right')
        self.label.bind('<Return>',self.enter_number);self.label.bind('<FocusOut>',self.enter_number)
        self.suffix=suffix
        self.scale=ttk.Scale(self,from_=low,to=high,variable=self.position,command=self.slide)
        self.scale.pack(fill='x',pady=spacing(self,(6,3)))
        self.scale.bind('<Left>',lambda event:self.nudge(-1))
        self.scale.bind('<Right>',lambda event:self.nudge(1))
        self.trace=variable.trace_add('write',self.refresh)
        self.bind('<Destroy>',self.destroyed,add='+');self.refresh()

    def slide(self,value):
        if self.syncing:return
        value=max(self.low,min(self.high,round(float(value)/self.step)*self.step))
        self.variable.set(int(value) if isinstance(self.variable,tk.IntVar) else round(value,4))

    def nudge(self,direction):
        self.slide(float(self.variable.get())+direction*self.step);return 'break'

    def enter_number(self,event=None):
        try:
            value=float(self.number.get())
            if not math.isfinite(value) or not self.low<=value<=self.input_high:raise ValueError()
            self.variable.set(int(round(value)) if isinstance(self.variable,tk.IntVar) else value)
        except (ValueError,tk.TclError):self.refresh()
        return 'break' if event and event.keysym=='Return' else None

    def refresh(self,*_):
        try:value=float(self.variable.get())
        except (ValueError,tk.TclError):return
        if not math.isfinite(value):return
        self.syncing=True;self.position.set(value);self.syncing=False
        self.value.set(f'{value:g}{self.suffix}')
        self.number.set(f'{value:g}')

    def limits(self,low,high):
        self.low=low;self.high=max(low,high);self.scale.configure(from_=low,to=self.high)
        self.input_high=max(self.input_high,self.high);self.label.configure(from_=low,to=self.input_high)

    def destroyed(self,event):
        if event.widget==self:
            try:self.variable.trace_remove('write',self.trace)
            except tk.TclError:pass
