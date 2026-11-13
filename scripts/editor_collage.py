"""A small fixed-template collage panel usable from any editor document."""
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageDraw,ImageTk
from ui_style import ScrollBody,BG,SURFACE,INK,ACCENT
from ui_dpi import px,spacing
from editor_controls import ParameterBar
from emoji_bridge.collage_layout import LAYOUTS,arrange,plan
from copy import copy


class CollagePanel:
    def __init__(self,e):
        self.e=e;self.preview_job=None;self.preview_active=False;self.preview_photo=None
        self.page=ttk.Frame(e.tabs,padding=px(e.window,12));e.tabs.add(self.page,text='拼图模板')
        self.preview_canvas=tk.Canvas(e.canvas,background=BG,highlightthickness=0)
        self.preview_canvas.bind('<Configure>',lambda _:self.schedule_preview())
        ttk.Button(self.page,text='应用拼图模板',command=self.apply,style='Editor.Primary.TButton').pack(side='bottom',fill='x',pady=spacing(e.window,(10,0)))
        scroll=ScrollBody(self.page);scroll.pack(fill='both',expand=True);body=scroll.body
        ttk.Label(body,text='选择拼图模板',style='Heading.TLabel').pack(anchor='w')
        self.note=tk.StringVar();ttk.Label(body,textvariable=self.note,wraplength=px(e.window,235),style='Muted.TLabel').pack(fill='x',pady=px(e.window,8))
        self.layout=tk.StringVar(value='四宫格');self.cards={};self.photos=[]
        grid=ttk.Frame(body);grid.pack(fill='x');grid.columnconfigure((0,1),weight=1)
        for i,(name,shape) in enumerate(LAYOUTS.items()):
            image=Image.new('RGBA',(px(e.window,84),px(e.window,52)),SURFACE);d=ImageDraw.Draw(image)
            columns,rows=shape or (1,3);width,height=image.size
            for y in range(rows):
                for x in range(columns):
                    rect=(round(8+x*(width-16)/columns),round(5+y*(height-10)/rows),round(8+(x+1)*(width-16)/columns)-3,round(5+(y+1)*(height-10)/rows)-3)
                    d.rounded_rectangle(rect,radius=2,fill='#3c4f66')
            photo=ImageTk.PhotoImage(image);self.photos.append(photo)
            button=ttk.Radiobutton(grid,text=name,image=photo,compound='top',variable=self.layout,value=name,style='Tool.TButton',command=self.preview)
            button.grid(row=i//2,column=i%2,sticky='ew',padx=px(e.window,3),pady=px(e.window,4));self.cards[name]=button
        self.cell=tk.IntVar(value=512);self.gap=tk.IntVar(value=12);self.transparent=tk.BooleanVar(value=True)
        self.cell_bar=ParameterBar(body,'格子宽度',self.cell,32,2048,step=16,suffix=' px',input_high=8000);self.cell_bar.pack(fill='x',pady=px(e.window,12))
        ParameterBar(body,'图片间距',self.gap,0,120,step=1,suffix=' px',input_high=200).pack(fill='x',pady=px(e.window,8))
        ttk.Checkbutton(body,text='透明背景',variable=self.transparent).pack(anchor='w',pady=px(e.window,6))
        ttk.Button(body,text='添加图片或动图',command=e.show_materials).pack(fill='x',pady=px(e.window,8))
        ttk.Label(body,text='图层列表从下到上排列；图片完整显示。文字、动画和撤销保留。',wraplength=px(e.window,235),style='Muted.TLabel').pack(fill='x')
        scroll.attach();self.opened=False
        for variable in (self.cell,self.gap,self.transparent):variable.trace_add('write',lambda *_:self.schedule_preview())

    def open(self):
        e=self.e;e.set_tool('collage')
        count=sum(l['kind']=='sticker' for l in e.doc.layers) if e.doc else 0
        self.note.set(f'当前 {count} 张图片 / 动图。'+('先添加图片，再选择模板。' if count<2 else '点模板预览，满意后应用。切换工具会退出预览。'))
        available=[]
        for name,grid in LAYOUTS.items():
            enabled=not grid or count<=grid[0]*grid[1]
            self.cards[name].configure(state='normal' if enabled else 'disabled')
            if enabled:available.append(name)
        if self.layout.get() not in available:self.layout.set(available[0])
        if not self.opened and e.doc:
            size=max([max(l['size']) for l in e.doc.layers if l['kind']=='sticker'] or [512])
            self.cell_bar.limits(32,max(2048,size));self.cell.set(size);self.opened=True
        e.show_property(self.page)

    def settings(self):
        return (self.layout.get(),self.cell.get(),self.gap.get(),(0,0,0,0) if self.transparent.get() else '#ffffff')

    def preview(self):
        if not self.e.doc or self.e.busy:return
        if not self.e.finish_text():return
        self.preview_active=True
        self.preview_canvas.place(x=0,y=0,relwidth=1,relheight=1)
        self.schedule_preview()

    def schedule_preview(self):
        if not self.preview_active or self.e.closed:return
        if self.preview_job:self.e.window.after_cancel(self.preview_job)
        self.preview_job=self.e.window.after(60,self.draw_preview)

    def draw_preview(self):
        self.preview_job=None
        if not self.preview_active or self.e.closed:return
        try:
            dimensions,layers,background=plan(self.e.doc,*self.settings())
            from layout_editor import preview_layer
            width=max(32,self.preview_canvas.winfo_width()-32);height=max(32,self.preview_canvas.winfo_height()-64)
            scale=min(width/dimensions[0],height/dimensions[1],1)
            size=tuple(max(1,round(v*scale)) for v in dimensions)
            image=self.e.backdrop.checker(size,(0,0),getattr(self.e,'light_checker',False)).convert('RGBA')
            if background[3]:image.alpha_composite(Image.new('RGBA',size,background))
            for layer in layers:
                if layer.get('visible') is False:continue
                image.alpha_composite(preview_layer(layer,scale),tuple(round(v*scale) for v in layer['position']))
            self.preview_photo=ImageTk.PhotoImage(image)
            canvas=self.preview_canvas;canvas.delete('all')
            canvas.create_image(canvas.winfo_width()/2,(canvas.winfo_height()+24)/2,image=self.preview_photo)
            canvas.create_text(canvas.winfo_width()/2,px(canvas,18),text=f'预览 · {self.layout.get()} · {dimensions[0]} × {dimensions[1]}',fill=INK)
            self.note.set('正在预览，作品尚未改变。\n满意后点击下方应用。')
        except (ValueError,KeyError,tk.TclError) as exc:
            self.hide_preview();self.note.set(str(exc))

    def hide_preview(self):
        self.preview_active=False
        if self.preview_job:self.e.window.after_cancel(self.preview_job);self.preview_job=None
        self.preview_canvas.place_forget();self.preview_photo=None

    def commit(self,result):
        document,revision,snapshot=result;e=self.e
        if e.doc is not document or e.doc.revision!=revision:
            e.status.set('作品已改变，旧拼图未覆盖。请重新预览后应用。');return
        self.hide_preview()
        e.doc.replace_scene(snapshot._state.base,snapshot.layers,snapshot.source_ids,'套用拼图模板')
        e.initial_workspace=False;e.zoom=1.;e.manual_scale=None;e.pan=(0.,0.)
        e.changed('拼图已应用，可撤销');e.reflow()
        self.note.set('拼图已应用。切换工具可以继续编辑。')

    def apply(self):
        e=self.e
        if not e.doc or e.busy:return
        if not e.finish_text():return
        try:args=self.settings()
        except (ValueError,tk.TclError):self.note.set('请设置有效的格子宽度和间距。');return
        document=e.doc;revision=document.revision;snapshot=copy(document);snapshot._undo=[];snapshot._redo=[]
        def work():
            arrange(snapshot,*args)
            return {'collage_arranged':(document,revision,snapshot)}
        e.submit(work,'应用拼图模板')
