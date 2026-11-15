from emoji_bridge.materials import is_dynamic
"""Direct canvas manipulation over the existing editor and immutable document history."""
from ui_dpi import px, spacing, factor
from copy import deepcopy,copy
from collections import OrderedDict
from pathlib import Path
import json
import time
import math
import uuid
import threading
import tkinter as tk
from tkinter import ttk
from ui_dialogs import messagebox,simpledialog,colorchooser
from PIL import Image,ImageTk,ImageOps,ImageDraw
from emoji_bridge.editing import EditDocument,layered_collage,_text_metrics,_font,_size,save_scene,load_scene,_rgba,_layer_size,_layer_image,SHAPE_NAMES
from material_editor_ui import EditorWindow,choose_frame
from emoji_bridge.editing import load_static


def draft_root(store):return store.root/'drafts'


def preview_layer(layer,scale,source=None):
    """Rasterize only display pixels; original coordinates still control wrapping."""
    if layer.get('text_motion') or layer.get('flip_h') or layer.get('flip_v') or (layer['kind']!='text' and layer.get('rotation')):
        if layer.get('text_motion'):
            from emoji_bridge.text_animation import render
            image=render(layer,layer.get('_elapsed',0))
        else:image=_layer_image(layer)
        return image.resize(tuple(max(1,round(n*scale)) for n in image.size),Image.Resampling.LANCZOS)
    if layer['kind']=='sticker':
        size=tuple(max(1,round(v*scale)) for v in layer['size'])
        if source is None:
            from emoji_bridge.raster_tools import image_effects
            source=image_effects(layer).convert('RGBa')
        if layer.get('fit')=='cover':return ImageOps.fit(source,size,method=Image.Resampling.LANCZOS).convert('RGBA')
        # Pillow's RGBA shortcut drops reducing_gap. Use its premultiplied-alpha
        # mode explicitly so small previews avoid a full-size Lanczos pass.
        return source.resize(size,Image.Resampling.LANCZOS,reducing_gap=1.0).convert('RGBA')
    if layer['kind']=='shape':
        # Rasterize geometry at display size, instead of allocating a full
        # multi-megapixel shape on Tk for every zoom. Final rendering is unchanged.
        return _layer_image({**layer,'size':tuple(max(1,round(v*scale)) for v in layer['size']),
                             'stroke_width':max(1,round(layer['stroke_width']*scale))})
    _,placements,size=_text_metrics(layer)
    image=Image.new('RGBA',tuple(max(1,round(v*scale)) for v in size));draw=ImageDraw.Draw(image)
    font=_font(max(1,min(4096,round(layer['size']*scale))));colors=layer.get('colors',())
    for index,char,x,y in placements:
        draw.text((x*scale,y*scale),char,font=font,anchor='ls',fill=colors[index] if index<len(colors) else layer['color'])
    if layer.get('rotation'):
        image=image.rotate(layer['rotation'],Image.Resampling.BICUBIC,expand=True)
        expected=tuple(max(1,round(v*scale)) for v in _layer_size(layer))
        if image.size!=expected:image=image.resize(expected,Image.Resampling.LANCZOS)
    return image


