"""Shared filters and additive organization controls for both material views."""
import tkinter as tk
from tkinter import ttk
from ui_dialogs import simpledialog, messagebox, prepare_window

SOURCES={'全部来源':'','QQ':'qq','微信':'wechat','本地 / 截图':'local','编辑作品':'edited'}
FORMATS={'全部格式':'','静态':'static','动态':'animated'}
VIEWS={'全部素材':'','常用':'favorite','最近使用':'recent','最近添加':'added','未分类':'unclassified','本地回收站':'trash'}


class Filters(ttk.Frame):
    def __init__(self,parent,changed,*,compact=False,initial='全部素材'):
        super().__init__(parent)
        self.view=tk.StringVar(value=initial);self.source=tk.StringVar(value='全部来源');self.media=tk.StringVar(value='全部格式')
        for n,(variable,values) in enumerate(((self.view,VIEWS),(self.source,SOURCES),(self.media,FORMATS))):
            choices=list(values)
            if compact and n==0:choices.remove('本地回收站')
            box=ttk.Combobox(self,textvariable=variable,values=choices,state='readonly',width=12)
            if compact:box.grid(row=0 if n==0 else 1,column=0 if n<2 else 1,sticky='ew',pady=2,padx=2,columnspan=2 if n==0 else 1)
            else:box.pack(side='left',padx=4)
            box.bind('<<ComboboxSelected>>',lambda e:changed())
        if compact:self.columnconfigure((0,1),weight=1)

    def values(self):return dict(view=VIEWS[self.view.get()],source=SOURCES[self.source.get()],media=FORMATS[self.media.get()])


def import_options(parent,store,count):
    window=tk.Toplevel(parent);window.title(f'加入素材库 · {count} 项');window.transient(parent);prepare_window(window,parent)
    ttk.Label(window,text='保存完整原件；不会发送、添加或删除客户端收藏。',padding=12).pack()
    ttk.Label(window,text='合集（可选已有，或输入新名称；留空不归类）').pack(anchor='w',padx=12)
    group=tk.StringVar();ttk.Combobox(window,textvariable=group,values=store.categories(),width=36).pack(fill='x',padx=12)
    ttk.Label(window,text='批量添加标签（逗号分隔；保留已有标签）').pack(anchor='w',padx=12,pady=(8,0))
    tags=tk.StringVar();ttk.Entry(window,textvariable=tags,width=40).pack(fill='x',padx=12)
    acquire=tk.BooleanVar(value=True);ttk.Checkbutton(window,text='需要时获取所选原件；仅缩略图不计作已入库',variable=acquire).pack(padx=12,pady=10)
    result=[]
    def accept():result.append(dict(collections=[group.get().strip()] if group.get().strip() else [],tags=tags.get(),acquire=acquire.get()));window.destroy()
    row=ttk.Frame(window,padding=12);row.pack(fill='x')
    ttk.Button(row,text='保存所选',command=accept).pack(side='right');ttk.Button(row,text='取消',command=window.destroy).pack(side='right',padx=6)
    window.grab_set();parent.wait_window(window);return result[0] if result else None


def organize(parent,store,ids,done,submit=None):
    if not ids:return
    window=tk.Toplevel(parent);window.title(f'整理 {len(ids)} 张素材');window.transient(parent);prepare_window(window,parent)
    ttk.Label(window,text='只整理应用内素材；不修改 QQ / 微信收藏。',padding=10).pack()
    group=tk.StringVar();tags=tk.StringVar();name=tk.StringVar(value=store.get(ids[0])['name'] if len(ids)==1 else '')
    if len(ids)==1:
        ttk.Label(window,text='名称').pack(anchor='w',padx=12);ttk.Entry(window,textvariable=name,width=42).pack(fill='x',padx=12)
    ttk.Label(window,text='合集（已有名称或新名称）').pack(anchor='w',padx=12,pady=(8,0))
    box=ttk.Combobox(window,textvariable=group,values=store.categories(),width=40);box.pack(fill='x',padx=12)
    ttk.Label(window,text='标签（逗号分隔）').pack(anchor='w',padx=12,pady=(8,0));ttk.Entry(window,textvariable=tags).pack(fill='x',padx=12)
    note=tk.StringVar();ttk.Label(window,textvariable=note,wraplength=360).pack(padx=12)
    def apply(**kwargs):
        try:
            title=name.get().strip()
            def work():
                store.organize(ids,**kwargs)
                if len(ids)==1 and title:store.update(ids,name=title)
                return {'text':f'已整理 {len(ids)} 张素材；原件和客户端收藏保持不变。'}
            if submit:
                if submit(work):window.destroy()
            else:work();done();window.destroy()
        except Exception as exc:note.set(str(exc))
    for labels in [
        [('加入合集',lambda:apply(add_collections=[group.get()]) if group.get().strip() else note.set('请先输入或选择合集')),
         ('移出此合集',lambda:apply(remove_collections=[group.get()]) if group.get().strip() else note.set('请先选择合集'))],
        [('添加这些标签',lambda:apply(add_tags=tags.get())),('移除这些标签',lambda:apply(remove_tags=tags.get()))],
        [('设为常用',lambda:apply(favorite=True)),('取消常用',lambda:apply(favorite=False))],
        [('移到本地回收站',lambda:apply(deleted=True)),('从回收站恢复',lambda:apply(deleted=False))]]:
        row=ttk.Frame(window,padding=(12,4));row.pack(fill='x')
        for title,command in labels:ttk.Button(row,text=title,command=command).pack(side='left',fill='x',expand=True)
    ttk.Label(window,text='移出合集不删文件。回收站仅隐藏本地条目，原件和草稿保留。',wraplength=350).pack(padx=12,pady=6)
    ttk.Button(window,text='保存名称 / 关闭',command=lambda:apply()).pack(pady=8)
    window.grab_set()


def manage_collections(parent,store,done):
    window=tk.Toplevel(parent);window.title('管理合集');window.transient(parent);prepare_window(window,parent)
    current=tk.StringVar();box=ttk.Combobox(window,textvariable=current,values=store.categories(),width=36);box.pack(padx=12,pady=12)
    def change(rename=False):
        value=simpledialog.askstring('合集名称','新名称：',initialvalue=current.get() if rename else '',parent=window)
        if value:
            try:store.collection(current.get(),value) if rename else store.collection(value);done();box.configure(values=store.categories());current.set(value)
            except Exception as exc:messagebox.showerror('合集未更改',str(exc),parent=window)
    ttk.Button(window,text='新建合集',command=change).pack(fill='x',padx=12)
    ttk.Button(window,text='重命名所选合集',command=lambda:change(True)).pack(fill='x',padx=12,pady=8)
