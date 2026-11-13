"""Minimal paint/erase/filter controls attached to the existing editor canvas."""
import tkinter as tk
from tkinter import ttk
from ui_dialogs import colorchooser
from emoji_bridge.raster_tools import stroke,FILTERS


class RasterTools:
    def __init__(self,editor):
        self.editor=editor;self.active=False;self.points=[];self.colour='#202020';self.preview=None
        self.page=ttk.Frame(editor.tabs,padding=10);editor.tabs.add(self.page,text='画笔 / 滤镜')
        from ui_style import ScrollBody,disclosure
        ttk.Button(self.page,text='结束绘制 / 选择图层',command=editor.select_tool).pack(side='bottom',fill='x',pady=(8,0))
        scroll=ScrollBody(self.page);scroll.pack(fill='both',expand=True);body=scroll.body
        self.mode=tk.StringVar(value='画笔');self.width=tk.IntVar(value=12);self.effect=tk.StringVar(value='原色')
        for value in ('画笔','当前帧画笔','橡皮擦','保留主体'):
            ttk.Radiobutton(body,text=value,variable=self.mode,value=value,command=self.activate).pack(anchor='w',pady=4)
        ttk.Label(body,text='笔宽（画布像素）').pack(anchor='w',pady=(10,2))
        ttk.Spinbox(body,from_=1,to=512,textvariable=self.width,width=8).pack(anchor='w')
        ttk.Button(body,text='画笔颜色…',command=self.colour_dialog).pack(fill='x',pady=8)
        ttk.Separator(body).pack(fill='x',pady=12)
        ttk.Label(body,text='选中图片或GIF的基础滤镜').pack(anchor='w')
        ttk.Combobox(body,textvariable=self.effect,values=tuple(FILTERS),state='readonly').pack(fill='x',pady=6)
        ttk.Button(body,text='应用滤镜',command=self.apply_filter).pack(fill='x')
        ttk.Label(disclosure(body,'画笔与蒙版说明'),text='一笔一次撤销。保留笔从原图恢复；GIF蒙版只修改当前帧。',wraplength=218).pack(fill='x',pady=8)
        scroll.attach()

    def activate(self):
        self.active=True;self.editor.show_property(self.page);self.editor.set_cursor('crosshair')
        self.editor.status.set('在画布拖动绘制；橡皮擦先在图层列表选中目标。')

    def colour_dialog(self):
        colour=colorchooser.askcolor(self.colour,parent=self.editor.window)[1]
        if colour:self.colour=colour

    def apply_filter(self):
        e=self.editor
        if not e.doc or not e.selected_layer or e.doc._find(e.selected_layer)['kind']!='sticker':e.status.set('请先选中图片或GIF图层');return
        effect=FILTERS[self.effect.get()]
        e.action(lambda:e.doc.update_layer(e.selected_layer,effect=effect),'应用滤镜')

    def press(self,event):
        e=self.editor
        e.playing=False
        try:
            width=int(self.width.get())
            if not 1<=width<=512:raise ValueError()
        except (ValueError,tk.TclError):e.status.set('笔宽请输入1～512');return
        self.points=[e.point(event)];self.pen=width;e.canvas.focus_set()

    def motion(self,event):
        if not self.points:return
        e=self.editor;self.points.append(e.point(event));e.canvas.delete('paint-stroke')
        xy=[v for x,y in self.points for v in (e.origin[0]+x*e.scale,e.origin[1]+y*e.scale)]
        if len(xy)>=4:e.canvas.create_line(*xy,fill='#bbbbbb' if self.mode.get()=='橡皮擦' else self.colour,width=max(1,self.pen*e.scale),capstyle='round',joinstyle='round',tags='paint-stroke')

    def release(self,event):
        if not self.points:return
        self.motion(event);points=self.points;self.points=[];e=self.editor;e.canvas.delete('paint-stroke')
        layer=e.selected_layer;erase=self.mode.get()=='橡皮擦';colour=self.colour;pen=self.pen
        mode=self.mode.get();frame=e.animation_frame
        def apply():e.selected_layer=stroke(e.doc,points,width=pen,colour=colour,erase=erase,preserve=mode=='保留主体',layer_id=layer,animation_frame=frame,current_frame=mode=='当前帧画笔')
        e.action(apply,'橡皮擦' if erase else '画笔')
