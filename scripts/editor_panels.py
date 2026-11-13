from emoji_bridge.materials import is_dynamic
"""Editor views over the same managed material store; bounded previews only."""
from ui_dpi import px, spacing, factor
from concurrent.futures import ThreadPoolExecutor
import queue
import time
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageTk,ImageDraw
from emoji_bridge.material_preview import FrameStream, thumbnail
from ui_style import MIDNIGHT,SURFACE,INK,BORDER,ACCENT,BG,MUTED,HOVER,FONT


class MaterialPanel(ttk.Frame):
    PAGE_SIZE = 24

    def __init__(self, parent, store, add, background=None):
        super().__init__(parent, padding=px(parent,6))
        self.store=store;self.add=add;self.page=0;self.selected=None;self.items=[]
        self.closed=False;self.generation=0;self.photos={};self.cards={};self.futures=[];self.pending_reload=True
        self.images={};self.card_photos={};self.columns=2;self.hovered=None;self.pressed=None
        self.last_revision=store.revision();self.last_watch=0;self.restore_scroll=0
        self.hover_job=None;self.preview=None;self.preview_tick=None;self.stream=None
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='editor-materials');self.events=queue.Queue()
        self.query=tk.StringVar();self.category=tk.StringVar(value='全部分类');self.recent=tk.BooleanVar()
        row=ttk.Frame(self);row.pack(fill='x')
        entry=ttk.Entry(row,textvariable=self.query,width=14);entry.pack(side='left',fill='x',expand=True)
        entry.bind('<Return>',lambda e:self.search())
        ttk.Button(row,text='搜索',width=5,command=self.search).pack(side='right')
        from ui_style import disclosure
        filter_body=disclosure(self,'分类与筛选')
        row=ttk.Frame(filter_body);row.pack(fill='x',pady=px(self,4))
        self.categories=ttk.Combobox(row,textvariable=self.category,state='readonly',width=12)
        self.categories.pack(side='left',fill='x',expand=True);self.categories.bind('<<ComboboxSelected>>',lambda e:self.search())
        ttk.Checkbutton(row,text='最近使用',variable=self.recent,command=self.search).pack(side='right')
        from material_organizer_ui import Filters
        self.filters=Filters(filter_body,self.search,compact=True,initial='全部素材');self.filters.pack(fill='x')
        ttk.Label(self,text='悬停预览 · 拖到画布添加',foreground=MUTED).pack(anchor='w')
        bottom=ttk.Frame(self);bottom.pack(side='bottom',fill='x')
        self.actions=ttk.Frame(bottom)
        ttk.Button(self.actions,text='添加到画布',command=self.add_selected).pack(fill='x',pady=px(self,4))
        tools=ttk.Frame(self.actions);tools.pack(fill='x')
        ttk.Button(tools,text='常用 / 取消',command=self.toggle_favorite).pack(side='left',fill='x',expand=True)
        ttk.Button(tools,text='标签 / 合集',command=self.organize_selected).pack(side='left',fill='x',expand=True)
        if background:ttk.Button(self.actions,text='用所选素材作背景',command=lambda:background([self.selected]) if self.selected else self.caption.set('请先点选素材')).pack(fill='x',pady=spacing(self,(0,4)))
        nav=ttk.Frame(bottom);nav.pack(fill='x');self.navigation=nav
        ttk.Button(nav,text='‹',width=3,command=lambda:self.turn(-1)).pack(side='left')
        ttk.Button(nav,text='›',width=3,command=lambda:self.turn(1)).pack(side='right')
        self.caption=tk.StringVar(value='加载中…');ttk.Label(nav,textvariable=self.caption).pack()
        area=ttk.Frame(self);area.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(area,highlightthickness=0,bg=BG if MIDNIGHT else '#eef2f6');self.canvas.pack(side='left',fill='both',expand=True)
        from ui_scroll import OverlayScrollbar
        self.scroll=OverlayScrollbar(self.canvas)
        self.grid=ttk.Frame(self.canvas);self.grid_id=self.canvas.create_window(0,0,window=self.grid,anchor='nw')
        self.canvas.bind('<Configure>',self.resize)
        self.grid.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.grid.columnconfigure((0,1),weight=1)
        self.bind('<Unmap>',lambda e:self.hide_preview())
        self.poll_id=self.after(50,self.poll);self.reload()

    def resize(self,event):
        self.canvas.itemconfigure(self.grid_id,width=event.width)
        columns=max(1,min(6,event.width//px(self,142)))
        if columns!=self.columns:
            for n in range(max(columns,self.columns)):self.grid.columnconfigure(n,weight=1 if n<columns else 0)
            self.columns=columns
            for n,(card,_) in enumerate(self.cards.values()):card.grid_configure(row=n//columns,column=n%columns)

    def queue_card(self,item):
        if not hasattr(self,'dirty_cards'):self.dirty_cards={};self.draw_after=None
        self.dirty_cards[item['id']]=item
        if self.draw_after is None:self.draw_after=self.after(16,self.flush_cards)

    def flush_cards(self):
        self.draw_after=None;cards,self.dirty_cards=self.dirty_cards,{}
        if not self.closed:
            for item in cards.values():self.draw_card(item)

    def draw_card(self,item):
        ident=item['id']
        if ident not in self.cards:return
        card=self.cards[ident][0]
        if not card.winfo_ismapped() or card.winfo_rooty()+px(self,158)<self.canvas.winfo_rooty() or card.winfo_rooty()>self.canvas.winfo_rooty()+self.canvas.winfo_height():
            card._paint_stale=True;return
        card._paint_stale=False;width=max(80,round(card.winfo_width()/factor(self)));height=158
        backdrop=Image.new('RGB',(width,height),BG);d=ImageDraw.Draw(backdrop)
        d.rounded_rectangle((1,1,width-2,height-2),radius=13,fill=HOVER if ident==self.hovered or ident==self.pressed else SURFACE,
                            outline=ACCENT if ident==self.selected else BORDER,width=1)
        self.card_photos[ident]=ImageTk.PhotoImage(backdrop.resize((px(self,width),px(self,height)),Image.Resampling.LANCZOS));card.delete('all');card.create_image(px(self,0),px(self,0),image=self.card_photos[ident],anchor='nw')
        if ident in self.images:
            picture=self.images[ident].copy();picture.thumbnail((width-20,96))
            self.photos[ident]=ImageTk.PhotoImage(picture.resize((px(self,picture.width),px(self,picture.height)),Image.Resampling.LANCZOS));card.create_image(px(self,width/2),px(self,56),image=self.photos[ident])
        else:card.create_text(px(self,width/2),px(self,56),text='预览不可用' if ident in getattr(self,'failed_thumbs',set()) else '加载…',fill=MUTED,font=(FONT,9))
        from tkinter.font import Font
        font=Font(card,family=FONT,size=10);name=item['name']
        while len(name)>1 and font.measure(name)>px(self,width-24):name=name[:-2]+'…' if not name.endswith('…') else name[:-2]+'…'
        card.create_text(px(self,12),px(self,118),text=name,anchor='w',fill=INK,font=(FONT,10))
        card.create_text(px(self,12),px(self,141),text='GIF · 动态' if is_dynamic(item['metadata']) else '静态图片',anchor='w',fill=MUTED,font=(FONT,9))
        card.create_text(px(self,width-18),px(self,141),text='★' if item['favorite'] else '☆',fill=ACCENT if item['favorite'] else MUTED,font=(FONT,11))
        if card.focus_get()==card:card.create_rectangle(*spacing(self,(5,5,width-6,height-6)),outline=INK,dash=spacing(self,(2,3)))

    def card_event(self,item,event,kind):
        ident=item['id'];card=self.cards[ident][0]
        if kind=='enter':self.hovered=ident;self.schedule_preview(item,card)
        elif kind=='leave':self.hovered=None;self.pressed=None;self.hide_preview()
        elif kind=='press':
            card.focus_set();self.select(ident);self.pressed=ident
            if event.y>px(self,128) and event.x>card.winfo_width()-px(self,34):self.toggle_favorite()
        elif kind=='release':self.pressed=None
        self.draw_card(item)

    def search(self):
        self.page=0;self.reload();self.canvas.yview_moveto(0)

    def toggle_favorite(self):
        if self.selected:
            self.store.organize([self.selected],favorite=not self.store.get(self.selected)['favorite']);self.reload(preserve_scroll=True)

    def organize_selected(self):
        if self.selected:
            from material_organizer_ui import organize
            organize(self,self.store,[self.selected],lambda:self.reload(preserve_scroll=True))

    def turn(self,delta):
        page=max(0,min(max(0,(getattr(self,'total',0)-1)//self.PAGE_SIZE),self.page+delta))
        if page!=self.page:self.page=page;self.reload();self.canvas.yview_moveto(0)

    def reload(self,preserve_scroll=False):
        if not self.winfo_ismapped():
            self.pending_reload=True;return
        self.pending_reload=False
        self.caption.set('正在更新素材…')
        self.hide_preview();self.generation+=1;generation=self.generation
        for future in self.futures:future.cancel()
        self.futures=[]
        text=self.query.get();category=self.category.get();recent=self.recent.get();offset=self.page*self.PAGE_SIZE
        filters=self.filters.values();self.restore_scroll=self.canvas.yview()[0] if preserve_scroll else 0
        store=self.store;events=self.events;limit=self.PAGE_SIZE
        def work():
            try:
                items,total=store.search(text,'' if category=='全部分类' else category,offset,limit,recent=recent,**filters)
                events.put(('items',generation,items,total,store.categories()))
            except Exception as exc:events.put(('error',generation,str(exc)))
        self.futures.append(self.pool.submit(work))

    def populate(self,items,total,categories):
        if self.page and self.page*self.PAGE_SIZE>=total:self.page=max(0,(total-1)//self.PAGE_SIZE);self.reload();return
        for child in self.grid.winfo_children():child.destroy()
        self.photos={};self.cards={};self.images={};self.card_photos={};self.failed_thumbs=set();self.items=items;self.total=total
        self.categories.configure(values=['全部分类',*categories])
        self.caption.set(f'{self.page+1} / {max(1,(total+23)//24)} · {total} 张')
        if not items:ttk.Label(self.grid,text='此范围暂无素材\n可调整名称或筛选条件。',style='Muted.TLabel',padding=px(self,12)).grid(row=0,column=0,columnspan=2,sticky='ew')
        self.show_actions()
        generation=self.generation;events=self.events
        for index,item in enumerate(items):
            card=tk.Canvas(self.grid,bg=BG,width=px(self,136),height=px(self,158),highlightthickness=0,takefocus=True)
            card.grid(row=index//self.columns,column=index%self.columns,sticky='ew',padx=px(self,3),pady=px(self,3))
            self.cards[item['id']]=(card,card)
            for widget in (card,):
                for sequence,kind in [('<ButtonPress-1>','press'),('<ButtonRelease-1>','release'),('<Enter>','enter'),('<Leave>','leave')]:
                    widget.bind(sequence,lambda e,i=item,k=kind:self.card_event(i,e,k))
                widget.bind('<Configure>',lambda e,i=item:self.queue_card(i))
                for sequence in ('<FocusIn>','<FocusOut>'):widget.bind(sequence,lambda e,i=item:self.draw_card(i))
                widget.bind('<space>',lambda e,i=item:(self.select(i['id']),'break')[-1])
                widget.bind('<Return>',lambda e,i=item:(self.add([i['id']]),'break')[-1])
                widget.bind('<Double-Button-1>',lambda e,i=item:self.add([i['id']]))
                widget.bind('<MouseWheel>',lambda e:(self.hide_preview(),self.canvas.yview_scroll(-int(e.delta/120),'units'),'break')[-1])
                widget.drag_source_register(1,'DND_Text')
                widget.dnd_bind('<<DragInitCmd>>',lambda e,i=item:self.drag_start(i))
            def load(i=item):
                try:
                    image=thumbnail(i['thumbnail']);image.thumbnail((112,86))
                    events.put(('thumb',generation,i['id'],image))
                except Exception as exc:events.put(('thumb_error',generation,i['id'],str(exc)))
            self.futures.append(self.pool.submit(load))
        self.after_idle(lambda:self.canvas.yview_moveto(self.restore_scroll) if not self.closed else None)

    def select(self,ident):
        self.selected=ident
        self.show_actions()
        for item in self.items:self.draw_card(item)

    def show_actions(self):
        if any(item['id']==self.selected for item in self.items):self.actions.pack(fill='x',before=self.navigation)
        else:self.actions.pack_forget()

    def drag_start(self,item):
        self.hide_preview();self.select(item['id'])
        # Internal text token, never expose a movable managed original to the shell.
        return ('copy','DND_Text','EmojiBridge:'+item['id'])

    def add_selected(self):
        if self.selected:self.add([self.selected])
        else:self.caption.set('请先点选一张素材')

    def schedule_preview(self,item,widget):
        self.hide_preview()
        self.hover_job=self.after(900,lambda:self.show_preview(item,widget))

    def show_preview(self,item,widget):
        self.hover_job=None
        if not widget.winfo_exists() or not widget.winfo_viewable():return
        popup=tk.Toplevel(self,background=SURFACE);popup.overrideredirect(True);self.preview=popup
        x=widget.winfo_rootx()+widget.winfo_width()+12
        if x+320>self.winfo_screenwidth():x=max(0,widget.winfo_rootx()-332)
        y=min(widget.winfo_rooty(),self.winfo_screenheight()-320)
        popup.geometry(f'320x300+{x}+{max(0,y)}')
        self.preview_label=tk.Label(popup,anchor='center',background=SURFACE,borderwidth=0,highlightthickness=0);self.preview_label.pack(fill='both',expand=True)
        tk.Label(popup,text=item['name'],background=SURFACE,foreground=INK,borderwidth=0,highlightthickness=0,wraplength=px(self,300)).pack(fill='x')
        self.preview_status=tk.Label(popup,text='正在准备原始预览…',background=SURFACE,foreground=INK,borderwidth=0);self.preview_status.pack(fill='x')
        self.stream=FrameStream(item['path'],size=(310,270),respect_loop=True);self.tick_preview()

    def tick_preview(self):
        self.preview_tick=None
        if not self.preview:return
        if not self.winfo_viewable():self.hide_preview();return
        delay=40
        try:
            frame,duration,_,_=self.stream.frames.get_nowait()
            if frame is not None:
                self.preview_photo=ImageTk.PhotoImage(frame);self.preview_label.configure(image=self.preview_photo);delay=duration
                self.preview_status.configure(text='')
            else:self.preview_status.configure(text='原件暂不可用，移开后重试');return
        except queue.Empty:pass
        if self.stream.done.is_set() and self.stream.frames.empty():return
        self.preview_tick=self.after(delay,self.tick_preview)

    def hide_preview(self):
        for attr in ('hover_job','preview_tick'):
            job=getattr(self,attr,None)
            if job:self.after_cancel(job);setattr(self,attr,None)
        if self.stream:self.stream.close();self.stream=None
        if self.preview:self.preview.destroy();self.preview=None

    def poll(self):
        if self.closed:return
        if self.winfo_ismapped():
            for item in getattr(self,'items',[]):
                card=self.cards.get(item['id'])
                if card and getattr(card[0],'_paint_stale',False):self.draw_card(item)
        if self.pending_reload and self.winfo_ismapped():self.reload(preserve_scroll=True)
        try:
            while True:
                event=self.events.get_nowait()
                if event[1]!=self.generation:continue
                if event[0]=='items':self.populate(*event[2:])
                elif event[0]=='thumb' and event[2] in self.cards:
                    self.images[event[2]]=event[3]
                    self.draw_card(next(i for i in self.items if i['id']==event[2]))
                elif event[0]=='error':self.caption.set(event[2])
                elif event[0]=='thumb_error' and event[2] in self.cards:
                    self.failed_thumbs.add(event[2]);self.draw_card(next(i for i in self.items if i['id']==event[2]))
        except queue.Empty:pass
        if time.monotonic()-self.last_watch>.9:
            self.last_watch=time.monotonic();revision=self.store.revision()
            if revision is not None and revision!=self.last_revision:self.last_revision=revision;self.reload(preserve_scroll=True)
        self.poll_id=self.after(50,self.poll)

    def close(self):
        self.closed=True;self.hide_preview();self.after_cancel(self.poll_id)
        if getattr(self,'draw_after',None):self.after_cancel(self.draw_after)
        self.pool.shutdown(wait=False,cancel_futures=True)
        self.photos.clear();self.images.clear();self.card_photos.clear();self.preview_photo=None


class LayerList(ttk.Frame):
    """Stable-id tree, with a small Listbox-compatible selection facade."""
    def __init__(self,parent,select,reorder):
        super().__init__(parent)
        self.on_select=select;self.on_reorder=reorder;self.drag=None;self.target=0;self.ids=[];self.photos={}
        ttk.Style(self).configure('Layers.Treeview',rowheight=px(self,54))
        self.tree=ttk.Treeview(self,show='tree',selectmode='browse',style='Layers.Treeview',height=7)
        self.tree.column('#0',width=px(self,230),stretch=True);self.tree.pack(side='left',fill='both',expand=True)
        from ui_scroll import OverlayScrollbar
        self.scroll=OverlayScrollbar(self.tree)
        self.line=tk.Frame(self.tree,height=3,bg='#1269bc')
        self.tree.bind('<ButtonPress-1>',self.press);self.tree.bind('<B1-Motion>',self.motion);self.tree.bind('<ButtonRelease-1>',self.release)
        self.tree.bind('<KeyRelease-Up>',lambda e:self.on_select(e));self.tree.bind('<KeyRelease-Down>',lambda e:self.on_select(e))

    def curselection(self):return tuple(self.ids.index(i) for i in self.tree.selection() if i in self.ids)
    def selection_clear(self,*args):self.tree.selection_remove(*self.tree.selection())
    def selection_set(self,index):self.tree.selection_set(self.ids[index])

    def set_rows(self,rows,selected):
        ids=[r[0] for r in rows]
        for ident in self.ids:
            if ident not in ids:self.tree.delete(ident);self.photos.pop(ident,None)
        for index,(ident,title,key,image) in enumerate(rows):
            prior=self.photos.get(ident)
            if prior is None or prior[0]!=key:self.photos[ident]=(key,ImageTk.PhotoImage(image.resize((px(self,image.width),px(self,image.height)),Image.Resampling.LANCZOS)))
            if not self.tree.exists(ident):self.tree.insert('','end',iid=ident)
            self.tree.item(ident,text=title,image=self.photos[ident][1]);self.tree.move(ident,'',index)
        self.ids=ids
        if selected in ids:self.tree.selection_set(selected)

    def press(self,event):
        ident=self.tree.identify_row(event.y)
        if ident:
            # This handler returns break, so the desktop's click-to-focus bridge
            # never sees it. A real click must acquire native keyboard focus too.
            self.tree.focus_force();self.tree.selection_set(ident);self.tree.focus(ident);self.on_select(event);self.drag=(ident,event.y)
        return 'break'

    def motion(self,event):
        if not self.drag or abs(event.y-self.drag[1])<4:return
        row=self.tree.identify_row(event.y)
        if row:
            x,y,w,h=self.tree.bbox(row);after=event.y>y+h/2
            self.target=self.ids.index(row)+int(after);line_y=y+h if after else y
        else:self.target=len(self.ids) if event.y>0 else 0;line_y=min(max(event.y,0),self.tree.winfo_height()-3)
        self.line.place(x=0,y=line_y,relwidth=1);self.line.lift()
        if event.y<12:self.tree.yview_scroll(-1,'units')
        elif event.y>self.tree.winfo_height()-12:self.tree.yview_scroll(1,'units')

    def release(self,event):
        if self.drag and self.line.winfo_manager():
            ident,_=self.drag;index=self.ids.index(ident)
            target=self.target-int(self.target>index)
            self.on_reorder(ident,target)
        self.drag=None;self.line.place_forget();return 'break'
