"""Guided recognition and bounded tracking on immutable editor snapshots."""
from uuid import uuid4
from copy import copy
from concurrent.futures import CancelledError
import json,tkinter as tk
from tkinter import ttk
from PIL import Image
from ui_style import ScrollBody,text_field
from ui_dpi import px,spacing
from editor_controls import ParameterBar
from emoji_bridge.capabilities import worker
from emoji_bridge.text_animation import STYLES,BUBBLES
from emoji_bridge.animated_edit import check_cancel

class Intelligence:
    def __init__(self,editor):
        self.e=editor;self.box=None;self.running=False
        self.page=ttk.Frame(editor.tabs,padding=px(editor.window,12));editor.tabs.add(self.page,text='动态文字')
        ttk.Button(self.page,text='应用到选中文字',command=self.motion,style='Editor.Primary.TButton').pack(side='bottom',fill='x',pady=spacing(editor.window,(8,0)))
        scroll=ScrollBody(self.page);scroll.pack(fill='both',expand=True);body=scroll.body
        ttk.Label(body,text='动态文字',style='Heading.TLabel').pack(anchor='w');self.style=tk.StringVar(value='弹入');self.bubble=tk.StringVar(value='无气泡')
        for var,values in [(self.style,list(STYLES.values())),(self.bubble,list(BUBBLES.values()))]:ttk.Combobox(body,textvariable=var,values=values,state='readonly').pack(fill='x',pady=px(editor.window,5))
        self.start=tk.IntVar(value=0);self.end=tk.IntVar(value=2000);self.stroke=tk.IntVar(value=1)
        self.time_bars=[]
        for title,var,high,step,unit in [('出现时间',self.start,10000,50,' 毫秒'),('结束时间',self.end,10000,50,' 毫秒'),('文字描边',self.stroke,20,1,' px')]:
            bar=ParameterBar(body,title,var,0,high,step=step,suffix=unit,input_high=1800000 if unit==' 毫秒' else high);bar.pack(fill='x',pady=px(editor.window,9))
            if unit==' 毫秒':self.time_bars.append(bar)
        scroll.attach()
        self.vision_page=ttk.Frame(editor.tabs,padding=px(editor.window,12));editor.tabs.add(self.vision_page,text='识字 / 跟随')
        self.note=tk.StringVar(value='在当前画面识别文字，或让文字、贴纸跟随移动的主体。')
        self.cancel_button=ttk.Button(self.vision_page,text='取消处理',command=editor.cancel_processing)
        ttk.Label(self.vision_page,textvariable=self.note,wraplength=px(editor.window,230),style='Muted.TLabel').pack(side='bottom',fill='x',pady=px(editor.window,8))
        actions=ttk.Frame(self.vision_page);actions.pack(side='bottom',fill='x',pady=px(editor.window,5))
        self.main_button=ttk.Button(actions,style='Editor.Primary.TButton');self.main_button.pack(side='left',fill='x',expand=True)
        self.correct_button=ttk.Button(actions,text='校正当前帧',command=lambda:self.track_region(True))
        scroll=ScrollBody(self.vision_page);scroll.pack(fill='both',expand=True);body=scroll.body
        self.mode=tk.StringVar(value='识别文字');switch=ttk.Frame(body);switch.pack(fill='x',pady=spacing(editor.window,(0,12)))
        for title in ('识别文字','跟随主体'):
            ttk.Radiobutton(switch,text=title,value=title,variable=self.mode,command=self.show_mode,style='Editor.Tool.TButton').pack(side='left',fill='x',expand=True)
        self.region=tk.StringVar(value='范围：完整画面')
        ttk.Label(body,textvariable=self.region,wraplength=px(editor.window,230),style='Muted.TLabel').pack(fill='x',pady=px(editor.window,6))
        row=ttk.Frame(body);row.pack(fill='x')
        ttk.Button(row,text='框选范围',command=self.select_region).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='清除范围',command=self.clear_region).pack(side='right',padx=px(editor.window,4))
        self.ocr_body=ttk.Frame(body);self.track_body=ttk.Frame(body)
        ttk.Label(self.ocr_body,text='把图片里的字变成可编辑文字',wraplength=px(editor.window,230)).pack(fill='x',pady=px(editor.window,12))
        box,self.text=text_field(self.ocr_body,height=6,width=20,wrap='word');box.pack(fill='x',pady=px(editor.window,10))
        row=ttk.Frame(self.ocr_body);row.pack(fill='x')
        ttk.Button(row,text='复制文字',command=self.copy_text).pack(side='left')
        ttk.Button(row,text='加入文字层',command=self.add_text).pack(side='right')
        ttk.Label(self.track_body,text='先选中要跟随的文字或贴纸，再框住画面里移动的主体。',wraplength=px(editor.window,230)).pack(fill='x',pady=px(editor.window,12))
        self.target=tk.StringVar();ttk.Label(self.track_body,textvariable=self.target,wraplength=px(editor.window,230),style='Muted.TLabel').pack(fill='x')
        self.track_seconds=tk.DoubleVar(value=5)
        ParameterBar(self.track_body,'从当前帧开始跟随',self.track_seconds,.5,60,step=.5,suffix=' 秒').pack(fill='x',pady=px(editor.window,12))
        ttk.Label(self.track_body,text='每次最多处理 60 秒。播放检查效果；跟丢时暂停、重新框选，再点校正。',wraplength=px(editor.window,230),style='Muted.TLabel').pack(fill='x',pady=px(editor.window,8))
        self.show_mode();scroll.attach()

    def show_mode(self):
        self.ocr_body.pack_forget();self.track_body.pack_forget()
        (self.ocr_body if self.mode.get()=='识别文字' else self.track_body).pack(fill='x')
        self.correct_button.pack_forget()
        self.main_button.configure(text='识别当前画面的文字' if self.mode.get()=='识别文字' else '开始跟随',command=self.ocr if self.mode.get()=='识别文字' else self.track_region)
        if self.mode.get()!='识别文字':self.correct_button.pack(side='right',padx=spacing(self.e.window,(5,0)))
        self.target.set('跟随图层：'+self.target_name())

    def target_name(self):
        e=self.e
        if not e.doc or not e.selected_layer:return '请先选择文字或贴纸'
        layer=e.doc._find(e.selected_layer)
        return str(layer.get('text','贴纸 / 动图'))[:24] if layer['kind']=='text' else '已选贴纸 / 动图'

    def open_section(self,section):
        self.e.show_property(self.page if section=='text' else self.vision_page)
        if section=='text':
            duration=sum(self.e.doc.animation.durations) if self.e.doc and self.e.doc.animation else 10000
            for bar in self.time_bars:bar.limits(0,min(1800000,max(10000,duration,self.end.get())))
        self.target.set('跟随图层：'+self.target_name())
        if section=='text' and (not self.e.selected_layer or self.e.doc._find(self.e.selected_layer)['kind']!='text'):
            self.e.status.set('先添加或选中文字，再设置动态文字。')

    def motion(self):
        e=self.e
        try:
            if not e.selected_layer or e.doc._find(e.selected_layer)['kind']!='text':raise ValueError('请先选中文字图层')
            start,end=self.start.get(),self.end.get()
            if not 0<=start<end<=1800000:raise ValueError('结束时间需要晚于出现时间。')
            motion={'style':next(k for k,v in STYLES.items() if v==self.style.get()),'bubble':next(k for k,v in BUBBLES.items() if v==self.bubble.get()),'start':start,'end':end,'stroke':max(0,min(20,self.stroke.get())),'outline':'#000000','bubble_color':'#ffffff','shadow':True}
            e.action(lambda:e.doc.update_layer(e.selected_layer,text_motion=motion),'动态文字已更新')
        except (ValueError,tk.TclError) as exc:e.status.set(str(exc))

    def select_region(self):
        e=self.e
        if e.busy:return
        if not e.finish_text():return
        e.set_tool('vision');e.hand_mode=False;e.playing=False;e.play_button.configure(text='播放动画');e.crop_mode=True;e.region_callback=self.selected_region
        self.note.set('在画布拖出一个矩形，松开确定范围。');e.status.set(self.note.get())

    def selected_region(self,box):
        self.e.crop_mode=False;self.e.canvas.delete('selection');self.e.set_cursor('arrow')
        if box[2]<=box[0] or box[3]<=box[1]:self.note.set('请拖出有宽度和高度的范围。');return
        self.box=box;self.region.set(f'范围：{box[2]-box[0]} × {box[3]-box[1]} 像素')
        self.note.set('范围已选好，点击识别或开始跟随。');self.e.status.set(self.note.get());self.e.show_property(self.vision_page)

    def clear_region(self):self.box=None;self.region.set('范围：完整画面')
    def copy_text(self):self.e.window.clipboard_clear();self.e.window.clipboard_append(self.text.get('1.0','end-1c'))
    def add_text(self):
        value=self.text.get('1.0','end-1c')
        if value.strip():self.e.action(lambda:self.e.doc.add_text(value,color='#ffffff',position=(20,20)),'识别文字已加入，可继续校对')
        else:self.note.set('先识别文字，结果会显示在这里。')

    def progress(self,stage,n=0,total=0):
        self.e.events.put(('progress',stage+(f' {n}/{total}' if total else '…')))

    def submit(self,fn,label):
        def work():
            try:return fn()
            except (InterruptedError,CancelledError) as exc:raise InterruptedError('处理已取消，原件和草稿保留') from exc
        if self.e.submit(work,label):
            self.running=True;self.note.set(label+'…');self.cancel_button.pack(side='bottom',fill='x')

    def event(self,event):
        if not self.running:return
        if event[0]=='progress':self.note.set(event[1])
        elif event[0] in ('done','error'):
            self.running=False;self.cancel_button.pack_forget()
            self.note.set('未完成：'+event[1]+'；可重试。' if event[0]=='error' else '处理完成，可以检查结果。')

    def ocr(self):
        e=self.e
        if not e.doc or e.busy:return
        doc=copy(e.doc);index=e.animation_frame;box=self.box;folder=e.store.root/'recognition'/uuid4().hex
        def work():
            folder.mkdir(parents=True);check_cancel(e.save_cancel);self.progress('准备当前画面')
            image=doc.render(animation_frame=index)
            if box:
                cropped=image.crop(box);image.close();image=cropped
            image.thumbnail((1600,1600),Image.Resampling.LANCZOS)
            rgb=Image.new('RGB',image.size,'white');rgb.paste(image,mask=image.getchannel('A'));image.close()
            path=folder/'frame.png';rgb.save(path);rgb.close();result=folder/'result.json'
            worker('vision','factory_vision_worker.py',{'action':'ocr','image':str(path),'result':str(result)},folder,e.save_cancel,progress=self.progress,timeout=90)
            return {'recognized_text':json.loads(result.read_text('utf-8'))['text']}
        self.submit(work,'识别当前画面的文字')

    def track_region(self,correct=False):
        e=self.e
        if e.busy:return
        if not e.doc or not e.doc.animation or not e.selected_layer or not self.box:
            self.note.set('需要一段动画、一个跟随图层，以及框选的主体范围。');return
        doc=copy(e.doc);ident=e.selected_layer;prior=doc._find(ident).get('tracking',{})
        if not any(l.get('animation') and l['id']!=ident and l.get('visible') is not False for l in doc.layers):
            self.note.set('先添加并选中要跟随的文字或贴纸；底层动图作为被跟随的画面。');return
        if correct and not prior.get('keys'):self.note.set('先完成一次跟随，再暂停到需要校正的帧。');return
        try:seconds=float(self.track_seconds.get())
        except (ValueError,tk.TclError):self.note.set('请设置有效的跟随时长。');return
        if not .5<=seconds<=60:self.note.set('每次跟随时长为0.5～60秒。');return
        animation=doc.animation;starts=[];ms=0
        for duration in animation.durations:starts.append(ms);ms+=duration
        start=e.animation_frame;end_ms=min(ms,starts[start]+round(seconds*1000));indices=[];next_ms=starts[start]
        for i in range(start,len(starts)):
            if starts[i]>=end_ms:break
            if starts[i]>=next_ms:indices.append(i);next_ms=starts[i]+80
        scale=min(1,960/max(doc.size));l,t,r,b=self.box
        box=[l*scale,t*scale,(r-l)*scale,(b-t)*scale]
        if box[2]<4 or box[3]<4:self.note.set('框选范围太小，请放大主体范围后重试。');return
        folder=e.store.root/'tracking'/uuid4().hex;revision=doc.revision
        def work():
            from editor_timeline import AnimationCovers
            folder.mkdir(parents=True);frames=[];covers=AnimationCovers(animation,doc,exclude=(ident,))
            for n,index in enumerate(indices):
                check_cancel(e.save_cancel);self.progress('准备跟随画面',n+1,len(indices))
                path=folder/f'{index:05}.png';image=covers.get(starts[index]/1000,960,e.save_cancel);image.save(path,compress_level=1);image.close();frames.append(str(path))
            durations=[b-a for a,b in zip([starts[i] for i in indices],[*[starts[i] for i in indices[1:]],end_ms])]
            result=folder/'track.json'
            worker('vision','factory_vision_worker.py',{'action':'track','frames':frames,'indices':indices,'durations':durations,'box':box,'time_offset':starts[start],'result':str(result)},folder,e.save_cancel,progress=self.progress,timeout=180)
            track=json.loads(result.read_text('utf-8'))
            for key in track['keys']:key['box']=[v/scale for v in key['box']]
            track['reference']=[v/scale for v in track['reference']]
            if correct:
                track['keys']=[k for k in prior['keys'] if k['ms']<starts[start]]+track['keys']+[k for k in prior['keys'] if k['ms']>=end_ms]
                track['reference']=prior['reference']
            track['duration']=ms
            from emoji_bridge.tracking import lost_ranges
            track['lost_ranges']=lost_ranges(track['keys'],ms);check_cancel(e.save_cancel)
            if e.closed or e.doc.revision!=revision:raise InterruptedError('作品已变化，请重新开始跟随')
            e.doc.update_layer(ident,tracking=track)
            return {'track_lost':sum(not k['ok'] for k in track['keys']),'track_ranges':track['lost_ranges']}
        self.submit(work,'跟随所框主体')
