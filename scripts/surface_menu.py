"""Small, owned command popover for the editor's two simple top menus.

Uses the existing ttk controls and focus semantics, avoiding Windows' light
non-client border on a Tk Menu. No global bindings or system dialog changes.
"""
import tkinter as tk
from tkinter import ttk
from ui_style import SURFACE,BORDER


class SurfaceMenu:
    def __init__(self, button):
        self.button=button;self.items=[];self.popup=None
        button.configure(command=self.toggle)
        button.bind('<Down>',lambda _:self.toggle())
        button.bind('<Destroy>',lambda _:self.close(False),add='+')

    def add_command(self, *, label, command, **_):
        self.items.append((label,command))

    def close(self, restore=True):
        popup=self.popup;self.popup=None
        if popup:
            try:popup.grab_release();popup.destroy()
            except tk.TclError:pass
        if restore and self.button.winfo_exists():self.button.focus_set()

    def invoke(self, index):
        command=self.items[index][1];self.close();command()

    def toggle(self):
        if self.popup:self.close();return 'break'
        p=tk.Toplevel(self.button,background=SURFACE,highlightbackground=BORDER,highlightthickness=1)
        self.popup=p;p.withdraw();p.overrideredirect(True);p.transient(self.button.winfo_toplevel())
        body=ttk.Frame(p,padding=5,style='Panel.TFrame');body.pack(fill='both',expand=True)
        buttons=[]
        for n,(label,_) in enumerate(self.items):
            b=ttk.Button(body,text=label,command=lambda i=n:self.invoke(i),style='Editor.Tool.TButton')
            b.pack(fill='x',pady=1);buttons.append(b)
            b.bind('<Up>',lambda _,i=n:(buttons[(i-1)%len(buttons)].focus_set(),'break')[1])
            b.bind('<Down>',lambda _,i=n:(buttons[(i+1)%len(buttons)].focus_set(),'break')[1])
            b.bind('<Return>',lambda _,i=n:(self.invoke(i),'break')[1])
        p.bind('<Escape>',lambda _:(self.close(),'break')[1])
        p.bind('<Tab>',lambda _:(self.close(),'break')[1])
        def outside(event):
            if not (p.winfo_rootx()<=event.x_root<p.winfo_rootx()+p.winfo_width() and p.winfo_rooty()<=event.y_root<p.winfo_rooty()+p.winfo_height()):self.close()
        p.bind('<ButtonPress-1>',outside,add='+')
        p.bind('<FocusOut>',lambda _:p.after_idle(lambda:self.close(False) if self.popup is p and p.focus_get() is None else None))
        p.update_idletasks();x=self.button.winfo_rootx();y=self.button.winfo_rooty()+self.button.winfo_height()+3
        x=max(0,min(x,p.winfo_screenwidth()-p.winfo_reqwidth()))
        y=max(0,min(y,p.winfo_screenheight()-p.winfo_reqheight()))
        p.geometry(f'+{x}+{y}');p.deiconify();p.grab_set()
        if buttons:buttons[0].focus_set()
        return 'break'
