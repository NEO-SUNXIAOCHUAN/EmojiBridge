"""Explicit static-frame extraction with a bounded, background GIF preview."""
import queue
import tkinter as tk
from tkinter import ttk
from PIL import ImageTk
from emoji_bridge.material_preview import FrameStream
from playback_keys import PlaybackKeys
from ui_dialogs import Dialog


def choose(parent,item):
    dialog=Dialog(parent,'GIF 提取静态帧',width=560)
    window=dialog.window
    ttk.Label(dialog.body,text='播放找到需要的画面，再提取为静态贴图。原 GIF 保持动画。',wraplength=512).pack(anchor='w',pady=(0,12))
    area=ttk.Frame(dialog.body,height=330);area.pack(fill='both',expand=True);area.pack_propagate(False)
    preview=ttk.Label(area,anchor='center');preview.pack(fill='both',expand=True)
    row=ttk.Frame(dialog.body);row.pack(fill='x',pady=(16,8))
    frame=tk.IntVar(value=1);count=int(item['metadata']['frames'])
    status=tk.StringVar(value='正在准备画面…')
    state={'stream':None,'playing':False,'photo':None,'timer':None,'position':0,'ready':False}
    def stop():
        if state['stream']:state['stream'].close();state['stream']=None
        state['playing']=False
        if play.winfo_exists():play.configure(text='播放 · 空格')
    def load(index,playing=False):
        stop();state['position']=index;state['ready']=False
        play.state(['disabled'])
        state['stream']=FrameStream(item['path'],(512,330),start_frame=index,loop=False,end_frame=None if playing else index+1)
        state['playing']=playing;play.configure(text='暂停 · 空格' if playing else '播放 · 空格')
    def toggle():
        if state['playing']:stop();return
        index=state['position']
        load(0 if index>=count-1 else index,True)
    play=ttk.Button(row,text='播放 · 空格',command=toggle);play.pack(side='left')
    ttk.Label(row,text=f'帧 / {count}').pack(side='left',padx=(16,6))
    entry=ttk.Spinbox(row,from_=1,to=count,textvariable=frame,width=8);entry.pack(side='left')
    def seek(*_):
        try:
            value=frame.get()-1
            if not 0<=value<count:raise ValueError()
            load(value)
        except (ValueError,tk.TclError):status.set(f'请输入 1～{count} 的帧号')
    ttk.Button(row,text='查看此帧',command=seek).pack(side='right');entry.bind('<Return>',seek)
    ttk.Label(dialog.body,textvariable=status,style='Muted.TLabel').pack(anchor='w')
    def accept():
        if state['ready']:dialog.finish(state['position'])
    extract=ttk.Button(dialog.buttons,text='提取当前帧',command=accept,style='Editor.Primary.TButton');extract.pack(side='right')
    ttk.Button(dialog.buttons,text='取消',command=lambda:dialog.finish(None)).pack(side='right',padx=8)
    keys=PlaybackKeys(window,play,toggle,lambda:state['ready'])
    def poll():
        delay=25
        stream=state['stream']
        if stream:
            try:
                image,duration,index,total=stream.frames.get_nowait()
                if image is None:stop();status.set('预览未完成：'+str(duration))
                else:
                    state['photo']=ImageTk.PhotoImage(image);preview.configure(image=state['photo'])
                    state['position']=index;state['ready']=True;frame.set(index+1)
                    status.set(f'{index+1} / {total} 帧 · 提取的是当前显示画面')
                    if state['playing'] and index<total-1:delay=duration
                    else:stop()
            except queue.Empty:pass
        extract.state(['!disabled'] if state['ready'] else ['disabled'])
        play.state(['!disabled'] if state['ready'] else ['disabled'])
        state['timer']=window.after(delay,poll)
    load(0);poll()
    # Allocate the preview before the modal sizes itself, avoiding layout jumps.
    try:return dialog.run(preview)
    finally:
        stop()
        keys.close()
        # Destroy has already removed widget bindings and pending Tcl callbacks.
        if state['timer']:
            try:parent.after_cancel(state['timer'])
            except tk.TclError:pass
