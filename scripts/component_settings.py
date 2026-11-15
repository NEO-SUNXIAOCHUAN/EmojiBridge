"""The same release component manager for native editing tools."""
def show_if_missing(parent,message):
    if str(message).startswith('需要安装“'):
        parent.after_idle(lambda:show(parent))

def show(parent):
    import tkinter as tk
    from tkinter import ttk,filedialog
    import queue,threading,webbrowser
    from emoji_bridge.release_components import status,install,catalog
    data=catalog()
    if not data:return
    window=tk.Toplevel(parent);window.title('可选组件');window.geometry('700x620')
    body=ttk.Frame(window,padding=20);body.pack(fill='both',expand=True)
    ttk.Label(body,text='可选组件',style='Heading.TLabel').pack(anchor='w')
    ttk.Label(body,text='下载 ZIP 后直接导入，无需解压或移动模型。当前作品保留。',wraplength=640).pack(anchor='w',pady=8)
    from ui_style import ScrollBody
    scroll=ScrollBody(body);scroll.pack(fill='both',expand=True)
    rows=scroll.body
    note=tk.StringVar();ttk.Label(body,textvariable=note,wraplength=640).pack(fill='x',pady=8)
    events=queue.Queue();cancel=threading.Event();busy=[False]
    def refresh():
        for child in rows.winfo_children():child.destroy()
        labels={'installed':'已安装','missing':'未安装','incompatible':'已有组件版本不兼容','corrupt':'文件校验失败'}
        for item in status():
            row=ttk.Frame(rows,padding=(0,10));row.pack(fill='x')
            ttk.Label(row,text=item['title']+' · '+labels[item['state']]).pack(anchor='w',fill='x')
            ttk.Label(row,text=f"{item['purpose']}\n下载 {item['bytes']/1048576:.1f} MB · 安装 {item['unpacked_bytes']/1048576:.1f} MB · {item['version']}",wraplength=600).pack(anchor='w',fill='x',pady=4)
            actions=ttk.Frame(row);actions.pack(anchor='w')
            ttk.Button(actions,text='下载组件',command=lambda u=item['url']:webbrowser.open(u)).pack(side='left')
            ttk.Button(actions,text='导入已下载组件包',command=lambda i=item['id']:begin(i)).pack(side='left',padx=8)
    def begin(ident):
        if busy[0]:return
        file=filedialog.askopenfilename(parent=window,title='选择对应组件 ZIP',filetypes=[('组件包','*.zip')])
        if not file:return
        busy[0]=True;cancel.clear();note.set('正在校验组件包…')
        def run():
            try:result=install(file,ident,cancel=cancel,progress=lambda s,d,t:events.put(('progress',f'{s} {d*100/max(t,1):.0f}%')));events.put(('done',result['text']))
            except Exception as exc:events.put(('done',str(exc)))
        threading.Thread(target=run,daemon=True).start()
    def poll():
        if not window.winfo_exists():return
        while not events.empty():
            kind,text=events.get();note.set(text)
            if kind=='done':busy[0]=False;refresh()
        window.after(100,poll)
    def close():
        if busy[0]:cancel.set();note.set('正在取消，结束后可关闭');return
        window.destroy()
    ttk.Button(body,text='取消当前导入',command=cancel.set).pack(side='left')
    ttk.Button(body,text='关闭',command=close).pack(side='right')
    window.protocol('WM_DELETE_WINDOW',close);refresh();poll()
