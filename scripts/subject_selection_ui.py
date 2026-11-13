"""In-canvas rectangle/lasso/polygon/prompts with optional OpenCV segmentation."""
import json,threading,uuid
from copy import copy
import tkinter as tk
from tkinter import ttk
from PIL import Image
from emoji_bridge.subject_selection import edit_polygon,frame_data,source_points,commit_masks
from emoji_bridge.animated_edit import layer_frame_index
from ui_style import ScrollBody,MUTED,disclosure


class SubjectSelection:
    def __init__(self,e):
        self.e=e;self.active=False;self.points=[];self.cancel=threading.Event();self.prompts=[]
        self.page=ttk.Frame(e.tabs,padding=12);e.tabs.add(self.page,text='主体修正')
        scroll=ScrollBody(self.page);scroll.pack(fill='both',expand=True);body=scroll.body
        ttk.Label(body,text='选区工具',style='Heading.TLabel').pack(anchor='w',pady=(0,12))
        self.mode=tk.StringVar(value='自由套索');self.keep=tk.BooleanVar(value=True);self.inverse=tk.BooleanVar()
        modes=ttk.Frame(body);modes.pack(fill='x')
        self.tool_buttons={}
        for i,(name,title) in enumerate((('框选识别','□ 框选'),('自由套索','⌁ 套索'),('多边形','◇ 多边形'),('保留点 +','+ 保留点'),('排除点 −','− 排除点'))):
            button=ttk.Button(modes,text=title,width=9,style='Editor.Tool.TButton',command=lambda n=name:(self.mode.set(n),self.activate()))
            button.grid(row=i//2,column=i%2,sticky='ew',padx=2,pady=3);self.tool_buttons[name]=button
        self.mode.trace_add('write',lambda *_:self.sync_tool())
        self.sync_tool()
        modes.columnconfigure((0,1),weight=1)
        ttk.Button(body,text='细节画笔',command=lambda:(self.deactivate(),e.cutout.brush('保留主体'))).pack(fill='x',pady=8)
        ttk.Button(body,text='涂抹标记抠主体…',command=lambda:e.cutout.activate()).pack(fill='x',pady=(0,8))
        ttk.Label(body,text='套索松开闭合；多边形回车确认。\n退格撤点，Esc 清除当前选区。',wraplength=218,style='Muted.TLabel').pack(fill='x',pady=8)
        ttk.Button(body,text='选择对象',command=lambda:(self.deactivate(),e.select_tool())).pack(fill='x',pady=8)
        self.params=self.page
        actions=ttk.Frame(self.params);actions.pack(side='bottom',fill='x',pady=(8,0))
        self.apply_button=ttk.Button(actions,text='应用选区 / 提示',command=self.finish,style='Editor.Primary.TButton');self.apply_button.pack(fill='x',pady=(0,6))
        self.propagate_button=ttk.Button(actions,text='传播修正',command=self.propagate);self.propagate_button.pack(fill='x',pady=(0,6))
        ttk.Button(actions,text='取消处理',command=self.cancel.set).pack(fill='x')
        params_scroll=scroll;params=body
        ttk.Label(params,text='主体选区',style='Heading.TLabel').pack(anchor='w',pady=(0,12))
        ttk.Label(params,text='选区作用').pack(anchor='w')
        row=ttk.Frame(params);row.pack(fill='x',pady=8)
        ttk.Radiobutton(row,text='保留',variable=self.keep,value=True).pack(side='left');ttk.Radiobutton(row,text='排除',variable=self.keep,value=False).pack(side='left',padx=12)
        ttk.Checkbutton(params,text='反选闭合区域',variable=self.inverse).pack(anchor='w')
        ttk.Label(params,text='处理范围').pack(anchor='w',pady=(16,6))
        self.scope=tk.StringVar(value='当前帧');ttk.Combobox(params,textvariable=self.scope,values=('当前帧','选定区间','向后传播','向前传播','前后传播'),state='readonly').pack(fill='x')
        self.view=tk.StringVar(value='结果')
        self.viewbar=ttk.Frame(e.canvas,padding=4)
        view_button=ttk.Menubutton(self.viewbar,text='检查视图 ▾',width=12);view_button.pack()
        view_menu=tk.Menu(view_button,tearoff=False);view_button.configure(menu=view_menu)
        for title in ('结果','原图','蒙版覆盖','黑底','白底'):
            view_menu.add_radiobutton(label=title,variable=self.view,value=title)
        view_menu.add_separator();view_menu.add_command(label='仅检查预览，不改变作品背景',state='disabled')
        self.view.trace_add('write',lambda *_:self.refresh_view())
        self.note=tk.StringVar(value='先选中图片或 GIF 图层，再绘制选区。')
        ttk.Label(params,textvariable=self.note,wraplength=218,foreground=MUTED).pack(fill='x',pady=12)
        model=disclosure(params,'识别方式与组件')
        from emoji_bridge.subject_model import ready
        self.engine=tk.StringVar(value='SAM2 主体识别' if ready() else '轮廓识别 / 光流')
        ttk.Combobox(model,textvariable=self.engine,values=('SAM2 主体识别','轮廓识别 / 光流'),state='readonly').pack(fill='x',pady=6)
        ttk.Button(model,text='准备 SAM2（可选）',command=self.prepare_model).pack(fill='x')
        scroll.attach();params_scroll.attach()
        for event,handler in [('<Return>',self.enter),('<BackSpace>',self.back),('<Escape>',self.escape),('<Double-Button-1>',self.enter)]:e.canvas.bind(event,handler,add='+')

    def sync_tool(self):
        for name,button in self.tool_buttons.items():button.state(['selected'] if self.mode.get()==name else ['!selected'])

    def activate(self):
        e=self.e
        if not e.doc:return
        e.show_property(self.params)
        layer=next((l for l in e.doc.layers if l['id']==e.selected_layer and l['kind']=='sticker'),None)
        if not layer:
            self.deactivate();self.note.set('先在画布或图层列表选中图片 / GIF，再选择左侧工具。');e.status.set('主体修正需要选中图片或 GIF 图层');return
        e.animation_effects.hide();e.dropped_item.hide() if e.dropped_item.active else None
        frame=self.index(layer)
        if not self.active or getattr(self,'prompt_layer',None)!=layer['id'] or getattr(self,'prompt_frame',None)!=frame:
            self.points=[];self.prompts=[]
        self.prompt_layer=layer['id'];self.prompt_frame=frame
        e.playing=False;e.raster.active=False;self.active=True
        self.viewbar.place(relx=1,x=-12,y=12,anchor='ne');self.viewbar.lift()
        self.note.set('目标：图层 '+str(next(i+1 for i,l in enumerate(e.doc.layers) if l['id']==layer['id']))+' · 当前第 '+str(frame+1)+' 帧')
        e.canvas.focus_set();e.set_cursor('crosshair')

    def deactivate(self):
        self.active=False;self.points=[];self.e.canvas.delete('subject-selection')
        self.viewbar.place_forget()
        if hasattr(self.e,'cutout'):self.e.cutout.show_original=False

    def prepare_model(self):
        e=self.e
        def work():
            from emoji_bridge.subject_model import prepare
            prepare(e.save_cancel,lambda stage,*_:e.events.put(('progress',stage)))
            return {'subject_model_ready':True}
        e.submit(work,'准备可选主体模型')

    def index(self,layer):return layer_frame_index(layer,self.e.doc.animation,self.e.animation_frame) if layer.get('animation') else 0

    def press(self,event):
        self.e.canvas.focus_set();p=self.e.point(event)
        frame=self.index(self.e.doc._find(self.e.selected_layer))
        if frame!=getattr(self,'prompt_frame',None):self.points=[];self.prompts=[];self.prompt_frame=frame
        if self.mode.get()=='多边形':self.points.append(p)
        elif self.mode.get() in ('保留点 +','排除点 −'):
            self.prompts.append({'point':p,'keep':self.mode.get()=='保留点 +'});self.points=[]
        else:self.points=[p]
        self.draw()

    def motion(self,event):
        if self.mode.get()=='自由套索' and self.points:self.points.append(self.e.point(event))
        elif self.mode.get()=='框选识别' and self.points:self.points=self.points[:1]+[self.e.point(event)]
        self.draw()

    def release(self,event):
        if self.mode.get() in ('自由套索','框选识别') and self.points:self.motion(event);self.finish()

    def draw(self):
        c=self.e.canvas;c.delete('subject-selection');o=self.e.origin;s=self.e.scale
        xy=[v for x,y in self.points for v in (o[0]+x*s,o[1]+y*s)]
        if len(xy)>=4:
            if self.mode.get()=='框选识别':c.create_rectangle(*xy[:4],outline='#a9adc3',width=2,tags='subject-selection')
            else:c.create_line(*xy,fill='#a9adc3',width=2,tags='subject-selection')
        for prompt in self.prompts:
            x,y=prompt['point'];c.create_text(o[0]+x*s,o[1]+y*s,text='+' if prompt['keep'] else '−',fill='#ffffff' if prompt['keep'] else '#ffb6b4',font=('Segoe UI',18,'bold'),tags='subject-selection')

    def enter(self,event=None):
        if self.active:self.finish();return 'break'
    def back(self,event=None):
        if self.active:
            if self.points:self.points.pop()
            self.draw();return 'break'
    def escape(self,event=None):
        if self.active:self.points=[];self.prompts=[];self.draw();return 'break'

    def finish(self):
        e=self.e
        if not self.active or e.busy:return
        if self.mode.get() in ('框选识别','保留点 +','排除点 −'):self.segment();return
        try:
            index=edit_polygon(e.doc,e.selected_layer,self.points,keep=self.keep.get(),invert=self.inverse.get(),animation_frame=e.animation_frame)
            e.preserve_playhead=e.play_elapsed;self.points=[];e.changed('已修正当前帧');e.paint(None,e.doc.size);self.note.set(f'第 {index+1} 帧已修正。可撤销；传播会跟随画面运动，异常处停止。')
        except ValueError as exc:self.note.set(str(exc))

    def refresh_view(self):
        self.e.cutout.show_original=self.view.get()=='原图';self.e.reflow()

    def segment(self):self.run(False)
    def propagate(self):self.run(True)

    def run(self,propagate):
        e=self.e
        if not self.active or e.busy:return
        layer=dict(e.doc._find(e.selected_layer));index=self.index(layer);revision=e.doc.revision
        if propagate and (not layer.get('animation') or self.scope.get()=='当前帧'):
            self.note.set('当前帧已保留。选择传播方向或区间后再执行。');return
        points=source_points(layer,self.points);prompts=[{'point':source_points(layer,[p['point']])[0],'keep':p['keep']} for p in self.prompts]
        if not propagate and len(points)<2 and not prompts:self.note.set('先框住主体，或添加保留 / 排除点。');return
        scope=self.scope.get();doc_range=e.doc.time_range;engine=self.engine.get();self.cancel.clear()
        def work():
            from emoji_bridge.capabilities import worker
            from emoji_bridge.frame_store import cancelled
            folder=e.store.root/'subject-repair'/uuid.uuid4().hex;folder.mkdir(parents=True)
            animation=layer.get('animation');count=len(animation.frames) if animation else 1
            start,end=0,count-1
            if scope=='选定区间' and doc_range:
                start=animation.frame_at(doc_range[0])[0];end=animation.frame_at(max(doc_range[0],doc_range[1]-1))[0]
            if scope=='向后传播':start=index
            if scope=='向前传播':end=index
            frame_indices=list(range(start,end+1)) if propagate else [index]
            if index not in frame_indices:raise ValueError('当前帧不在传播选区内')
            if engine=='SAM2 主体识别' and len(frame_indices)>180:raise ValueError('SAM2 首版一次最多传播180帧；请用时间轴缩小区间，原素材不会截短')
            frames=[];masks=[]
            for i in frame_indices:
                cancelled(self.cancel);image,mask=frame_data(layer,i);image.save(folder/f'{i}.png');mask.save(folder/f'{i}-mask.png');frames.append(str(folder/f'{i}.png'));masks.append(str(folder/f'{i}-mask.png'))
            request={'action':'propagate' if propagate else 'segment','result':str(folder/'result.json'),'frames':frames,'masks':masks,'indices':frame_indices,'anchor':index,'points':prompts,'box':points,'keyframes':sorted({p['frame'] for p in layer.get('mask_edits',[]) if p.get('kind')!='propagation'})}
            def progress(stage,*_):
                try:
                    data=json.loads((folder/'progress.json').read_text('utf8'));text=f"主体修正 {data['done']} / {data['total']} · 第 {data['frame']+1} 帧"
                except (OSError,ValueError):text=stage
                e.events.put(('progress',text))
            if engine=='SAM2 主体识别':
                from emoji_bridge.subject_model import execute
                execute(request,folder,self.cancel,progress)
            else:worker('vision','subject_vision_worker.py',request,folder,self.cancel,progress)
            result=json.loads((folder/'result.json').read_text('utf8'));changed={}
            for i,file in result['masks'].items():
                with Image.open(file) as image:changed[int(i)]=image.convert('L')
            cancelled(self.cancel)
            if e.closed or e.doc.revision!=revision:raise InterruptedError('作品已改变，未覆盖新修改')
            commit_masks(e.doc,layer['id'],changed,{'frame':index,'kind':'propagation' if propagate else 'segmentation','points':prompts,'box':points,'range':[start,end],'algorithm':result['algorithm'],'stopped':result.get('stopped',[])})
            return {'subject_repair':result,'subject_playhead':e.play_elapsed}
        e.submit(work,'传播主体修正' if propagate else '识别选中的主体')
