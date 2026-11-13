"""Editor-local effect workspace; output re-enters the existing layer/store pipeline."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog
from PIL import Image, ImageTk, ImageDraw
from emoji_bridge.dropped_item import ItemOptions, generate, save_material, render_frame, schedule
from emoji_bridge.frame_store import cancelled
from playback_keys import PlaybackKeys
from ui_style import BG,SURFACE,INK,MUTED,disclosure


class DroppedItem:
    def __init__(self,editor):
        self.e=editor;self.pool=ThreadPoolExecutor(max_workers=1);self.events=queue.Queue();self.cancel=threading.Event()
        self.active=False;self.closed=False;self.generation=0;self.source=None;self.source_id=None;self.result=None;self.playing=False;self.frame=0
        self.request=None;self.timer=None;self.job=None;self.replace_id=None
        self.run_mode=None
        self.play_elapsed=0.;self.play_start=time.monotonic()
        self.quick_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='item-current-frame');self.quick_job=None;self.quick_after=None;self.quick_image=None;self.ready=False
        self.page=ttk.Frame(editor.tabs,padding=12);editor.tabs.add(self.page,text='掉落物')
        from ui_style import ScrollBody
        actions=ttk.Frame(self.page);actions.pack(side='bottom',fill='x',pady=(8,0))
        scroll=ScrollBody(self.page);scroll.pack(fill='both',expand=True);self.body=scroll.body
        ttk.Label(self.body,text='掉落物',font=('Microsoft YaHei UI',14,'bold')).pack(anchor='w',pady=(0,8))
        self.preset=tk.StringVar(value='原画');self.duration=tk.StringVar(value='3');self.direction=tk.StringVar(value='顺时针')
        self.turns=tk.StringVar(value='1');self.bob=tk.DoubleVar(value=5.5);self.thickness=tk.DoubleVar(value=3.5)
        self.size=tk.StringVar(value='512');self.timing=tk.StringVar(value='完整动作适配时长');self.background=tk.StringVar(value='透明')
        self.freeze=tk.BooleanVar(value=False);self.shadow=tk.BooleanVar(value=False)
        for label,var,values in [('外观',self.preset,('原画','像素')),('方向',self.direction,('顺时针','逆时针')),
                                  ('循环时长 / 秒',self.duration,('2','3','4','6','10'))]:
            row=ttk.Frame(self.body);row.pack(fill='x',pady=4)
            ttk.Label(row,text=label).pack(side='left')
            ttk.Combobox(row,textvariable=var,values=values,width=12,state='readonly' if var!=self.duration else 'normal').pack(side='right')
        for label,var,high in [('上下浮动',self.bob,12),('薄片厚度',self.thickness,10)]:
            row=ttk.Frame(self.body);row.pack(fill='x',pady=(12,3))
            ttk.Label(row,text=label).pack(side='left')
            note=ttk.Label(row,text=f'{var.get():.1f}%');note.pack(side='right')
            var.trace_add('write',lambda *_,v=var,n=note:n.configure(text=f'{v.get():.1f}%'))
            ttk.Scale(self.body,from_=0 if var is self.bob else .5,to=high,variable=var).pack(fill='x')
        advanced=disclosure(self.body,'输出与动画规则')
        for label,var,values in [('输出尺寸',self.size,('256','512','768','1024')),('每周期圈数',self.turns,('1','2','3')),
                                  ('动作时间',self.timing,('完整动作适配时长','保持原速循环')),('背景',self.background,('透明','午夜黑','白色'))]:
            ttk.Label(advanced,text=label).pack(anchor='w',pady=(8,2))
            ttk.Combobox(advanced,textvariable=var,values=values,state='readonly').pack(fill='x')
        ttk.Checkbutton(advanced,text='定格打开效果时的当前帧',variable=self.freeze).pack(anchor='w',pady=5)
        ttk.Checkbutton(advanced,text='柔和阴影（需非透明背景）',variable=self.shadow).pack(anchor='w')
        ttk.Label(advanced,text='默认完整原动作适配一个周期，会调整原动作速度。原速模式按所选时长循环/截取，接缝取决于原动画。背面为镜像，文字也会镜像。',wraplength=245,foreground=MUTED).pack(fill='x',pady=8)
        self.add=ttk.Button(actions,text='加入当前合成',style='Editor.Primary.TButton',command=lambda:self.finish('add'));self.add.pack(fill='x',pady=(0,6))
        row=ttk.Frame(actions);row.pack(fill='x',pady=4)
        ttk.Button(row,text='保存为素材',command=lambda:self.finish('save')).pack(side='left',fill='x',expand=True)
        export=ttk.Menubutton(row,text='导出 ▾');export.pack(side='right',padx=(6,0))
        menu=tk.Menu(export,tearoff=False);export.configure(menu=menu)
        for fmt in ('PNG','GIF'):menu.add_command(label='导出 '+fmt,command=lambda f=fmt:self.export(f))
        from xp_progress import XPProgress
        self.progress=XPProgress(actions,editor)
        self.stop=ttk.Button(actions,text='取消处理',command=self.abort);self.stop.pack(fill='x')
        self.progress.pack(fill='x',pady=8,before=self.stop)
        self.note=ttk.Label(self.body,text='选中透明图片或 GIF 后打开效果。',wraplength=235,foreground=MUTED);self.note.pack(fill='x',pady=8)
        scroll.attach()
        self.overlay=ttk.Frame(editor.canvas_host,padding=12)
        top=ttk.Frame(self.overlay);top.pack(fill='x')
        ttk.Label(top,text='掉落物预览',font=('Microsoft YaHei UI',13,'bold')).pack(side='left')
        ttk.Button(top,text='返回画布',command=self.hide).pack(side='right')
        self.preview=tk.Canvas(self.overlay,background=BG,highlightthickness=0);self.preview.pack(fill='both',expand=True,pady=12)
        self.preview.bind('<Configure>',lambda ev:self.draw())
        bottom=ttk.Frame(self.overlay);bottom.pack(fill='x')
        self.play=ttk.Button(bottom,text='播放 · 空格',command=self.toggle);self.play.pack(side='left')
        self.caption=ttk.Label(bottom,text='预览256px · 正式输出按所选尺寸');self.caption.pack(side='left',padx=12)
        self.keys=PlaybackKeys(self.overlay,self.play,self.toggle,lambda:self.active and self.result is not None)
        self.overlay.bind('<Escape>',lambda ev:self.hide())
        for var in (self.preset,self.duration,self.direction,self.turns,self.bob,self.thickness,self.size,self.timing,self.background,self.freeze,self.shadow):var.trace_add('write',self.changed)
        self.poll_id=editor.window.after(40,self.poll)

    def options(self):
        value=ItemOptions(size=int(self.size.get()),seconds=float(self.duration.get()),direction=1 if self.direction.get()=='顺时针' else -1,
            turns=int(self.turns.get()),bob=self.bob.get()/100,thickness=self.thickness.get()/100,pixel=self.preset.get()=='像素',
            timing='fit' if self.timing.get()=='完整动作适配时长' else 'original',freeze=self.initial_frame if self.freeze.get() else None,
            background={'透明':None,'午夜黑':'#08090b','白色':'#ffffff'}[self.background.get()],shadow=self.shadow.get())
        value.validate();return value

    def open(self):
        e=self.e
        if not e.doc or e.busy or not e.finish_text():return
        layer=next((l for l in e.doc.layers if l['id']==e.selected_layer),None)
        if not layer or layer['kind']!='sticker':e.status.set('请先选中图片或 GIF 图层，再打开“效果 → 掉落物”。');return
        info=layer.get('dropped_item',{});self.source_id=info.get('source_id') or layer.get('source_id')
        if not self.source_id:e.status.set('此图层没有托管原件，请先从素材库添加。');return
        self.input_layer=dict(layer);self.source_draft=None
        self.source=None;self.result=None;self.quick_image=layer['image'].copy();self.ready=False;self.replace_id=layer['id'] if info else None;self.initial_frame=0
        self.play_elapsed=0;self.play_start=time.monotonic();self.playing=True
        if layer.get('animation') and not info:
            from emoji_bridge.animated_edit import layer_frame_index
            self.initial_frame=layer_frame_index(layer,e.doc.animation,e.animation_frame)
        self.active=True;self.keys.set_active(True);e.playing=False
        self.overlay.place(x=0,y=0,relwidth=1,relheight=1);self.overlay.lift();e.show_property(self.page)
        if info:
            p=info['options'];self.duration.set(str(p['seconds']));self.size.set(str(p['size']));self.turns.set(str(p['turns']))
            self.preset.set('像素' if p['pixel'] else '原画');self.direction.set('顺时针' if p['direction']==1 else '逆时针')
            self.bob.set(p['bob']*100);self.thickness.set(p['thickness']*100)
            self.timing.set('完整动作适配时长' if p['timing']=='fit' else '保持原速循环')
            self.background.set({None:'透明','#08090b':'午夜黑','#ffffff':'白色'}[p['background']]);self.shadow.set(p['shadow'])
            self.freeze.set(p['freeze'] is not None);self.initial_frame=p['freeze'] or 0
        else:
            # A freeze choice belongs to the previously opened source, not to
            # every later GIF the user selects.
            self.freeze.set(False)
        self.changed();self.draw();self.preview.focus_set()

    def abort(self):
        if self.request:self.e.window.after_cancel(self.request);self.request=None
        if self.quick_after:self.e.window.after_cancel(self.quick_after);self.quick_after=None
        self.cancel.set();self.generation+=1;self.playing=False;self.play.configure(text='播放 · 空格')
        self.progress.finish(cancel=self.cancel)
        self.ready=False;self.add.state(['disabled'])
        if self.job:self.job.cancel()
        self.note.configure(text='已取消后续处理；已完成文件和原件保留。调整参数即可重新准备。')

    def hide(self):
        if self.run_mode in (None,'preview') or not self.job or self.job.done():self.abort()
        self.playing=False;self.active=False;self.keys.set_active(False);self.overlay.place_forget()
        self.e.show_property(self.e.object_page);self.e.canvas.focus_set()

    def changed(self,*_):
        if not self.active:return
        self.cancel.set();self.generation+=1;self.ready=False
        self.add.state(['disabled'])
        if self.request:self.e.window.after_cancel(self.request)
        self.request=self.e.window.after(220,self.prepare)
        if not self.quick_after:self.quick_after=self.e.window.after(35,self.quick)

    def elapsed(self):
        return self.play_elapsed+((time.monotonic()-self.play_start)*1000 if self.playing else 0)

    def quick(self):
        self.quick_after=None
        if not self.active or self.source is None:return
        try:options=replace(self.options(),size=256)
        except (ValueError,tk.TclError):return
        generation=self.generation;source=self.source;elapsed=self.elapsed()%(options.seconds*1000)
        if self.quick_job:self.quick_job.cancel()
        def work():
            from bisect import bisect_right
            times,_,indices=schedule(source,options)
            index=indices[max(0,bisect_right(times,elapsed)-1)]
            image=source.frames[index] if hasattr(source,'frames') else source
            self.events.put((generation,'quick',render_frame(image,elapsed,options)))
        self.quick_job=self.quick_pool.submit(work)

    def prepare(self):
        self.request=None
        if not self.active:return
        self.run('preview')

    def run(self,mode,path=None):
        if not self.active:return
        if self.job and not self.job.done() and self.run_mode not in (None,'preview'):return
        try:options=self.options()
        except (ValueError,tk.TclError) as exc:self.note.configure(text=str(exc));return
        self.run_mode=mode;self.cancel.set();self.cancel=threading.Event();cancel=self.cancel;self.generation+=1;generation=self.generation
        if self.job:self.job.cancel()
        source_id=self.source_id;source=self.source;store=self.e.store;revision=self.e.doc.revision;frame=self.frame
        input_layer=self.input_layer;source_draft=self.source_draft
        self.note.configure(text='正在准备预览…' if mode=='preview' else '正在逐帧生成；可取消…');self.progress.configure(value=0)
        if not self.progress.winfo_manager():self.progress.pack(fill='x',pady=8,before=self.stop)
        def progress(done,total,stage):self.events.put((generation,'progress',done/max(1,total)*100,stage))
        def process():
            activity=None
            try:
                from emoji_bridge.task_budget import admission
                lease=admission('生成掉落物' if mode!='preview' else '掉落物预览',cancel=cancel,priority=1 if mode=='preview' else 0)
                with lease:
                    cancelled(cancel)
                    if mode!='preview':activity=self.progress.begin('生成掉落物')
                    from emoji_bridge.dropped_item import layer_source
                    if source is None:
                        original,owned=layer_source(store,input_layer,cancel=cancel)
                    else:original=source;owned=source_draft
                    self.events.put((generation,'source',original,owned))
                    result=generate(original,owned,replace(options,size=256) if mode=='preview' else options,store.root/'item-effects',cancel=cancel,progress=progress)
                    result['source_draft']=owned
                    item=None
                    if mode=='save':item,_,_=save_material(store,result,source_id,cancel=cancel,progress=progress)
                    elif mode in ('PNG','GIF'):
                        if mode=='PNG':
                            image=result['animation'].frames[min(frame,len(result['animation'].frames)-1)];cancelled(cancel)
                            temp=Path(path).with_suffix('.partial.png')
                            try:image.save(temp,'PNG');cancelled(cancel);temp.replace(path)
                            finally:temp.unlink(missing_ok=True)
                        else:
                            from emoji_bridge.dropped_item import document
                            from emoji_bridge.animated_edit import export_gif
                            export_gif(document(result,source_id),path,cancel=cancel,progress=progress)
                    cancelled(cancel)
                    if activity:self.progress.finish(cancel=cancel,activity=activity)
                    self.events.put((generation,'done',mode,result,original,item,revision))
            except Exception as exc:
                if activity:self.progress.finish(error=exc,cancel=cancel,activity=activity)
                self.events.put((generation,'error',str(exc) or type(exc).__name__))
        self.job=self.pool.submit(process)

    def finish(self,mode):
        if not self.ready:self.note.configure(text='正在完成本次参数的预览，请稍候。');return
        self.run(mode)

    def export(self,format):
        if not self.ready:return
        path=filedialog.asksaveasfilename(parent=self.e.window,defaultextension='.'+format.lower(),filetypes=[(format,'*.'+format.lower())])
        if path:self.run(format,path)

    def toggle(self):
        if not self.result:return
        if self.playing:self.play_elapsed+=(time.monotonic()-self.play_start)*1000
        else:self.play_start=time.monotonic()
        self.playing=not self.playing;self.play.configure(text='暂停 · 空格' if self.playing else '播放 · 空格')

    def draw(self):
        if self.quick_image is None and not self.result:return
        image=self.quick_image if self.quick_image is not None else self.result['animation'].frames[self.frame]
        checker=Image.new('RGBA',image.size,SURFACE);d=ImageDraw.Draw(checker)
        for y in range(0,image.height,16):
            for x in range(0,image.width,16):
                if (x//16+y//16)%2:d.rectangle((x,y,x+15,y+15),fill='#242832')
        checker.alpha_composite(image)
        edge=max(64,min(512,self.preview.winfo_width()-32,self.preview.winfo_height()-32))
        self.photo=ImageTk.PhotoImage(checker.resize((edge,edge),Image.Resampling.NEAREST if self.preset.get()=='像素' else Image.Resampling.BILINEAR))
        self.preview.delete('all');self.preview.create_image(self.preview.winfo_width()/2,self.preview.winfo_height()/2,image=self.photo)
        if self.result:self.caption.configure(text=f'{self.elapsed()%sum(self.result["animation"].durations)/1000:.2f}s / {sum(self.result["animation"].durations)/1000:.2f}s · 预览256px')

    def poll(self):
        if self.closed:return
        try:
            while True:
                event=self.events.get_nowait()
                if event[0]!=self.generation:continue
                if event[1]=='quick':
                    if not self.ready:self.quick_image=event[2];self.draw()
                    continue
                if event[1]=='source':self.source=event[2];self.source_draft=event[3];self.quick();continue
                if event[1]=='progress':self.progress.configure(value=event[2]);continue
                if event[1]=='error':
                    self.note.configure(text='未完成：'+event[2])
                    continue
                _,_,mode,result,source,item,revision=event;self.source=source
                if mode=='preview':
                    self.result=result;self.ready=True;self.quick_image=None;self.frame=result['animation'].frame_at(self.elapsed())[0];self.play.configure(text='暂停 · 空格' if self.playing else '播放 · 空格');self.add.state(['!disabled']);self.draw()
                    self.note.configure(text='预览就绪；透明帧保留。GIF只有二值透明，柔和阴影请选择背景。')
                elif mode=='add':
                    if self.e.doc.revision!=revision:self.note.configure(text='作品已变化，未加入旧结果；请再次点击。');continue
                    animation=result['animation'];image=animation.frames[0];layers=self.e.doc.layers;ident=self.replace_id or uuid4().hex
                    existing=next((l for l in layers if l['id']==ident),None)
                    edge=min(image.width,*self.e.doc._state.base.size)
                    value=dict(existing) if existing else {'id':ident,'kind':'sticker','position':(0,0),'size':(edge,edge)}
                    value.update(image=image,animation=animation,source_id=self.source_id,dropped_item={'source_id':self.source_id,'options':result['options'],'source_draft':result['source_draft']})
                    if existing:layers=[value if l['id']==ident else l for l in layers]
                    else:layers.append(value)
                    self.e.doc.replace_scene(self.e.doc._state.base,layers,list(dict.fromkeys(self.e.doc.source_ids+[self.source_id])),'掉落物')
                    self.e.selected_layer=ident;self.hide();self.e.changed('掉落物已加入合成；原件与效果参数保留。');self.e.reflow()
                else:
                    self.note.configure(text='已保存到素材库。' if mode=='save' else '已导出 '+mode+'；透明母版和原件仍保留。')
                    if item:
                        if self.e.on_saved:self.e.on_saved(item)
                        self.e.material_panel.reload(preserve_scroll=True)
        except queue.Empty:pass
        if self.active and self.result and self.playing and self.ready:
            frame=self.result['animation'].frame_at(self.play_elapsed+(time.monotonic()-self.play_start)*1000)[0]
            if frame!=self.frame:self.frame=frame;self.draw()
        self.poll_id=self.e.window.after(25,self.poll)

    def close(self):
        if self.closed:return
        self.closed=True;self.cancel.set();self.keys.close()
        if self.request:self.e.window.after_cancel(self.request)
        if self.quick_after:self.e.window.after_cancel(self.quick_after)
        self.quick_pool.shutdown(wait=False,cancel_futures=True)
        self.e.window.after_cancel(self.poll_id);self.pool.shutdown(wait=False,cancel_futures=True)
