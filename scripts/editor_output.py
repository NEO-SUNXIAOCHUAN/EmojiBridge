"""A distinct drag surface, asynchronously bound to one immutable scene revision."""
from concurrent.futures import ThreadPoolExecutor, CancelledError
from copy import copy
import threading
import queue
import tkinter as tk
from tkinter import ttk,filedialog
from PIL import ImageTk
from ui_dpi import px
from emoji_bridge import work_output
from emoji_bridge.work_output import copy_image
from emoji_bridge.file_io import copy_file,check_cancel


def prepare_output(*args, **kwargs):
    return work_output.prepare_output(*args, **kwargs)


class FinishedOutput(ttk.Frame):
    def __init__(self,parent,editor,*,compact=False):
        super().__init__(parent)
        self.editor=editor;self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='finished-work')
        self.compact=compact;self.preview_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='finished-preview');self.preview_future=None;self.preview_key=None
        self.future=None;self.request_key=None;self.ready_key=None;self.observed=None;self.settled=0
        self.path=None;self.photo=None;self.pending=None;self.failed=None;self.closed=False;self.operation_future=None
        self.size=None;self.request_size=None;self.failed_size=None;self.ready_size=None;self.retry_after_cancel=False
        self.cancel=threading.Event();self.progress=queue.Queue()
        self.operation_cancel=threading.Event()
        from editor_drag_card import DragCard
        self.card=DragCard(self,self);self.card.pack(side='left',padx=px(self,5))
        self.card.drag_source_register(1,'DND_Files');self.card.dnd_bind('<<DragInitCmd>>',self.drag_start)
        self.card.dnd_bind('<<DragEndCmd>>',self.drag_end)
        self.copy_button=ttk.Button(self,text='复制图片',width=8,command=lambda:self.use('copy'));self.copy_button.pack(side='left')
        self.save_button=ttk.Button(self,text='另存为…',width=8,command=self.save_as);self.save_button.pack(side='left',padx=3)
        if compact:self.copy_button.pack_forget();self.save_button.pack_forget()
        self.scale_choice=tk.StringVar(value='原尺寸')
        self.scale_box=ttk.Combobox(self,textvariable=self.scale_choice,values=('原尺寸','50% 输出','25% 输出'),state='readonly',width=9)
        self.scale_box.bind('<<ComboboxSelected>>',lambda event:self.prepare())
        self.cancel_button=ttk.Button(self,text='取消准备',width=8,command=self.cancel_prepare)
        self.job=self.after(100,self.poll)

    def key(self):
        e=self.editor
        painting=getattr(getattr(e,'raster',None),'points',None)
        return e.doc.revision if e.doc and not e.inline and not e.gesture and not painting and not getattr(e,'text_dirty',False) and not getattr(e,'initial_workspace',False) else None

    def output_size(self):
        if not self.editor.doc:return None
        factor={'50% 输出':.5,'25% 输出':.25}.get(self.scale_choice.get(),1.) if self.editor.doc.animation else 1.
        return tuple(max(1,round(n*factor)) for n in self.editor.doc.size)

    def ready(self):return self.ready_key is not None and self.ready_key==self.key() and self.ready_size==self.output_size() and self.path and self.path.exists()

    def show_ready(self):
        if self.card.preview is None and self.photo:self.card.preview=self.photo
        self.card.configure(image=self.photo,text=f'拖出{self.path.suffix[1:].upper()}\n{self.size[0]}×{self.size[1]} · 就绪')

    def prepare(self):
        if self.editor.busy:return
        if not self.editor.finish_text():return
        if self.future and self.cancel.is_set():self.retry_after_cancel=True
        self.failed=None;self.settled=5;self.start(explicit=True)

    def preview_current(self,key):
        if self.preview_future and self.preview_future.done():
            try:
                revision,image=self.preview_future.result()
                if revision==key:self.card.set_preview(image)
                image.close()
            except Exception:pass
            self.preview_future=None
        if key is None or key==self.preview_key or self.preview_future:return
        self.preview_key=key;snapshot=copy(self.editor.doc)
        def render():
            from editor_timeline import AnimationCovers
            from emoji_bridge.animated_edit import GifSource
            source=snapshot.animation or GifSource(b'',(snapshot._state.base,),(100,),None)
            return key,AnimationCovers(source,snapshot).get(0,320,threading.Event())
        self.preview_future=self.preview_pool.submit(render)

    def start(self,explicit=False):
        key=self.key()
        size=self.output_size()
        if self.closed or self.editor.closed or self.editor.busy or getattr(self.editor,'save_waiting',False) or key is None or self.future or self.operation_future or self.ready() or (self.failed==key and self.failed_size==size):return
        snapshot=copy(self.editor.doc);self.request_key=key
        self.request_size=size;self.request_explicit=explicit
        self.cancel=threading.Event()
        if snapshot.animation and not self.compact:self.cancel_button.pack(side='left') if not self.compact else None
        self.card.configure(text='拖出成品\n正在准备…',image='')
        if explicit:self.editor.status.set('正在准备当前成品，可点卡片右侧取消。')
        self.future=self.submit_output(prepare_output,snapshot,self.editor.store.root,visible=explicit,continue_pending=bool(self.pending),cancel=self.cancel,
            output_size=size,progress=lambda n,total,phase:self.progress.put((key,size,n,total,phase)))
        self.card.draw()

    def submit_output(self,fn,*args,visible=True,continue_pending=False,**kwargs):
        from emoji_bridge.task_activity import begin,finish
        current=getattr(self,'activity',{})
        activity=(current if current.get('active') else begin('准备 / 导出当前成品')) if visible else None
        if activity:self.activity=activity
        token=kwargs.get('cancel',self.operation_cancel)
        def work():
            try:
                result=fn(*args,**kwargs)
                if activity and (not continue_pending or token.is_set()):finish(activity,cancel=token)
                return result
            except Exception as exc:
                if activity:finish(activity,error=exc,cancel=token)
                raise
        return self.pool.submit(work)

    def request(self,callback,on_error=None,*,cancel=None):
        """Join the current output; callbacks run on Tk's thread, bound to revision and size."""
        if self.closed or self.editor.busy or not self.editor.doc or not self.editor.finish_text():
            if on_error:on_error(CancelledError('当前作品仍在编辑或忙碌，请稍后再试'))
            return None
        self._fail_pending(CancelledError('已由新的成品操作替换'))
        key=self.key()
        self.pending=(key,self.output_size(),callback,on_error,cancel)
        self.prepare()
        self._complete_pending()
        return key

    def _fail_pending(self,error):
        pending=self.pending;self.pending=None
        if pending and getattr(self,'activity',{}).get('active'):
            from emoji_bridge.task_activity import finish
            finish(self.activity,error=error)
        if pending and pending[3]:pending[3](error)

    def _complete_pending(self):
        if not self.pending:return
        revision,size,callback,on_error,cancel=self.pending
        if cancel is not None and cancel.is_set():
            self._fail_pending(CancelledError('已取消成品操作；原件和草稿保留'));return
        if revision!=self.key() or size!=self.output_size():
            self._fail_pending(CancelledError('作品或输出尺寸已改变，请重新操作'));return
        if self.editor.busy:return
        if not self.ready():return
        self.pending=None
        try:callback(self.path,revision)
        except Exception as exc:
            if on_error:on_error(exc)
            else:self.editor.status.set('成品操作未完成：'+str(exc))

    def cancel_prepare(self):
        self.operation_cancel.set()
        self.cancel.set();self.retry_after_cancel=False;self.failed=self.key();self.failed_size=self.output_size()
        self._fail_pending(CancelledError('已取消成品准备；原件和草稿保留'))
        self.card.configure(text='拖出成品\n已取消，点此准备',image='')
        self.editor.status.set('已取消成品操作；完成文件保留，可重新准备。')

    def poll(self):
        if self.closed:return
        key=self.key()
        size=self.output_size()
        dynamic=bool(self.editor.doc and self.editor.doc.animation)
        if dynamic and not self.editor.embedded:self.scale_box.pack(side='left',padx=3)
        else:self.scale_box.pack_forget()
        self.copy_button.configure(text='静态复制不可用' if dynamic else '复制图片',width=12 if dynamic else 8,state='disabled' if dynamic else 'normal')
        if self.future and (self.request_key!=key or self.request_size!=size):self.cancel.set()
        try:
            while True:
                revision,dimensions,n,total,phase=self.progress.get_nowait()
                token=self.operation_cancel if self.operation_future else self.cancel
                if revision==key and dimensions==size and not token.is_set():self.card.configure(text=f'{phase}\n{n}/{total}',image='')
        except queue.Empty:pass
        if key!=self.observed or size!=getattr(self,'observed_size',None):
            self.card.set_preview(None);self.preview_key=None
            self.observed=key;self.observed_size=size;self.settled=0
            if self.ready():self.show_ready()
            elif self.failed==key and self.failed_size==size:self.card.configure(text='拖出成品\n点此重试',image='')
            else:self.card.configure(text='拖出成品\n等待准备…' if key is not None else '拖出成品\n编辑完成后准备',image='')
        else:self.settled+=1
        self.preview_current(key)
        if self.future and self.future.done():
            future=self.future;self.future=None
            retry=self.retry_after_cancel and self.cancel.is_set()
            self.cancel_button.pack_forget()
            try:
                path,preview,size=future.result()
                if self.cancel.is_set() and self.pending and not retry:self._fail_pending(CancelledError('成品准备已取消；未启动保存或发送'))
                if self.request_key==key and self.request_size==self.output_size() and not self.cancel.is_set():
                    self.ready_key=key;self.ready_size=size;self.path=path;self.card.set_preview(preview);self.photo=self.card.preview;self.size=size;self.failed=None;self.show_ready()
                    if getattr(self,'request_explicit',False) and not self.pending:self.editor.status.set('成品已就绪，按住卡片即可拖出。')
            except Exception as exc:
                self.failed=self.request_key;self.failed_size=self.request_size
                # The shared resource queue raises InterruptedError on cancel;
                # encoding workers use CancelledError. Both settle the old job,
                # while an explicit new request retains its own callback.
                if retry and isinstance(exc,(CancelledError,InterruptedError)):
                    self.failed=None
                elif self.request_key==key and self.request_size==self.output_size():
                    retry=False
                    cancelled=isinstance(exc,(CancelledError,InterruptedError)) and self.cancel.is_set()
                    self.card.configure(text='拖出成品\n已取消，点此准备' if cancelled else '拖出成品\n点此重试',image='')
                    self.editor.status.set('已取消准备，原件和草稿保留；点击卡片可重试。' if cancelled else '成品准备未完成：'+str(exc));self._fail_pending(exc)
            self.retry_after_cancel=False
            if retry:self.start(explicit=True)
        heavy=dynamic and (len(self.editor.doc.animation.frames)>100 or
            self.editor.doc.size[0]*self.editor.doc.size[1]*len(self.editor.doc.animation.frames)>64_000_000)
        try:typing=self.editor.window.focus_get() is self.editor.text
        except (KeyError,tk.TclError):
            # A native ttk combobox popdown has no Python widget counterpart.
            # Defer automatic preparation while its keyboard focus is active.
            typing=True
        marking=getattr(getattr(self.editor,'cutout',None),'marking',False)
        # Prompt edits are not image edits. Do not encode an animation or write
        # an output per stroke; explicit save/export still calls prepare().
        if self.settled>=3 and not heavy and not typing and not marking:self.start()
        elif heavy and not self.future and not self.ready() and self.failed!=key:
            self.card.configure(text='拖出成品\n点击准备完整动图',image='')
        self._complete_pending()
        if self.operation_future and self.operation_future.done():
            try:
                result=self.operation_future.result()
                self.editor.status.set(result if isinstance(result,str) else self.operation_message)
            except Exception as exc:self.editor.status.set(str(exc))
            self.operation_future=None;self.cancel_button.pack_forget()
        self.job=self.after(100,self.poll)

    def save_as(self):
        if not self.editor.doc:return
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label='独立兼容副本…',command=self.compatibility_copy)
        if self.editor.doc.animation:
            menu.add_command(label='动态成品（GIF / APNG / WebP）…',command=lambda:self.use('export'))
            menu.add_command(label='高质量 GIF（gifski）…',command=self.high_quality_gif)
            menu.add_command(label='PNG 图片（当前合成帧）',command=lambda:self.use('frame'))
        else:menu.add_command(label='PNG 图片（完整作品）',command=lambda:self.use('export'))
        if self.editor.doc.animation and getattr(self.editor,'open_video',None):
            menu.add_separator();menu.add_command(label='MP4（原色合成，透明区域填白）',command=self.to_video)
        menu.tk_popup(self.save_button.winfo_rootx(),self.save_button.winfo_rooty()+self.save_button.winfo_height())

    def high_quality_gif(self):
        if self.operation_future or self.editor.busy or not self.editor.doc or not self.editor.finish_text():return
        destination=filedialog.asksaveasfilename(parent=self.editor.window,title='高质量GIF · 透明阈值128，高质量不保证更小',defaultextension='.gif',filetypes=[('GIF 动图','*.gif')])
        if not destination:return
        snapshot=copy(self.editor.doc);size=self.output_size();token=self.operation_cancel=threading.Event();self.cancel_button.pack(side='left') if not self.compact else None
        def encode():
            path,_,_=prepare_output(snapshot,self.editor.store.root,format='gifski',output_size=size,cancel=token,progress=lambda n,t,s:self.progress.put((snapshot.revision,size,n,t,s)))
            copy_file(path,destination,cancel=token)
        self.operation_future=self.submit_output(encode);self.operation_message='高质量 GIF 已导出，原件及完整透明草稿保留'
        self.editor.status.set('准备高质量 GIF 编码器 / 首次下载…')

    def export_gif(self):
        if self.operation_future or self.editor.busy or not self.editor.doc or not self.editor.finish_text():return
        destination=filedialog.asksaveasfilename(parent=self.editor.window,title='导出 GIF 动图',defaultextension='.gif',filetypes=[('GIF 动图','*.gif')])
        if not destination:return
        snapshot=copy(self.editor.doc);size=self.output_size();self.cancel.set()
        token=self.operation_cancel=threading.Event()
        self.cancel_button.pack(side='left') if not self.compact else None
        def export():
            path,_,_=prepare_output(snapshot,self.editor.store.root,format='gif',output_size=size,cancel=token,
                progress=lambda n,t,s:self.progress.put((snapshot.revision,size,n,t,s)))
            copy_file(path,destination,cancel=token)
        self.operation_future=self.submit_output(export)
        self.operation_message='GIF 已导出；原件及透明草稿保留。'
        self.editor.status.set('正在导出 GIF…')

    def to_video(self):
        if self.operation_future or self.editor.busy or not self.editor.doc or not self.editor.finish_text():return
        destination=filedialog.asksaveasfilename(parent=self.editor.window,title='导出 MP4 · 透明区域填白，不经GIF转码',defaultextension='.mp4',filetypes=[('MP4 视频','*.mp4')])
        if not destination:return
        snapshot=copy(self.editor.doc);size=self.output_size();self.cancel.set()
        token=self.operation_cancel=threading.Event()
        key=snapshot.revision;self.cancel_button.pack(side='left') if not self.compact else None
        def export():
            path,_,_=work_output.prepare_video_output(snapshot,self.editor.store.root,output_size=size,cancel=token,
                progress=lambda n,total,phase:self.progress.put((key,size,n,total,phase)))
            copy_file(path,destination,cancel=token)
        self.operation_future=self.submit_output(export)
        self.operation_message='MP4已由原色合成帧导出；透明区域填白，奇数尺寸补齐1像素；原件和草稿保留。'
        self.editor.status.set('正在直接编码 MP4，保留原帧时序…')

    def compatibility_copy(self):
        if self.operation_future or self.editor.busy:return
        from compatibility_dialog import configure,generate
        choice=configure(self.editor.window,self.editor.store)
        if not choice:return
        def use_ready(path,revision):
            self.operation_cancel=threading.Event();self.cancel_button.pack(side='left') if not self.compact else None
            self.operation_message='兼容副本已完成；原件和草稿保留。'
            size=self.output_size()
            self.operation_future=self.submit_output(generate,self.editor.store,choice,files=[path],cancel=self.operation_cancel,
                progress=lambda n,total,phase:self.progress.put((revision,size,n,total,phase)))
            self.editor.status.set('后台准备独立兼容副本，可取消。')
        self.request(use_ready,lambda exc:self.editor.status.set(str(exc)))

    def use(self,action):
        if self.operation_future or self.editor.busy or not self.editor.doc or not self.editor.finish_text():return
        destination=None
        dynamic=bool(self.editor.doc.animation)
        frame_index=self.editor.animation_frame if action=='frame' and dynamic else None
        snapshot=copy(self.editor.doc);output_size=self.output_size()
        if action=='copy' and dynamic:
            self.editor.status.set('复制图片不能保留动画。请拖出或导出 GIF；需要静态图时主动提取一帧。');return
        if action in ('export','frame'):
            chosen=work_output.preferred_format(snapshot) if dynamic and action!='frame' else 'png'
            extension='.'+('png' if chosen=='apng' else chosen)
            title=f'另存为 PNG · 当前合成帧 {frame_index+1}' if frame_index is not None else '另存为当前成品'
            types=[('GIF 动图（256色、10毫秒精度）','*.gif'),('APNG 动图（无损透明）','*.png'),('动态 WebP（无损透明）','*.webp')] if dynamic and action!='frame' else [('PNG 图片','*.png')]
            destination=filedialog.asksaveasfilename(parent=self.editor.window,title=title,defaultextension=extension,filetypes=types)
            if not destination:return
            from pathlib import Path
            if Path(destination).suffix.lower()!=extension:
                selected={'.gif':'gif','.png':'apng','.webp':'webp'}.get(Path(destination).suffix.lower()) if dynamic and action!='frame' else None
                if not selected:self.editor.status.set('请选择列表中的输出格式；原件与草稿保留。');return
                token=self.operation_cancel=threading.Event();self.cancel_button.pack(side='left') if not self.compact else None
                def encode():
                    path,_,_=prepare_output(snapshot,self.editor.store.root,output_size=output_size,format=selected,cancel=token,
                        progress=lambda n,total,phase:self.progress.put((snapshot.revision,output_size,n,total,phase)))
                    copy_file(path,destination,cancel=token)
                self.operation_future=self.submit_output(encode);self.operation_message='动态成品已导出为 '+selected.upper()
                self.editor.status.set('正在编码 '+selected.upper()+'…');return
        if frame_index is not None:
            token=self.operation_cancel=threading.Event();self.cancel_button.pack(side='left') if not self.compact else None
            def export_frame():
                path,_,_=prepare_output(snapshot,self.editor.store.root,output_size=output_size,frame_index=frame_index,cancel=token)
                copy_file(path,destination,cancel=token)
            self.operation_future=self.submit_output(export_frame)
            self.operation_message=f'已另存当前合成帧 {frame_index+1} 为 PNG，保留透明信息；原 GIF、图层与草稿保持不变。'
            self.editor.status.set('正在另存当前合成帧…');return
        def use_ready(path,revision):
            token=self.operation_cancel=threading.Event();self.cancel_button.pack(side='left') if not self.compact else None
            if action=='copy':
                self.operation_future=self.submit_output(copy_image,path,self.winfo_id())
                self.operation_message='完整成品已复制为图片（PNG / DIBV5），未发送；目标软件可能改变透明显示。'
            else:
                self.operation_future=self.submit_output(copy_file,path,destination,cancel=token)
                self.operation_message='已导出当前 '+path.suffix[1:].upper()+' 成品；未发送或添加收藏。'
        self.request(use_ready,lambda exc:self.editor.status.set('成品操作未完成：'+str(exc)))

    def drag_start(self,event=None):
        if self.card.cancel_hit():return ('refuse_drop','DND_Files',())
        self.card.dragged=True;self.card.hide_tip()
        if not self.ready():
            self.prepare();self.editor.status.set('成品正在准备，准备完成后按住整张卡片拖出。')
            return ('refuse_drop','DND_Files',())
        return ('copy','DND_Files',(str(self.path),))

    def drag_end(self,event=None):
        self.card.pressed=None;self.card.dragged=False;self.card.draw()
        cancelled=getattr(event,'action',None) in ('refuse_drop','none')
        self.editor.status.set('拖放已取消，成品仍可再次拖出。' if cancelled else '拖放已结束，文件继续保留；聊天输入后请自行确认发送。')

    def close(self):
        # Closing callers have already cancelled their task. Never run a UI
        # continuation after the owning editor/page has begun destruction.
        self.pending=None
        self.card.hide_tip();self.preview_pool.shutdown(wait=False,cancel_futures=True)
        self.closed=True;self.cancel.set();self.operation_cancel.set();self.after_cancel(self.job);self.pool.shutdown(wait=False,cancel_futures=True);self.photo=None
