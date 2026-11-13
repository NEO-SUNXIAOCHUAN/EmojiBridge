"""Templates and bounded output copies in the existing editor properties panel."""
from pathlib import Path
from uuid import uuid4
from copy import copy
import tkinter as tk
from tkinter import ttk,filedialog
from ui_style import ScrollBody
from ui_dialogs import simpledialog
from emoji_bridge.template_packs import export_pack,import_pack,instantiate

class TemplateTools:
 def __init__(self,e):
  self.e=e;self.slots=[];self.installed=None
  self.page=ttk.Frame(e.tabs,padding=10);e.tabs.add(self.page,text='模板 / 输出');scroll=ScrollBody(self.page);scroll.pack(fill='both',expand=True);body=scroll.body
  ttk.Label(body,text='自己的模板',style='Heading.TLabel').pack(anchor='w');self.summary=tk.StringVar(value='把选中图层标记为可替换图片或文字。');ttk.Label(body,textvariable=self.summary,wraplength=235).pack(fill='x',pady=8)
  ttk.Button(body,text='将选中图层标记为槽位',command=self.slot).pack(fill='x',pady=4);ttk.Button(body,text='导出模板包…',command=self.export).pack(fill='x',pady=4);ttk.Button(body,text='导入模板包…',command=self.import_file).pack(fill='x',pady=4)
  self.fields=ttk.Frame(body);self.fields.pack(fill='x');self.apply_button=ttk.Button(body,text='套用模板（保留当前草稿）',command=self.apply)
  ttk.Separator(body).pack(fill='x',pady=16);ttk.Label(body,text='按目标体积另存副本',style='Heading.TLabel').pack(anchor='w')
  self.kib=tk.IntVar(value=1024);self.edge=tk.IntVar(value=128);self.fps=tk.IntVar(value=8);self.colors=tk.IntVar(value=32)
  for title,var in [('目标 KiB',self.kib),('最小长边',self.edge),('最低帧率',self.fps),('最少颜色',self.colors)]:ttk.Label(body,text=title).pack(anchor='w',pady=(6,0));ttk.Entry(body,textvariable=var).pack(fill='x')
  ttk.Button(body,text='生成体积副本…',command=self.compress).pack(fill='x',pady=12);ttk.Label(body,text='最多8次尝试 / 120秒；保留完整时长。未达标会显示实际体积，不覆盖原件。',wraplength=235,style='Muted.TLabel').pack(fill='x')
  self.scroll=scroll;scroll.attach()
 def slot(self):
  e=self.e
  if not e.selected_layer or not e.doc:return
  layer=e.doc._find(e.selected_layer)
  if layer['kind'] not in ('text','sticker'):e.status.set('请选择文字或图片图层');return
  name=simpledialog.askstring('槽位名称','例如主角、配角、标题',parent=e.window)
  if not name:return
  self.slots=[s for s in self.slots if s['layer']!=layer['id'] and s['key']!=name]
  self.slots.append({'key':name,'layer':layer['id'],'kind':'text' if layer['kind']=='text' else 'image','default':layer.get('text',layer.get('source_id'))});self.summary.set('已标记：'+ '、'.join(s['key'] for s in self.slots))
 def export(self):
  e=self.e
  if not e.doc or e.busy:return
  path=filedialog.asksaveasfilename(parent=e.window,defaultextension='.ebtemplate',filetypes=[('EmojiBridge 模板包','*.ebtemplate')])
  if path:
   snapshot=copy(e.doc);slots=list(self.slots);e.submit(lambda:{'template_export':export_pack(snapshot,path,slots)},'导出模板包')
 def import_file(self):
  path=filedialog.askopenfilename(parent=self.e.window,filetypes=[('EmojiBridge / Petpet 模板包','*.ebtemplate *.zip')])
  if path:self.e.submit(lambda:{'template_import':import_pack(path,self.e.store.root)},'检查并导入模板')
 def show(self,result):
  self.installed,manifest=result;self.values={}
  for widget in self.fields.winfo_children():widget.destroy()
  items,_=self.e.store.search(limit=500);names={i['id']:i['name'] for i in items};self.choices={i['name']+' · '+i['id'][:6]:i['id'] for i in items}
  for slot in manifest['slots']:
   ttk.Label(self.fields,text=slot['key']).pack(anchor='w',pady=(8,2));var=tk.StringVar(value=slot.get('default','') if slot['kind']=='text' else '')
   if slot['kind']=='text':ttk.Entry(self.fields,textvariable=var).pack(fill='x')
   else:ttk.Combobox(self.fields,textvariable=var,values=list(self.choices),state='readonly').pack(fill='x')
   self.values[slot['key']]=(var,slot['kind'])
  self.apply_button.pack(fill='x',after=self.fields,pady=8);self.e.show_property(self.page)
  self.scroll.attach()
 def apply(self):
  if not self.installed:return
  e=self.e;values={key:self.choices.get(var.get()) if kind=='image' else var.get() for key,(var,kind) in self.values.items()}
  def work():
   if e.doc:
    from emoji_bridge.editing import save_scene
    save_scene(e.doc,e.store.root/'drafts'/('before-template-'+uuid4().hex),'套用模板前')
   document,recipe=instantiate(self.installed,values,e.store);e.doc=document;e.editing_recipe=recipe
   return {'loaded':True,'template_recipe':recipe}
  e.submit(work,'套用模板')
 def compress(self):
  e=self.e
  if not e.doc or not e.doc.animation or e.busy:e.status.set('请先打开动态作品');return
  try:target=self.kib.get()*1024;edge=self.edge.get();fps=self.fps.get();colors=self.colors.get()
  except tk.TclError:e.status.set('请输入有效体积及质量底线');return
  destination=filedialog.asksaveasfilename(parent=e.window,defaultextension='.gif',filetypes=[('GIF 副本','*.gif')])
  if not destination:return
  snapshot=copy(e.doc)
  def work():
   from emoji_bridge.target_size import compress
   from emoji_bridge.file_io import copy_file
   result=compress(snapshot,e.store.root/'compressed'/uuid4().hex,target,min_edge=edge,min_fps=fps,min_colors=colors,cancel=e.save_cancel)
   copy_file(result['selected']['path'],destination,cancel=e.save_cancel);return {'compressed':result}
  e.submit(work,'搜索目标体积')
