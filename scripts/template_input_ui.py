"""Template slots use explicit, immutable versions of the current edit."""
import tkinter as tk
from tkinter import ttk, filedialog
from emoji_bridge.template_inputs import capture,persist


def current(factory,n,ids=None,whole=False):
    e=factory.e
    if e.busy or not e.doc or not e.finish_text():return
    if not whole and ids is None:
        ids=[e.selected_layer] if e.selected_layer else []
    if not whole and not ids:factory.message.set('先在画布或图层列表选择主体，或从当前作品选择。');return
    selected=e.subject_selection
    if selected.active and (selected.points or selected.prompts):
        factory.message.set('选区尚未应用；请点“应用选区并用于模板”。');return
    try:doc=capture(e.doc,None if whole else ids)
    except ValueError as exc:factory.message.set(str(exc));return
    key=factory.selected;revision=e.doc.revision;frame=None
    if doc.animation and factory.current.get('animation_policy')!='preserve':
        frame=0
    factory.save_form()
    label='整个作品' if whole else ' + '.join('文字' if l['kind']=='text' else '主体 / 图层' for l in doc.layers)
    def work():
        slot=persist(doc,e.store.root/'template-inputs',revision=revision,label=label,frame=frame,cancel=e.save_cancel)
        return {'edited_template_slot':(key,n,slot)}
    e.submit(work,'准备当前编辑结果（保留原图层）')


def select_layers(factory,n):
    e=factory.e
    # One explicit layer/group choice; does not change the canvas selection.
    win=tk.Toplevel(e.window);win.title('从当前作品选择');win.transient(e.window.winfo_toplevel())
    ttk.Label(win,text='单选使用单层；多选将所选层组合，保留相对位置。',padding=12).pack()
    rows=list(reversed(e.doc.layers));listing=tk.Listbox(win,selectmode='extended',exportselection=False,height=8)
    for i,l in enumerate(rows):listing.insert('end',f'{len(rows)-i} · '+(l.get('text','图片 / 主体')[:24]))
    listing.pack(fill='both',expand=True,padx=12)
    def use():
        ids=[rows[i]['id'] for i in listing.curselection()]
        if ids:win.destroy();current(factory,n,ids)
    ttk.Button(win,text='使用所选图层 / 组合',command=use).pack(pady=12)


def slot_menu(factory,n,widget):
    menu=tk.Menu(widget,tearoff=False)
    menu.add_command(label='使用当前选中图层 / 主体',command=lambda:current(factory,n))
    menu.add_command(label='从当前作品选择图层 / 组合…',command=lambda:select_layers(factory,n))
    menu.add_command(label='使用整个作品（画布与输出选区）',command=lambda:current(factory,n,whole=True))
    menu.add_separator()
    menu.add_command(label='从素材库选择…',command=lambda:factory.choose_slot(n))
    menu.add_command(label='从文件选择…',command=lambda:file_slot(factory,n))
    menu.add_separator()
    menu.add_command(label='使用指定默认示例（灭霸）',command=lambda:example_slot(factory,n))
    menu.tk_popup(widget.winfo_rootx(),widget.winfo_rooty()+widget.winfo_height())


def file_slot(factory,n):
    e=factory.e;file=filedialog.askopenfilename(parent=e.window,title='模板图片输入',filetypes=[('图片','*.png *.gif *.webp *.jpg *.jpeg *.bmp'),('全部','*.*')])
    if not file:return
    key=factory.selected
    def work():
        item,_=e.store.import_file(file,cancel=e.save_cancel)
        return {'template_slot':(key,n,item['id'])}
    e.submit(work,'保存模板输入原件')


def example_slot(factory,n):
    from pathlib import Path
    from shutil import copyfile
    import hashlib
    e=factory.e;key=factory.selected
    source=Path(__file__).resolve().parents[1]/'assets/factory/default-input.png'
    def work():
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        folder=e.store.root/'template-inputs'/digest;folder.mkdir(parents=True,exist_ok=True)
        target=folder/'example.png'
        if not target.exists():copyfile(source,target)
        slot={'snapshot':str(target),'thumbnail':str(target),'source_ids':[],
              'label':'指定默认示例 · 灭霸','animated':False,'frame':None,'revision':digest}
        return {'edited_template_slot':(key,n,slot)}
    e.submit(work,'准备默认示例（不加入素材库）')
