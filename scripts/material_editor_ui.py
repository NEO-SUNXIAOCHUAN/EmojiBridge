from emoji_bridge.materials import is_dynamic
"""Small static editor on the managed library; rendering stays off the Tk thread."""
from ui_dpi import px, spacing, factor
from concurrent.futures import ThreadPoolExecutor,CancelledError
from copy import deepcopy
from pathlib import Path
import queue
import tkinter as tk
from tkinter import ttk
from ui_dialogs import colorchooser, messagebox, prepare_window

from PIL import Image, ImageOps, ImageTk
from emoji_bridge.editing import EditDocument, load_static, collage

LAYOUTS = {'纵向长图': 'vertical', '横排三格': 'row3', '竖排三格': 'col3', '九宫格': 'grid9'}


def choose_frame(parent, item):
    """GIF never enters a static workflow without an explicit frame confirmation."""
    from gif_frame_picker import choose
    return choose(parent,item)


class MaterialPicker:
    def __init__(self, parent, store):
        self.window = tk.Toplevel(parent); self.window.title('从素材库添加贴图')
        prepare_window(self.window, parent)
        self.window.transient(parent); self.answer = None; self.store = store; self.offset = 0; self.rows = []
        self.query = tk.StringVar(); top = ttk.Frame(self.window, padding=12); top.pack(fill='x')
        entry = ttk.Entry(top, textvariable=self.query, width=34); entry.pack(side='left')
        def search(): self.offset = 0; self.reload()
        ttk.Button(top, text='搜索', command=search).pack(side='left'); entry.bind('<Return>', lambda e: search())
        self.list = tk.Listbox(self.window, width=54, height=15, exportselection=False); self.list.pack(padx=12)
        self.list.bind('<Double-Button-1>', lambda e: self.accept())
        self.note = tk.StringVar(); ttk.Label(self.window, textvariable=self.note, padding=12).pack()
        row = ttk.Frame(self.window, padding=12); row.pack(fill='x')
        ttk.Button(row, text='上一页', command=lambda: self.turn(-1)).pack(side='left')
        ttk.Button(row, text='下一页', command=lambda: self.turn(1)).pack(side='left')
        ttk.Button(row, text='选作贴图', command=self.accept).pack(side='right')
        self.reload(); self.window.grab_set(); parent.wait_window(self.window)

    def reload(self):
        self.rows, self.total = self.store.search(self.query.get(), offset=self.offset, limit=40)
        self.list.delete(0, 'end')
        for item in self.rows:
            self.list.insert('end', item['name'] + (' · GIF 需提取帧' if is_dynamic(item['metadata']) else ''))
        self.note.set(f'{self.offset+1 if self.total else 0}–{min(self.offset+40,self.total)} / {self.total}')

    def turn(self, direction):
        value = self.offset + direction*40
        if 0 <= value < self.total: self.offset = value; self.reload()

    def accept(self):
        if self.list.curselection(): self.answer = self.rows[self.list.curselection()[0]]; self.window.destroy()