class LayoutEditor(EditorWindow):
    integrated_panels=True
    supports_single_gif=True
    def __init__(self,*args,**kwargs):
        self.inline=None;self.zoom=1.;self.pan=(0.,0.);self.handles={};self.objects={};self.object_photos={}
        self.preview_cache={};self.preview_sources={};self.display_keys={};self.display_images={};self.drag_after=None;self.cursor_name='arrow'
        self.frame_previews=OrderedDict();self.frame_pixels=0;self.base_key=None;self.base_photo=None
        from editor_backdrop import Backdrop
        self.backdrop=Backdrop()
        self.initial_workspace=kwargs.get('document') is None and kwargs.get('document_loader') is None
        self.gesture=None;self.resize_after=None;self.draft_id=None;self.last_motion=0;self.drop_after=None
        self.animation_frame=0;self.animation_source=None;self.playing=True;self.play_elapsed=0;self.play_start=time.monotonic()
        self.animation_job=None;self.save_cancel=threading.Event()
        self.work_id=uuid.uuid4().hex;self.save_task=None;self.save_waiting=False
        self.save_state={'state':'idle','text':'未保存','revision':None}
        self.text_after=None;self.text_group=None;self.text_layer=None;self.text_dirty=False;self.text_syncing=False;self.text_last=0
        self.view_active=True
        from emoji_bridge.interactive_preview import PreviewQueue
        self.display_jobs=PreviewQueue()
        super().__init__(*args,**kwargs)
        if self.closed:return
        self.tabs.select(0);self.layer_thumbnails={};self.layer_names={}
        self.editor_tabs.select(self.properties_host)
        self.layout_file=self.store.root/'editor-layout.json'
        try:
            import json
            prefs=json.loads(self.layout_file.read_text('utf8'));self.browser_width=px(self.window,max(240,min(420,int(prefs.get('browser_width_dip',prefs.get('browser_width',272))))))
            self.panes.paneconfigure(self.browser_host,width=self.browser_width)
        except (OSError,ValueError,TypeError):self.browser_width=px(self.window,272)
        self.panes.bind('<ButtonRelease-1>',lambda _:self.remember_browser(),add='+')
        toolbar=self.top if self.embedded else ttk.Frame(self.window,padding=spacing(self.window,(12,0,12,5)))
        if not self.embedded:toolbar.pack(fill='x',before=self.panes)
        self.toolbar=toolbar
        self.save_button.configure(command=self.save_menu)
        self.editor_tabs.configure(style='Editor.TNotebook');self.tabs.configure(style='Editor.Property.TNotebook')
        from ui_style import WORKSPACE
        self.canvas.configure(background=WORKSPACE)
        from editor_icons import tool_icons
        self.tool_icons=tool_icons(self.window)
        self.rail=ttk.Frame(self.panes,padding=spacing(self.window,(3,5)));self.panes.add(self.rail,before=self.canvas_host,stretch='never',minsize=px(self.window,60),width=px(self.window,66))
        self.tool_buttons={}
        for key,title,command in [('select','选择',self.select_tool),('text','文字',self.new_text),('material','素材',self.show_materials),
                                  ('shape','图形',lambda:self.show_property(self.shapes_page)),('background','背景',lambda:self.show_property(self.background_page)),
                                  ('transform','变换',lambda:self.show_property(self.transform_page)),('cutout','抠主体',lambda:self.cutout.activate())]:
            button=ttk.Button(self.rail,text=title,image=self.tool_icons[key],compound='top',width=5,style='Editor.Tool.TButton',command=lambda k=key,c=command:(self.set_tool(k),c()));button.pack(fill='x',pady=px(self.window,2));self.tool_buttons[key]=button
        if hasattr(self,'collage_page'):
            ttk.Button(self.rail,text='拼图',width=5,command=lambda:self.show_property(self.collage_page)).pack(fill='x',pady=px(self.window,2))
        from raster_tools_ui import RasterTools
        self.raster=RasterTools(self)
        self.tool_buttons['paint']=ttk.Button(self.rail,text='画笔',image=self.tool_icons['paint'],compound='top',style='Editor.Tool.TButton',width=5,command=lambda:(self.set_tool('paint'),self.raster.activate()))
        self.tool_buttons['paint'].pack(fill='x',pady=px(self.window,2))
        from dropped_item_ui import DroppedItem
        self.dropped_item=DroppedItem(self)
        from animation_effects_ui import AnimationEffects
        self.animation_effects=AnimationEffects(self)
        from editor_intelligence import Intelligence
        self.intelligence=Intelligence(self)
        from editor_template_tools import TemplateTools
        self.template_tools=TemplateTools(self)
        from editor_collage import CollagePanel
        self.collage_controller=CollagePanel(self)
        # Reuse the effects panel for additional tools instead of another rail.
        extra=ttk.Frame(self.animation_effects.page,padding=spacing(self.window,(0,8)))
        ttk.Button(extra,text='动态文字 / 识别 / 跟踪',command=lambda:self.show_property(self.intelligence.page)).pack(fill='x',pady=px(self.window,3))
        ttk.Button(extra,text='模板包 / 目标体积',command=lambda:self.show_property(self.template_tools.page)).pack(fill='x',pady=px(self.window,3))
        self.tool_buttons['effect']=ttk.Button(self.rail,text='效果',image=self.tool_icons['effect'],compound='top',style='Editor.Tool.TButton',width=5,command=lambda:(self.set_tool('effect'),self.animation_effects.open()))
        self.tool_buttons['effect'].pack(fill='x',pady=px(self.window,2))
        self.rail_button_layouts=[(button,{key:button.cget(key) for key in ('image','compound','padding')}) for button in self.rail.winfo_children()]
        self.rail_full_height=sum(button.winfo_reqheight()+4 for button,_ in self.rail_button_layouts)+10
        self.rail_compact=False
        self.rail.bind('<Configure>',self.resize_tool_rail)
        # The left browser owns the common tool switcher. Keep old commands in
        # one compact menu instead of a second vertical rail beside navigation.
        self.panes.forget(self.rail)
        switcher=ttk.Frame(self.browser_host,padding=spacing(self.window,(8,8)));switcher.pack(fill='x',before=self.browser_tabs)
        for key,title,command in [('material','素材',self.show_materials),('effect','效果',self.animation_effects.open),('text','文字',self.new_text),('cutout','主体',lambda:self.cutout.activate())]:
            ttk.Button(switcher,text=title,width=4,command=lambda k=key,c=command:(self.set_tool(k),c())).pack(side='left',expand=True,fill='x',padx=px(self.window,1))
        more=ttk.Menubutton(toolbar,text='工具',width=5);more.pack(side='left',padx=px(self.window,4))
        more_menu=tk.Menu(more,tearoff=False);more.configure(menu=more_menu)
        self.more_tools_button=more;self.more_tools_menu=more_menu
        for title,command in [('选择对象',self.select_tool),('基础图形',lambda:self.show_property(self.shapes_page)),('画笔 / 滤镜',self.raster.activate),('背景',lambda:self.show_property(self.background_page)),('裁切 / 旋转',lambda:self.show_property(self.transform_page)),('拼图',self.collage_controller.open),('动态文字 / 跟踪 / OCR',lambda:self.show_property(self.intelligence.page)),('模板包 / 目标体积',lambda:self.show_property(self.template_tools.page))]:more_menu.add_command(label=title,command=command)
        more_menu.add_command(label='抠主体',command=lambda:self.cutout.activate())
        more_menu.add_command(label='我的世界掉落物',command=self.dropped_item.open)
        self.browser_toggle=ttk.Button(toolbar,text='浏览',width=5,command=self.toggle_browser)
        from surface_menu import SurfaceMenu
        canvas_menu=ttk.Button(toolbar,text='画布 ▾',width=7);canvas_menu.pack(side='left',padx=px(self.window,4))
        menu=SurfaceMenu(canvas_menu);menu.add_command(label='画布尺寸…',command=self.canvas_size);menu.add_command(label='扩展背景铺满工作区',command=self.fill_workspace)
        self.canvas_menu=menu
        view=ttk.Button(toolbar,text='视图 ▾',width=7);view.pack(side='left',padx=px(self.window,2))
        view_menu=SurfaceMenu(view)
        for label,command in [('适应窗口',lambda:self.zoom_by(None)),('放大',lambda:self.zoom_by(1.25)),('缩小',lambda:self.zoom_by(.8)),('素材 / 效果面板',self.toggle_browser),('属性 / 图层面板',self.toggle_tools),('深 / 浅透明棋盘',self.toggle_checker)]:view_menu.add_command(label=label,command=command)
        if not self.embedded:
            ttk.Button(toolbar,text='−',width=3,command=lambda:self.zoom_by(.8)).pack(side='left')
            ttk.Button(toolbar,text='适应窗口',width=8,command=lambda:self.zoom_by(None)).pack(side='left',padx=px(self.window,4))
            ttk.Button(toolbar,text='+',width=3,command=lambda:self.zoom_by(1.25)).pack(side='left')
        self.tools_toggle=ttk.Button(toolbar,text='收起面板',width=8,command=self.toggle_tools)
        if not self.embedded:self.tools_toggle.pack(side='right')
        self.canvas.bind('<Motion>',self.hover)
        self.canvas.bind('<Leave>',lambda e:self.set_cursor('arrow') if not self.gesture else None)
        from editor_panels import MaterialPanel
        from editor_output import FinishedOutput
        self.material_panel=MaterialPanel(self.materials_host,self.store,self.add_materials,lambda ids:self.add_materials(ids,background=True));self.material_panel.pack(fill='both',expand=True)
        self.empty_properties=ttk.Frame(self.object_body)
        self.text_action=ttk.Frame(self.object_page,padding=spacing(self.window,(0,6,0,0)))
        self.add_text_button=ttk.Button(self.text_action,text='添加文字图层',style='Editor.Primary.TButton',command=self.add_text)
        self.add_text_button.pack(fill='x')
        from ui_style import MUTED
        ttk.Label(self.empty_properties,text='选中画布中的对象后，可以在这里调整文字、颜色与大小。',wraplength=px(self.window,245),foreground=MUTED).pack(anchor='w',pady=spacing(self.window,(0,18)))
        ttk.Button(self.empty_properties,text='添加文字',command=self.new_text).pack(fill='x',pady=px(self.window,4))
        ttk.Button(self.empty_properties,text='添加素材',command=self.show_materials).pack(fill='x',pady=px(self.window,4))
        ttk.Label(self.empty_properties,text='重叠对象可到“图层”页选择。\n双击文字编辑；拖动角点缩放。',wraplength=px(self.window,245),foreground=MUTED).pack(anchor='w',pady=spacing(self.window,(18,0)))
        background=ttk.Frame(self.tabs,padding=px(self.window,10));self.tabs.add(background,text='背景');self.background_page=background
        from ui_style import ScrollBody
        background_scroll=ScrollBody(background);background_scroll.pack(fill='both',expand=True);background=background_scroll.body
        ttk.Label(background,text='新作品默认白色背景。',wraplength=px(self.window,240)).pack(anchor='w',pady=px(self.window,6))
        ttk.Button(background,text='白色背景',command=lambda:self.set_background('#ffffff')).pack(fill='x',pady=px(self.window,4))
        ttk.Button(background,text='选择背景颜色…',command=self.choose_canvas_background).pack(fill='x',pady=px(self.window,4))
        ttk.Button(background,text='透明背景',command=lambda:self.set_background((0,0,0,0))).pack(fill='x',pady=px(self.window,4))
        ttk.Button(background,text='从素材选择图片 / GIF 背景…',command=self.show_materials).pack(fill='x',pady=px(self.window,4))
        ttk.Label(background,text='素材页点“用所选素材作背景”。图片或单 GIF 按比例裁切填满，保持独立底层；新背景替换原背景，可撤销。透明主体与文字可放在上面。\n\n透明背景只影响画布空白，不会自动去除照片原有底色。',wraplength=px(self.window,240)).pack(anchor='w',pady=px(self.window,8))
        background_scroll.attach()
        self.output=FinishedOutput(self.output_area,self,compact=True);self.output.pack(side='right',padx=px(self.window,4))
        self.output_area_row=None
        self.window.bind('<Configure>',self.fit_output_area,add='+');self.window.after_idle(self.fit_output_area)
        self.timeline_host=ttk.Frame(self.canvas_host,padding=spacing(self.window,(8,4)))
        animation_tools=ttk.Frame(self.timeline_host);animation_tools.pack(fill='x')
        self.animation_tools=animation_tools
        self.play_button=ttk.Button(animation_tools,text='暂停动画',command=self.toggle_play)
        self.play_button.pack(side='left')
        self.time_caption=tk.StringVar(value='00:00.0')
        ttk.Label(animation_tools,textvariable=self.time_caption,style='Muted.TLabel').pack(side='left',padx=px(self.window,12))
        self.timeline_toggle=ttk.Button(animation_tools,text='收起',width=5,command=self.toggle_timeline);self.timeline_toggle.pack(side='right')
        ttk.Button(animation_tools,text='全段',width=5,command=lambda:self.action(lambda:self.doc.set_time_range(0,sum(self.doc.animation.durations)),'已恢复完整动画输出')).pack(side='right')
        playback=ttk.Frame(self.timeline_host);playback.pack(fill='x',pady=spacing(self.window,(3,2)))
        ttk.Label(playback,text='所选动图倍速',style='Muted.TLabel').pack(side='left')
        speed=self.animation_effects.speed
        ttk.Scale(playback,from_=.25,to=4,variable=speed,length=px(self.window,140)).pack(side='left',fill='x',expand=True,padx=px(self.window,8))
        speed_label=tk.StringVar(value='1×')
        speed.trace_add('write',lambda *_:speed_label.set(f'{speed.get():.2g}×'))
        ttk.Label(playback,textvariable=speed_label,width=5).pack(side='left')
        def timing_action(kind):
            self.animation_effects.timing.set(kind);self.animation_effects.apply_timing()
        ttk.Button(playback,text='应用倍速',command=lambda:timing_action('变速')).pack(side='left',padx=px(self.window,3))
        ttk.Button(playback,text='倒放',width=5,command=lambda:timing_action('倒放')).pack(side='left')
        self.timeline=None
        self.gif_note=tk.StringVar()
        self.gif_note_label=ttk.Label(self.timeline_host,textvariable=self.gif_note,style='Muted.TLabel')
        # Timing is already shown in the strip; keep this string for callers,
        # without another permanent explanatory row above the timeline.
        self.timeline_host.bind('<Configure>',lambda ev:self.gif_note_label.configure(wraplength=max(140,ev.width-20)),add='+')
        self.cancel_save_button=ttk.Button(self.footer,text='取消处理',command=self.cancel_processing)
        self.animation_job=self.window.after(30,self.tick_animation)
        for actions in [[('上移一层',1),('下移一层',-1)],[('置于顶层',100000),('置于底层',-100000)]]:
            row=ttk.Frame(self.layers_host);row.pack(fill='x',pady=px(self.window,3))
            for label,delta in actions:ttk.Button(row,text=label,command=lambda d=delta:self.reorder_layer(d)).pack(side='left',fill='x',expand=True)
        ttk.Button(self.layers_host,text='删除选中图层',command=self.delete_layer).pack(fill='x',pady=px(self.window,3))
        self.color_note=tk.StringVar(value='文字颜色：#202020')
        self.color_note.trace_add('write',lambda *_args:self.refresh_text_color_swatch())
        ttk.Label(self.text_controls,textvariable=self.color_note).pack(anchor='w',pady=px(self.window,4))
        self.live_text_note=ttk.Label(self.layer_actions,text='文字实时更新',style='Muted.TLabel')
        from ui_style import disclosure
        rotation_row=disclosure(self.text_controls,'精确旋转')
        self.text_rotation=tk.DoubleVar(value=0)
        ttk.Label(rotation_row,text='文字旋转 °').pack(side='left')
        ttk.Spinbox(rotation_row,from_=-360,to=360,increment=15,textvariable=self.text_rotation,width=6).pack(side='left',padx=px(self.window,4))
        ttk.Button(rotation_row,text='应用角度',command=self.rotate_text).pack(side='left')
        shape_page=ttk.Frame(self.tabs,padding=px(self.window,10));self.tabs.add(shape_page,text='图形');self.shapes_page=shape_page
        from ui_style import ScrollBody
        shape_scroll=ScrollBody(shape_page);shape_scroll.pack(fill='both',expand=True);shapes=shape_scroll.body
        for shape,title in SHAPE_NAMES.items():
            ttk.Button(shapes,text='添加'+title,command=lambda s=shape:self.add_shape(s)).pack(fill='x',pady=px(self.window,3))
        self.shape_color='#202020';self.shape_stroke=tk.IntVar(value=4);self.shape_fill=tk.BooleanVar(value=False)
        ttk.Button(shapes,text='图形颜色…',command=self.choose_shape_color).pack(fill='x',pady=px(self.window,8))
        row=ttk.Frame(shapes);row.pack(fill='x')
        ttk.Label(row,text='线宽').pack(side='left')
        ttk.Spinbox(row,from_=1,to=512,textvariable=self.shape_stroke,width=7).pack(side='left',padx=px(self.window,6))
        ttk.Checkbutton(shapes,text='填充矩形 / 椭圆',variable=self.shape_fill).pack(anchor='w',pady=px(self.window,6))
        ttk.Button(shapes,text='更新选中图形',command=self.update_shape).pack(fill='x',pady=px(self.window,4))
        ttk.Label(shapes,text='选中对象后，拖上方圆点旋转，拖四角缩放。图层页可调整遮挡顺序。\n画布滚轮缩放；Delete 删除所选图层；Ctrl+Z / Ctrl+Y 撤销、重做。输入文字时保留输入框自己的按键。',wraplength=px(self.window,240)).pack(fill='x',pady=px(self.window,10))
        shape_scroll.attach()
        self.canvas.configure(takefocus=True)
        self.canvas.bind('<Double-Button-1>',self.begin_text)
        from subject_selection_ui import SubjectSelection
        self.subject_selection=SubjectSelection(self)
        self.shortcut_host=self.window.winfo_toplevel();self.shortcut_bindings=[]
        for sequence,command in [('<Delete>','delete'),('<BackSpace>','delete'),('<Control-z>','undo'),('<Control-y>','redo')]:
            binding=self.shortcut_host.bind(sequence,lambda e,c=command:self.shortcut(e,c),add='+')
            self.shortcut_bindings.append((sequence,binding))
        self.canvas.bind('<MouseWheel>',self.wheel_zoom)
        self.canvas.bind('<Button-4>',self.wheel_zoom);self.canvas.bind('<Button-5>',self.wheel_zoom)
        self.canvas.bind('<Configure>',self.resized)
        self.canvas.bind('<Map>',self.resized)
        self.canvas.drop_target_register('DND_Files','DND_Text');self.canvas.dnd_bind('<<Drop>>',self.drop_materials)
        self.sync_properties()
        self.text.configure(undo=True)
        self.text.edit_modified(False)
        self.text.bind('<<Modified>>',self.text_modified)
        self.font_size.trace_add('write',lambda *args:self.schedule_text() if not self.text_syncing else None)
        self.text.bind('<FocusOut>',lambda event:self.flush_text(end_group=True),add='+')
        self.set_tool('select')
        from factory_workspace import FactoryWorkspace
        self.factory_workspace=FactoryWorkspace(self)
        self.install_recovery_tools()

    def fit_output_area(self,event=None):
        if self.closed or (event is not None and event.widget is not self.window):return
        left=sum(w.winfo_reqwidth()+px(self.window,8) for w in self.top.pack_slaves() if w is not self.output_area)
        row=self.window.winfo_width()<left+self.output_area.winfo_reqwidth()+px(self.window,28)
        if self.output_area_row==row:return
        self.output_area_row=row;self.output_area.pack_forget()
        if row:self.output_area.pack(fill='x',before=self.panes,padx=px(self.window,10),pady=spacing(self.window,(0,5)))
        else:self.output_area.pack(in_=self.top,side='right')

    def cancel_processing(self):
        if hasattr(self,'factory_workspace'):self.factory_workspace.after_subject_slot=None
        self.save_cancel.set()
        if self.save_task:self.save_task.cancel.set()
        if hasattr(self,'dropped_item'):self.dropped_item.abort()
        if hasattr(self,'cutout'):self.cutout.cancel.set()
        if hasattr(self,'subject_selection'):self.subject_selection.cancel.set()
        self.output.cancel_prepare()
        self.status.set('已取消后续步骤；正在结束当前处理，完成文件保留。')

    def resize_tool_rail(self,event):
        compact=event.height<self.rail_full_height
        if compact==self.rail_compact:return
        self.rail_compact=compact
        for button,layout in self.rail_button_layouts:
            button.configure(**({'image':'','compound':'none','padding':(2,3)} if compact else layout))
            button.pack_configure(pady=1 if compact else 2)

    def text_modified(self,event=None):
        if not self.text.edit_modified():return
        self.text.edit_modified(False)
        if not self.text_syncing and not self.inline:self.schedule_text()

    def schedule_text(self):
        if self.closed or self.busy or self.inline or self.text_syncing or not self.doc:return
        if self.text_layer!=self.selected_layer or not self.selected_layer:return
        if self.doc._find(self.selected_layer)['kind']!='text':return
        self.text_dirty=True
        if self.text_after:self.window.after_cancel(self.text_after)
        self.text_after=self.window.after(140,self.flush_text)

    def flush_text(self,end_group=False):
        if self.text_after:self.window.after_cancel(self.text_after);self.text_after=None
        if self.text_dirty and not self.busy and self.doc and self.text_layer:
            try:
                layer=self.doc._find(self.text_layer)
                props={'text':self.text.get('1.0','end-1c'),'size':self.font_size.get()}
                if any(layer[k]!=v for k,v in props.items()):
                    now=time.monotonic()
                    if self.text_group is None or now-self.text_last>.9:self.text_group=uuid.uuid4().hex
                    self.doc.update_layer(self.text_layer,history_group=self.text_group,**props);self.text_last=now
                    if self.applied_collage:self.collage_states[self.doc.revision]=deepcopy(self.applied_collage)
                    # Update the changed object only. No full animation/export or disk I/O.
                    self.paint_layer(self.doc._find(self.text_layer));self.draw_bounds()
                    self.undo_button.state(['!disabled']);self.redo_button.state(['disabled'])
                    self.status.set('文字已更新。 有未保存修改。')
                self.text_dirty=False
            except (ValueError,tk.TclError) as exc:
                self.status.set('文字尚未应用：'+str(exc));return False
        if end_group:self.text_group=None
        return True

    def set_tool(self,key):
        if getattr(self,'hand_mode',False):
            self.hand_mode=False;self.pan_gesture=None;self.set_cursor('arrow')
            if hasattr(self,'hand_button'):self.hand_button.configure(text='平移')
        if key!='collage' and hasattr(self,'collage_controller'):self.collage_controller.hide_preview()
        self.active_tool=key
        if key!='cutout' and hasattr(self,'cutout'):self.cutout.deactivate()
        if hasattr(self,'factory_workspace'):
            self.factory_workspace.highlight(key)
            if key not in ('catalog','template','effect','material'):self.factory_workspace.layout.hide()
        if key not in ('cutout','catalog','template','material') and hasattr(self,'subject_selection'):self.subject_selection.deactivate()
        if key!='effect' and hasattr(self,'animation_effects'):self.animation_effects.hide()
        if key!='effect' and hasattr(self,'dropped_item') and self.dropped_item.active:self.dropped_item.hide()
        if hasattr(self,'raster') and key!='paint':self.raster.active=False
        for name,button in self.tool_buttons.items():button.state(['selected'] if key==name else ['!selected'])

    def select_tool(self):
        self.hand_mode=False
        self.pan_gesture=None
        if hasattr(self,'hand_button'):self.hand_button.configure(text='平移')
        if self.inline and not self.finish_text():return
        self.set_tool('select')
        self.show_property(self.shapes_page if self.doc and self.selected_layer and self.doc._find(self.selected_layer)['kind']=='shape' else self.object_page)
        self.crop_mode=False;self.canvas.focus_set();self.set_cursor('arrow')
        self.status.set('点击选中，拖动位置；上方圆点旋转，四角缩放。双击文字直接编辑。')

    def show_property(self,page):
        if hasattr(self,'collage_controller') and page is not self.collage_controller.page:self.collage_controller.hide_preview()
        if hasattr(self,'cutout') and page is not self.cutout.page:self.cutout.deactivate()
        if hasattr(self,'animation_effects') and page is not self.animation_effects.page:self.animation_effects.hide()
        if hasattr(self,'dropped_item') and self.dropped_item.active and page is not self.dropped_item.page:self.dropped_item.hide()
        if not self.tools.winfo_manager():self.toggle_tools()
        if not getattr(self,'factory_layout',False):self.editor_tabs.select(self.properties_host)
        changed=self.tabs.select()!=str(page)
        self.tabs.select(page)
        if changed:
            from ui_style import ScrollBody
            def reset_scroll(widget):
                if isinstance(widget,ScrollBody):widget.canvas.yview_moveto(0)
                for child in widget.winfo_children():reset_scroll(child)
            reset_scroll(page)
        if hasattr(self,'factory_workspace'):self.factory_workspace.fit_fields()
        # Settle nested notebooks before the next animated preview/host capture.
        # This only drains geometry/paint work, never user callbacks or tasks.
        self.window.update_idletasks()

    def new_text(self):
        if self.busy or not self.doc or not self.finish_text():return
        self.text_layer=None
        self.text.delete('1.0','end');self.text.insert('1.0','双击编辑文字')
        self.show_property(self.object_page);self.add_text()

    def show_text(self):
        """Opening a tool is not an insertion. Only Add text creates a layer."""
        if not self.finish_text():return
        self.set_tool('text');self.show_property(self.object_page)
        self.empty_properties.pack_forget();self.image_controls.pack_forget()
        if self.layer_actions.winfo_manager():self.text_controls.pack(fill='x',before=self.layer_actions)
        else:self.text_controls.pack(fill='x')
        self.text_action.pack(side='bottom',fill='x',before=self.object_scroll)
        self.object_scroll.canvas.yview_moveto(0)
        self.status.set('双击画布添加文字；双击已有文字可直接编辑，也可点击“添加文字图层”。')

    def sync_properties(self):
        if not hasattr(self,'text_controls'):return
        layer=self.doc._find(self.selected_layer) if self.doc and self.selected_layer else None
        if hasattr(self,'text_action'):
            if layer and layer['kind']=='text':self.text_action.pack(side='bottom',fill='x',before=self.object_scroll)
            else:self.text_action.pack_forget()
        for frame in (self.text_controls,self.image_controls):frame.pack_forget()
        self.layer_actions.pack_forget()
        if hasattr(self,'empty_properties'):self.empty_properties.pack_forget()
        if not layer:
            self.selection_title.set('选择对象，开始编辑')
            if hasattr(self,'empty_properties'):self.empty_properties.pack(fill='x')
            return
        self.selection_title.set('文字图层' if layer['kind']=='text' else SHAPE_NAMES[layer['shape']] if layer['kind']=='shape' else 'GIF 图层' if layer.get('animation') else '图片图层')
        self.layer_actions.pack(fill='x',pady=px(self.window,12))
        if layer['kind']=='text':
            self.update_layer_button.pack_forget()
            self.live_text_note.pack(side='left',before=self.delete_layer_button,padx=spacing(self.window,(0,8)))
        else:
            self.live_text_note.pack_forget()
            self.update_layer_button.pack(side='left',before=self.delete_layer_button)
        frame=self.text_controls if layer['kind']=='text' else self.image_controls if layer['kind']=='sticker' else None
        if frame:frame.pack(fill='x',before=self.layer_actions)

    def save_menu(self):
        # Windows dispatches the selected menu command after tk_popup returns.
        # Destroying it in finally deletes that pending command (including Save).
        previous=getattr(self,'_save_menu',None)
        if previous:previous.destroy()
        menu=self.build_save_menu()
        self._save_menu=menu
        try:menu.tk_popup(self.save_button.winfo_rootx(),self.save_button.winfo_rooty()+self.save_button.winfo_height())
        finally:menu.grab_release()

    def build_save_menu(self):
        menu=tk.Menu(self.save_button,tearoff=False)
        menu.add_command(label='保存为素材 · 完整作品',command=self.save)
        menu.add_command(label='保存选中主体进素材库',command=self.save_subject,state='normal' if self.selected_layer else 'disabled')
        menu.add_separator()
        menu.add_command(label='导出 GIF 动图…',command=self.output.export_gif)
        menu.add_command(label='转为 MP4…',command=self.output.to_video)
        return menu

    def preview_document(self,viewport):
        # This view draws independent display layers. A full-resolution composite
        # is needed for save/export, not for every move, undo or selection change.
        return None,self.doc.size if self.doc else None

    def toggle_play(self):
        if self.animation_effects.active:self.animation_effects.toggle();return
        if not self.doc or not self.doc.animation:return
        if self.playing:self.play_elapsed += (time.monotonic()-self.play_start)*1000
        else:
            if self.doc.playback_frame(self.play_elapsed)[1]:self.play_elapsed=self.doc.time_range[0] if self.doc.time_range else 0
            self.play_start=time.monotonic()
        self.playing=not self.playing
        self.play_button.configure(text='暂停动画' if self.playing else '播放动画')

    def set_view_active(self,active):
        if not active and hasattr(self,'collage_controller'):self.collage_controller.hide_preview()
        if self.view_active==active:return
        if not active and self.dropped_item.active:self.dropped_item.hide()
        if not active:
            self.animation_effects.hide();self.display_jobs.clear_pending()
        if self.playing:
            if active:self.play_start=time.monotonic()
            else:self.play_elapsed+=(time.monotonic()-self.play_start)*1000
        self.view_active=active

    def toggle_timeline(self):
        self.timeline_collapsed=not getattr(self,'timeline_collapsed',False)
        if self.timeline:
            if self.timeline_collapsed:self.timeline.pack_forget()
            else:self.timeline.pack(fill='x')
        self.timeline_toggle.configure(text='展开' if self.timeline_collapsed else '收起')

    def tick_animation(self):
        if self.closed:return
        from emoji_bridge.animated_edit import GIF_NOTE
        if not self.busy and not getattr(self,'save_waiting',False):self.cancel_save_button.pack_forget()
        elif self.busy:self.cancel_save_button.pack(side='right',padx=px(self.window,4))
        animation=self.doc.animation if self.doc else None
        if animation is not self.animation_source:
            preserve=getattr(self,'preserve_playhead',None);self.preserve_playhead=None
            self.animation_source=animation;self.animation_frame=animation.frame_at(preserve)[0] if animation and preserve is not None else 0;self.play_elapsed=preserve if preserve is not None else self.doc.time_range[0] if animation and self.doc.time_range else 0;self.play_start=time.monotonic();self.playing=preserve is None and not self.animation_effects.active and not self.subject_selection.active and not getattr(getattr(self,'cutout',None),'marking',False)
            self.play_button.configure(text='暂停动画' if self.playing else '播放动画',state='normal' if animation else 'disabled')
            self.gif_note.set((str(len(animation.frames))+' 帧 · '+f'{sum(animation.durations)/1000:.2f} 秒 · 导出 GIF 保留动画') if animation else '')
        if animation:
            if self.timeline is None:
                from editor_timeline import EditorTimeline
                self.timeline=EditorTimeline(self.timeline_host,self.scrub_animation)
                if not getattr(self,'timeline_collapsed',False):self.timeline.pack(fill='x')
            if getattr(self,'timeline_source',None) is not animation:
                from editor_timeline import AnimationCovers
                start,end=self.doc.time_range or (0,sum(animation.durations))
                self.timeline_source=animation;self.timeline.set_source(AnimationCovers(animation,copy(self.doc)),start/1000,end/1000)
                self.timeline_revision=self.doc.revision;self.timeline_pending=None
            if getattr(self,'timeline_revision',None)!=self.doc.revision:
                pending=getattr(self,'timeline_pending',None)
                if not pending or pending[0]!=self.doc.revision:self.timeline_pending=(self.doc.revision,time.monotonic())
                elif time.monotonic()-pending[1]>.3 and not (self.gesture or self.inline or self.text_dirty or self.busy):
                    from editor_timeline import AnimationCovers
                    self.timeline.cache=AnimationCovers(animation,copy(self.doc));self.timeline.draw()
                    self.timeline_revision=self.doc.revision;self.timeline_pending=None
            if not self.timeline_host.winfo_manager():self.timeline_host.pack(side='bottom',fill='x',before=self.canvas)
            if not self.timeline.dragging:
                start,end=self.doc.time_range or (0,sum(animation.durations))
                self.timeline.start=start/1000;self.timeline.end=end/1000
        else:self.timeline_host.pack_forget()
        if animation and self.playing and self.view_active and not self.dropped_item.active and not self.animation_effects.active and not self.busy and not self.gesture and not self.inline and self.window.winfo_ismapped():
            elapsed=self.play_elapsed+(time.monotonic()-self.play_start)*1000
            index,ended=self.doc.playback_frame(elapsed)
            if index!=self.animation_frame or self.display_jobs.running:
                self.animation_frame=index
                for layer in self.doc.layers:
                    if layer.get('animation') or layer.get('text_motion') or layer.get('tracking'):self.paint_layer(layer)
            if ended:
                self.play_elapsed=elapsed;self.playing=False;self.play_button.configure(text='重新播放')
        if self.view_active and self.doc and not self.gesture and not self.inline and self.display_jobs.serial!=getattr(self,'display_serial',-1):
            self.display_serial=self.display_jobs.serial
            for layer in self.doc.layers:
                if layer.get('animation'):self.paint_layer(layer)
            for layer in self.doc.layers:
                if layer['id'] in self.objects:self.canvas.tag_raise(self.objects[layer['id']])
            self.draw_bounds()
        if animation and self.timeline:
            from video_timeline import clock
            elapsed=sum(animation.durations[:self.animation_frame])/1000
            if self.animation_effects.active:elapsed=self.animation_effects.position()/1000
            if self.doc.time_range and self.playing:
                elapsed=max(self.doc.time_range[0]/1000,elapsed)
            if not self.timeline.dragging:self.timeline.set_position(elapsed)
            total=self.animation_effects.playback_bounds()[1] if self.animation_effects.active else sum(animation.durations)
            self.time_caption.set(f'{clock(elapsed)} / {clock(total/1000)}')
        self.animation_job=self.window.after(30,self.tick_animation)

    def scrub_animation(self,timeline,released):
        if not self.doc or not self.doc.animation or self.busy:return
        if self.animation_effects.active:self.animation_effects.seek(timeline.position*1000)
        self.playing=False;self.play_button.configure(text='播放动画');self.play_elapsed=timeline.position*1000
        self.animation_frame=self.doc.animation.frame_at(self.play_elapsed)[0]
        for layer in self.doc.layers:
            if layer.get('animation') or layer.get('text_motion') or layer.get('tracking'):self.paint_layer(layer)
        if released:
            start,end=(round(v*100)*10 for v in (timeline.start,timeline.end))
            current=self.doc.time_range or (0,sum(self.doc.animation.durations))
            if (start,end)!=current:
                self.action(lambda:self.doc.set_time_range(start,end),'输出选区已更新；原始动画和图层保留')

    def extract_gif(self):
        if self.busy:return
        ident=self.material_panel.selected
        if self.doc and self.selected_layer:
            layer=self.doc._find(self.selected_layer)
            if layer.get('animation'):ident=layer.get('source_id')
        if not ident or not is_dynamic(self.store.get(ident)['metadata']):
            self.status.set('请在素材页或图层中选中 GIF，再提取静态帧。');return
        self.add_materials([ident],static_frame=True)

    def expand_canvas(self):
        vw=max(100,self.canvas.winfo_width()-16);vh=max(100,self.canvas.winfo_height()-16)
        width,height=self.doc.size;ratio=max(width/vw,height/vh,1)
        size=_size((math.ceil(vw*ratio),math.ceil(vh*ratio)))
        dx=(size[0]-width)//2;dy=(size[1]-height)//2
        if size==(width,height):return
        # Expand the artboard without stretching, cropping or replacing any source.
        base=Image.new('RGBA',size,self.doc._state.base.getpixel((0,0)))
        base.paste(self.doc._state.base,(dx,dy))
        layers=[{**l,'position':(l['position'][0]+dx,l['position'][1]+dy)} for l in self.doc.layers]
        self.doc.replace_scene(base,layers,self.doc.source_ids,'画布铺满工作区（扩展背景，保留素材比例）')

    def fill_workspace(self):
        if self.busy or not self.doc or not self.finish_text():return
        try:self.expand_canvas()
        except ValueError as exc:self.status.set(str(exc));return
        self.zoom=1.;self.pan=(0.,0.);self.changed('画布已扩展，原图尺寸和比例保持不变')
        self.paint(None,self.doc.size)

    def toggle_tools(self):
        if self.tools.winfo_manager():
            self.tools_width=self.tools.winfo_width();self.panes.forget(self.tools);self.tools_toggle.configure(text='展开面板')
        else:
            self.panes.add(self.tools,stretch='never',minsize=px(self.window,260),width=getattr(self,'tools_width',px(self.window,300)));self.tools_toggle.configure(text='收起面板')

    def show_materials(self):
        if hasattr(self,'animation_effects'):self.animation_effects.hide()
        self.show_browser(self.materials_host)
        if hasattr(self,'factory_workspace'):
            self.set_tool('material');self.sync_properties();self.show_property(self.object_page)
        if not self.busy:self.status.set('选中素材后添加到画布，或拖到作品中的指定位置。')

    def show_browser(self,page):
        if hasattr(self,'factory_workspace'):
            self.factory_workspace.layout.show(page);return
        if not self.browser_host.winfo_manager():self.toggle_browser()
        self.browser_tabs.select(page)

    def toggle_browser(self):
        if hasattr(self,'factory_workspace'):
            self.factory_workspace.toggle_refine();return
        if self.browser_host.winfo_manager():
            self.browser_width=self.browser_host.winfo_width();self.panes.forget(self.browser_host)
        else:self.panes.add(self.browser_host,before=self.canvas_host,stretch='never',minsize=px(self.window,240),width=getattr(self,'browser_width',px(self.window,272)))

    def remember_browser(self):
        if self.browser_host.winfo_manager():
            from emoji_bridge.state import save_json
            self.browser_width=self.browser_host.winfo_width()
            try:prefs=json.loads(self.layout_file.read_text('utf8'))
            except (OSError,ValueError):prefs={}
            key='factory_browser_width' if getattr(self,'factory_layout',False) else 'browser_width'
            prefs[key+'_dip']=round(self.browser_width/factor(self.window));save_json(self.layout_file,prefs)

    def add_sticker(self):
        self.show_materials();self.status.set('在左侧点选素材后添加，或把缩略图拖到画布。')

    def choose_canvas_background(self):
        color=colorchooser.askcolor('#ffffff',parent=self.window,title='画布背景颜色')[1]
        if color:self.set_background(color)

    def set_background(self,color):
        def change():
            old=self.doc._state.base;layers=[l for l in self.doc.layers if l.get('role')!='background']
            # Older flattened scenes may contain artwork in the base. Promote it
            # to a layer, rather than erase it while changing the canvas color.
            if any(low!=high for low,high in old.getextrema()):
                layers.insert(0,dict(id=uuid.uuid4().hex,kind='sticker',image=old,size=old.size,position=(0,0),source_id=None))
            self.doc.replace_scene(Image.new('RGBA',old.size,color),layers,self.doc.source_ids,'更换画布背景')
        self.action(change,'更换背景')

    def add_materials(self,ids,point=None,*,background=False,static_frame=False):
        if self.busy or not self.doc or not self.finish_text():return
        frames={};items=[]
        for ident in ids:
            item=self.store.get(ident)
            if is_dynamic(item['metadata']) and static_frame:
                frame=choose_frame(self.window,item)
                if frame is None:continue
                frames[ident]=frame
            items.append(item)
        if not items:return
        if background and len(items)!=1:
            self.status.set('请选择一张图片或 GIF 作为背景；当前作品未改变。');return
        retained=[l for l in self.doc.layers if not background or l.get('role')!='background']
        if background and is_dynamic(items[0]['metadata']) and items[0]['id'] not in frames:
            # Using the existing GIF as background moves that animation to the
            # bottom rather than inserting a second copy of the same source.
            retained=[l for l in retained if not (l.get('animation') and l.get('source_id')==items[0]['id'])]
        point=point or (self.doc.size[0]/2,self.doc.size[1]/2)
        def add():
            from emoji_bridge.dynamic_cutout import material_animation
            animations={i['id']:material_animation(self.store,i['id'],cancel=self.save_cancel,
                progress=lambda n,t,p:self.events.put(('progress',f'{p}：{n}帧'))) for i in items if is_dynamic(i['metadata']) and i['id'] not in frames}
            images=[animations[i['id']].frames[0] if i['id'] in animations else load_static(self.store.original(i['id']),frame=frames.get(i['id'])) for i in items]
            total=sum(im.width*im.height for im in images)+sum(l['image'].width*l['image'].height for l in retained if l['kind']=='sticker')
            if total>64_000_000:raise ValueError('图层原件合计超过 6400 万像素，请减少素材；未缩小原件')
            layers=list(retained);parents=list(self.doc.source_ids)
            for index,(item,image) in enumerate(zip(items,images)):
                ratio=min(1,self.doc.size[0]*.6/image.width,self.doc.size[1]*.6/image.height)
                size=tuple(max(1,round(v*ratio)) for v in image.size)
                position=(round(point[0]-size[0]/2+index*18),round(point[1]-size[1]/2+index*18))
                ident=uuid.uuid4().hex
                layer=dict(id=ident,kind='sticker',image=image,size=size,position=position,source_id=item['id'])
                if item['id'] in animations:layer['animation']=animations[item['id']]
                if background:
                    layer.update(size=self.doc.size,position=(0,0),fit='cover',role='background');layers.insert(0,layer)
                else:layers.append(layer)
                if item['id'] not in parents:parents.append(item['id'])
            self.doc.replace_scene(self.doc._state.base,layers,parents,'添加素材图层');self.selected_layer=ident
            self.store.mark_used([i['id'] for i in items])
            self.frame_history.extend({'material_id':i,'frame':f} for i,f in frames.items())
            return {'materials_added':True}
        self.submit(add,'添加素材到当前作品')

    def drop_materials(self,event):
        if self.busy or self.drop_after or not self.doc:return 'refuse_drop'
        x=float(event.x_root)-self.canvas.winfo_rootx();y=float(event.y_root)-self.canvas.winfo_rooty()
        point=((x-self.origin[0])/self.scale,(y-self.origin[1])/self.scale)
        if not (0<=point[0]<=self.doc.size[0] and 0<=point[1]<=self.doc.size[1]):
            self.status.set('请拖到画布内部，灰色区域不是作品。');return 'refuse_drop'
        if not self.finish_text():return 'refuse_drop'
        if str(event.data).startswith('EmojiBridge:'):
            ident=str(event.data).split(':',1)[1]
            try:
                if is_dynamic(self.store.get(ident)['metadata']):
                    # End the native OLE drop before opening the explicit frame
                    # dialog, so the modal does not run inside DoDragDrop.
                    def choose():
                        self.drop_after=None;self.add_materials([ident],point)
                    self.drop_after=self.window.after_idle(choose)
                else:self.add_materials([ident],point)
            except ValueError as exc:self.status.set(str(exc));return 'refuse_drop'
        else:
            if getattr(event,'type','DND_Files') not in ('DND_Files','CF_HDROP'):return 'refuse_drop'
            paths=self.canvas.tk.splitlist(event.data)
            from video_tools import VIDEO_EXTENSIONS
            videos=[p for p in paths if Path(p).suffix.lower() in VIDEO_EXTENSIONS]
            paths=[p for p in paths if p not in videos]
            if videos and getattr(self,'open_video',None):self.window.after_idle(lambda:self.open_video(videos))
            if not paths:return 'copy' if videos else 'refuse_drop'
            def import_files():
                ids=[];errors=[]
                for path in paths:
                    try:ids.append(self.store.import_file(path,kind='drop',cancel=self.save_cancel)[0]['id'])
                    except Exception as exc:errors.append(str(exc))
                return {'canvas_import':(ids,point,errors)}
            self.submit(import_files,'托管拖入原件')
        return 'copy'

    def result_ready(self,result):
        if result.get('timing_applied'):
            self.animation_effects.speed.set(1);self.animation_effects.open_timing()
        if 'scribble_result' in result:self.cutout.ready(*result['scribble_result'])
        if result.get('cutout_model_ready'):
            self.cutout.settled();self.cutout.note.configure(text=result['cutout_model_ready']+' 已导入；选择此模型后点击处理。')
        if hasattr(self,'factory_workspace'):self.factory_workspace.result(result)
        self.cancel_save_button.pack_forget()
        if 'subject_repair' in result:
            self.preserve_playhead=result.get('subject_playhead',self.play_elapsed);self.playing=False
            data=result['subject_repair'];stopped=data.get('stopped',[])
            text=f"已更新 {len(data['masks'])} 帧；原件和关键帧保留。"
            if stopped:text+=' 待修正帧：'+', '.join(str(row['frame']+1) for row in stopped)
            self.subject_selection.note.set(text);self.status.set(text)
        if result.get('subject_model_ready'):
            self.subject_selection.engine.set('SAM2 主体识别');self.subject_selection.note.set('SAM2 已准备；点 / 框用于主体识别，套索仍可直接修正。CPU 传播按所选区间处理。')
        if 'template_import' in result:self.template_tools.show(result['template_import'])
        if result.get('collage_arranged'):
            self.collage_controller.commit(result['collage_arranged'])
        if 'template_recipe' in result:self.editing_recipe=result['template_recipe']
        if 'compressed' in result:
            value=result['compressed'];row=value['selected'];self.status.set(('已达到目标' if value['met'] else '未达到目标')+f' · {row["bytes"]/1024:.1f} KiB · {row["size"]} · {row["duration_ms"]/1000:.2f} 秒；独立副本已保存')
        if 'recognized_text' in result:
            self.intelligence.text.delete('1.0','end');self.intelligence.text.insert('1.0',result['recognized_text']);self.show_property(self.intelligence.vision_page)
        if 'track_lost' in result:
            self.intelligence.open_section('vision')
            self.status.set('跟随完成；'+('有 '+str(result['track_lost'])+' 帧需要校正' if result['track_lost'] else '主体没有跟丢')+'。播放检查效果，暂停后可重新框选校正。')
        if result.get('loaded'):self.store.mark_used([i['id'] for i in self.sources])
        if result.get('canvas_import'):
            ids,point,errors=result['canvas_import'];self.material_panel.reload()
            if ids:self.add_materials(ids,point)
            if errors:messagebox.showwarning('部分文件未导入','\n'.join(errors[:5]),parent=self.window)
        if result.get('saved'):
            self.store.mark_used([result['saved']['id']]);self.material_panel.page=0
        if result.get('saved') or result.get('materials_added'):self.material_panel.reload()

    def set_cursor(self,name):
        if self.cursor_name!=name:
            cursor=name
            if name=='rotate':
                if not getattr(self,'rotation_cursor',None):
                    # Tk on Windows cannot load a cursor from some Unicode
                    # installation paths. Its small immutable resource is cached.
                    import tempfile,shutil
                    file=Path(tempfile.gettempdir())/'EmojiBridge-rotate-S0105.cur'
                    if not file.exists():shutil.copyfile(Path(__file__).resolve().parents[1]/'assets/cursors/rotate.cur',file)
                    self.rotation_cursor='@'+file.as_posix()
                cursor=self.rotation_cursor
            try:self.canvas.configure(cursor=cursor)
            except tk.TclError:
                if name!='rotate':raise
                self.canvas.configure(cursor='exchange')
            self.cursor_name=name

    def handle_at(self,event):
        return next((k for k,(x,y) in self.handles.items() if abs(event.x-x)<=px(self.window,9) and abs(event.y-y)<=px(self.window,9)),None)

    def hover(self,event):
        if getattr(self,'hand_mode',False):self.set_cursor('fleur');return
        if getattr(getattr(self,'cutout',None),'marking',False):self.cutout.hover(event);return
        if getattr(getattr(self,'subject_selection',None),'active',False):self.set_cursor('crosshair');return
        if hasattr(self,'raster') and self.raster.active:self.set_cursor('crosshair');return
        if self.gesture or self.inline:return
        if self.crop_mode:self.set_cursor('crosshair');return
        handle=self.handle_at(event)
        if handle:
            self.set_cursor({'nw':'size_nw_se','se':'size_nw_se','ne':'size_ne_sw','sw':'size_ne_sw','w':'size_we','e':'size_we','rotate':'rotate'}[handle]);return
        self.set_cursor('fleur' if self.doc and self.doc.hit_layer(self.point(event),tolerance=2/self.scale) else 'arrow')

    def make_document(self,images,ids,**options):
        if len(images)>1:doc=layered_collage(images,ids,**options)
        else:
            doc=EditDocument(Image.new('RGBA',images[0].size,'white'),ids)
            doc.add_sticker(images[0],(0,0),source_id=ids[0])
        layers=doc.layers
        for layer in layers:
            if layer.get('source_id') in self.animations:layer['animation']=self.animations[layer['source_id']]
        doc.replace_scene(doc._state.base,layers,ids,'打开素材')
        doc._initial=doc._state;doc._undo.clear();doc.mark_saved();return doc

    def replace_collage(self,images,ids,**options):
        if self.doc and self.doc.animation:raise ValueError('动态作品请直接移动、缩放图层；重新套用静态拼图布局暂不支持')
        scene=layered_collage(images,ids,**options)
        if not self.doc:self.doc=scene;return
        overlays=[l for l in self.doc.layers if l.get('role')!='collage']
        parents=list(dict.fromkeys([*ids,*[l['source_id'] for l in overlays if l.get('source_id')]]))
        self.doc.replace_scene(scene._state.base,[*scene.layers,*overlays],parents,'调整独立图片拼图')

    def paint(self,image,size):
        if not self.doc:return
        if self.canvas.winfo_width()<16 or self.canvas.winfo_height()<16:
            self.resized();return
        self.opening_label.place_forget()
        if self.initial_workspace:
            self.initial_workspace=False
            # The subclass toolbar is packed after the loader starts. Settle Tk's
            # geometry before taking the first artboard aspect ratio.
            self.window.update_idletasks()
            try:
                # The first Map may be delayed until after a user edit. Never
                # turn those changes into the initial/saved state or erase undo.
                if not self.doc.dirty:
                    # Fitting an untouched, single library item is an initial
                    # view, not a user edit. Keep the loader's unsaved state
                    # (multi-item compositions still need saving).
                    self.expand_canvas();self.doc._initial=self.doc._state;self.doc._undo.clear();self.doc.mark_saved()
                if self.applied_collage:self.collage_states[self.doc.revision]=deepcopy(self.applied_collage)
            except ValueError as exc:self.status.set(str(exc))
        size=self.doc.size
        fit=min((self.canvas.winfo_width()-16)/size[0],(self.canvas.winfo_height()-16)/size[1])
        self.scale=getattr(self,'manual_scale',None) or max(.005,fit)*self.zoom
        w,h=max(1,round(size[0]*self.scale)),max(1,round(size[1]*self.scale))
        self.origin=((self.canvas.winfo_width()-w)/2+self.pan[0],(self.canvas.winfo_height()-h)/2+self.pan[1])
        x,y=self.origin
        ids={l['id'] for l in self.doc.layers}
        for ident in list(self.objects):
            if ident not in ids:self.canvas.delete(self.objects.pop(ident))
        for cache in (self.preview_cache,self.preview_sources,self.display_keys,self.object_photos,self.display_images):
            for key in list(cache):
                if key not in ids:del cache[key]
        # One display image replaces hundreds of Tcl checkerboard objects.
        # Cache only the visible crop, so zoom cannot allocate a giant artboard.
        left,top=max(0,int(-x)),max(0,int(-y));right,bottom=min(w,left+self.canvas.winfo_width()+2),min(h,top+self.canvas.winfo_height()+2)
        base_key=(id(self.doc._state.base),w,h,left,top,right,bottom,getattr(self,'light_checker',False))
        if self.base_key!=base_key:
            display_size=(max(1,right-left),max(1,bottom-top))
            solid=self.backdrop.solid_color(self.doc._state.base)
            if solid is not None:base=Image.new('RGBA',display_size,solid)
            elif right>left and bottom>top:
                factor=2**max(0,int(math.log2(max(1,1/self.scale))))
                source_key=(id(self.doc._state.base),factor)
                if getattr(self,'base_source_key',None)!=source_key:
                    self.base_source=self.doc._state.base.reduce(factor) if factor>1 else self.doc._state.base
                    self.base_source_key=source_key
                # One bounded display source; use exact source/display ratio for
                # odd canvas dimensions, so pan, hit testing and export still align.
                sx=self.base_source.width/self.doc.size[0];sy=self.base_source.height/self.doc.size[1]
                base=self.base_source.resize(display_size,Image.Resampling.LANCZOS,box=(left/self.scale*sx,top/self.scale*sy,min(self.base_source.width,right/self.scale*sx),min(self.base_source.height,bottom/self.scale*sy)))
            else:base=Image.new('RGBA',display_size)
            if base.getextrema()[3]!=(255,255):
                check=self.backdrop.checker(display_size,(left,top),getattr(self,'light_checker',False))
                if solid!=(0,0,0,0):check.paste(base,(0,0),base)
                base=check
            self.base_photo=ImageTk.PhotoImage(base);self.base_key=base_key
        self.photo=self.base_photo
        if not self.canvas.find_withtag('artboard'):
            self.canvas.create_image(x+left,y+top,image=self.photo,anchor='nw',tags='artboard')
            self.canvas.create_rectangle(x,y,x+w,y+h,outline='#777e8a',width=1,tags='artboard-boundary')
        else:
            self.canvas.coords('artboard',x+left,y+top);self.canvas.itemconfigure('artboard',image=self.photo)
            self.canvas.coords('artboard-boundary',x,y,x+w,y+h)
        self.canvas.tag_lower('artboard')
        for layer in self.doc.layers:
            self.paint_layer(layer)
            if layer['id'] in self.objects:self.canvas.tag_raise(self.objects[layer['id']])
        self.canvas.tag_raise('artboard-boundary')
        self.draw_bounds()
        self.dimensions.set(f'{size[0]} × {size[1]} · {self.scale:.0%}')
        if hasattr(self,'cutout'):self.cutout.draw()

    def paint_layer(self,layer):
        if hasattr(self,'cutout'):layer=self.cutout.preview_layer(layer)
        if layer.get('visible') is False:
            if layer['id'] in self.objects:self.canvas.itemconfigure(self.objects[layer['id']],state='hidden')
            return
        elapsed=sum(self.doc.animation.durations[:self.animation_frame]) if self.doc.animation else 0
        if layer.get('tracking'):
            from emoji_bridge.tracking import tracked_layer
            layer=tracked_layer(layer,elapsed)
        # Offscreen basic GIF layers retain document/time state but don't queue
        # frames that cannot be seen. Re-entering the viewport requests NOW.
        ident=layer['id']
        if layer.get('animation') and layer['kind']=='sticker' and not layer.get('effect'):
            width,height=_layer_size(layer);x,y=layer['position']
            left,top=self.origin[0]+x*self.scale,self.origin[1]+y*self.scale
            if left>=self.canvas.winfo_width() or top>=self.canvas.winfo_height() or left+width*self.scale<=0 or top+height*self.scale<=0:
                if ident in self.objects:self.canvas.itemconfigure(self.objects[ident],state='hidden')
                return
        if ident in self.objects:self.canvas.itemconfigure(self.objects[ident],state='normal')
        if layer.get('text_motion'):layer={**layer,'_elapsed':elapsed}
        selection=getattr(self,'subject_selection',None)
        inspect_mode=selection.view.get() if selection and selection.active and layer['id']==self.selected_layer else '结果'
        if inspect_mode in ('蒙版覆盖','黑底','白底') and layer['kind']=='sticker':
            from emoji_bridge.subject_selection import frame_data
            from PIL import ImageChops
            original,mask=frame_data(layer,selection.index(layer));image=original.copy()
            image.putalpha(ImageChops.multiply(original.getchannel('A'),mask))
            if inspect_mode=='蒙版覆盖':
                tint=Image.new('RGBA',original.size,'#bd3654');tint.putalpha(ImageChops.invert(mask).point(lambda p:p//2));image=Image.alpha_composite(original,tint)
            else:
                background=Image.new('RGBA',original.size,'black' if inspect_mode=='黑底' else 'white');background.alpha_composite(image);image=background
            layer={**layer,'animation':None,'image':image,'mask':None}
        original_preview=bool(getattr(getattr(self,'cutout',None),'show_original',False) and layer['id']==self.selected_layer)
        pixel_key=id(layer.get('image'))
        if layer.get('animation'):
            from emoji_bridge.animated_edit import layer_frame,layer_frame_index
            pixel_key=(id(layer['animation']),layer_frame_index(layer,self.doc.animation,self.animation_frame),original_preview)
        if original_preview and layer['kind']=='sticker':
            layer=dict(layer,mask=None)
            if layer.get('animation'):
                from emoji_bridge.cutout_masks import MaskedFrames
                frames=layer['animation'].frames
                if isinstance(frames,MaskedFrames):layer=dict(layer,image=frames.originals[layer_frame_index(layer,self.doc.animation,self.animation_frame)],animation=None)
            pixel_key=(pixel_key,'original')
        s=self.scale;ident=layer['id']
        key=(layer.get('_elapsed'),str(layer.get('text_motion')),layer.get('flip_h'),layer.get('flip_v'),pixel_key,id(layer.get('mask')),layer.get('effect'),layer.get('text'),layer['size'],layer.get('box_width'),layer.get('color'),layer.get('colors'),layer.get('fit'),layer.get('rotation'),layer.get('shape'),layer.get('stroke_width'),layer.get('fill'),s)
        cached=self.preview_cache.get(ident)
        frame_key=(ident,key)
        if layer.get('animation') and frame_key in self.frame_previews:
            cached=(key,self.frame_previews[frame_key]);self.frame_previews.move_to_end(frame_key)
        if cached and cached[0]==key:image=cached[1]
        elif layer.get('animation') and not original_preview:
            # Decode/filter/transform animation frames off Tk. One active worker
            # and a latest request per layer; stale geometry is never displayed.
            animation=layer['animation'];frame_index=pixel_key[1];snapshot=dict(layer)
            signature=(id(animation),key[1:4],key[5:])
            display_job_key=(ident,signature,frame_index)
            def render():
                return preview_layer({**snapshot,'image':animation.frames[frame_index]},s)
            self.display_jobs.request(ident,display_job_key,render)
            image=self.display_jobs.get(display_job_key)
            completed=self.display_jobs.completed(ident)
            if image is None and completed and completed[0][1]==signature:image=completed[1]
            if image is None:
                # The previous visible frame stays until a matching result is
                # ready; no full frame calculation is performed on this thread.
                return
            key=(key,id(image))
        else:
            if layer.get('animation'):layer={**layer,'image':layer_frame(layer,self.doc.animation,self.animation_frame)}
            source=None
            if layer['kind']=='sticker':
                original=layer['image'];tw,th=(max(1,round(v*s)) for v in layer['size'])
                factor=max(1,min(original.width//tw,original.height//th));source_key=(pixel_key,id(layer.get('mask')),layer.get('effect'),factor)
                prior=self.preview_sources.get(ident)
                if prior and prior[0]==source_key:source=prior[1]
                else:
                    from emoji_bridge.raster_tools import image_effects
                    source=image_effects(layer,original).convert('RGBa')
                    if factor>1:source=source.reduce(factor)
                    self.preview_sources[ident]=(source_key,source)
            image=preview_layer(layer,s,source)
            self.preview_cache[ident]=(key,image)
            if layer.get('animation'):
                self.frame_previews[frame_key]=image;self.frame_pixels+=image.width*image.height
                while self.frame_pixels>12_000_000 or len(self.frame_previews)>60:
                    _,old=self.frame_previews.popitem(last=False);self.frame_pixels-=old.width*old.height
        # Workspace clips to the viewport, not the export artboard. Off-canvas
        # objects stay visible/selectable while final rendering keeps its bounds.
        px,py=(round(v*s) for v in layer['position'])
        vx,vy=self.origin[0]+px,self.origin[1]+py
        left,top=max(0,int(-vx)),max(0,int(-vy))
        right,bottom=min(image.width,int(self.canvas.winfo_width()-vx)),min(image.height,int(self.canvas.winfo_height()-vy))
        display_key=(left,top,right,bottom)
        # A pending frame may reuse the last completed bitmap. Its requested
        # frame index changed, but its pixels did not: don't upload it to Tk again.
        if self.display_images.get(ident) is image and self.display_keys.get(ident)==display_key:photo=self.object_photos[ident]
        else:
            self.display_images[ident]=image
            if right>left and bottom>top:image=image.crop((left,top,right,bottom))
            else:image=Image.new('RGBA',(1,1))
            photo=ImageTk.PhotoImage(image);self.object_photos[ident]=photo;self.display_keys[ident]=display_key
        x=self.origin[0]+px+left;y=self.origin[1]+py+top
        if ident in self.objects:
            if self.canvas.itemcget(self.objects[ident],'image')!=str(photo):self.canvas.itemconfigure(self.objects[ident],image=photo)
            self.canvas.coords(self.objects[ident],x,y)
        else:self.objects[ident]=self.canvas.create_image(x,y,image=photo,anchor='nw')

    def draw_bounds(self,box=None):
        if self.closed or self.inline:return
        self.canvas.delete('selection');self.handles={}
        if not self.doc or not self.selected_layer:return
        if self.selected_layer not in [l['id'] for l in self.doc.layers]:return
        a,b,c,d=box or self.doc.layer_bounds(self.selected_layer);x,y=self.origin;s=self.scale
        a,b,c,d=x+a*s,y+b*s,x+c*s,y+d*s
        self.canvas.create_rectangle(a,b,c,d,outline='#1269bc',width=px(self.window,2),tags='selection')
        points={'nw':(a,b),'ne':(c,b),'sw':(a,d),'se':(c,d)}
        if self.doc._find(self.selected_layer)['kind']=='text':
            points.update(w=(a,(b+d)/2),e=(c,(b+d)/2))
        # Rotation uses the same non-destructive gesture for every layer kind.
        # Only text needs side handles for wrapping; corners remain resize grips.
        self.canvas.create_line((a+c)/2,b,(a+c)/2,b-px(self.window,26),fill='#1269bc',tags='selection')
        self.handles['rotate']=((a+c)/2,b-px(self.window,26))
        self.canvas.create_oval((a+c)/2-px(self.window,6),b-px(self.window,32),(a+c)/2+px(self.window,6),b-px(self.window,20),fill='white',outline='#1269bc',width=px(self.window,2),tags='selection')
        for key,(xx,yy) in points.items():
            self.handles[key]=(xx,yy)
            self.canvas.create_rectangle(xx-px(self.window,5),yy-px(self.window,5),xx+px(self.window,5),yy+px(self.window,5),fill='white',outline='#1269bc',width=px(self.window,2),tags='selection')

    def press(self,event):
        if getattr(self,'hand_mode',False):return self.pan_press(event)
        if self.inline:
            if not self.finish_text():return
        if not self.doc:return
        if self.busy:
            # Selection is UI state; the worker already owns an immutable target.
            self.selected_layer=self.doc.hit_layer(self.point(event),tolerance=2/self.scale)
            self.refresh_layers();self.target_selected(follow=True);return
        if getattr(getattr(self,'cutout',None),'marking',False):self.cutout.press(event);return
        if getattr(getattr(self,'subject_selection',None),'active',False):self.subject_selection.press(event);return
        if hasattr(self,'raster') and self.raster.active:self.raster.press(event);return
        self.canvas.focus_force()
        if self.crop_mode:return super().press(event)
        handle=self.handle_at(event)
        point=self.point(event)
        if not handle:
            self.selected_layer=self.doc.hit_layer(point,tolerance=2/self.scale)
            self.refresh_layers()
            self.target_selected(follow=True)
        if self.selected_layer:
            if not handle:self.set_cursor('fleur')
            layer=self.doc._find(self.selected_layer)
            if layer.get('locked'):
                self.status.set('图层已锁定，可定位或明确解锁');return
            self.gesture={'handle':handle,'start':point,'layer':dict(layer),'box':self.doc.layer_bounds(layer['id']),'props':{}}

    def motion(self,event):
        if getattr(self,'pan_gesture',None):return self.pan_move(event)
        if getattr(getattr(self,'cutout',None),'marking',False):self.cutout.motion(event);return
        if getattr(getattr(self,'subject_selection',None),'active',False):self.subject_selection.motion(event);return
        if hasattr(self,'raster') and self.raster.points:self.raster.motion(event);return
        if self.crop_mode:return super().motion(event)
        if not self.gesture:return
        g=self.gesture;layer=g['layer'];p=self.point(event);dx=p[0]-g['start'][0];dy=p[1]-g['start'][1]
        a,b,c,d=g['box'];handle=g['handle']
        if abs(dx)<1e-9 and abs(dy)<1e-9:props={}
        elif handle is None:props={'position':(round(layer['position'][0]+dx),round(layer['position'][1]+dy))}
        elif handle=='rotate':
            center=((a+c)/2,(b+d)/2)
            start=math.atan2(g['start'][1]-center[1],g['start'][0]-center[0])
            current=math.atan2(p[1]-center[1],p[0]-center[0])
            angle=round((layer.get('rotation',0)-math.degrees(current-start))%360,1)
            props=self.rotated_properties(layer,angle)
        elif handle in ('e','w'):
            original_width=_text_metrics(layer)[2][0]
            width=max(10,round(original_width+(dx if handle=='e' else -dx)))
            props={'box_width':width}
            new_width,new_height=_layer_size({**layer,**props})
            if layer.get('rotation'):props['position']=(round((a+c-new_width)/2),round((b+d-new_height)/2))
            elif handle=='w':props['position']=(round(c-new_width),round(b))
        elif layer['kind']=='shape':
            anchor=(c if 'w' in handle else a,d if 'n' in handle else b)
            width=max(2,round(abs(p[0]-anchor[0])));height=max(2,round(abs(p[1]-anchor[1])))
            props={'size':(width,height),'position':(round(anchor[0]-width if 'w' in handle else anchor[0]),round(anchor[1]-height if 'n' in handle else anchor[1]))}
        else:
            anchor=(c if 'w' in handle else a,d if 'n' in handle else b)
            ratio=max(.05,min(12,((p[0]-anchor[0])*(g['start'][0]-anchor[0])+(p[1]-anchor[1])*(g['start'][1]-anchor[1]))/
                max(1,(g['start'][0]-anchor[0])**2+(g['start'][1]-anchor[1])**2)))
            width=(c-a)*ratio;height=(d-b)*ratio
            props={'position':(round(anchor[0]-width if 'w' in handle else anchor[0]),round(anchor[1]-height if 'n' in handle else anchor[1]))}
            if layer['kind']=='text':
                props['size']=max(1,min(4096,round(layer['size']*ratio)))
                if layer.get('box_width'):props['box_width']=max(1,round(layer['box_width']*ratio))
                width,height=_layer_size({**layer,**props})
                props['position']=(round(anchor[0]-width if 'w' in handle else anchor[0]),round(anchor[1]-height if 'n' in handle else anchor[1]))
            else:props['size']=(max(1,round(layer['size'][0]*ratio)),max(1,round(layer['size'][1]*ratio)))
        g['props']=props
        if self.drag_after is None:self.drag_after=self.window.after(16,self.paint_gesture)

    def paint_gesture(self):
        self.drag_after=None
        if not self.gesture:return
        preview={**self.gesture['layer'],**self.gesture['props']}
        try:
            size=_size(_layer_size(preview))
            self.paint_layer(preview)
            x,y=preview['position'];self.draw_bounds((x,y,x+size[0],y+size[1]))
        except ValueError:self.status.set('尺寸超出当前范围；松开后会保留合法状态。')

    def release(self,event):
        if getattr(self,'pan_gesture',None):return self.pan_release(event)
        if getattr(getattr(self,'cutout',None),'marking',False):self.cutout.release(event);return
        if getattr(getattr(self,'subject_selection',None),'active',False):self.subject_selection.release(event);return
        if hasattr(self,'raster') and self.raster.points:self.raster.release(event);return
        if self.crop_mode:return super().release(event)
        if not self.gesture:return
        self.motion(event)
        if self.drag_after:self.window.after_cancel(self.drag_after);self.drag_after=None
        self.paint_gesture();g=self.gesture;self.gesture=None
        if any(value!=g['layer'].get(key) for key,value in g['props'].items()):
            try:self.doc.update_layer(g['layer']['id'],**g['props']);self.changed('图层已调整')
            except ValueError as exc:self.paint(None,self.doc.size);self.status.set(str(exc))
        self.hover(event)

    def changed(self,message):
        if self.applied_collage:self.collage_states[self.doc.revision]=deepcopy(self.applied_collage)
        self.refresh_layers();self.status.set(message+'。'+(' 有未保存修改。' if self.doc.dirty else ''))
        if not self.save_waiting:self.save_state={'state':'dirty' if self.doc.dirty else 'saved','text':'有未保存修改' if self.doc.dirty else '已保存','revision':self.doc.revision}

    def begin_text(self,event=None):
        if getattr(getattr(self,'cutout',None),'marking',False):
            # Tk replaces ButtonPress with Double-ButtonPress for quick repeated
            # strokes. It is still a new stroke, never an inline text command.
            if event is not None:self.press(event)
            return 'break'
        if getattr(getattr(self,'subject_selection',None),'active',False):return
        if self.busy or not self.doc or self.crop_mode or getattr(self,'hand_mode',False):return
        if getattr(getattr(self,'raster',None),'active',False):return
        # An explicit text tool + double click is an insertion intent. Other
        # tools retain selection/transform; no implicit insertion on tool open.
        if event is not None and getattr(self,'active_tool',None)=='text':
            point=self.point(event);hit=self.doc.hit_layer(point,tolerance=2/self.scale)
            if hit and self.doc._find(hit)['kind']=='text':self.selected_layer=hit
            else:
                if not self.finish_text():return
                try:
                    value=self.text.get('1.0','end-1c').strip() or '在这里写字'
                    self.selected_layer=self.doc.add_text(value,self.font_size.get(),self.text_color,point)
                except (ValueError,tk.TclError) as exc:self.status.set(str(exc));return 'break'
                self.gesture=None
                if self.drag_after:self.window.after_cancel(self.drag_after);self.drag_after=None
                self.changed('添加文字');self.paint(None,self.doc.size)
        if not self.selected_layer:return
        layer=self.doc._find(self.selected_layer)
        if layer['kind']!='text':return
        if layer.get('locked'):
            self.status.set('图层已锁定，请先在图层操作中解锁。');return 'break'
        self.gesture=None;self.canvas.delete('selection');self.handles={}
        if self.inline:return
        a,b,c,d=self.doc.layer_bounds(layer['id']);x,y=self.origin;s=self.scale
        # Tk's native IME text widget is upright. Commit restores rotation on
        # the same layer; no rendered image replaces the editable characters.
        if layer.get('rotation'):
            width,height=_text_metrics(layer)[2];a=(a+c-width)/2;b=(b+d-height)/2;c=a+width;d=b+height
        text=tk.Text(self.canvas,wrap='char',undo=True,exportselection=False,borderwidth=1,highlightthickness=1,
                     font=('Microsoft YaHei',-max(1,round(layer['size']*s))),padx=0,pady=0,spacing1=0,spacing3=round(4*s))
        text.place(x=x+a*s,y=y+b*s,width=max(45,(c-a)*s+4),height=max(50,(d-b)*s+12))
        text.insert('1.0',layer['text']);text.configure(fg=self.hex(layer['color']))
        for index,color in enumerate(layer.get('colors',())):
            tag='color_'+self.hex(color)[1:];text.tag_configure(tag,foreground=self.hex(color));text.tag_add(tag,f'1.0+{index}c',f'1.0+{index+1}c')
        self.inline=text;self.inline_layer=layer['id']
        self.canvas.itemconfigure(self.objects[layer['id']],state='hidden')
        text.bind('<Control-Return>',lambda e:(self.finish_text(),'break')[1])
        text.bind('<Escape>',lambda e:(self.finish_text(cancel=True),'break')[1])
        text.bind('<KeyRelease>',lambda e:self.sync_inline())
        text.bind('<ButtonRelease-1>',lambda e:self.sync_inline())
        text.focus_set();self.status.set('文字编辑中：可中文输入、换行和选字改色。旋转文字暂时正向输入，完成后恢复角度。Ctrl+Enter完成，Esc取消；Delete仅删文字。')
        return 'break'

    @staticmethod
    def hex(color):return '#%02x%02x%02x'%tuple(color[:3])

    def sync_inline(self):
        if self.inline:
            self.text.delete('1.0','end');self.text.insert('1.0',self.inline.get('1.0','end-1c'))
            ranges=self.inline.tag_ranges('sel');index=str(ranges[0]) if ranges else 'insert'
            colors=[t[6:] for t in self.inline.tag_names(index) if t.startswith('color_')]
            self.color_note.set('文字颜色：#'+colors[-1] if colors else '文字颜色：'+self.hex(self.doc._find(self.inline_layer)['color']))

    def inline_value(self):
        text=self.inline.get('1.0','end-1c');layer=self.doc._find(self.inline_layer);colors=[]
        for index in range(len(text)):
            color=layer['color']
            for tag in self.inline.tag_names(f'1.0+{index}c'):
                if tag.startswith('color_'):color=_rgba('#'+tag[6:])
            colors.append(color)
        return text,tuple(colors)

    def finish_text(self,cancel=False):
        if not self.inline:return self.flush_text(end_group=True)
        if not cancel:
            text,colors=self.inline_value()
            try:self.doc.update_layer(self.inline_layer,text=text,colors=colors)
            except ValueError as exc:self.status.set(str(exc));return False
            if self.applied_collage:self.collage_states[self.doc.revision]=deepcopy(self.applied_collage)
        self.inline.destroy();self.inline=None
        self.paint(None,self.doc.size);self.refresh_layers();return True

    def choose_text_color(self):
        chosen=colorchooser.askcolor(self.text_color,parent=self.window)[1]
        if not chosen:return
        self.text_color=chosen
        if self.inline:
            selected=self.inline.tag_ranges('sel')
            start,end=selected if selected else ('1.0','end-1c')
            # Remove older foreground tags only from this range.
            for tag in self.inline.tag_names():
                if tag.startswith('color_'):self.inline.tag_remove(tag,start,end)
            tag='color_'+chosen[1:];self.inline.tag_configure(tag,foreground=chosen);self.inline.tag_add(tag,start,end)
            self.sync_inline()
            return
        if self.selected_layer and self.doc._find(self.selected_layer)['kind']=='text':
            self.action(lambda:self.doc.color_text(self.selected_layer,chosen),'调整文字颜色')

    def pick_layer(self,event=None):
        target=self.layer_ids[self.layers.curselection()[0]] if self.layers.curselection() else None
        stamp=(id(self.doc),target,self.doc.revision if self.doc else None)
        if stamp==getattr(self,'properties_stamp',None):
            self.selected_layer=target;self.draw_bounds()
            if event is not None:self.target_selected(follow=True)
            return
        if target==self.text_layer and self.window.focus_get() is self.text and not self.inline:
            self.selected_layer=target;self.draw_bounds();return
        if not self.flush_text(end_group=target!=self.text_layer):return
        if self.inline and not self.finish_text():return
        self.text_syncing=True
        if target in self.layer_ids:
            self.layers.selection_clear(0,'end');self.layers.selection_set(self.layer_ids.index(target))
        if target and self.doc._find(target)['kind']=='shape':
            self.selected_layer=target;layer=self.doc._find(target)
            self.shape_color=self.hex(layer['color']);self.shape_stroke.set(layer['stroke_width']);self.shape_fill.set(layer.get('fill',False))
            self.draw_bounds()
        else:
            self.selected_layer=target
            if target:
                layer=self.doc._find(target)
                if layer['kind']=='text':
                    self.text.delete('1.0','end');self.text.insert('1.0',layer['text']);self.font_size.set(layer['size']);self.text_color=self.hex(layer['color'])
                else:self.sticker_scale.set(round(layer['size'][0]/layer['image'].width*100))
            self.draw_bounds()
        if self.selected_layer and self.doc._find(self.selected_layer)['kind']=='text':
            layer=self.doc._find(self.selected_layer)
            self.text_rotation.set(round(layer.get('rotation',0),1))
            self.color_note.set('文字颜色：局部多色' if len(set(layer.get('colors',())))>1 else '文字颜色：'+self.hex(layer.get('colors',[layer['color']])[0] if layer.get('colors') else layer['color']))
        self.text.edit_modified(False);self.text_syncing=False
        self.text_layer=self.selected_layer if self.selected_layer and self.doc._find(self.selected_layer)['kind']=='text' else None
        self.sync_properties()
        self.properties_stamp=stamp
        self.target_selected(follow=event is not None)

    def target_selected(self,follow=False):
        """Refresh a tool's target without navigating or resetting its view."""
        if hasattr(self,'cutout'):self.cutout.target_changed()
        if getattr(self,'active_tool',None)=='select':
            page=self.shapes_page if self.selected_layer and self.doc._find(self.selected_layer)['kind']=='shape' else self.object_page
            if self.tabs.select()!=str(page):self.show_property(page)
        if follow and hasattr(self,'factory_workspace'):self.factory_workspace.follow_selection()

    def refresh_layers(self):
        if not self.doc:return
        rows=[];self.layer_ids=[]
        if not hasattr(self,'layer_thumbnails'):self.layer_thumbnails={}
        for layer in reversed(self.doc.layers):
            ident=layer['id'];self.layer_ids.append(ident)
            key=(id(layer.get('image')),layer.get('text'),layer.get('color'),layer.get('colors'),layer.get('rotation'),layer.get('shape'),layer.get('size'),layer.get('stroke_width'),layer.get('fill'))
            prior=self.layer_thumbnails.get(ident)
            if not prior or prior[0]!=key:
                if layer['kind']=='sticker':
                    source=layer['image'];image=source.reduce(max(1,min(source.width//44,source.height//44)));image.thumbnail((44,44))
                elif layer['kind']=='text':
                    # A preview-only paper tile keeps dark text legible in the
                    # midnight layer list without changing its document color.
                    color=layer['color'];luma=sum(a*b for a,b in zip(color[:3],(.2126,.7152,.0722)))
                    image=Image.new('RGBA',(44,44));draw=ImageDraw.Draw(image)
                    draw.rounded_rectangle((0,0,43,43),radius=7,fill='#dfe5ec' if luma<145 else '#303a49')
                    draw.text((2,8),layer['text'][:2],font=_font(20),fill=color)
                else:
                    image=preview_layer(layer,min(1,44/max(layer['size'])))
                self.layer_thumbnails[ident]=(key,image)
            title='文字：'+layer['text'][:20] if layer['kind']=='text' else SHAPE_NAMES[layer['shape']] if layer['kind']=='shape' else '图片 / 贴图'
            if layer.get('source_id'):
                try:
                    source=layer['source_id']
                    if source not in self.layer_names:self.layer_names[source]=self.store.get(source)['name']
                    title=self.layer_names[source]
                except ValueError:pass
            if layer.get('role')=='background':title='背景 · '+title
            if layer.get('animation'):title='GIF · '+title
            if layer.get('visible') is False:title='隐藏 · '+title
            if layer.get('locked'):title='锁定 · '+title
            rows.append((ident,title,key,self.layer_thumbnails[ident][1]))
        self.layer_thumbnails={i:v for i,v in self.layer_thumbnails.items() if i in self.layer_ids}
        if self.selected_layer not in self.layer_ids:self.selected_layer=None
        self.layers.set_rows(rows,self.selected_layer)
        self.undo_button.state(['!disabled'] if self.doc.can_undo else ['disabled'])
        self.redo_button.state(['!disabled'] if self.doc.can_redo else ['disabled'])
        self.draw_bounds()
        if not self.inline:self.pick_layer()
        else:self.sync_properties()

    def reorder_to(self,ident,top_index):
        if self.busy or ident not in self.layer_ids:return
        self.selected_layer=ident
        self.reorder_layer(self.layer_ids.index(ident)-top_index)

    def update_layer(self):
        if self.busy or not self.doc or not self.selected_layer:return
        if self.doc._find(self.selected_layer)['kind']=='shape':return self.update_shape()
        try:size=self.font_size.get()
        except tk.TclError:self.status.set('请输入有效字号。');return
        if self.inline and not self.finish_text():return
        if self.doc and self.selected_layer and self.doc._find(self.selected_layer)['kind']=='text':
            layer=self.doc._find(self.selected_layer);props={'size':size}
            value=self.text.get('1.0','end-1c')
            if value!=layer['text']:props['text']=value
            self.action(lambda:self.doc.update_layer(self.selected_layer,**props),'更新文字')
        else:super().update_layer()

    @staticmethod
    def rotated_properties(layer,angle):
        width,height=_layer_size(layer);new_width,new_height=_layer_size({**layer,'rotation':angle})
        x,y=layer['position']
        return {'rotation':angle,'position':(round(x+(width-new_width)/2),round(y+(height-new_height)/2))}

    def rotate_text(self):
        if self.busy or not self.doc or not self.selected_layer:return
        if self.doc._find(self.selected_layer)['kind']!='text':self.status.set('请先选中文字图层。');return
        try:angle=self.text_rotation.get()
        except tk.TclError:self.status.set('请输入有效旋转角度。');return
        if not self.finish_text():return
        try:props=self.rotated_properties(self.doc._find(self.selected_layer),angle)
        except (tk.TclError,ValueError,OverflowError):self.status.set('请输入有效旋转角度。');return
        self.action(lambda:self.doc.update_layer(self.selected_layer,**props),'旋转文字（保留可编辑内容）')

    def add_shape(self,shape):
        if self.busy or not self.doc:return
        try:stroke=self.shape_stroke.get()
        except tk.TclError:self.status.set('请输入有效线宽。');return
        # Read Tk variables before the worker starts.
        fill=self.shape_fill.get();color=self.shape_color
        def add_ready():
            size=(max(20,min(160,self.doc.size[0]//3)),max(20,min(100,self.doc.size[1]//3)))
            position=tuple(round((full-part)/2) for full,part in zip(self.doc.size,size))
            self.selected_layer=self.doc.add_shape(shape,position,size,color,stroke,fill)
        self.action(add_ready,'添加'+SHAPE_NAMES[shape])

    def choose_shape_color(self):
        color=colorchooser.askcolor(self.shape_color,parent=self.window,title='图形颜色')[1]
        if not color:return
        self.shape_color=color
        if self.doc and self.selected_layer and self.doc._find(self.selected_layer)['kind']=='shape':
            self.action(lambda:self.doc.update_layer(self.selected_layer,color=color),'调整图形颜色')

    def update_shape(self):
        if self.busy or not self.doc or not self.selected_layer:return
        if self.doc._find(self.selected_layer)['kind']!='shape':self.status.set('请先选中图形图层。');return
        try:properties={'stroke_width':self.shape_stroke.get(),'fill':self.shape_fill.get(),'color':self.shape_color}
        except tk.TclError:self.status.set('请输入有效线宽。');return
        self.action(lambda:self.doc.update_layer(self.selected_layer,**properties),'更新图形')

    def shortcut(self,event,command):
        if self.closed or not self.view_active or not self.window.winfo_ismapped() or self.inline:return
        try:widget=self.window.focus_get() or event.widget
        except (KeyError,tk.TclError):return
        if widget.winfo_class() in ('Text','Entry','TEntry','Spinbox','TSpinbox','TCombobox'):return
        current=widget
        while current is not None and current is not self.window:current=getattr(current,'master',None)
        if current is None:return
        if command=='delete':self.delete_layer()
        else:self.history(command)
        return 'break'

    def action(self,fn,label):
        if not self.finish_text():return
        return super().action(fn,label)

    def apply_collage(self):
        if self.inline and not self.finish_text():return
        return super().apply_collage()

    def delete_layer(self,event=None):
        if self.inline:return
        if self.doc and self.selected_layer:
            layer=next((l for l in self.doc.layers if l['id']==self.selected_layer),None)
            if layer and layer.get('locked'):
                self.status.set('图层已锁定，请先在图层操作中解锁。');return 'break'
        super().delete_layer();return 'break'

    def reorder_layer(self,delta):
        if self.inline and not self.finish_text():return
        if self.selected_layer:self.action(lambda:self.doc.move_layer(self.selected_layer,delta),'调整遮挡顺序')

    def history(self,command):
        if not self.finish_text():return
        return super().history(command)

    def resized(self,event=None):
        if self.closed:return
        width=self.window.winfo_width()
        if width<400:return
        narrow=width<px(self.window,1050) and not getattr(self,'factory_layout',False)
        if narrow and not getattr(self,'narrow_layout',False) and hasattr(self,'browser_toggle'):
            if self.browser_host.winfo_manager():
                self.toggle_browser();self.auto_browser_hidden=True
        elif not narrow and getattr(self,'auto_browser_hidden',False):
            if not self.browser_host.winfo_manager():self.toggle_browser()
            self.auto_browser_hidden=False
        self.narrow_layout=narrow
        # Throttle to the latest geometry while resizing, instead of postponing
        # every paint until the user has stopped moving the window edge.
        if self.resize_after is None:self.resize_after=self.window.after(16,self.reflow)

    def toggle_checker(self):
        self.light_checker=not getattr(self,"light_checker",False);self.reflow()

    def reflow(self):
        if self.resize_after:self.window.after_cancel(self.resize_after)
        self.resize_after=None
        if self.closed or not self.doc:return
        if self.gesture:
            self.resize_after=self.window.after(33,self.reflow);return
        if self.busy:
            self.resize_after=self.window.after(33,self.reflow);return
        # Geometry notifications (including DPI layout settling and page return)
        # must not commit or destroy an active native text/IME edit. The normal
        # finish/cancel path schedules the next document paint.
        if self.inline:return
        self.gesture=None;self.paint(None,self.doc.size)

    def wheel_zoom(self,event):
        if self.busy or self.gesture or self.inline or not self.doc:return 'break'
        delta=getattr(event,'delta',0)
        if not delta:delta=120 if getattr(event,'num',0)==4 else -120 if getattr(event,'num',0)==5 else 0
        if delta:self.zoom_by(1.15**max(-4,min(4,delta/120)),anchor=(event.x,event.y))
        return 'break'

    def zoom_by(self,factor,anchor=None):
        if self.busy or self.gesture or not self.doc:return
        if self.inline and not self.finish_text():return
        if factor is None:self.zoom=1.;self.pan=(0.,0.);self.manual_scale=None
        else:
            old=self.zoom;self.zoom=max(.2,min(4,self.zoom*factor))
            self.manual_scale=self.scale*self.zoom/old
            if anchor is not None:
                point=((anchor[0]-self.origin[0])/self.scale,(anchor[1]-self.origin[1])/self.scale)
                scale=self.scale*self.zoom/old
                centered=((self.canvas.winfo_width()-round(self.doc.size[0]*scale))/2,
                          (self.canvas.winfo_height()-round(self.doc.size[1]*scale))/2)
                self.pan=tuple(anchor[i]-point[i]*scale-centered[i] for i in (0,1))
        self.reflow()

    def install_recovery_tools(self):
        row=ttk.Frame(self.canvas_host,padding=spacing(self.window,(4,2)));row.pack(side='bottom',fill='x',before=self.canvas)
        zoomrow=ttk.Frame(row);zoomrow.pack(fill='x')
        recoverrow=ttk.Frame(row);recoverrow.pack(fill='x')
        for parent,text,cmd in [(zoomrow,'−',lambda:self.zoom_by(.8)),(zoomrow,'适应画布',lambda:self.zoom_by(None)),(zoomrow,'+',lambda:self.zoom_by(1.25)),(zoomrow,'平移',self.hand_tool),(recoverrow,'定位所选',self.locate_selected),(recoverrow,'移回画布',self.return_selected)]:
            button=ttk.Button(parent,text=text,width=8 if text=='平移' else max(2,len(text)*2),command=cmd)
            button.pack(side='left',padx=px(self.window,2))
            if text=='平移':self.hand_button=button
        self.canvas.bind('<ButtonPress-2>',self.pan_press);self.canvas.bind('<B2-Motion>',self.pan_move);self.canvas.bind('<ButtonRelease-2>',self.pan_release)
        self.hand_mode=False;self.pan_gesture=None
        self.canvas.bind('<Escape>',self.exit_hand_tool,add='+')
        for text,key in [('显示 / 隐藏','visible'),('锁定 / 解锁','locked')]:
            ttk.Button(self.layers_host,text=text,command=lambda k=key:self.toggle_layer_flag(k)).pack(side='left',fill='x',expand=True)

    def toggle_layer_flag(self,key):
        if self.busy or not self.selected_layer:return
        layer=self.doc._find(self.selected_layer)
        self.action(lambda:self.doc.update_layer(self.selected_layer,**{key:not layer.get(key,key=='visible')}),'调整图层状态')

    def hand_tool(self):
        if getattr(self,'hand_mode',False):
            self.select_tool();return
        self.select_tool();self.hand_mode=True;self.set_cursor('fleur')
        self.hand_button.configure(text='退出平移')
        self.status.set('拖动平移工作区；再点“退出平移”或按 Esc 返回编辑。中键也可随时平移。')

    def exit_hand_tool(self,event=None):
        if getattr(self,'hand_mode',False):
            self.select_tool();return 'break'

    def pan_press(self,event):
        self.canvas.focus_set();self.pan_gesture=(event.x,event.y,self.pan);return 'break'

    def pan_move(self,event):
        if self.pan_gesture:
            x,y,pan=self.pan_gesture;self.pan=(pan[0]+event.x-x,pan[1]+event.y-y);self.paint(None,self.doc.size)
        return 'break'

    def pan_release(self,event):
        self.pan_move(event);self.pan_gesture=None;return 'break'

    def locate_selected(self):
        if self.busy or not self.selected_layer:return
        a,b,c,d=self.doc.layer_bounds(self.selected_layer)
        self.pan=(self.canvas.winfo_width()/2-(a+c)*self.scale/2-(self.origin[0]-self.pan[0]),
                  self.canvas.winfo_height()/2-(b+d)*self.scale/2-(self.origin[1]-self.pan[1]))
        self.paint(None,self.doc.size);self.status.set('已定位所选，作品位置与尺寸未改变')

    def return_selected(self):
        if self.busy or not self.selected_layer:return
        from emoji_bridge.template_inputs import return_to_canvas
        self.action(lambda:return_to_canvas(self.doc,[self.selected_layer]),'移回画布（可撤销）')

    def canvas_size(self):
        if self.busy or not self.doc:return
        if self.inline and not self.finish_text():return
        width=simpledialog.askinteger('画布尺寸','宽度（像素）',initialvalue=self.doc.size[0],minvalue=1,parent=self.window)
        if width is None:return
        height=simpledialog.askinteger('画布尺寸','高度（像素）',initialvalue=self.doc.size[1],minvalue=1,parent=self.window)
        if height is None:return
        def change():
            from emoji_bridge.editing import _size
            base=Image.new('RGBA',_size((width,height)));base.alpha_composite(self.doc._state.base,(0,0))
            self.doc.replace_base(base,description='调整画布尺寸')
        self.action(change,'调整画布')

    def save_draft(self):
        if self.busy or not self.doc:return
        if not self.finish_text():return
        self.factory_workspace.save_form()
        self.draft_id=self.draft_id or uuid.uuid4().hex;name=self.name.get()
        def save():
            save_scene(self.doc,draft_root(self.store)/self.draft_id,name,extra={'extracted_frames':self.frame_history,**getattr(self,'editing_recipe',{})},cancel=self.save_cancel);self.doc.mark_saved()
            return {'draft_saved':True}
        self.submit(save,'保存可编辑草稿')

    def save_subject(self):
        if not self.selected_layer:self.status.set('请先在画布或图层列表选择主体。');return
        self.save(subject=True)

    def save(self,subject=False):
        if not self.doc:return
        if self.busy:self.status.set('当前处理尚未完成，完成后即可保存。');return
        if getattr(self,'save_waiting',False):self.status.set('正在保存当前版本，请等待完成。');return
        if not self.finish_text():return
        self.factory_workspace.save_form()
        from emoji_bridge.scene_save import SceneSave
        document=self.doc
        if subject:
            from emoji_bridge.template_inputs import capture
            document=capture(document,[self.selected_layer])
        job=self.save_task=SceneSave.capture(document,(self.name.get().strip() or '创作作品')+(' · 主体' if subject else ''),document.size if subject else self.output.output_size(),
                    {'extracted_frames':self.frame_history,**getattr(self,'editing_recipe',{})},self.work_id)
        self.save_document=None if subject else self.doc;self.save_waiting=True
        self.cancel_save_button.pack(side='right',padx=px(self.window,4))
        self.save_state={'state':'saving','text':'准备成品','job_id':job.job_id,'work_id':job.work_id,'revision':job.revision,'started':time.monotonic()}
        self.status.set('正在准备保存；可继续编辑，本次保存点击时的版本。')
        def work():
            try:
                item=job.run(self.store,lambda phase,n,total:self.events.put(('scene_save_progress',job,phase,n,total)))
                self.events.put(('scene_save_done',job,item))
            except Exception as exc:self.events.put(('scene_save_error',job,str(exc)))
        threading.Thread(target=work,name='save-scene-snapshot',daemon=True).start()

    def handle_task_event(self,event):
        if hasattr(self,'intelligence'):self.intelligence.event(event)
        if event[0]=='error' and hasattr(self,'cutout') and self.cutout.active:
            self.cutout.settled();self.cutout.note.configure(text=event[1]+'；原件与标记保留。')
        if event[0]=='error' and hasattr(self,'factory_workspace'):
            self.factory_workspace.after_subject_slot=None
        if not event[0].startswith('scene_save_'):return False
        _,job,*values=event
        if job is not self.save_task or self.closed:return True
        if event[0]=='scene_save_progress':
            phase,n,total=values;text=phase+(f' {n}/{total}' if total else '…')
            self.save_state.update(state='saving',text=text,completed=n,total=total)
        else:
            self.save_waiting=False;self.cancel_save_button.pack_forget()
            self.save_state['elapsed']=time.monotonic()-self.save_state['started']
            if event[0]=='scene_save_error':
                self.return_after_save=False
                self.save_state.update(state='error',text='保存未完成：'+values[0])
            else:
                item=values[0]
                if self.doc is self.save_document:self.doc._saved_revision=job.revision
                self.unsaved_output=bool(self.doc.dirty)
                text='已保存回素材库'+('；更新的修改尚未保存。' if self.doc.dirty else '。')
                self.save_state.update(state='saved',text=text,item_id=item['id'])
                self.material_panel.reload(preserve_scroll=True)
                if self.on_saved:
                    try:self.on_saved(item)
                    except Exception as exc:
                        self.return_after_save=False
                        self.save_state.update(text='作品已保存；列表刷新未完成：'+str(exc))
                if getattr(self,'return_after_save',False) and not self.doc.dirty:
                    self.return_after_save=False
                    self.window.after_idle(self.saved_return)
                elif self.doc.dirty:self.return_after_save=False
        self.status.set(self.save_state['text'])
        return True

    def close(self,force=False):
        if not force and not self.finish_text():return False
        if not force and self.doc and (self.doc.dirty or self.unsaved_output):
            from ui_dialogs import unsaved_choice
            choice=unsaved_choice(self.window)
            if choice=='edit':self.return_after_save=False;return False
            if choice=='save':
                self.return_after_save=True;self.save();return False
            force=True
        return super().close(force)

    def saved_return(self):
        if self.doc.dirty:return
        callback=self.on_return
        self.close(force=True)
        if callback:callback()

    def before_close(self):
        if hasattr(self,'factory_workspace'):self.factory_workspace.close()
        if hasattr(self,'subject_selection'):self.subject_selection.cancel.set()
        self.display_jobs.close()
        if hasattr(self,'animation_effects'):self.animation_effects.close()
        if hasattr(self,'dropped_item'):self.dropped_item.close()
        if self.text_after:self.window.after_cancel(self.text_after);self.text_after=None
        for sequence,binding in getattr(self,'shortcut_bindings',[]):self.shortcut_host.unbind(sequence,binding)
        self.shortcut_bindings=[]
        self.save_cancel.set()
        if self.save_task:self.save_task.cancel.set()
        if hasattr(self,'cutout'):self.cutout.cancel.set()
        if self.animation_job:self.window.after_cancel(self.animation_job);self.animation_job=None
        if self.drop_after:self.window.after_cancel(self.drop_after);self.drop_after=None
        if self.drag_after:self.window.after_cancel(self.drag_after);self.drag_after=None
        if self.resize_after:self.window.after_cancel(self.resize_after);self.resize_after=None
        if hasattr(self,'material_panel'):self.material_panel.close()
        if hasattr(self,'output'):self.output.close()
        self.object_photos.clear();self.display_images.clear();self.preview_cache.clear()
        self.frame_previews.clear();self.preview_sources.clear();self.base_photo=None
        if hasattr(self.layers,'photos'):self.layers.photos.clear()
        self.photo=None
