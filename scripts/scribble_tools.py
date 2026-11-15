"""Manual-submit subject marking UI on the existing editor canvas."""
import copy
import math
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageDraw,ImageTk
from emoji_bridge.subject_marks import digest,document_points
from emoji_bridge.subject_selection import source_points,frame_data
from emoji_bridge.animated_edit import layer_frame_index
from ui_style import ScrollBody,disclosure,MUTED

MODELS={'U²-Net · 自动':'u2net','BiRefNet Lite · 精细':'birefnet-general-lite','IS-Net Anime · 试验':'isnet-anime'}


class ScribbleTools:
    def __init__(self,e):
        self.editor=e;self.active=False;self.marking=False;self.cancel=threading.Event();self.events=queue.Queue();self.stroke=None
        self.show_original=False;self.pending=None;self.last_item=None;self.submissions=0;self.overlay_key=None;self.draw_id=None
        self.target=None;self.target_doc=None;self.target_states={};self.loading_target=False
        self.page=ttk.Frame(e.tabs,padding=10);e.tabs.add(self.page,text='抠主体')
        actions=ttk.Frame(self.page);actions.pack(side='bottom',fill='x',pady=(8,0))
        scroll=ScrollBody(self.page);scroll.pack(fill='both',expand=True);body=scroll.body
        ttk.Label(body,text='抠主体与修正',style='Heading.TLabel').pack(anchor='w',pady=(0,8))
        ttk.Label(body,text='自动处理，或先用标记指定主体。',wraplength=230).pack(fill='x',pady=4)
        self.model=tk.StringVar(value=next(iter(MODELS)));self.edge=tk.StringVar(value='384');self.mode=tk.StringVar(value='keep');self.radius=tk.DoubleVar(value=24)
        ttk.Combobox(body,textvariable=self.model,values=tuple(MODELS),state='readonly').pack(fill='x',pady=8)
        ttk.Label(body,text='效果不理想可换模型，再点击处理。',wraplength=230,foreground=MUTED).pack(fill='x',pady=(0,8))
        offline=disclosure(body,'模型文件')
        self.model_status=ttk.Label(body,wraplength=230,foreground=MUTED);self.model_status.pack(fill='x')
        from component_settings import show as show_components
        ttk.Button(offline,text='可选组件：下载 / 导入',command=lambda:show_components(e.window)).pack(fill='x',pady=4)
        ttk.Button(offline,text='下载所选模型（浏览器）',command=self.download_model).pack(fill='x',pady=4)
        ttk.Label(offline,text='下载完成后点下方导入，选择 ONNX 文件或配套 ZIP 即可，无需找安装目录。',wraplength=230,foreground=MUTED).pack(fill='x')
        ttk.Button(offline,text='导入所选模型…',command=self.import_model).pack(fill='x',pady=4)
        self.model.trace_add('write',self.refresh_model_status);self.refresh_model_status()
        self.auto_button=ttk.Button(actions,text='自动抠主体',width=1,command=self.start_auto,style='Editor.Primary.TButton');self.auto_button.grid(row=0,column=0,sticky='ew',padx=(0,3))
        row=ttk.Frame(body);row.pack(fill='x')
        ttk.Radiobutton(row,text='标记主体',variable=self.mode,value='keep',command=self.enable_marks).pack(side='left')
        ttk.Radiobutton(row,text='擦除标记',variable=self.mode,value='erase',command=self.enable_marks).pack(side='left')
        ttk.Label(body,text='笔刷大小').pack(anchor='w',pady=(12,0))
        ttk.Scale(body,from_=4,to=96,variable=self.radius).pack(fill='x')
        row=ttk.Frame(body);row.pack(fill='x',pady=8)
        ttk.Button(row,text='撤销标记',width=1,command=lambda:self.history(False)).pack(side='left',expand=True,fill='x')
        ttk.Button(row,text='重做标记',width=1,command=lambda:self.history(True)).pack(side='left',expand=True,fill='x')
        ttk.Button(row,text='清空标记',width=1,command=self.clear).pack(side='left',expand=True,fill='x')
        correction=disclosure(body,'需要时：排除与细节修正')
        ttk.Radiobutton(correction,text='标记排除区域',variable=self.mode,value='exclude',command=self.enable_marks).pack(anchor='w')
        ttk.Label(correction,text='绿色保留，红色排除；其余区域未知。相连的多人可补涂排除。',wraplength=225,foreground=MUTED).pack(fill='x',pady=6)
        ttk.Button(correction,text='高级蒙版修正…',command=self.advanced).pack(fill='x')
        settings=disclosure(body,'动态范围与输出')
        ttk.Label(settings,text='处理当前选段，未选段时处理完整动画。移动主体用现有光流跟随；出画或遮挡不稳定时停止，不应用不完整结果。',wraplength=225,foreground=MUTED).pack(fill='x')
        ttk.Label(settings,text='动态处理最长边（0 为原尺寸）').pack(anchor='w',pady=(8,0))
        ttk.Combobox(settings,textvariable=self.edge,values=('256','384','512','0'),width=10).pack(fill='x')
        self.note=ttk.Label(body,text='先选中图片或 GIF 图层。',wraplength=230,foreground=MUTED);self.note.pack(fill='x',pady=12)
        actions.columnconfigure((0,1),weight=1,uniform='cutout-actions')
        self.button=ttk.Button(actions,text='按标记处理',width=1,command=self.start);self.button.grid(row=0,column=1,sticky='ew',padx=(3,0))
        self.apply_button=ttk.Button(actions,text='应用结果',command=self.apply)
        from xp_progress import XPProgress
        self.stop=ttk.Button(actions,text='取消处理',command=self.stop_processing);self.bar=XPProgress(actions,e,maximum=100)
        # Reserve the changing action row. Packing new controls into this
        # bottom-anchored panel moved Start under a second click in the embedded
        # desktop layout, which could accidentally hit Cancel instead.
        actions.rowconfigure(1,minsize=max(self.apply_button.winfo_reqheight(),self.stop.winfo_reqheight())+8)
        actions.rowconfigure(2,minsize=68)
        self.bar.grid(row=2,column=0,columnspan=2,sticky='ew')
        self.apply_button.grid(row=1,column=0,columnspan=2,sticky='ew');self.apply_button.grid_remove()
        self.stop.grid(row=1,column=0,columnspan=2,sticky='ew');self.stop.grid_remove()
        ttk.Button(actions,text='返回选择工具',command=e.select_tool).grid(row=3,column=0,columnspan=2,sticky='ew',pady=(6,0))
        scroll.attach();self.page.bind('<Destroy>',self.destroyed,add='+');self.poll_id=self.page.after(60,self.poll)
        for variable in (self.model,self.edge):variable.trace_add('write',self.settings_changed)
        e.canvas.bind('<Leave>',lambda _:e.canvas.delete('subject-brush'),add='+')

    def layer(self):
        e=self.editor
        if not e.doc:return None
        return next((l for l in e.doc.layers if l['id']==e.selected_layer and l['kind']=='sticker'),None)

    def settings_changed(self,*_):
        if self.loading_target:return
        if self.pending:
            self.pending=None;self.apply_button.grid_remove();self.editor.reflow()
        self.note.configure(text='设置已更新；点击开始/重新处理才会计算。')

    def target_changed(self):
        e=self.editor
        if self.target_doc is not e.doc:
            self.target_states={};self.target=None;self.pending=None;self.target_doc=e.doc
        target=e.selected_layer
        if target==self.target:
            self.sync_actions();return
        if self.target:
            self.target_states[self.target]={'model':self.model.get(),'edge':self.edge.get(),'radius':self.radius.get(),
                'pending':self.pending,'note':self.note.cget('text')}
        self.target=target;self.stroke=None;self.overlay_key=None
        state=self.target_states.get(target,{})
        self.loading_target=True
        try:
            self.model.set(state.get('model',next(iter(MODELS))));self.edge.set(state.get('edge','384'));self.radius.set(state.get('radius',24))
        finally:self.loading_target=False
        self.pending=state.get('pending')
        self.note.configure(text=state.get('note','可自动抠主体，或标记后点击开始。') if self.layer() else '请选择图片或 GIF 图层；当前工具保持不变。')
        self.sync_actions();self.draw()

    def sync_actions(self):
        layer=self.layer();enabled=bool(layer and not layer.get('locked') and not self.editor.busy and not self.active)
        for button in (self.button,self.auto_button):button.state(['!disabled'] if enabled else ['disabled'])
        self.apply_button.grid_remove()

    def prompt(self,layer):
        e=self.editor;animation=layer.get('animation');index=layer_frame_index(layer,e.doc.animation,e.animation_frame) if animation else 0
        old=layer.get('subject_marks',{})
        # A new reference frame has separate marks. The old prompt remains in
        # the layer/draft until the user actually draws a new stroke.
        if old.get('frame')==index:return copy.deepcopy(old)
        return {'frame':index,'time_ms':sum(animation.durations[:index]) if animation else 0,'source_size':list(layer['image'].size),'strokes':[]}

    def activate(self):
        e=self.editor
        if e.busy or not e.finish_text():return
        e.set_tool('cutout');e.subject_selection.deactivate();e.raster.active=False;e.crop_mode=False;e.hand_mode=False
        e.show_property(self.page);self.deactivate();e.playing=False;e.canvas.focus_set();e.set_cursor('arrow')
        self.target_changed()
        self.note.configure(text='可直接选层、拖动；点自动抠主体，或明确选择标记工具。' if self.layer() else '请先选中图片或 GIF 图层。')
        self.draw()

    def enable_marks(self):
        if self.editor.busy:return
        self.editor.set_tool('cutout');self.marking=True;self.stroke=None
        self.note.configure(text='在主体内部涂几笔，然后点击开始；涂抹本身不计算。');self.draw()

    def deactivate(self):
        self.marking=False;self.mode.set('');self.stroke=None;self.overlay_key=None
        if self.draw_id:
            self.page.after_cancel(self.draw_id);self.draw_id=None
        self.editor.canvas.delete('subject-marks','subject-brush')

    def advanced(self):
        self.deactivate();self.editor.subject_selection.activate()

    def brush(self,mode):
        self.deactivate();self.editor.raster.mode.set(mode);self.editor.raster.activate()

    def original(self,value):self.show_original=value;self.editor.reflow()

    def press(self,event):
        layer=self.layer();e=self.editor
        if not layer or e.busy or layer.get('locked'):return
        p=e.point(event);r=float(self.radius.get())/2/e.scale
        center,u,v=source_points(layer,[p,(p[0]+r,p[1]),(p[0],p[1]+r)])
        w,h=layer['image'].size
        if not (0<=center[0]<w and 0<=center[1]<h):return
        self.stroke={'mode':self.mode.get(),'points':[(center[0]/w,center[1]/h)],'basis':[[(u[0]-center[0])/w,(u[1]-center[1])/h],[(v[0]-center[0])/w,(v[1]-center[1])/h]]}
        self.stroke_target=(layer['id'],self.prompt(layer)['frame']);e.canvas.focus_set();self.draw()

    def motion(self,event):
        self.hover(event)
        if not self.stroke:return
        layer=self.layer()
        if not layer or (layer['id'],self.prompt(layer)['frame'])!=self.stroke_target:self.stroke=None;return
        w,h=layer['image'].size;x,y=source_points(layer,[self.editor.point(event)])[0];p=(max(0,min(1,x/w)),max(0,min(1,y/h)))
        old=self.stroke['points'][-1];distance=math.hypot((p[0]-old[0])*w,(p[1]-old[1])*h)
        if distance<max(.5,math.hypot(*self.stroke['basis'][0])*min(w,h)/4):return
        self.stroke['points'].append(p);self.schedule_draw()

    def release(self,event):
        if not self.stroke:return
        self.motion(event);layer=self.layer()
        if layer and self.stroke:
            prompt=self.prompt(layer);prompt['strokes'].append(self.stroke);self.commit_marks(layer,prompt)
        self.stroke=None;self.draw()

    def commit_marks(self,layer,prompt):
        e=self.editor
        e.doc._commit(operation='主体标记',layers=[dict(l,subject_marks=prompt) if l['id']==layer['id'] else l for l in e.doc.layers])
        self.pending=None;self.apply_button.grid_remove();e.preserve_playhead=e.play_elapsed
        e.undo_button.state(['!disabled']);e.redo_button.state(['disabled']);e.status.set('标记已更新，尚未计算；点击开始抠主体。')
        e.save_state={'state':'dirty','text':'标记有未保存修改','revision':e.doc.revision}
        self.note.configure(text='标记已保留，尚未计算；点击开始/重新处理。')
        self.button.configure(text='重新处理' if layer.get('cutout_prompt_digest') else '开始抠主体');self.overlay_key=None

    def clear(self):
        layer=self.layer()
        if not layer or self.active:return
        prompt=self.prompt(layer);prompt['strokes']=[];self.commit_marks(layer,prompt);self.draw()

    def history(self,redo):
        e=self.editor
        if not e.doc or self.active:return
        states=e.doc._redo if redo else e.doc._undo
        if not states:return
        operation=states[-1].operations[-1] if redo and states[-1].operations else e.doc.operations[-1] if e.doc.operations else ''
        if operation!='主体标记':self.note.configure(text='没有可撤销/重做的标记；作品操作使用顶部撤销。');return
        (e.doc.redo if redo else e.doc.undo)();self.pending=None;self.apply_button.grid_remove();self.overlay_key=None;self.draw();e.changed('已恢复标记')

    def hover(self,event):
        e=self.editor;e.set_cursor('crosshair');r=float(self.radius.get())/2
        e.canvas.delete('subject-brush');e.canvas.create_oval(event.x-r,event.y-r,event.x+r,event.y+r,outline='white',width=1,tags='subject-brush')

    def draw(self):
        if self.draw_id:
            self.page.after_cancel(self.draw_id);self.draw_id=None
        e=self.editor;layer=self.layer()
        if not self.marking or not layer:e.canvas.delete('subject-marks');return
        prompt=self.prompt(layer);strokes=prompt['strokes']+([self.stroke] if self.stroke else [])
        size=(max(1,e.canvas.winfo_width()),max(1,e.canvas.winfo_height()))
        key=(digest(strokes),repr((layer['position'],layer['size'],layer.get('rotation'),layer.get('flip_h'),layer.get('flip_v'),layer.get('fit'))),e.origin,e.scale,size)
        if key==self.overlay_key and e.canvas.find_withtag('subject-marks'):
            e.canvas.tag_raise('subject-marks');e.canvas.tag_raise('subject-brush');return
        self.overlay_key=key;overlay=Image.new('RGBA',size);draw=ImageDraw.Draw(overlay)
        for stroke in strokes:
            u,v=stroke['basis'];rim=[(math.cos(a)*u[0]+math.sin(a)*v[0],math.cos(a)*u[1]+math.sin(a)*v[1]) for a in [i*math.tau/16 for i in range(16)]]
            color={'keep':(65,220,145,100),'exclude':(255,80,100,110),'erase':(0,0,0,0)}[stroke['mode']];previous=None
            for point in stroke['points']:
                poly=document_points(layer,[(point[0]+x,point[1]+y) for x,y in rim]);poly=[(e.origin[0]+x*e.scale,e.origin[1]+y*e.scale) for x,y in poly]
                draw.polygon(poly,fill=color)
                if previous:
                    for i in range(16):draw.polygon([previous[i],poly[i],poly[(i+1)%16],previous[(i+1)%16]],fill=color)
                previous=poly
        self.photo=ImageTk.PhotoImage(overlay);e.canvas.delete('subject-marks');e.canvas.create_image(0,0,anchor='nw',image=self.photo,tags='subject-marks');e.canvas.tag_raise('subject-brush')

    def schedule_draw(self):
        # Merge pointer paints only. This never schedules model inference.
        if self.draw_id is None:self.draw_id=self.page.after(16,self.draw)

    def start(self):return self.submit(False)
    def start_auto(self):return self.submit(True)

    def refresh_model_status(self,*_):
        from emoji_bridge.background_remove import model_present
        name=MODELS.get(self.model.get(),'u2net')
        self.model_status.configure(text='已找到本地模型，处理时会校验。' if model_present(name) else '所选模型需下载（约 168–214 MB），下载并导入后可离线使用。')

    def download_model(self):
        import webbrowser
        from emoji_bridge.background_remove import model_url
        webbrowser.open(model_url(MODELS[self.model.get()]))

    def import_model(self):
        e=self.editor
        if e.busy or self.active:return
        from tkinter import filedialog
        from emoji_bridge.background_remove import import_model
        label=self.model.get();model=MODELS[label]
        source=filedialog.askopenfilename(parent=e.window,title='导入 '+label,filetypes=[('模型文件或配套模型包','*.onnx *.zip')])
        if not source:return
        self.cancel.clear()
        def progress(stage,n=0,total=0):self.events.put(('progress',stage,n,total))
        def work():
            try:
                import_model(source,name=model,cancel=self.cancel,progress=progress)
                return {'cutout_model_ready':label}
            except Exception as exc:self.events.put(('error',str(exc)));raise
        self.active=True;self.stop.grid(row=1,column=0,sticky='ew',pady=4)
        if not e.submit(work,'导入离线模型',xp=self.bar):self.settled()
        self.sync_actions()

    def submit(self,automatic):
        e=self.editor;layer=self.layer()
        if e.closed or e.busy or self.active or not layer:return False
        if self.pending and self.valid(self.pending[0]):return False
        if layer.get('locked'):self.note.configure(text='该图层已锁定，请先解锁。');return False
        if not e.finish_text():return False
        prompt=self.prompt(layer);animation=layer.get('animation')
        from emoji_bridge.subject_marks import rasterize
        if not automatic and rasterize(prompt['strokes'],(256,256)).histogram()[1]==0:self.note.configure(text='请先在想保留的主体上涂几笔。');return False
        try:edge=int(self.edge.get());model=MODELS[self.model.get()]
        except (ValueError,KeyError):self.note.configure(text='请选择模型，动态尺寸请输入整数。');return False
        if edge<0:self.note.configure(text='尺寸须为正数，0 表示原尺寸。');return False
        count=len(animation.frames) if animation else 1;start,end=0,count
        if animation and e.doc.time_range:
            start=animation.frame_at(e.doc.time_range[0])[0];end=animation.frame_at(e.doc.time_range[1]-1)[0]+1
            cycle=sum(animation.durations)
            if e.doc.time_range[1]-e.doc.time_range[0]>=cycle or end<=start:
                # A short looping layer can cross its source cycle inside the
                # composition selection. Process its source frames once; do not
                # alter the composition's preview or export selection.
                start,end=0,count
        prompt['range']=[start,end];prompt['selection_ms']=list(e.doc.time_range) if e.doc.time_range else None
        if not start<=prompt['frame']<end:self.note.configure(text='请把播放头移到所选区间，再标记主体。');return False
        token={'doc':e.doc,'revision':e.doc.revision,'layer':layer['id'],'model':self.model.get(),'edge':self.edge.get(),'prompt':copy.deepcopy(prompt),'playhead':e.play_elapsed}
        self.cancel.clear();self.active=True;self.pending=None;self.apply_button.grid_remove();self.button.state(['disabled']);self.stop.grid(row=1,column=0,sticky='ew',pady=4);self.bar.grid(row=2,column=0,sticky='ew');self.bar.configure(mode='indeterminate');self.bar.start(12)
        def progress(stage,n=0,total=0):self.events.put(('progress',stage,n,total))
        def work():
            try:
                if automatic:
                    from emoji_bridge.background_remove import remove_background
                    from emoji_bridge.dynamic_cutout import cutout_animation
                    if animation:
                        value=cutout_animation(animation,max_edge=edge,cancel=self.cancel,progress=progress,model_name=model)
                        changed=dict(layer,animation=value['animation'],image=value['animation'].frames[0]);changed.pop('mask',None)
                    else:
                        image,_=frame_data(layer,0);value=remove_background(image,cancel=self.cancel,progress=progress,model_name=model);changed=dict(layer,mask=value['mask'])
                    value={**value,'layer':changed}
                else:
                    from emoji_bridge.scribble_cutout import process
                    value=process(layer,prompt,model,max_edge=edge,cancel=self.cancel,progress=progress)
                return {'scribble_result':(token,value)}
            except Exception as exc:self.events.put(('error',str(exc)));raise
        if not e.submit(work,'自动整图抠主体' if automatic else '按标记抠主体',xp=self.bar):
            self.settled();return False
        self.submissions+=1
        self.sync_actions()
        # The UI counter is also exposed to the desktop acceptance probe.
        self.note.configure(text='正在处理；原件与标记保留，可取消。')
        return True

    def valid(self,token):
        e=self.editor
        state={'model':self.model.get(),'edge':self.edge.get()} if self.target==token['layer'] else self.target_states.get(token['layer'],{})
        return not self.cancel.is_set() and not e.closed and e.doc is token['doc'] and e.doc.revision==token['revision'] and state.get('model')==token['model'] and state.get('edge')==token['edge']

    def ready(self,token,result):
        self.settled()
        if not self.valid(token):self.note.configure(text='作品或设置已改变，旧结果未覆盖；可以重新处理。');return
        self.pending=(token,result);self.button.configure(text='重新处理')
        self.apply()
        self.note.configure(text='已应用到处理的图层，可撤销。补涂后点击重新处理。')

    def preview_layer(self,layer):
        if self.pending and layer['id']==self.pending[0]['layer'] and self.valid(self.pending[0]):return self.pending[1]['layer']
        return layer

    def apply(self):
        if not self.pending:return
        token,result=self.pending;e=self.editor
        if not self.valid(token):self.pending=None;self.apply_button.grid_remove();self.note.configure(text='作品已改变，请重新处理。');return
        e.preserve_playhead=token['playhead'];e.playing=False
        e.doc.replace_scene(e.doc._state.base,[result['layer'] if l['id']==token['layer'] else l for l in e.doc.layers],e.doc.source_ids,'应用抠主体')
        self.pending=None;self.apply_button.grid_remove();self.deactivate();e.set_cursor('arrow');e.changed('已应用透明主体，可撤销或保存为素材');e.paint(None,e.doc.size)

    def settled(self):
        self.refresh_model_status()
        self.active=False;self.bar.stop();self.stop.grid_remove();self.sync_actions()

    def stop_processing(self):
        self.cancel.set();self.note.configure(text='已请求取消，正在收尾；原图和标记保留。');self.editor.status.set('正在取消抠主体')

    def destroyed(self,event):
        if event.widget is self.page:
            self.cancel.set()
            try:self.page.after_cancel(self.poll_id)
            except tk.TclError:pass
            if self.draw_id:
                try:self.page.after_cancel(self.draw_id)
                except tk.TclError:pass

    def poll(self):
        if self.editor.closed:return
        try:
            while True:
                event=self.events.get_nowait()
                if event[0]=='error':self.settled();self.note.configure(text=event[1]+'；可继续标记后重新处理。')
                elif not self.cancel.is_set():
                    self.note.configure(text=event[1])
                    if event[3]:self.bar.stop();self.bar.configure(mode='determinate',value=event[2]/event[3]*100)
        except queue.Empty:pass
        self.poll_id=self.page.after(60,self.poll)