class EditorWindow:
    def __init__(self, parent, store, ids, on_saved=None, *, host=None, on_return=None, document=None, document_loader=None):
        self.store = store; self.on_saved = on_saved; self.closed = False; self.busy = False
        self.doc = None; self.selected_layer = None; self.layer_ids = []; self.photo = None
        self.embedded=host is not None;self.on_return=on_return
        self.unsaved_output = len(ids)>1
        self.collage_states = {}; self.applied_collage = None; self.initial_collage = None; self.image_by_id = {}
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='static-editor')
        self.events = queue.Queue(); self.sources = []; self.source_images = []; self.frames = {}; self.frame_history = []
        self.animations = {}
        self.drag = None; self.crop_mode = False; self.scale = 1; self.origin = (0, 0)
        self.window = host if host is not None else tk.Toplevel(parent)
        if not self.embedded:
            self.window.title('素材库 · 静态编辑 / 拼图');self.window.geometry('1180x850');self.window.minsize(980,740);self.window.protocol('WM_DELETE_WINDOW',self.close)
            prepare_window(self.window, parent)
        top = ttk.Frame(self.window, padding=spacing(self.window,(8,6))); top.pack(fill='x')
        compact=getattr(self,'integrated_panels',False)
        if compact:
            from ui_style import editor_style,FONT
            editor_style(self.window)
            ttk.Button(top,text='‹ 返回',width=7,command=self.on_return or self.close).pack(side='left',padx=spacing(self.window,(0,4)))
        else:ttk.Button(top, text='返回素材库', command=self.on_return or self.close).pack(side='left')
        self.top=top
        self.undo_button = ttk.Button(top, text='↶ 撤销', width=7, command=lambda: self.history('undo'))
        self.undo_button.pack(side='left', padx=spacing(self.window,(12, 4)))
        self.redo_button = ttk.Button(top, text='↷ 重做', width=7, command=lambda: self.history('redo'))
        self.redo_button.pack(side='left')
        if not compact:ttk.Button(top, text='重置', width=5, command=self.reset).pack(side='left', padx=px(self.window,8))
        self.name = tk.StringVar(value=store.get(ids[0])['name']+' - 作品' if len(ids)==1 else '创作作品')
        self.name_entry=ttk.Entry(top, textvariable=self.name, width=16 if compact else 22)
        self.name_entry.pack(side='left', padx=px(self.window,8))
        self.output_area=ttk.Frame(self.window);self.output_area.pack(in_=top,side='right')
        self.save_button=ttk.Button(self.output_area,text='保存 / 导出' if compact else '另存为新作品',command=self.save,style='Editor.Primary.TButton' if compact else 'TButton')
        self.save_button.pack(side='right')
        self.status = tk.StringVar(value='正在打开原件…')
        footer=ttk.Frame(self.window,padding=spacing(self.window,(12,3)));footer.pack(side='bottom',fill='x');self.footer=footer
        self.status_label=ttk.Label(footer,textvariable=self.status)
        self.status_label.pack(side='left',fill='x',expand=True)
        footer.bind('<Configure>',lambda ev:self.status_label.configure(wraplength=max(160,ev.width-260)))
        self.dimensions = tk.StringVar()
        ttk.Label(footer,textvariable=self.dimensions,style='Muted.TLabel').pack(side='right',padx=spacing(self.window,(12,0)))
        from ui_style import MIDNIGHT,BG,WORKSPACE
        body = tk.PanedWindow(self.window, orient='horizontal',sashwidth=px(self.window,8),bg=BG if MIDNIGHT else '#eef2f6',borderwidth=0)
        body.pack(fill='both', expand=True,padx=px(self.window,8),pady=spacing(self.window,(0,4)));self.panes=body
        tools = ttk.Frame(body, width=px(self.window,264)); tools.pack_propagate(False)
        self.tools=tools
        self.canvas_host=ttk.Frame(body)
        self.canvas = tk.Canvas(self.canvas_host, background=WORKSPACE, highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.opening_label=ttk.Label(self.canvas,text='正在打开作品…\n原件与可编辑图层正在载入',anchor='center',justify='center',padding=px(self.window,20),style='Muted.TLabel')
        self.opening_label.place(relx=.5,rely=.5,anchor='center')
        body.add(self.canvas_host,stretch='always',minsize=px(self.window,240));body.add(tools,stretch='never',minsize=px(self.window,264),width=px(self.window,264))
        self.canvas.bind('<ButtonPress-1>', self.press); self.canvas.bind('<B1-Motion>', self.motion)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<Configure>', lambda e: self.draw_bounds())
        if getattr(self,'integrated_panels',False):
            self.browser_host=ttk.Frame(body,width=px(self.window,272));self.browser_host.pack_propagate(False)
            body.add(self.browser_host,before=self.canvas_host,stretch='never',minsize=px(self.window,240),width=px(self.window,272))
            self.browser_tabs=ttk.Notebook(self.browser_host,style='Editor.Property.TNotebook')
            self.browser_tabs.pack(fill='both',expand=True)
            self.materials_host=ttk.Frame(self.browser_tabs);self.effects_host=ttk.Frame(self.browser_tabs)
            self.browser_tabs.add(self.materials_host,text='素材');self.browser_tabs.add(self.effects_host,text='效果')
            self.editor_tabs=ttk.Notebook(tools);self.editor_tabs.pack(fill='both',expand=True)
            self.properties_host=ttk.Frame(self.editor_tabs);self.layers_host=ttk.Frame(self.editor_tabs,padding=px(self.window,6))
            for page,title in [(self.properties_host,'属性'),(self.layers_host,'图层')]:self.editor_tabs.add(page,text=title)
            tabs=ttk.Notebook(self.properties_host)
        else:tabs = ttk.Notebook(tools)
        tabs.pack(fill='both', expand=True)
        self.tabs=tabs
        edit = ttk.Frame(tabs, padding=px(self.window,10)); tabs.add(edit, text='对象' if compact else '编辑');self.object_page=edit
        from ui_style import ScrollBody
        object_scroll=ScrollBody(edit);object_scroll.pack(fill='both',expand=True);edit=object_scroll.body;self.object_body=edit;self.object_scroll=object_scroll
        transform=ttk.Frame(tabs,padding=px(self.window,10));tabs.add(transform,text='变换' if compact else '裁剪 / 旋转');self.transform_page=transform
        row = ttk.Frame(transform); row.pack(fill='x')
        ttk.Button(row, text='左转 90°', command=lambda: self.action(lambda: self.doc.rotate(90), '旋转整幅画面')).pack(side='left')
        ttk.Button(row, text='右转 90°', command=lambda: self.action(lambda: self.doc.rotate(-90), '旋转整幅画面')).pack(side='left')
        row = ttk.Frame(transform); row.pack(fill='x', pady=px(self.window,6))
        ttk.Button(row, text='左右翻转', command=lambda: self.action(lambda: self.doc.flip(horizontal=True), '翻转整幅画面')).pack(side='left')
        ttk.Button(row, text='上下翻转', command=lambda: self.action(lambda: self.doc.flip(horizontal=False), '翻转整幅画面')).pack(side='left')
        ttk.Button(transform, text='拖选裁剪区域', command=self.crop).pack(fill='x')
        ttk.Label(transform, text='作用于整幅画面；保留独立图层、动画和撤销。', wraplength=px(self.window,245)).pack(anchor='w', pady=px(self.window,6))
        self.selection_title=tk.StringVar(value='点击画布或图层选择对象')
        if compact:ttk.Label(edit,textvariable=self.selection_title,wraplength=px(self.window,255),font=(FONT,11,'bold')).pack(anchor='w',pady=spacing(self.window,(2,12)))
        self.text_controls=ttk.Frame(edit);self.text_controls.pack(fill='x')
        self.image_controls=ttk.Frame(edit);self.image_controls.pack(fill='x')
        ttk.Label(self.text_controls, text='文字内容').pack(anchor='w')
        from ui_style import text_field
        text_box,self.text=text_field(self.text_controls,height=4,width=24,font=('Microsoft YaHei UI',11))
        text_box.pack(fill='x',pady=spacing(self.window,(4,8)));self.text.insert('1.0','在这里写字')
        row = ttk.Frame(self.text_controls); row.pack(fill='x', pady=px(self.window,6))
        ttk.Label(row, text='字号').pack(side='left'); self.font_size = tk.IntVar(value=40)
        ttk.Spinbox(row, from_=8, to=512, textvariable=self.font_size, width=6).pack(side='left', padx=px(self.window,6))
        self.text_color = '#202020'
        self.text_color_button=ttk.Button(row, text='文字颜色', command=self.choose_text_color,compound='left')
        self.text_color_button.pack(side='left');self.refresh_text_color_swatch()
        if not compact:ttk.Button(self.text_controls, text='添加文字', command=self.add_text).pack(fill='x')
        ttk.Button(self.image_controls, text='从素材库添加贴图', command=self.add_sticker).pack(fill='x',pady=spacing(self.window,(0,8)))
        row = ttk.Frame(self.image_controls); row.pack(fill='x', pady=px(self.window,6))
        ttk.Label(row, text='贴图缩放 %').pack(side='left'); self.sticker_scale = tk.IntVar(value=100)
        ttk.Spinbox(row, from_=1, to=800, textvariable=self.sticker_scale, width=7).pack(side='left', padx=px(self.window,6))
        ttk.Label(self.image_controls, text='画布拖动位置，四角等比缩放。\n图层页调整遮挡顺序。', wraplength=px(self.window,245)).pack(anchor='w', pady=spacing(self.window,(6, 3)))
        if getattr(self,'integrated_panels',False):
            from editor_panels import LayerList
            self.layers=LayerList(self.layers_host,self.pick_layer,self.reorder_to);self.layers.pack(fill='both',expand=True)
        else:
            self.layers = tk.Listbox(edit, height=5, exportselection=False); self.layers.pack(fill='x')
            self.layers.bind('<<ListboxSelect>>', self.pick_layer)
        row = ttk.Frame(edit); row.pack(fill='x', pady=px(self.window,6))
        self.update_layer_button=ttk.Button(row, text='更新选中图层', command=self.update_layer);self.update_layer_button.pack(side='left')
        self.delete_layer_button=ttk.Button(row, text='删除图层', command=self.delete_layer);self.delete_layer_button.pack(side='left', padx=px(self.window,4))
        self.layer_actions=row
        object_scroll.attach()
        if len(ids)>1:
            group = ttk.Frame(tabs, padding=px(self.window,10)); tabs.add(group, text='拼图'); tabs.select(group)
            self.collage_page=group
            ttk.Button(group,text='应用布局 / 顺序',command=self.apply_collage,style='Editor.Primary.TButton').pack(side='bottom',fill='x',pady=spacing(self.window,(8,0)))
            from ui_style import ScrollBody
            collage_scroll=ScrollBody(group);collage_scroll.pack(fill='both',expand=True);group=collage_scroll.body
            self.layout = tk.StringVar(value='九宫格' if len(ids)>3 and len(ids)<=9 else '横排三格' if len(ids)<=3 else '纵向长图')
            ttk.Label(group, text='布局（合成一张图片）').pack(anchor='w')
            ttk.Combobox(group, values=list(LAYOUTS), textvariable=self.layout, state='readonly').pack(fill='x', pady=px(self.window,5))
            self.order = tk.Listbox(group, height=7, exportselection=False); self.order.pack(fill='x')
            row = ttk.Frame(group); row.pack(fill='x', pady=px(self.window,6))
            ttk.Button(row, text='上移', command=lambda: self.reorder(-1)).pack(side='left')
            ttk.Button(row, text='下移', command=lambda: self.reorder(1)).pack(side='left', padx=px(self.window,6))
            self.gap = tk.IntVar(value=12); self.cell = tk.IntVar(value=0); self.fit = tk.StringVar(value='完整显示')
            for label, variable, start, end in [('间距（像素）',self.gap,0,200),('格子宽度（像素）',self.cell,32,8000)]:
                ttk.Label(group, text=label).pack(anchor='w', pady=spacing(self.window,(6,2)))
                ttk.Spinbox(group, from_=start, to=end, textvariable=variable, width=12).pack(anchor='w')
            ttk.Combobox(group, values=['完整显示','裁切填充'], textvariable=self.fit, state='readonly').pack(fill='x', pady=px(self.window,10))
            self.background = '#ffffff'; self.transparent = tk.BooleanVar(value=False)
            ttk.Button(group, text='选择背景色', command=self.choose_background).pack(fill='x')
            ttk.Checkbutton(group, text='透明背景 / 空位', variable=self.transparent).pack(anchor='w', pady=px(self.window,6))
            ttk.Label(group, text='三格 / 九宫格不足时留空，不自动复制。格子为方形，长图按原比例等宽排列。缩小格子会降低输出像素，请看下方尺寸。', wraplength=px(self.window,245)).pack(anchor='w', pady=px(self.window,10))
            collage_scroll.attach()
        self.poll_id = self.window.after(50, self.poll)
        if document_loader is not None:
            def load_draft():
                self.doc,data=document_loader(cancel=getattr(self,'save_cancel',None))
                return {'draft_data':data}
            self.submit(load_draft,'打开可编辑草稿');return
        if document is not None:
            self.doc=document;self.submit(lambda:{},'打开可编辑草稿');return
        try:
            for ident in ids:
                item = store.get(ident); frame = None
                if is_dynamic(item['metadata']) and not getattr(self,'supports_single_gif',False):
                    frame = choose_frame(self.window, item)
                    if frame is None: self.close(force=True); return
                    self.frames[ident] = frame
                    self.frame_history.append({'material_id':ident,'frame':frame})
                    self.unsaved_output = True
                self.sources.append(item)
            def load():
                if sum(i['metadata']['oriented_size'][0]*i['metadata']['oriented_size'][1] for i in self.sources)>64_000_000:
                    raise ValueError('所选原图合计超过 6400 万像素，请减少所选数量后再拼图；未自动缩小原图')
                self.source_images = []
                for item in self.sources:
                    if is_dynamic(item['metadata']) and item['id'] not in self.frames:
                        from emoji_bridge.animated_edit import GifSource
                        from emoji_bridge.dynamic_cutout import material_animation
                        animation=material_animation(store,item['id'],cancel=getattr(self,'save_cancel',None),
                            progress=lambda n,t,p:self.events.put(('progress',f'{p}：{n}帧')));self.animations[item['id']]=animation
                        self.source_images.append(animation.frames[0])
                    else:self.source_images.append(load_static(store.original(item['id']),frame=self.frames.get(item['id'])))
                self.image_by_id = {i['id']:image for i,image in zip(self.sources,self.source_images)}
                if len(ids)==1: self.doc = self.make_document(self.source_images,ids)
                else:
                    width = max(max(im.size) for im in self.source_images)
                    # Tk variables are only read/written on the main thread.
                    layout = 'grid9' if 3<len(ids)<=9 else 'row3' if len(ids)<=3 else 'vertical'
                    try:
                        self.doc = self.make_document(self.source_images,ids,layout=layout,gap=12,background='#ffffff',fit='contain',cell_size=(width,width))
                    except ValueError as exc:
                        return {'loaded': True, 'needs_layout': str(exc)}
                return {'loaded': True}
            self.submit(load, '打开原件')
        except Exception as exc:
            self.status.set(str(exc))

    def make_document(self, images, ids, **options):
        return EditDocument(images[0] if len(images)==1 else collage(images,**options),source_ids=ids)

    def replace_collage(self, images, ids, **options):
        image=collage(images,**options)
        if self.doc:self.doc.replace_base(image,description='调整拼图布局与顺序',source_ids=ids,keep_layers=True)
        else:self.doc=EditDocument(image,source_ids=ids)

    def preview_document(self,viewport):
        image=self.doc.render() if self.doc else None
        size=image.size if image else None
        if image:image.thumbnail(viewport,Image.Resampling.LANCZOS)
        return image,size

    def submit(self, fn, label, *, xp=None):
        if self.busy or self.closed: return False
        if hasattr(self,'save_cancel'):self.save_cancel.clear()
        import time,uuid
        if getattr(self,'activity',{}).pop('continuation',False):self.activity.update(text=label,state='running',active=True)
        else:self.activity={'id':uuid.uuid4().hex,'state':'running','active':True,'text':label,'started':time.monotonic()}
        self.busy = True; self.status.set(label+'…')
        # Layered preview takes its viewport at paint time. Avoid re-entering
        # Tk geometry and other page callbacks while this editor is being built.
        if not getattr(self,'integrated_panels',False):self.window.update_idletasks()
        viewport = (max(200,self.canvas.winfo_width()-32), max(200,self.canvas.winfo_height()-32))
        self.viewport=viewport
        xp_activity=(xp.activity if xp.activity.get('active') else xp.begin(label)) if xp else None
        def work():
            try:
                from emoji_bridge.task_budget import admission
                with admission(label,cancel=getattr(self,'save_cancel',None),waiting=lambda text:self.events.put(('progress',text))):
                    result = fn() or {};image,size=self.preview_document(viewport)
                continuation=bool(result.get('prepared_template_spec'))
                if xp and not continuation:xp.finish(cancel=getattr(self,'save_cancel',None),activity=xp_activity)
                self.activity.update(active=continuation,state='running' if continuation else 'success',continuation=continuation,elapsed=time.monotonic()-self.activity['started'])
                self.events.put(('done', label, result, image, size))
            except Exception as exc:
                if xp:xp.finish(error=exc,cancel=getattr(self,'save_cancel',None),activity=xp_activity)
                self.activity.update(active=False,state='cancelled' if isinstance(exc,(InterruptedError,CancelledError)) else 'error',elapsed=time.monotonic()-self.activity['started'])
                self.events.put(('error', str(exc)))
        self.active_future=self.pool.submit(work); return True

    def action(self, fn, label):
        if self.doc and not self.busy:
            self.crop_mode = False
            self.submit(lambda: (fn(), {})[1], label)

    def poll(self):
        if self.closed: return
        try:
            while True:
                event = self.events.get_nowait()
                if getattr(self,'handle_task_event',lambda e:False)(event):continue
                if event[0]=='progress':
                    if not getattr(self,'save_cancel',None) or not self.save_cancel.is_set():self.status.set(event[1])
                    continue
                self.busy = False
                if event[0]=='error':
                    self.status.set('未完成：'+event[1])
                    if not self.doc:self.opening_label.configure(text='作品未能打开\n'+event[1],wraplength=px(self.window,360))
                    continue
                _, label, result, image, size = event
                if result.get('draft_data'):
                    data=result['draft_data'];self.frame_history=data.get('extra',{}).get('extracted_frames',[])
                    self.editing_recipe={k:v for k,v in data.get('extra',{}).items() if k!='extracted_frames'}
                    if data.get('extra',{}).get('work_snapshot'):self.draft_id=None
                if result.get('loaded') and len(self.sources)>1:
                    self.cell.set(max(max(im.size) for im in self.source_images)); self.refresh_order()
                    if self.doc: result['collage'] = self.collage_settings()
                if self.doc and len(self.sources)>1:
                    if result.get('collage'):
                        self.applied_collage=deepcopy(result['collage'])
                        if self.initial_collage is None:self.initial_collage=deepcopy(self.applied_collage)
                    if result.get('history')=='reset':
                        self.collage_states[self.doc.revision]=deepcopy(self.initial_collage)
                    if result.get('history'):
                        self.applied_collage=deepcopy(self.collage_states[self.doc.revision])
                        self.restore_collage(self.applied_collage)
                    self.collage_states[self.doc.revision]=deepcopy(self.applied_collage)
                if size:
                    self.paint(image,size)
                self.refresh_layers(); self.status.set(label+'完成。'+(' 有未保存修改。' if self.doc and self.doc.dirty else ''))
                if result.get('draft_saved'):self.unsaved_output=False
                if result.get('needs_layout'):
                    self.status.set(result['needs_layout']+'。在拼图页调整格子宽度后点击“应用布局 / 顺序”。')
                if result.get('saved'):
                    self.unsaved_output = False
                    self.status.set('已另存回素材库，原素材未覆盖。可以返回库内导出或添加收藏。')
                    if self.on_saved:
                        try:self.on_saved(result['saved'])
                        except Exception as exc:self.status.set('作品已保存，但列表刷新未完成：'+str(exc)+'。可返回素材库刷新，勿重复保存。')
                if self.closed:return
                self.result_ready(result)
        except queue.Empty: pass
        self.poll_id = self.window.after(50,self.poll)

    def result_ready(self,result):
        """Optional view-specific continuation after the shared worker settles."""
        pass

    def paint(self,image,size):
        self.opening_label.place_forget()
        self.photo=ImageTk.PhotoImage(image);self.scale=image.width/size[0]
        self.origin=((self.canvas.winfo_width()-image.width)/2,(self.canvas.winfo_height()-image.height)/2)
        self.canvas.delete('all');x,y=self.origin
        for yy in range(0,image.height,16):
            for xx in range(0,image.width,16):
                self.canvas.create_rectangle(x+xx,y+yy,x+min(xx+16,image.width),y+min(yy+16,image.height),fill='#fff' if (xx//16+yy//16)%2 else '#e5e7eb',outline='')
        self.canvas.create_image(x,y,anchor='nw',image=self.photo)
        self.dimensions.set(f'输出 {size[0]} × {size[1]} 像素 · PNG 无损保存透明信息 · 画面仅缩放预览 {self.scale:.0%}')

    def refresh_layers(self):
        if not self.doc: return
        self.layers.delete(0,'end'); self.layer_ids=[]
        for index,layer in reversed(list(enumerate(self.doc.layers))):
            self.layer_ids.append(layer['id']); self.layers.insert('end',f'{index+1} · '+(('文字：'+layer['text'][:12]) if layer['kind']=='text' else '图片 / 贴图'))
        if self.selected_layer in self.layer_ids: self.layers.selection_set(self.layer_ids.index(self.selected_layer))
        else: self.selected_layer=None
        self.undo_button.state(['!disabled'] if self.doc.can_undo else ['disabled'])
        self.redo_button.state(['!disabled'] if self.doc.can_redo else ['disabled'])
        self.draw_bounds()

    def pick_layer(self, event=None):
        if self.busy or not self.layers.curselection(): return
        self.selected_layer=self.layer_ids[self.layers.curselection()[0]]
        layer=next(l for l in self.doc.layers if l['id']==self.selected_layer)
        if layer['kind']=='text':
            self.text.delete('1.0','end'); self.text.insert('1.0',layer['text']); self.font_size.set(layer['size'])
            self.text_color = '#%02x%02x%02x' % tuple(layer['color'][:3])
        else: self.sticker_scale.set(round(layer['size'][0]/layer['image'].width*100))
        self.draw_bounds()

    def draw_bounds(self):
        if self.closed or self.busy: return
        self.canvas.delete('selection')
        if self.doc and self.selected_layer:
            box=self.doc.layer_bounds(self.selected_layer); x,y=self.origin; s=self.scale
            self.canvas.create_rectangle(x+box[0]*s,y+box[1]*s,x+box[2]*s,y+box[3]*s,outline='#1269bc',width=2,tags='selection')

    def point(self,event): return ((event.x-self.origin[0])/self.scale,(event.y-self.origin[1])/self.scale)

    def press(self,event):
        if self.busy or not self.doc: return
        p=self.point(event)
        if self.crop_mode:
            self.drag=('crop',p); return
        self.selected_layer=None
        for layer in reversed(self.doc.layers):
            a,b,c,d=self.doc.layer_bounds(layer['id'])
            if a<=p[0]<=c and b<=p[1]<=d:
                self.selected_layer=layer['id']; self.drag=('layer',p,layer['position']); break
        self.refresh_layers()
        if self.selected_layer: self.pick_layer()

    def motion(self,event):
        if not self.drag: return
        p=self.point(event); x,y=self.origin; s=self.scale; start=self.drag[1]
        self.canvas.delete('selection')
        if self.drag[0]=='crop': box=(*start,*p)
        else:
            box=self.doc.layer_bounds(self.selected_layer); dx=p[0]-start[0];dy=p[1]-start[1]
            box=(box[0]+dx,box[1]+dy,box[2]+dx,box[3]+dy)
        self.canvas.create_rectangle(x+box[0]*s,y+box[1]*s,x+box[2]*s,y+box[3]*s,outline='#1269bc',width=2,dash=(4,3),tags='selection')

    def release(self,event):
        if not self.drag or self.busy: return
        drag=self.drag; self.drag=None; p=self.point(event); start=drag[1]
        if drag[0]=='crop':
            w,h=self.doc.size
            box=(max(0,round(min(start[0],p[0]))), max(0,round(min(start[1],p[1]))), min(w,round(max(start[0],p[0]))), min(h,round(max(start[1],p[1]))))
            if getattr(self,'region_callback',None):
                callback=self.region_callback;self.region_callback=None;callback(box)
            else:self.action(lambda:self.doc.crop(box),'裁剪')
        else:
            position=(round(drag[2][0]+p[0]-start[0]),round(drag[2][1]+p[1]-start[1]))
            if position!=tuple(drag[2]): self.action(lambda:self.doc.update_layer(self.selected_layer,position=position),'移动图层')
            else: self.draw_bounds()

    def crop(self):
        if not self.busy: self.crop_mode=True; self.status.set('在画布拖出要保留的矩形，松开完成裁剪；可撤销。')

    def choose_text_color(self):
        color=colorchooser.askcolor(self.text_color,parent=self.window)[1]
        if color: self.text_color=color;self.refresh_text_color_swatch()

    def refresh_text_color_swatch(self):
        from PIL import ImageDraw
        from ui_style import MUTED
        note=self.color_note.get() if hasattr(self,'color_note') else ''
        multicolor='多色' in note
        color='#'+note.rsplit('#',1)[1][:6] if '#' in note else self.text_color
        palette=[]
        if multicolor and self.doc and self.selected_layer:
            for value in self.doc._find(self.selected_layer).get('colors',()):
                value=tuple(value)
                if value not in palette:palette.append(value)
                if len(palette)==3:break
        key=(color,tuple(palette))
        if getattr(self,'text_swatch_key',None)==key:return
        image=Image.new('RGBA',(20,20),color);draw=ImageDraw.Draw(image)
        for index,value in enumerate(palette):
            start=1+round(index*18/len(palette));end=round((index+1)*18/len(palette))
            draw.rectangle((start,1,end,18),fill=value)
        draw.rectangle((0,0,19,19),outline=MUTED,width=1)
        self.text_color_photo=ImageTk.PhotoImage(image,master=self.window)
        self.text_color_button.configure(image=self.text_color_photo,text='文字颜色 · 多色' if multicolor else '文字颜色')
        self.text_swatch_key=key

    def add_text(self):
        if self.busy or not self.doc: return
        try: text=self.text.get('1.0','end').strip(); size=self.font_size.get();color=self.text_color
        except Exception as exc: self.status.set(str(exc)); return
        def add(): self.selected_layer=self.doc.add_text(text,size,color,(20,20))
        self.action(add,'添加文字')

    def add_sticker(self):
        if self.busy or not self.doc: return
        item=MaterialPicker(self.window,self.store).answer
        if not item: return
        frame=None
        if is_dynamic(item['metadata']):
            frame=choose_frame(self.window,item)
            if frame is None:return
            self.frame_history.append({'material_id':item['id'],'frame':frame})
        def add():
            image=load_static(self.store.original(item['id']),frame=frame)
            ratio=min(1, self.doc.size[0]*.5/image.width,self.doc.size[1]*.5/image.height)
            size=(max(1,round(image.width*ratio)),max(1,round(image.height*ratio)))
            self.selected_layer=self.doc.add_sticker(image,(20,20),size=size,source_id=item['id'])
        self.action(add,'添加贴图')

    def update_layer(self):
        if self.busy or not self.selected_layer:return
        layer=next(l for l in self.doc.layers if l['id']==self.selected_layer)
        try:
            if layer['kind']=='text': kwargs={'text':self.text.get('1.0','end').strip(),'size':self.font_size.get(),'color':self.text_color}
            else:
                ratio=self.sticker_scale.get()/100
                kwargs={'size':(max(1,round(layer['image'].width*ratio)),max(1,round(layer['image'].height*ratio)))}
        except Exception as exc: self.status.set(str(exc));return
        self.action(lambda:self.doc.update_layer(self.selected_layer,**kwargs),'更新图层')

    def delete_layer(self):
        if self.selected_layer: self.action(lambda:self.doc.remove_layer(self.selected_layer),'删除图层')

    def reset(self):
        if self.doc and not self.busy and messagebox.askyesno('重置','恢复刚进入编辑时的画面？此操作仍可撤销。',parent=self.window):
            self.history('reset')

    def history(self, command):
        if self.busy or not self.doc:return
        def apply():
            getattr(self.doc,command)()
            return {'history':command}
        self.crop_mode=False
        self.submit(apply,{'undo':'撤销','redo':'重做','reset':'重置'}[command])

    def collage_settings(self):
        return {'order':[i['id'] for i in self.sources],'layout':self.layout.get(),'gap':self.gap.get(),
                'cell':self.cell.get(),'fit':self.fit.get(),'background':self.background,'transparent':self.transparent.get()}

    def restore_collage(self, state):
        by_id={i['id']:i for i in self.sources}
        self.sources=[by_id[ident] for ident in state['order']]
        self.source_images=[self.image_by_id[ident] for ident in state['order']]
        for key in ('layout','gap','cell','fit','transparent'):getattr(self,key).set(state[key])
        self.background=state['background'];self.refresh_order()

    def refresh_order(self):
        self.order.delete(0,'end')
        for item in self.sources: self.order.insert('end',item['name'])

    def reorder(self,direction):
        if self.busy or not self.order.curselection():return
        index=self.order.curselection()[0];target=index+direction
        if 0<=target<len(self.sources):
            for values in (self.sources,self.source_images):values[index],values[target]=values[target],values[index]
            self.refresh_order();self.order.selection_set(target);self.status.set('顺序已调整，点击“应用布局 / 顺序”更新画面。')

    def choose_background(self):
        color=colorchooser.askcolor(self.background,parent=self.window)[1]
        if color:self.background=color;self.transparent.set(False)

    def apply_collage(self):
        if self.busy or not self.source_images:return
        try:
            layout=LAYOUTS[self.layout.get()];gap=self.gap.get();width=self.cell.get()
            fit='contain' if self.fit.get()=='完整显示' else 'cover'
            bg=(0,0,0,0) if self.transparent.get() else self.background
        except Exception as exc:self.status.set(str(exc));return
        settings=self.collage_settings()
        def apply():
            self.replace_collage(self.source_images,[i['id'] for i in self.sources],layout=layout,gap=gap,background=bg,fit=fit,cell_size=(width,width))
            return {'collage':settings}
        self.submit(apply,'应用拼图')

    def save(self):
        if self.busy or not self.doc:return
        name=self.name.get().strip() or '新作品'
        frames=[dict(value) for value in self.frame_history if value['material_id'] in self.doc.source_ids]
        collage_recipe=deepcopy(self.applied_collage)
        def save():
            item,_=self.store.save_work(self.doc.render(),name=name,source_ids=self.doc.source_ids,
                                       recipe={'operations':self.doc.operations,'extracted_frames':frames,'collage':collage_recipe})
            self.doc.mark_saved();return {'saved':item}
        self.submit(save,'保存新作品')

    def close(self,force=False):
        if self.closed:return True
        if not force and ((self.doc and self.doc.dirty) or self.unsaved_output) and not messagebox.askyesno('未保存修改','当前修改尚未保存。放弃修改并返回素材库？',parent=self.window):return False
        if hasattr(self,'save_cancel'):self.save_cancel.set()
        self.closed=True;self.window.after_cancel(self.poll_id);self.pool.shutdown(wait=False,cancel_futures=True)
        # Unmap once before tearing down hundreds of native controls. Keeping
        # them mapped makes Windows repaint the parent for every destroyed HWND.
        if self.embedded:self.window.pack_forget()
        else:self.window.withdraw()
        self.before_close()
        # Tcl destroys the subtree in one native operation. Then retain normal
        # Tkinter cleanup of Python child references and registered commands.
        self.window.tk.call('destroy',self.window._w)
        self.window.destroy();return True

    def before_close(self):pass
