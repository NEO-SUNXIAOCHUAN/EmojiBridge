"""Transcript browsing and correction beside the existing clip selection."""
from pathlib import Path
from uuid import uuid4
import json,tkinter as tk
from tkinter import ttk,filedialog
from emoji_bridge.capabilities import worker,models

class SpeechPanel:
 def __init__(self,video):
  self.v=video;self.rows=[];self.indices=[];self.source_id=None
  self.panel=ttk.Frame(video.window,padding=12);self.model=tk.StringVar(value='tiny')
  row=ttk.Frame(self.panel);row.pack(fill='x');ttk.Label(row,text='台词与字幕').pack(side='left');ttk.Combobox(row,textvariable=self.model,values=['tiny','base','small'],state='readonly',width=8).pack(side='left',padx=5)
  ttk.Button(row,text='本地转写',command=self.transcribe).pack(side='left');ttk.Button(row,text='收起',command=self.toggle).pack(side='right')
  tools=ttk.Frame(self.panel);tools.pack(fill='x',pady=4)
  ttk.Button(tools,text='下载并安装所选模型',command=self.prepare_model).pack(side='left')
  from component_settings import show as show_components
  ttk.Button(tools,text='字幕组件：下载 / 导入',command=lambda:show_components(video.window)).pack(side='left',padx=4)
  ttk.Button(tools,text='官方下载页',command=self.download_page).pack(side='left',padx=4)
  self.query=tk.StringVar();ttk.Entry(self.panel,textvariable=self.query).pack(fill='x',pady=6);self.query.trace_add('write',lambda *_:self.refresh())
  self.list=tk.Listbox(self.panel,height=5,exportselection=False);self.list.pack(fill='x');self.list.bind('<<ListboxSelect>>',self.select)
  self.text=tk.Text(self.panel,height=2,wrap='word');self.text.pack(fill='x',pady=5)
  actions=ttk.Frame(self.panel);actions.pack(fill='x')
  for label,fn in [('保存校对',self.correct),('导出SRT',self.srt),('字幕进入所选片段',self.edit)]:ttk.Button(actions,text=label,command=fn).pack(side='left',padx=2)
  ttk.Label(self.panel,text='默认 tiny 随完整离线包提供。base / small 需先下载；点“下载并安装”即可，完成后无需再次下载。',wraplength=360,style='Muted.TLabel').pack(anchor='w',pady=5)
 def download_page(self):
  import webbrowser
  model=self.model.get()
  if model in ('tiny','base','small'):webbrowser.open('https://huggingface.co/Systran/faster-whisper-'+model+'/tree/main')
 def prepare_model(self):
  v=self.v
  if v.busy:return
  model=self.model.get();folder=v.store.root/'speech/model-prepare'/model;folder.mkdir(parents=True,exist_ok=True)
  def work():
   worker('speech','factory_speech_worker.py',{'action':'prepare','model':model,'models':str(models('speech')),'result':str(folder/'ready.json')},folder,v.cancel,timeout=900)
   return {'message':model+' 模型已安装，点击本地转写即可。'}
  v.submit(work,'下载并校验字幕模型，可取消；完成后自动安装')
 def toggle(self):
  if self.panel.winfo_manager():self.panel.pack_forget()
  else:self.panel.pack(side='right',fill='y',before=self.v.preview)
 def transcribe(self):
  v=self.v
  if not v.source or v.busy:return
  v.stop_preview();source=dict(v.source);model=self.model.get();folder=v.store.root/'speech'/source['sha256'];folder.mkdir(parents=True,exist_ok=True);result=folder/(model+'.json')
  def work():
   if not result.exists():worker('speech','factory_speech_worker.py',{'video':source['path'],'model':model,'models':str(models('speech')),'result':str(result)},folder,v.cancel)
   return {'transcript':json.loads(result.read_text('utf-8')),'transcript_path':str(result),'transcript_source':source['sha256']}
  v.submit(work,'本地语音转写 / 首次准备模型')
 def loaded(self,value):
  self.rows=value['transcript']['segments'];self.path=Path(value['transcript_path']);self.source_id=value['transcript_source'];self.refresh()
  if not self.rows:self.v.status.set('本次未识别到台词；可检查音轨或换模型重试')
 def refresh(self):
  self.list.delete(0,'end');self.indices=[]
  for i,row in enumerate(self.rows):
   if self.query.get().casefold() in row['text'].casefold():self.indices.append(i);self.list.insert('end',f"{row['start']:.2f}–{row['end']:.2f}  {row['text']}")
 def select(self,event=None):
  if not self.list.curselection() or not self.v.source or self.source_id!=self.v.source['sha256']:return
  row=self.rows[self.indices[self.list.curselection()[0]]];self.text.delete('1.0','end');self.text.insert('1.0',row['text']);v=self.v;v.start.set(str(row['start']));v.end.set(str(row['end']));v.apply_range();v.seek(row['start'],True)
 def correct(self):
  if not self.list.curselection():return
  self.rows[self.indices[self.list.curselection()[0]]]['text']=self.text.get('1.0','end-1c');data=json.loads(self.path.read_text('utf-8'));data['segments']=self.rows;self.path.write_text(json.dumps(data,ensure_ascii=False),'utf-8');self.refresh()
 def srt(self):
  if not self.rows:return
  path=filedialog.asksaveasfilename(parent=self.v.window,defaultextension='.srt',filetypes=[('字幕','*.srt')])
  if not path:return
  def stamp(t):
   n=round(t*1000);h,n=divmod(n,3600000);m,n=divmod(n,60000);s,ms=divmod(n,1000);return f'{h:02}:{m:02}:{s:02},{ms:03}'
  Path(path).write_text('\n\n'.join(f"{i+1}\n{stamp(r['start'])} --> {stamp(r['end'])}\n{r['text']}" for i,r in enumerate(self.rows)),'utf-8')
 def edit(self):
  v=self.v
  if v.busy or not v.source or self.source_id!=v.source['sha256']:v.status.set('请先对当前视频转写');return
  try:start,end,fps,width=v.options()
  except ValueError as exc:v.status.set(str(exc));return
  source=dict(v.source);rows=[dict(r) for r in self.rows if r['end']>start and r['start']<end]
  def work():
   from emoji_bridge.dynamic_cutout import video_animation
   from emoji_bridge.editing import EditDocument,save_scene
   from PIL import Image
   animated=video_animation(source['path'],start,end,max_edge=width,fps=fps,cancel=v.cancel)
   doc=EditDocument(Image.new('RGBA',animated.frames[0].size));ident=doc.add_sticker(animated.frames[0]);doc.replace_scene(doc._state.base,[{**doc._find(ident),'animation':animated}],[])
   for row in rows:
    ident=doc.add_text(row['text'],size=max(14,round(doc.size[0]/20)),color='white',position=(10,round(doc.size[1]*.76)),box_width=doc.size[0]-20)
    doc.update_layer(ident,text_motion={'style':'none','start':max(0,round((row['start']-start)*1000)),'end':min(round((end-start)*1000),round((row['end']-start)*1000)),'stroke':2,'outline':'#000000','shadow':True})
   recipe={'type':'video-clip','recipe_version':1,'source_sha256':source['sha256'],
           'source_range_ms':[round(start*1000),round(end*1000)],
           'subtitles':rows,'source_video':source['path']}
   folder=v.store.root/'drafts'/uuid4().hex;save_scene(doc,folder,'台词片段',extra=recipe);return {'edit_draft':folder,'edit_document':doc}
  v.submit(work,'字幕进入可编辑片段')
