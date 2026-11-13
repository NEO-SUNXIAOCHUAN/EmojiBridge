"""Small local-video front end; FFmpeg outputs rejoin the existing material store."""
import hashlib
import json
import math
import queue
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog
from PIL import Image,ImageGrab,ImageTk

VIDEO_EXTENSIONS={'.mp4','.m4v','.mov','.mkv','.avi','.webm','.wmv','.mpeg','.mpg','.ts'}


def own_source(store,path,cancel):
    """Keep external source bytes, so a moved download does not break later edits."""
    path=Path(path).resolve()
    if not path.is_file():raise ValueError('请选择本地视频或 GIF 文件')
    base=store.root/'video-sources';base.mkdir(parents=True,exist_ok=True)
    owned=path.is_relative_to(store.root.resolve())
    with tempfile.TemporaryDirectory(prefix='import-',dir=base) as folder:
        temp=Path(folder)/'original';digest=hashlib.sha256()
        with path.open('rb') as source, temp.open('wb') as output:
            while block:=source.read(1024*1024):
                if cancel.is_set():raise InterruptedError('已取消导入，原文件未改变')
                digest.update(block)
                if not owned:output.write(block)
        ident=digest.hexdigest();directory=base/ident;directory.mkdir(exist_ok=True)
        destination=path if owned else directory/('original'+path.suffix.lower())
        if not owned and not destination.exists():temp.replace(destination)
        previous=directory/'source.json'
        name=json.loads(previous.read_text(encoding='utf-8'))['name'] if previous.exists() else path.name
        info={'sha256':ident,'name':name,'path':str(destination)}
        (directory/'source.json').write_text(json.dumps(info,ensure_ascii=False),encoding='utf-8')
    return info


