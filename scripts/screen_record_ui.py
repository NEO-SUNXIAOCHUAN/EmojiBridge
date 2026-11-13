"""Choose a region, explicitly start/stop, then use the existing clip editor."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import time
import tkinter as tk
from tkinter import ttk
from ui_dialogs import prepare_window
from emoji_bridge.screen_record import RegionRecording


class RecorderWindow:
    def __init__(self,parent,store,on_recorded):
        self.store=store;self.on_recorded=on_recorded;self.region=None;self.recorder=None;self.future=None;self.closed=False
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='region-record')
        self.window=tk.Toplevel(parent);self.window.title('EmojiBridge · 区域录屏');self.window.geometry('440x280');prepare_window(self.window,parent)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.bind('<Destroy>',self.destroyed,add='+')
        self.note=tk.StringVar(value='先拖选区域，再开始录制。无声音、12帧/秒，最长10分钟。')
        ttk.Label(self.window,textvariable=self.note,wraplength=360,padding=15).pack(fill='x')
        self.choose_button=ttk.Button(self.window,text='选择屏幕区域',command=self.choose);self.choose_button.pack(fill='x',padx=15,pady=4)
        self.start_button=ttk.Button(self.window,text='开始录制',command=self.start,state='disabled');self.start_button.pack(fill='x',padx=15,pady=4)
        self.stop_button=ttk.Button(self.window,text='停止并选段',command=self.stop,state='disabled');self.stop_button.pack(fill='x',padx=15,pady=4)
        self.job=self.window.after(100,self.poll)

    def choose(self):
        if self.future or self.recorder:return
        self.window.withdraw();overlay=tk.Toplevel(self.window);overlay.overrideredirect(True)
        # Win32 Tk rejects fullscreen on an override-redirect window.
        overlay.geometry(f'{overlay.winfo_screenwidth()}x{overlay.winfo_screenheight()}+0+0')
        overlay.attributes('-alpha',.25);overlay.attributes('-topmost',True)
        canvas=tk.Canvas(overlay,bg='black',cursor='crosshair',highlightthickness=0);canvas.pack(fill='both',expand=True)
        origin=[]
        def start(event):origin[:]=[event.x_root,event.y_root];canvas.delete('roi')
        def drag(event):
            if origin:
                canvas.delete('roi');canvas.create_rectangle(origin[0]-overlay.winfo_rootx(),origin[1]-overlay.winfo_rooty(),event.x,event.y,outline='white',width=3,tags='roi')
        def finish(event):
            if origin:
                x,y=origin;self.region=(min(x,event.x_root),min(y,event.y_root),abs(event.x_root-x),abs(event.y_root-y))
                self.note.set(f'区域 {self.region[2]}×{self.region[3]}。请将录屏面板移出选区，再点开始。')
                self.start_button.state(['!disabled'])
            overlay.destroy();self.window.deiconify()
        canvas.bind('<ButtonPress-1>',start);canvas.bind('<B1-Motion>',drag);canvas.bind('<ButtonRelease-1>',finish)
        overlay.bind('<Escape>',lambda e:(overlay.destroy(),self.window.deiconify()))

    def start(self):
        if not self.region or self.future or self.recorder:return
        target=self.store.root/'video-sources'/'recordings'/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.mp4')
        self.choose_button.state(['disabled']);self.start_button.state(['disabled']);self.note.set('正在准备录屏组件…')
        self.future=self.pool.submit(RegionRecording,self.region,target);self.phase='start'

    def stop(self):
        if self.future or not self.recorder:return
        self.stop_button.state(['disabled']);self.note.set('正在结束录制并保存…');self.phase='stop'
        self.future=self.pool.submit(self.recorder.stop)

    def poll(self):
        if self.closed:return
        if self.future and self.future.done():
            future=self.future;self.future=None
            try:
                result=future.result()
                if self.phase=='start':self.recorder=result;self.stop_button.state(['!disabled'])
                else:
                    self.recorder=None;self.note.set('录屏已保存，已打开选段；生成GIF或当前帧图片后自动回素材库。')
                    self.choose_button.state(['!disabled']);self.start_button.state(['!disabled']);self.on_recorded(result)
            except Exception as exc:
                self.recorder=None;self.note.set(str(exc));self.choose_button.state(['!disabled']);self.start_button.state(['!disabled'])
        if self.recorder and not self.future:
            self.note.set(f'正在录制 {time.monotonic()-self.recorder.started:.1f} 秒 · 点击停止后选段')
            if not self.recorder.running():self.stop()
        self.job=self.window.after(100,self.poll)

    def close(self):
        if self.future or self.recorder:
            self.stop();self.note.set('请等待录制保存完成，再关闭。');return
        self.closed=True;self.window.after_cancel(self.job);self.pool.shutdown(wait=False);self.window.destroy()

    def destroyed(self,event):
        if event.widget is not self.window or self.closed:return
        self.closed=True
        if self.recorder and not self.future:self.pool.submit(self.recorder.stop)
        elif self.future and self.phase=='start':
            def finish(future):
                try:future.result().stop()
                except Exception:pass
            self.future.add_done_callback(finish)
        self.pool.shutdown(wait=False)
