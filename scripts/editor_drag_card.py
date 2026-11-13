"""One native drag surface: image, label and whitespace share the hit area."""
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageDraw,ImageTk
from ui_dpi import px
from ui_style import BG,INK,FONT


class DragCard(tk.Canvas):
    def __init__(self,parent,owner):
        self.owner=owner;self.hovered=False;self.legacy_text='拖出成品\n未准备';self.preview=None
        self.badge='未准备';self.hover_job=None;self.tip=None;self.pressed=None;self.dragged=False
        super().__init__(parent,width=px(parent,196),height=px(parent,64),highlightthickness=0,bg=BG,takefocus=1,cursor='hand2')
        self.bind('<Enter>',self.enter);self.bind('<Leave>',self.leave)
        self.bind('<ButtonPress-1>',self.press);self.bind('<ButtonRelease-1>',self.release)
        self.bind('<FocusIn>',lambda e:self.draw());self.bind('<FocusOut>',lambda e:self.draw())
        self.bind('<Return>',lambda e:owner.prepare());self.bind('<space>',lambda e:owner.prepare())
        self.bind('<Configure>',lambda e:self.draw());self.bind('<Destroy>',lambda e:self.hide_tip())
        self.draw()

    def configure(self,cnf=None,**kw):
        if isinstance(cnf,dict):kw={**cnf,**kw};cnf=None
        changed=False
        if 'text' in kw:
            text=kw.pop('text');self.legacy_text=text;changed=True
            self.badge=('重试' if '重试' in text else '已取消' if '已取消' in text else '' if '就绪' in text else '编辑中' if '编辑完成' in text else '未准备' if any(s in text for s in ('等待','点击准备','未准备')) else '准备中')
        kw.pop('image',None)
        result=super().configure(cnf,**kw) if cnf is not None or kw else None
        if changed:self.draw()
        return result

    config=configure
    def cget(self,key):return self.legacy_text if key=='text' else super().cget(key)

    def set_preview(self,image):
        if image is None:self.preview=None
        else:
            image=image.convert('RGBA');bounds=image.getbbox()
            if bounds:image=image.crop(bounds)
            # Small content must also fill the preview tile. thumbnail() only
            # shrinks, leaving a tiny subject as the same tiny dot in the card.
            fit=min(px(self,52)/image.width,px(self,52)/image.height)
            image=image.resize(tuple(max(1,round(n*fit)) for n in image.size),Image.Resampling.LANCZOS)
            self.preview=ImageTk.PhotoImage(image,master=self)
        self.draw()

    def draw(self):
        if not self.winfo_exists():return
        p=lambda n:px(self,n);w=p(196);h=p(64)
        try:active=self.hovered or self.focus_get()==self
        except (KeyError,tk.TclError):active=self.hovered
        doc=self.owner.editor.doc
        from emoji_bridge.work_output import preferred_format
        kind=preferred_format(doc).upper() if doc else 'PNG'
        cancelling=self.owner.future is not None or self.owner.operation_future is not None
        stamp=(active,kind,self.badge,str(self.preview),cancelling)
        if stamp==getattr(self,'stamp',None):return
        self.stamp=stamp;self.delete('all')
        image=Image.new('RGB',(w*2,h*2),BG);d=ImageDraw.Draw(image)
        d.rounded_rectangle((1,1,w*2-2,h*2-2),radius=p(12)*2,fill='#202b39' if active else '#191f29',outline='#779dcc' if active else '#415875',width=max(2,p(1)*2))
        d.rounded_rectangle((p(6)*2,p(4)*2,p(62)*2,p(60)*2),radius=p(8)*2,fill='#2a3240')
        self.surface=ImageTk.PhotoImage(image.resize((w,h),Image.Resampling.LANCZOS),master=self)
        self.create_image(0,0,image=self.surface,anchor='nw')
        if self.preview:self.create_image(p(34),p(32),image=self.preview)
        else:
            self.create_rectangle(p(23),p(20),p(45),p(44),outline='#90a1b8',width=p(1))
            self.create_line(p(26),p(38),p(32),p(32),p(36),p(36),p(42),p(29),fill='#90a1b8',width=p(1))
        self.create_text(p(73),p(23 if self.badge else 32),text='拖出 '+kind,anchor='w',fill=INK,font=(FONT,9))
        if self.badge:self.create_text(p(74),p(44),text=self.badge,anchor='w',fill='#b4c9e3' if self.badge!='重试' else '#e8c393',font=(FONT,8))
        if cancelling:
            self.create_line(p(176),p(39),p(184),p(47),fill='#becbdb',width=p(1));self.create_line(p(184),p(39),p(176),p(47),fill='#becbdb',width=p(1))
        else:
            for x in (177,182):
                for y in (26,32,38):self.create_oval(p(x),p(y),p(x+1),p(y+1),fill='#8b9eb7',outline='')

    def press(self,event):self.pressed=(event.x,event.y);self.dragged=False;self.hide_tip();self.focus_set()
    def cancel_hit(self):return self.pressed and self.pressed[0]>=px(self,166) and self.pressed[1]>=px(self,33) and (self.owner.future or self.owner.operation_future)

    def release(self,event):
        if self.pressed and not self.dragged and abs(event.x-self.pressed[0])+abs(event.y-self.pressed[1])<px(self,6):
            if self.cancel_hit():self.owner.cancel_prepare()
            elif not self.owner.ready():self.owner.prepare()
        self.pressed=None

    def enter(self,event):
        self.hovered=True;self.draw();self.hide_tip();self.hover_job=self.after(650,self.show_tip)
    def leave(self,event):self.hovered=False;self.hide_tip();self.draw()

    def show_tip(self):
        self.hover_job=None
        if not self.hovered or self.pressed:return
        self.tip=tk.Toplevel(self);self.tip.withdraw();self.tip.overrideredirect(True);self.tip.attributes('-topmost',True)
        size=self.owner.output_size();text='按住拖到聊天输入框或文件夹'
        if size:text+=f'\n{size[0]} × {size[1]} 像素'
        if self.badge:text+='\n'+('点击重试' if self.badge=='重试' else '点击准备成品' if self.badge in ('未准备','已取消') else '准备中可点右侧取消')
        ttk.Label(self.tip,text=text,padding=px(self,9)).pack()
        self.tip.geometry(f'+{self.winfo_rootx()}+{self.winfo_rooty()+self.winfo_height()+px(self,6)}');self.tip.deiconify()

    def hide_tip(self):
        if self.hover_job:self.after_cancel(self.hover_job);self.hover_job=None
        if self.tip:self.tip.destroy();self.tip=None