class VideoWindow:
    def __init__(self,parent,store,paths=(),on_saved=None,on_edit=None,on_edit_materials=None,*,host=None,on_return=None):
        from ui_style import video_style,BG,FONT
        from video_timeline import ClipTimeline
        self.on_edit=on_edit;self.on_edit_materials=on_edit_materials;self.result_item=None;self.embedded=host is not None
        self.store=store;self.on_saved=on_saved;self.closed=False;self.busy=False;self.source=None;self.metadata=None
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='video');self.events=queue.Queue();self.cancel=threading.Event()
        self.seek_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='video-seek');self.seek_token=0;self.seek_future=None
        self.output=None;self.photo=None;self.card_photo=None;self.stream=None;self.seek_after=None;self.pending_seek=None;self.frame_cache=None;self.selection=None
        self.original_preview=None;self.resize_after=None;self.seek_stop=threading.Event()
        self.window=host if host is not None else tk.Toplevel(parent)
        self.window.title('EmojiBridge · 视频选段');self.window.geometry('1120x860');self.window.minsize(900,730)
        self.window.configure(background=BG);video_style(self.window);self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.header=ttk.Frame(self.window,padding=(20,14));self.header.pack(fill='x')
        self.header_title=ttk.Label(self.header,text='视频选段',style='Video.Title.TLabel');self.header_title.pack(side='left')
        self.return_button=None
        if self.embedded and on_return:
            self.return_button=ttk.Button(self.header,text='返回创作',style='Video.Tool.TButton',command=on_return);self.return_button.pack(side='left',padx=(12,0))
        ttk.Button(self.header,text='打开素材',style='Video.Tool.TButton',command=self.choose).pack(side='left',padx=(20,6))
        ttk.Button(self.header,text='粘贴文件',style='Video.Tool.TButton',command=self.paste).pack(side='left')
        ttk.Button(self.header,text='区域录屏',command=self.record_region).pack(side='left',padx=4)
        self.recent=ttk.Combobox(self.header,state='readonly',width=24);self.recent.pack(side='left',padx=10,fill='x',expand=True)
        self.recent.bind('<<ComboboxSelected>>',self.open_recent)
        save=self.save_button=ttk.Menubutton(self.header,text='另存为');save.pack(side='right')
        menu=tk.Menu(save,tearoff=False);save.configure(menu=menu)
        menu.add_command(label='导出已生成文件…',command=self.export)
        menu.add_separator();menu.add_command(label='GIF 动图',command=lambda:self.convert('gif'))
        menu.add_command(label='PNG 当前画面',command=lambda:self.convert('png'))
        menu.add_command(label='MP4 选中片段',command=lambda:self.convert('mp4'))
        self.lower=ttk.Frame(self.window);self.lower.pack(side='bottom',fill='x')
        self.preview=tk.Label(self.window,text='打开视频或 GIF，开始选段\n也可以拖入本地文件，或粘贴剪贴板中的媒体文件。',bg='#20252b',fg='#c8d1da',font=(FONT,12))
        self.preview.pack(fill='both',expand=True,padx=20)
        self.preview.bind('<Configure>',self.resize_preview)
        for widget in (self.window,self.preview):
            widget.drop_target_register('DND_Files');widget.dnd_bind('<<Drop>>',self.drop)
        controls=self.controls=ttk.Frame(self.lower,padding=(20,10));controls.pack(fill='x')
        self.play_button=ttk.Button(controls,text='播放 · 空格',width=12,command=self.play);self.play_button.pack(side='left')
        self.position=tk.DoubleVar(value=0);self.position_label=ttk.Label(controls,text='00:00.0 / 00:00.0');self.position_label.pack(side='left',padx=12)
        self.zoom_hint=ttk.Label(controls,text='滚轮缩放 · Shift＋滚轮横移',style='Video.Muted.TLabel');self.zoom_hint.pack(side='left',padx=8)
        self.timeline=ClipTimeline(self.lower,self.timeline_changed)
        for label,fn in [('全片',lambda:self.timeline.fit()),('选区',lambda:self.timeline.fit(True)),('−',lambda:self.timeline.zoom(1/1.5)),('＋',lambda:self.timeline.zoom(1.5))]:
            ttk.Button(controls,text=label,width=5,command=fn).pack(side='right',padx=2)
        self.timeline.pack(fill='x',padx=20)
        action=self.action=ttk.Frame(self.lower,padding=(20,12));action.pack(fill='x')
        self.mode=tk.StringVar(value='保留背景')
        for mode in ('保留背景','抠出主体'):
            ttk.Radiobutton(action,text=mode,variable=self.mode,value=mode,command=self.mode_changed).pack(side='left',padx=(0,16))
        ttk.Button(action,text='高级设置',command=self.toggle_advanced).pack(side='left',padx=6)
        self.primary=ttk.Button(action,text='生成 GIF',style='Video.Primary.TButton',command=self.generate);self.primary.pack(side='right')
        self.start=tk.StringVar(value='0');self.end=tk.StringVar(value='2');self.fps=tk.StringVar(value='12');self.width=tk.StringVar(value='640')
        self.audio=tk.BooleanVar(value=False);self.cutout_edge=tk.StringVar(value='384');self.cutout_fps=tk.StringVar(value='8')
        self.advanced=ttk.Frame(self.lower,padding=(20,4))
        opts=ttk.Frame(self.advanced);opts.pack(fill='x')
        for n,(title,var,size) in enumerate([('开始秒',self.start,8),('结束秒',self.end,8),('GIF帧率',self.fps,5),('输出宽度',self.width,7),('抠图最长边',self.cutout_edge,6),('抠图帧率',self.cutout_fps,5)]):
            field=ttk.Frame(opts);field.grid(row=n//3,column=n%3,sticky='w',padx=(0,20),pady=3)
            ttk.Label(field,text=title,width=12).pack(side='left');entry=ttk.Entry(field,textvariable=var,width=size);entry.pack(side='left',padx=(3,10))
            if var in (self.start,self.end):entry.bind('<Return>',self.apply_range);entry.bind('<FocusOut>',self.apply_range)
        ttk.Checkbutton(self.advanced,text='MP4 保留声音；尺寸填 0 为原尺寸，MP4 剩余透明区域使用白底',variable=self.audio).pack(anchor='w',pady=5)
        self.limit_note=ttk.Label(self.advanced,text='GIF 输出≤60秒；动态抠图按帧处理，限30分钟/18000帧/8GiB帧缓存。2～5秒仅是建议，预览播放完整选区。',style='Video.Muted.TLabel');self.limit_note.pack(anchor='w')
        self.footer=ttk.Frame(self.lower,padding=(20,4));self.footer.pack(fill='x')
        self.card=ttk.Label(self.footer,text='生成后可直接拖出成品',anchor='w',compound='left');self.card.pack(side='left',fill='x',expand=True)
        self.card.drag_source_register(1,'DND_Files');self.card.dnd_bind('<<DragInitCmd>>',self.drag)
        self.edit_result=ttk.Button(self.footer,text='编辑成品',command=self.edit_generated);self.edit_result.pack(side='right');self.edit_result.state(['disabled'])
        self.status=tk.StringVar(value='尚未打开素材；打开、粘贴或录屏后即可选择片段。')
        self.status_label=ttk.Label(self.lower,textvariable=self.status,wraplength=1020,padding=(20,8),style='Video.Muted.TLabel');self.status_label.pack(fill='x')
        self.progress_row=ttk.Frame(self.lower,padding=(20,0,20,12))
        self.bar=ttk.Progressbar(self.progress_row,maximum=100);self.bar.pack(side='left',fill='x',expand=True)
        ttk.Button(self.progress_row,text='取消',command=self.cancel_processing).pack(side='right',padx=(10,0))
        from playback_keys import PlaybackKeys
        self.playback_keys=PlaybackKeys(self.window,self.play_button,self.play,lambda:bool(self.source and self.metadata and not self.busy and not self.closed))
        self.compact=None;self.window.bind('<Configure>',self.responsive,add='+')
        from video_speech_ui import SpeechPanel
        self.speech=SpeechPanel(self)
        ttk.Button(self.header,text='台词 / 字幕',command=self.speech.toggle).pack(side='left',padx=4)
        self.refresh_recent();self.update_source_state();self.poll_id=self.window.after(30,self.poll)
        if paths:self.open_file(paths[0])

    def responsive(self,event):
        if event.widget is not self.window:return
        small=event.width<1000;short=event.height<650;mode=(small,short)
        if mode==self.compact:return
        self.compact=mode
        for widget,options in [(self.recent,{'side':'left','padx':10,'fill':'x','expand':True,'before':self.save_button}),
                               (self.zoom_hint,{'side':'left','padx':8})]:
            if small:widget.pack_forget()
            else:widget.pack(**options)
        if self.return_button:
            if small:self.return_button.pack_forget()
            else:self.return_button.pack(side='left',padx=(12,0),after=self.header_title)
        self.header.configure(padding=(20,5 if short else 14));self.controls.configure(padding=(20,4 if short else 10))
        self.action.configure(padding=(20,4 if short else 12));self.footer.configure(padding=(20,0 if short else 4))
        self.timeline.canvas.configure(height=110 if short else 150)
        self.limit_note.configure(wraplength=max(500,event.width-45))
        # Generated output keeps its own drag card. Before generation the status
        # already explains the next action, so no empty footer needs that space.
        if short and not self.output:self.footer.pack_forget()
        elif not self.footer.winfo_manager():self.footer.pack(fill='x',before=self.status_label)

    def update_source_state(self):
        ready=bool(self.source and self.metadata)
        state=['!disabled'] if ready and not self.busy else ['disabled']
        for button in (self.play_button,self.primary,self.save_button):button.state(state)
        self.timeline.enabled=ready and not self.busy
        if ready:
            if not self.timeline.winfo_manager():self.timeline.pack(fill='x',padx=20,before=self.action)
            if not self.controls.winfo_manager():self.controls.pack(fill='x',before=self.timeline)
        else:
            self.controls.pack_forget();self.timeline.pack_forget()

    def mode_changed(self):
        self.primary.configure(text='抠主体并编辑' if self.mode.get()=='抠出主体' else '生成 GIF')

    def record_region(self):
        previous=getattr(self,'recorder_window',None)
        if previous and not previous.closed:previous.window.lift();return
        from screen_record_ui import RecorderWindow
        self.recorder_window=RecorderWindow(self.window,self.store,self.open_file)

    def generate(self):
        if self.mode.get()=='抠出主体':self.cutout()
        else:self.convert('gif')

    def toggle_advanced(self):
        if self.advanced.winfo_manager():self.advanced.pack_forget()
        else:self.advanced.pack(fill='x',before=self.footer if self.footer.winfo_manager() else self.status_label)

    def apply_range(self,event=None):
        if not self.metadata:return
        if self.busy:
            self.start.set(f'{self.timeline.start:.3f}');self.end.set(f'{self.timeline.end:.3f}');return
        try:
            start,end,_,_=self.options()
            self.timeline.start=start;self.timeline.end=end;self.timeline.set_position(max(start,min(end-.001,self.position.get())))
            self.timeline_changed(self.timeline,True)
        except ValueError as exc:self.status.set(str(exc))

    def timeline_changed(self,timeline,released):
        if self.busy:return
        selection=(round(timeline.start,3),round(timeline.end,3))
        if self.selection!=selection:
            self.output=None;self.result_item=None;self.edit_result.state(['disabled']);self.card.configure(image='',text='选区已变化，生成后可拖出本次成品')
        self.selection=selection
        self.stop_preview();self.start.set(f'{timeline.start:.3f}');self.end.set(f'{timeline.end:.3f}')
        self.position.set(timeline.position);self.seek(timeline.position,immediate=released)

    def edit_generated(self):
        if self.result_item and self.on_edit_materials:
            if self.on_edit_materials([self.result_item['id']]):self.edit_return()

    def edit_return(self):
        self.stop_preview()
        if not self.embedded:self.window.withdraw();self.window.master.lift()

    def refresh_recent(self):
        self.history=[]
        for file in sorted((self.store.root/'video-sources').glob('*/source.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            try:self.history.append(json.loads(file.read_text(encoding='utf-8')))
            except (ValueError,OSError):pass
        self.recent['values']=[v['name']+' · '+v['sha256'][:6] for v in self.history]
        if self.source:self.recent.set(self.source['name'])

    def open_recent(self,event=None):
        index=self.recent.current()
        if index>=0:self.open_file(self.history[index]['path'])

    def choose(self):
        path=filedialog.askopenfilename(parent=self.window,title='选择本地视频或 GIF',filetypes=[('视频 / GIF','*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.mpeg *.mpg *.ts *.gif'),('所有文件','*.*')])
        if path:self.open_file(path)

    def paste(self):
        try:value=ImageGrab.grabclipboard()
        except OSError as exc:self.status.set('暂时无法读取剪贴板：'+str(exc));return
        if isinstance(value,list):
            files=[p for p in value if Path(p).suffix.lower() in VIDEO_EXTENSIONS|{'.gif'}]
            if files:self.open_file(files[0]);return
        self.status.set('剪贴板中没有可读取的视频或 GIF 文件；截图请在素材库“粘贴图片”。')

    def drop(self,event):
        paths=self.window.tk.splitlist(event.data)
        if not paths:return 'refuse_drop'
        return 'copy' if self.open_file(paths[0]) else 'refuse_drop'

    def progress(self,stage,percent):self.events.put(('progress',stage,percent))

    def cancel_processing(self):
        self.cancel.set();self.status.set('已取消后续处理，正在结束当前步骤；原件和已完成文件保留。')

    def submit(self,fn,label):
        if self.busy:self.status.set('当前任务处理中，可取消后继续。');return False
        self.busy=True;self.cancel.clear();self.status.set(label);self.bar['value']=0
        self.update_source_state();self.progress_row.pack(fill='x')
        from emoji_bridge.task_activity import begin,finish
        from emoji_bridge.task_budget import admission
        activity=self.activity=begin(label)
        def work():
            try:
                with admission(label,cancel=self.cancel,waiting=lambda text:self.progress(text,0)):
                    result=fn()
                finish(activity,cancel=self.cancel);self.events.put(('done',result))
            except Exception as exc:
                finish(activity,error=exc,cancel=self.cancel);self.events.put(('error',str(exc)))
        self.pool.submit(work);return True

    def open_file(self,path):
        if self.busy:self.status.set('当前任务处理中，可取消后打开另一文件。');return False
        self.stop_preview();self.playback_keys.blur();self.seek_token+=1;self.result_item=None;self.edit_result.state(['disabled'])
        self.seek_stop.set()
        self.source=None;self.metadata=None;self.frame_cache=None
        self.output=None;self.card.configure(image='',text='新文件读取中；生成成品后可以拖出')
        def work():
            from emoji_bridge.video import probe
            from emoji_bridge.video_preview import FrameCache
            source=own_source(self.store,path,self.cancel);metadata=probe(source['path'],cancel=self.cancel,progress=self.progress)
            cache=FrameCache(source['path'],metadata,self.store.root/'video-preview')
            cover=cache.get(0,720,self.cancel)
            return {'source':source,'metadata':metadata,'preview_image':cover}
        return self.submit(work,'读取本地视频与预览…')

    def seek(self,value,immediate=False):
        from video_timeline import clock
        self.position.set(float(value));self.timeline.set_position(float(value))
        self.position_label.configure(text=f'{clock(float(value))} / {clock(self.metadata["duration"] if self.metadata else 0)}')
        if self.seek_after and immediate:self.window.after_cancel(self.seek_after);self.seek_after=None
        if not self.seek_after:self.seek_after=self.window.after(1 if immediate else 65,self.show_frame)

    def show_frame(self):
        self.seek_after=None
        if not self.frame_cache or self.busy:return
        self.seek_token+=1;token=self.seek_token;seconds=self.position.get();cache=self.frame_cache
        self.seek_stop.set();self.seek_stop=threading.Event();cancel=self.seek_stop
        if self.seek_future:self.seek_future.cancel()
        def work():
            try:self.events.put(('seek',token,cache.get(seconds,720,cancel)))
            except Exception as exc:
                if not cancel.is_set():self.events.put(('seek_error',token,str(exc)))
        self.seek_future=self.seek_pool.submit(work)

    def options(self):
        if not self.source:raise ValueError('请先打开视频或 GIF')
        start,end=float(self.start.get()),float(self.end.get());fps=float(self.fps.get());width=int(self.width.get())
        if not (0<=start<end<=self.metadata['duration']+.02):raise ValueError('开始与结束须在视频时长内，且结束晚于开始')
        if not 1<=fps<=60 or width<0:raise ValueError('帧率请输入 1～60，宽度输入正数或0（原尺寸）')
        return start,end,fps,width or None

    def play(self):
        if self.stream:self.stop_preview();return
        if self.busy:return
        try:start,end,_,_=self.options()
        except ValueError as exc:self.status.set(str(exc));return
        from emoji_bridge.video_preview import VideoStream
        import time
        self.seek_token+=1
        self.seek_stop.set()
        if self.seek_after:self.window.after_cancel(self.seek_after);self.seek_after=None
        position=self.position.get()
        if not start<=position<end-.05:position=start
        self.stream=VideoStream(self.source['path'],self.metadata,position,end)
        self.play_started=None;self.play_origin=position;self.next_frame=0
        self.play_button.configure(text='暂停 · 空格');self.status.set('正在播放选区 · 空格暂停 · 静音')

    def stop_preview(self):
        if self.stream:
            self.stream.close();self.stream=None
            self.status.set('已暂停 · 空格继续 · 保留当前帧')
        if hasattr(self,'play_button'):self.play_button.configure(text='播放 · 空格')

    def set_view_active(self,active):
        self.playback_keys.set_active(active)
        if not active:self.stop_preview()

    def cutout(self):
        try:
            start,end,_,_=self.options();edge=int(self.cutout_edge.get());fps=float(self.cutout_fps.get())
            if edge<0:raise ValueError('最长边须为正数，0表示原尺寸')
        except ValueError as exc:self.status.set(str(exc));return
        if self.busy:return
        self.stop_preview();source=dict(self.source)
        self.output=None;self.card.configure(image='',text='正在准备本次动态主体…')
        def work():
            from emoji_bridge.dynamic_cutout import video_animation,cutout_animation,save_subject
            import time
            began=time.perf_counter()
            def progress(stage,done,total):self.progress(stage,done/max(total,1)*100)
            animation=video_animation(source['path'],start,end,max_edge=edge,fps=fps,cancel=self.cancel,progress=progress,metadata=self.metadata)
            decoded=time.perf_counter()
            result=cutout_animation(animation,max_edge=0,cancel=self.cancel,progress=progress)
            inferred=time.perf_counter()
            result['source_info']={'source_sha256':source['sha256'],'start':start,'end':end,'fps':fps,'max_edge':edge}
            item,doc,directory=save_subject(self.store,result,name=Path(source['name']).stem+' · 动态主体',cancel=self.cancel,progress=progress)
            return {'output':self.store.original(item['id']),'cover':self.store.original(item['id']),'item':item,'warning':None,'edit_draft':directory,'edit_document':doc,'seconds':result['seconds'],
                'timings':{'decode':decoded-began,'matting':inferred-decoded,'encode_save':time.perf_counter()-inferred,'total_before_editor':time.perf_counter()-began,'cache_hit':result['cache_hit'],'stages':result['stages']}}
        self.submit(work,'准备动态主体；模型只加载一次…')

    def convert(self,format):
        try:
            if format=='png':
                if not self.source:raise ValueError('请先打开视频或 GIF')
                start,end,fps,width=0,self.metadata['duration'],None,None
            else:start,end,fps,width=self.options()
            if format=='gif':
                out_width=width or self.metadata['width'];out_height=round(out_width*self.metadata['height']/self.metadata['width'])
                frames=math.ceil((end-start)*fps)
                from emoji_bridge.frame_store import MAX_FRAME_COUNT,MAX_FRAME_PIXELS,MAX_SPOOL_BYTES
                if frames>MAX_FRAME_COUNT or out_width*out_height>MAX_FRAME_PIXELS or out_width*out_height*frames*4>MAX_SPOOL_BYTES:
                    raise ValueError('此设置超过18000帧、单帧3200万像素或8 GiB帧缓存范围，请调整选段、宽度或GIF帧率；原视频不变')
        except ValueError as exc:self.status.set(str(exc));return
        if self.busy:return
        self.stop_preview();source=dict(self.source);seconds=self.position.get();audio=self.audio.get()
        self.output=None;self.card.configure(image='',text='正在生成本次成品…')
        def work():
            from emoji_bridge.video import convert,frame
            if format=='png':output=frame(source['path'],seconds,root=self.store.root/'video-output',cancel=self.cancel,progress=self.progress)
            else:output=convert(source['path'],start,end,format,root=self.store.root/'video-output',fps=fps if format=='gif' else None,width=width,audio=audio,cancel=self.cancel,progress=self.progress)
            provenance={'schema':'video-work-v1','source_sha256':source['sha256'],'source_path':source['path'],'start':start,'end':end,'frame_time':seconds if format=='png' else None,'format':format,'width':None if format=='png' else width,'fps':fps if format=='gif' else None}
            item=None;warning=None
            if format!='mp4':
                try:item,_=self.store.import_file(output,kind='edited',name=Path(source['name']).stem+(' · 当前帧' if format=='png' else ' · GIF片段'),source=json.dumps(provenance,ensure_ascii=False),cancel=self.cancel)
                except (ValueError,OSError) as exc:warning='文件已生成，但入库未完成：'+str(exc)+'。可先拖出 / 导出，再调整设置重试。'
            cover=frame(output,0,root=self.store.root/'video-output',width=96,cancel=self.cancel,progress=self.progress) if format=='mp4' else output
            return {'output':Path(output),'cover':cover,'item':item,'warning':warning}
        self.submit(work,'正在生成 '+format.upper()+'…')

    def drag(self,event=None):
        if not self.output:return ('refuse_drop','DND_Files',())
        return ('copy','DND_Files',(str(self.output),))

    def export(self):
        if not self.output:self.status.set('请先用“另存为”生成文件。');return
        path=filedialog.asksaveasfilename(parent=self.window,defaultextension=self.output.suffix,filetypes=[(self.output.suffix[1:].upper(),'*'+self.output.suffix)])
        if path:
            source=self.output
            if Path(path).resolve()==source.resolve():return
            self.submit(lambda:(shutil.copyfile(source,path) and {'message':'已导出已有文件，没有重新转换。'}),'导出已有文件…')

    def image(self,path,card=False):
        with Image.open(path) as source:value=source.convert('RGBA')
        if card:
            value.thumbnail((76,44),Image.Resampling.LANCZOS);self.card_photo=ImageTk.PhotoImage(value)
            self.card.configure(image=self.card_photo,text=f'  拖出 {self.output.suffix[1:].upper()} · 已保存在本机')
        else:self.show_image(value)

    def show_image(self,value):
        self.original_preview=value;value=value.copy()
        value.thumbnail((max(100,self.preview.winfo_width()-4),max(100,self.preview.winfo_height()-4)),Image.Resampling.LANCZOS)
        self.photo=ImageTk.PhotoImage(value);self.preview.configure(image=self.photo,text='')

    def resize_preview(self,event=None):
        if self.resize_after:self.window.after_cancel(self.resize_after)
        def resize():
            self.resize_after=None
            if self.original_preview is not None and not self.stream:self.show_image(self.original_preview)
        self.resize_after=self.window.after(70,resize)

    def poll(self):
        if self.closed:return
        try:
            while True:
                event=self.events.get_nowait()
                if event[0]=='seek':
                    if event[1]==self.seek_token and not self.stream:self.show_image(event[2])
                    continue
                if event[0]=='seek_error':
                    if event[1]==self.seek_token:self.status.set('预览未就绪：'+event[2])
                    continue
                if event[0]=='progress':self.status.set(event[1]);self.bar['value']=event[2];continue
                self.busy=False;self.update_source_state();self.progress_row.pack_forget()
                if event[0]=='error':self.status.set('未完成：'+event[1]+'；原文件保留，可重试。');self.card.configure(text='未生成本次成品');continue
                value=event[1];self.bar['value']=100
                if 'transcript' in value:self.speech.loaded(value)
                if 'source' in value:
                    from emoji_bridge.video_preview import FrameCache
                    self.source=value['source'];self.metadata=value['metadata'];duration=self.metadata['duration']
                    self.update_source_state()
                    self.frame_cache=FrameCache(self.source['path'],self.metadata,self.store.root/'video-preview')
                    self.position.set(0);self.start.set('0');self.end.set(f'{min(2,duration):.3f}');self.refresh_recent()
                    self.selection=(0,round(min(2,duration),3))
                    from video_timeline import clock
                    self.timeline.set_source(self.frame_cache,end=min(2,duration));self.position_label.configure(text=f'{clock(0)} / {clock(duration)}')
                    self.status.set(f'{self.source["name"]} · {duration:.2f}秒 · {self.metadata["width"]}×{self.metadata["height"]}')
                    self.card.configure(image='',text='生成后可直接拖出成品')
                if 'frame' in value:self.image(value['frame'])
                if 'preview_image' in value:self.show_image(value['preview_image'])
                if 'edit_draft' in value and self.on_edit and not self.cancel.is_set():
                    import time
                    began=time.perf_counter()
                    if self.on_edit(value['edit_draft'],prepared_document=value['edit_document']):self.edit_return()
                    self.last_timings={**value.get('timings',{}),'enter_editor':time.perf_counter()-began}
                if 'output' in value:
                    self.output=value['output'];self.image(value['cover'],card=True);self.result_item=value['item']
                    if not self.footer.winfo_manager():self.footer.pack(fill='x',before=self.status_label)
                    self.edit_result.state(['!disabled'] if self.result_item else ['disabled'])
                    if value['item'] and self.on_saved:self.on_saved(value['item'])
                    self.status.set('已生成并加入素材库，可拖出或继续编辑。' if value['item'] else 'MP4 已保存，可拖出或另存文件。')
                    if value.get('warning'):self.status.set(value['warning'])
                if 'message' in value:self.status.set(value['message'])
        except queue.Empty:pass
        if self.stream:
            import time
            from video_timeline import clock
            now=time.monotonic()
            if now>=self.next_frame:
                try:
                    frame,position=self.stream.frames.get_nowait()
                    if frame is None:
                        self.stop_preview();self.status.set('选区播放结束' if position=='结束' else '预览未完成：'+str(position))
                        if position=='结束':
                            end=float(self.end.get());self.position.set(end);self.timeline.set_position(end)
                            self.position_label.configure(text=f'{clock(end)} / {clock(self.metadata["duration"])}')
                    else:
                        if self.play_started is None:self.play_started=now
                        self.show_image(frame);self.position.set(position);self.timeline.set_position(position)
                        self.position_label.configure(text=f'{clock(position)} / {clock(self.metadata["duration"])}')
                        self.next_frame=self.play_started+(position-self.play_origin)+1/self.stream.fps
                except queue.Empty:pass
        self.poll_id=self.window.after(20,self.poll)

    def close(self):
        recorder=getattr(self,'recorder_window',None)
        if recorder and not recorder.closed:
            recorder.close()
            if not recorder.closed:return
        self.closed=True;self.cancel.set();self.playback_keys.close();self.stop_preview();self.window.after_cancel(self.poll_id)
        if self.seek_after:self.window.after_cancel(self.seek_after)
        self.seek_stop.set();self.seek_pool.shutdown(wait=False,cancel_futures=True)
        if self.resize_after:self.window.after_cancel(self.resize_after)
        self.pool.shutdown(wait=False,cancel_futures=True);self.window.destroy()
