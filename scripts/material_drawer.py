"""Small explicit-copy/drag drawer over the same managed material library."""
from pathlib import Path
import sys,argparse,ctypes,queue,threading
APP=Path(__file__).resolve().parents[1];sys.path[:0]=[str(APP/'src'),str(APP/'scripts'),str(APP/'third_party/tkdnd')]
import os
os.environ['EMOJI_BRIDGE_DESKTOP_STYLE']='midnight'
from tkinter import ttk
from PIL import Image,ImageTk
from material_library_ui import create_root,Preview
from emoji_bridge.materials import MaterialStore
from emoji_bridge.work_output import copy_image
from ui_style import apply

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--library',required=True);parser.add_argument('--restore',type=int,default=0);args=parser.parse_args();store=MaterialStore(args.library);root=create_root();apply(root);root.title('EmojiBridge · 表情抽屉');root.geometry('540x560');root.minsize(400,400)
 import tkinter as tk
 header=ttk.Frame(root,padding=14);header.pack(fill='x');ttk.Label(header,text='表情抽屉',style='Heading.TLabel').pack(side='left')
 view=tk.StringVar(value='常用');choose=ttk.Combobox(header,textvariable=view,values=['常用','最近使用','全部',*store.categories()],state='readonly',width=16);choose.pack(side='right')
 canvas=tk.Canvas(root,highlightthickness=0,bg='#08090b');canvas.pack(fill='both',expand=True);body=ttk.Frame(canvas);canvas.create_window(0,0,window=body,anchor='nw');body.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind_all('<MouseWheel>',lambda e:canvas.yview_scroll(-e.delta//120,'units'))
 message=tk.StringVar(value='拖动缩略图输出原件；双击预览。不会自动发送。');ttk.Label(root,textvariable=message,wraplength=500,padding=12).pack(fill='x');photos=[];events=queue.Queue();serial=0;closed=False;selected=[None];cards={};ready={};preparing=set()
 from ui_style import SELECTED,SURFACE
 ttk.Style(root).configure('Drawer.Selected.TLabel',background=SELECTED)
 ttk.Style(root).configure('Drawer.TLabel',background=SURFACE)
 def select(ident):
  selected[0]=ident
  for key,card in cards.items():card.configure(style='Drawer.Selected.TLabel' if key==ident else 'Drawer.TLabel')
 def prepare(ident):
  if ident in ready or ident in preparing:return
  preparing.add(ident)
  def work():
   try:
    folder=store.root/'drag-out'/'drawer'/ident;folder.mkdir(parents=True,exist_ok=True)
    paths=store.export([ident],folder);events.put(('file',ident,paths[0]))
   except Exception as exc:events.put(('message',str(exc),None));preparing.discard(ident)
  threading.Thread(target=work,daemon=True).start()
 def refresh(_=None):
  nonlocal serial
  serial+=1;version=serial;filter=view.get()
  def work():
   try:
    items,_=store.search(view={'常用':'favorite','最近使用':'recent'}.get(filter,''),category=filter if filter not in ('常用','最近使用','全部') else '',limit=48)
    rows=[]
    for item in items:
     with Image.open(item['thumbnail']) as image:cover=image.convert('RGBA');cover.thumbnail((100,92))
     rows.append((item,cover))
    events.put((version,rows,None))
   except Exception as exc:events.put((version,[],str(exc)))
  threading.Thread(target=work,daemon=True).start()
 def copy():
  if not selected[0]:return
  ident=selected[0];owner=root.winfo_id();message.set('正在准备复制…')
  def work():
   try:copy_image(store.original(ident),owner);store.mark_used([ident]);events.put(('message','已复制静态图片；动图请拖出原件。',None))
   except Exception as exc:events.put(('message',str(exc),None))
  threading.Thread(target=work,daemon=True).start()
 ttk.Button(header,text='复制所选',command=copy).pack(side='left',padx=8)
 def poll():
  if closed:return
  try:
   while True:
    version,rows,error=events.get_nowait()
    if version=='message':message.set(rows);continue
    if version=='file':ready[rows]=error;preparing.discard(rows);message.set('原件就绪，可拖出；文件在拖放结束后继续保留。');continue
    if version!=serial:continue
    for widget in body.winfo_children():widget.destroy()
    photos.clear();cards.clear()
    if error:message.set(error)
    if not rows:ttk.Label(body,text='这里还没有素材，可在素材库设置常用。',padding=24).pack()
    for index,(item,image) in enumerate(rows):
     photo=ImageTk.PhotoImage(image);photos.append(photo);card=ttk.Label(body,image=photo,text=item['name'][:12],compound='top',padding=8,cursor='hand2',style='Drawer.Selected.TLabel' if selected[0]==item['id'] else 'Drawer.TLabel');card.grid(row=index//4,column=index%4,padx=2,pady=3);cards[item['id']]=card
     card.bind('<Button-1>',lambda e,i=item:(select(i['id']),prepare(i['id'])));card.bind('<Enter>',lambda e,i=item:prepare(i['id']));card.bind('<Double-1>',lambda e,i=item:Preview(root,i));card.drag_source_register(1,'DND_Files')
     def drag(event,i=item):
      file=ready.get(i['id'])
      if not file:prepare(i['id']);message.set('正在准备原件，完成后可拖出。');return ('refuse_drop',)
      threading.Thread(target=store.mark_used,args=([i['id']],),daemon=True).start();return ('copy','DND_Files',(str(file),))
     card.dnd_bind('<<DragInitCmd>>',drag)
  except queue.Empty:pass
  root.after(40,poll)
 def close():
  nonlocal closed
  closed=True;root.destroy()
  user=ctypes.windll.user32
  user.IsWindow.argtypes=[ctypes.c_void_p];user.SetForegroundWindow.argtypes=[ctypes.c_void_p]
  if args.restore and user.IsWindow(args.restore):user.SetForegroundWindow(args.restore)
 choose.bind('<<ComboboxSelected>>',refresh);root.bind('<Escape>',lambda e:close());root.protocol('WM_DELETE_WINDOW',close);refresh();poll();root.mainloop()
if __name__=='__main__':main()
