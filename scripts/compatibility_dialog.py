"""Small explicit compatibility-copy settings, shared by library and editor."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog
from ui_dialogs import prepare_window
from concurrent.futures import CancelledError
from emoji_bridge.compatibility_copy import settings,set_settings,describe
from emoji_bridge.media import prepare_asset
from emoji_bridge.file_io import copy_file,check_cancel


def configure(parent,store,has_source=True):
    window=tk.Toplevel(parent);window.title('兼容副本');window.transient(parent);prepare_window(window,parent)
    body=ttk.Frame(window,padding=18);body.pack(fill='both',expand=True);result=[]
    target=tk.StringVar(value='微信');edge=tk.StringVar();fps=tk.StringVar();colors=tk.StringVar()
    for row,(label,var,values) in enumerate((('目标配置',target,('微信','QQ')),
            ('最长边',edge,('不缩小','240','320','480','640')),('帧率',fps,('原时序','10','15','20','30')),
            ('颜色数',colors,('255','128','64')))):
        ttk.Label(body,text=label).grid(row=row,column=0,sticky='w',padx=4,pady=5)
        box=ttk.Combobox(body,textvariable=var,values=values,state='readonly',width=16);box.grid(row=row,column=1)
        if row==0:box.bind('<<ComboboxSelected>>',lambda e:load())
    note=tk.StringVar(value='仅修改兼容副本；原件和完整质量导出保留。\n降低尺寸/帧率/颜色会损失细节，时长与动作速度保持。\n参数是本地选择，不保证客户端接受。')
    ttk.Label(body,textvariable=note,wraplength=370).grid(row=4,column=0,columnspan=2,pady=12)
    def load():
        value=settings(store.root,'wechat' if target.get()=='微信' else 'qq')
        edge.set(str(value['max_edge']) if value['max_edge'] else '不缩小')
        fps.set(str(value['max_fps']) if value['max_fps'] else '原时序');colors.set(str(value['colors']))
    def finish(generate):
        platform='wechat' if target.get()=='微信' else 'qq'
        value={'max_edge':int(edge.get()) if edge.get()!='不缩小' else None,
               'max_fps':int(fps.get()) if fps.get()!='原时序' else None,'colors':int(colors.get())}
        if platform=='wechat' and value['max_edge'] is None:
            note.set('微信默认兼容配置最长边320；原尺寸请使用“导出原文件”或编辑器完整作品导出。');return
        directory=filedialog.askdirectory(parent=window,title='保存独立兼容副本') if generate else None
        if generate and not directory:return
        set_settings(store.root,platform,value)
        if generate:result.append((platform,value,Path(directory)))
        window.destroy()
    buttons=ttk.Frame(body);buttons.grid(row=5,column=0,columnspan=2)
    ttk.Button(buttons,text='保存设置',command=lambda:finish(False)).pack(side='left',padx=4)
    ttk.Button(buttons,text='生成副本…',command=lambda:finish(True),state='normal' if has_source else 'disabled').pack(side='left',padx=4)
    load();window.wait_window();return result[0] if result else None


def generate(store,choice,*,ids=(),files=(),cancel=None,progress=None):
    platform,options,directory=choice;lines=[]
    sources=[(ident[:12],lambda ident=ident:store.original(ident)) for ident in ids]
    sources += [(Path(file).stem,lambda file=file:Path(file)) for file in files]
    try:
        for name,get_source in sources:
            check_cancel(cancel)
            _,asset=prepare_asset(get_source(),platform,store.root/'compatible-assets',cancel=cancel,
                progress=progress,**options)
            source=Path(asset['prepared']);output=directory/(asset['source_sha256'][:12]+'-'+source.parent.name+source.suffix)
            copy_file(source,output,cancel=cancel)
            lines.append(name+'：'+describe(asset['prepared_metadata']))
    except (CancelledError,InterruptedError):lines.append('已取消；先前完成文件保留。')
    return '\n'.join(lines)+'\n原件未覆盖；仅生成本地文件，未向客户端发送。'
