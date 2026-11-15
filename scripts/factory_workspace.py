"""One preset browser over existing template workers and the native document.

Templates produce a new, undoable layer in the current document. Merely browsing
never imports a material, replaces the document, or commits a motion preview.
"""
from ui_dpi import px, spacing, factor
from pathlib import Path
from types import SimpleNamespace
from collections import OrderedDict
from uuid import uuid4
import json,time,queue
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageTk,ImageDraw
from ui_style import ScrollBody,entry_hint,disclosure,BG,SURFACE,INK,MUTED,ACCENT
from emoji_bridge.animation_recipe import EFFECTS
from emoji_bridge.interactive_preview import PreviewQueue
from emoji_bridge.material_preview import FrameStream
from emoji_bridge.materials import is_dynamic
from emoji_bridge.editing import load_static
from emoji_bridge.animated_edit import GifSource
from emoji_bridge.state import save_json
from factory_service import Factory

APP=Path(__file__).resolve().parents[1]
MOTIONS=('squash','spin_bounce','jelly','glitch','outline','shadow','glow','crt','film','rgb','retro')

def directory(templates):
    """Stable typed identities; interleave a few motions, never a fake ranking."""
    effects=[dict(key='effect:'+key,name=EFFECTS[key],kind='effect',group='动效' if key in MOTIONS[:4] else '滤镜与轮廓',
                  keywords=[key,'Q弹' if key in MOTIONS[:2] else '滤镜'],verified=True) for key in MOTIONS]
    result=[]
    for n,template in enumerate(templates):
        if n<len(effects):result.append(effects[n])
        result.append({**template,'kind':'template'})
    return result

def select_rows(rows,query='',kind='全部',group='全部分类',favorites=None):
    query=query.strip().casefold()
    return [r for r in rows if (kind=='全部' or r['kind']=={'表情模板':'template','动态效果':'effect'}[kind])
            and (group=='全部分类' or r.get('group')==group)
            and (favorites is None or r['key'] in favorites)
            and query in ' '.join([r['name'],r['key'],*map(str,r.get('keywords',[])),*map(str,r.get('tags',[]))]).casefold()]

class FactoryWorkspace:
    def __init__(self,e):
        self.e=e;self.closed=False;self.selected=None;self.forms={};self.cards={};self.photos={};self.images={}
        self.page_number=0;self.columns=3;self.hover=None;self.stream=None;self.scrolls={};self.scope=None
        self.jobs=PreviewQueue(6_000_000);self.applied=set();self.refine=False;self.target_slot=None;self.batch=[]
        self.service=SimpleNamespace(store=e.store,task={'active':False},cancel=e.save_cancel,closed=False,url='',token='',start=self.start)
        self.factory=Factory(self.service);self.rows=directory(self.factory.catalog);self.filtered=self.rows
        self.preferences=e.store.root/'desktop-ui.json'
        try:self.favorites=set(json.loads(self.preferences.read_text('utf8')).get('factory_favorites',[]))
        except (OSError,ValueError):self.favorites=set()
        # Hide the legacy effects-only browser. Its preview/render engine remains.
        for child in e.effects_host.winfo_children():child.pack_forget()
        e.animation_effects.cards={}
        e.browser_tabs.tab(e.effects_host,text='模板与效果')
        head=ttk.Frame(e.effects_host,padding=spacing(self.e.window,(12,8)));head.pack(fill='x')
        ttk.Label(head,text='模板与效果',style='Heading.TLabel').pack(anchor='w',pady=spacing(self.e.window,(0,8)))
        self.query=tk.StringVar();search=ttk.Frame(head);search.pack(fill='x')
        entry=ttk.Entry(search,textvariable=self.query);entry.pack(side='left',fill='x',expand=True);entry_hint(entry,self.query,'搜索模板、效果')
        ttk.Button(search,text='清除',width=4,command=self.clear).pack(side='right',padx=spacing(self.e.window,(6,0)))
        self.kind=tk.StringVar(value='全部');segments=ttk.Frame(head);segments.pack(fill='x',pady=px(self.e.window,8))
        for title in ('全部','表情模板','动态效果'):
            ttk.Radiobutton(segments,text=title,value=title,variable=self.kind,style='Editor.Segment.TRadiobutton').pack(side='left',expand=True,fill='x')
        filters=ttk.Frame(head);filters.pack(fill='x')
        self.group=tk.StringVar(value='全部分类');self.only_favorites=tk.BooleanVar()
        ttk.Combobox(filters,textvariable=self.group,values=['全部分类',*dict.fromkeys(r['group'] for r in self.rows)],state='readonly',width=12).pack(side='left',fill='x',expand=True)
        ttk.Checkbutton(filters,text='收藏',variable=self.only_favorites).pack(side='right',padx=spacing(self.e.window,(8,0)))
        self.scroll=ScrollBody(e.effects_host);self.scroll.pack(fill='both',expand=True);self.grid=self.scroll.body
        nav=ttk.Frame(e.effects_host,padding=spacing(self.e.window,(12,4)));nav.pack(fill='x',side='bottom',before=self.scroll)
        pager=ttk.Frame(nav);pager.pack(fill='x')
        ttk.Button(pager,text='‹',width=3,command=lambda:self.turn(-1)).pack(side='left')
        ttk.Button(pager,text='›',width=3,command=lambda:self.turn(1)).pack(side='right')
        self.count=tk.StringVar();ttk.Label(pager,textvariable=self.count,style='Muted.TLabel').pack()
        self.hint=tk.StringVar(value='单击选择 · 右键加入批量');ttk.Label(nav,textvariable=self.hint,style='Muted.TLabel').pack()
        auxiliary=ttk.Frame(nav);auxiliary.pack(fill='x',pady=spacing(self.e.window,(4,0)))
        ttk.Button(auxiliary,text='卡片示例 A / B',command=lambda:e.show_property(self.example_page)).pack(side='left')
        self.batch_button=ttk.Button(auxiliary,text='批量任务与结果',command=self.show_batch);self.batch_button.pack(side='right')
        for var in (self.query,self.kind,self.group,self.only_favorites):var.trace_add('write',lambda *_:self.filter())
        self.scroll.bind('<Configure>',self.resize,add='+')
        # Template fields share the current inspector, never another editor.
        self.params=ttk.Frame(e.tabs,padding=px(self.e.window,10));e.tabs.add(self.params,text='模板输入')
        self.actions=ttk.Frame(self.params);self.actions.pack(side='bottom',fill='x',pady=spacing(self.e.window,(8,0)))
        self.generate_button=ttk.Button(self.actions,text='生成表情 · 加入当前作品',style='Editor.Primary.TButton',command=self.generate);self.generate_button.pack(side='bottom',fill='x')
        self.message=tk.StringVar(value='选择模板，填写需要的图片或文字。')
        self.message_label=ttk.Label(self.actions,textvariable=self.message,style='Muted.TLabel',wraplength=px(self.e.window,350));self.message_label.pack(fill='x',pady=spacing(self.e.window,(0,4)))
        self.actions.bind('<Configure>',lambda ev:self.message_label.configure(wraplength=max(220,ev.width-10)))
        self.field_scroll=ScrollBody(self.params);self.field_scroll.pack(fill='both',expand=True);self.fields=self.field_scroll.body
        self.pending=None;self.busy_token=None
        from xp_progress import XPProgress
        self.progress=XPProgress(self.actions,e,mode='indeterminate')
        self.progress.pack(fill='x',before=self.generate_button)
        ttk.Button(self.actions,text='取消准备 / 生成',command=self.cancel_front).pack(fill='x')
        self.example_wait=None
        self.example_page=ttk.Frame(e.tabs,padding=px(self.e.window,12));e.tabs.add(self.example_page,text='卡片示例')
        ttk.Label(self.example_page,text='仅改变目录示例，正式生成仍使用模板图片槽。',style='Muted.TLabel',wraplength=px(self.e.window,350)).pack(fill='x',pady=px(self.e.window,6))
        self.example_mode=tk.StringVar(value={'default':'默认示例','custom':'自选 A / B','recent':'最近使用'}.get(self.factory.live.config['mode'],'默认示例'))
        choice=ttk.Combobox(self.example_page,textvariable=self.example_mode,values=['默认示例','自选 A / B','最近使用'],state='readonly');choice.pack(fill='x');choice.bind('<<ComboboxSelected>>',lambda _:self.set_examples())
        for slot in ('a','b'):ttk.Button(self.example_page,text='选择示例 '+slot.upper(),command=lambda s=slot:self.choose_example(s)).pack(fill='x',pady=px(self.e.window,4))
        ttk.Button(self.example_page,text='交换 A / B',command=self.swap_examples).pack(fill='x',pady=px(self.e.window,4))
        self.custom_files={};self.examples_requested=0
        self.batch_page=ttk.Frame(e.tabs,padding=px(self.e.window,10));e.tabs.add(self.batch_page,text='批量任务')
        self.batch_label=tk.StringVar(value='右键模板卡，可加入本批。动效仍对当前选中图层应用。')
        ttk.Label(self.batch_page,textvariable=self.batch_label,wraplength=px(self.e.window,380),style='Muted.TLabel').pack(fill='x')
        buttons=ttk.Frame(self.batch_page);buttons.pack(fill='x',pady=px(self.e.window,6))
        ttk.Button(buttons,text='生成本批',command=lambda:self.generate(batch=True)).pack(side='left')
        ttk.Button(buttons,text='清空选择',command=self.clear_batch).pack(side='left',padx=px(self.e.window,4))
        ttk.Button(buttons,text='取消',command=e.cancel_processing).pack(side='right')
        self.batch_progress=XPProgress(self.batch_page,e,mode='indeterminate');self.batch_progress.pack(fill='x')
        self.batch_lines=tk.Text(self.batch_page,height=2,wrap='word')
        ttk.Label(self.batch_page,text='批量文案（可选，每行生成一项；留空沿用当前模板输入）',style='Muted.TLabel').pack(anchor='w')
        self.batch_lines.pack(fill='x',pady=spacing(self.e.window,(2,5)))
        self.results=ttk.Treeview(self.batch_page,columns=('state',),show='tree headings',selectmode='extended',height=3)
        self.results.heading('#0',text='本批结果');self.results.heading('state',text='状态');self.results.column('#0',width=220);self.results.column('state',width=100);self.results.pack(fill='both',expand=True)
        actions=ttk.Frame(self.batch_page);actions.pack(side='bottom',fill='x',pady=px(self.e.window,6),before=self.batch_page.winfo_children()[0])
        actions.columnconfigure((0,1),weight=1)
        ttk.Button(actions,text='加入当前作品',command=self.add_results).grid(row=0,column=0,sticky='ew',padx=px(self.e.window,2),pady=px(self.e.window,2))
        ttk.Button(actions,text='保存回库',command=self.save_results).grid(row=0,column=1,sticky='ew',padx=px(self.e.window,2),pady=px(self.e.window,2))
        ttk.Button(actions,text='重试失败项',command=self.retry_batch).grid(row=1,column=0,columnspan=2,sticky='ew',padx=px(self.e.window,2),pady=px(self.e.window,2))
        self.batch_job=None
        self.configure_layout();self.filter();self.poll_id=e.window.after(60,self.poll)

    def configure_layout(self):
        e=self.e;e.factory_layout=True
        # The work column owns its preview and contextual fields. No empty third
        # full-height column; enlargement rearranges these SAME widgets/document.
        self.work=e.canvas_host;self.refine=True;self.browser_width=304
        self.rail=ttk.Frame(e.panes,padding=spacing(self.e.window,(4,4)));e.panes.add(self.rail,before=e.browser_host,stretch='never',minsize=px(self.e.window,148),width=px(e.window,148))
        footer=ttk.Frame(self.rail);footer.pack(side='bottom',fill='x',pady=spacing(self.e.window,(4,0)))
        self.tool_scroll=ScrollBody(self.rail);self.tool_scroll.canvas.configure(width=px(e.window,130));self.tool_scroll.pack(fill='both',expand=True)
        body=self.tool_scroll.body
        groups=[('内容',[
            ('catalog','模板与效果',self.open),('material','素材',e.show_materials)]),
            ('编辑',[
            ('select','选择 / 变换',lambda:(e.select_tool(),e.sync_properties(),e.show_property(e.object_page))),
            ('text','文字',e.show_text),('shape','基础图形',lambda:e.show_property(e.shapes_page)),
            ('cutout','主体 / 修正',lambda:e.cutout.activate()),('transform','裁剪 / 旋转',lambda:e.show_property(e.transform_page)),
            ('paint','画笔 / 滤镜',e.raster.activate),('background','背景',lambda:e.show_property(e.background_page)),('layers','图层',self.layers)]),
            ('动画与进阶',[
            ('timing','时间 / 帧操作',e.animation_effects.open_timing),
            ('motion_text','动态文字',lambda:e.intelligence.open_section('text')),
            ('tracking','识字 / 跟随',lambda:e.intelligence.open_section('vision')),
            ('collage','拼图',self.open_collage),('dropped','掉落物',e.dropped_item.open),
            ('template_tools','模板包 / 体积',lambda:e.show_property(e.template_tools.page))])]
        self.tool_buttons={}
        from editor_icons import tool_icons
        self.rail_icons=tool_icons(e.window,size=16);self.blank_icon=tk.PhotoImage(master=e.window,width=px(e.window,16),height=px(e.window,16))
        for group,actions in groups:
            ttk.Label(body,text=group,style='Panel.Muted.TLabel',padding=spacing(self.e.window,(8,5))).pack(fill='x')
            for key,title,command in actions:
                icon=self.rail_icons.get('effect' if key=='catalog' else key,self.blank_icon)
                button=ttk.Button(body,text=title,image=icon,compound='left',style='Editor.Rail.TButton',command=lambda k=key,c=command,t=title:self.activate(k,t,c))
                button.pack(fill='x',pady=px(self.e.window,1));self.tool_buttons[key]=button
        self.tool_scroll.attach();e.more_tools_button.pack_forget()
        self.enlarge=ttk.Button(footer,text='放大编辑',command=self.toggle_refine);self.enlarge.pack(fill='x')
        ttk.Button(footer,text='适应窗口',command=lambda:e.zoom_by(None)).pack(fill='x',pady=spacing(self.e.window,(3,0)))
        # The S0115 horizontal tool switcher duplicated this labelled rail.
        for child in e.browser_host.winfo_children():
            if child is not e.browser_tabs:child.pack_forget()
        from editor_workspace import WorkspaceLayout
        self.layout=WorkspaceLayout(self)
        e.timeline_collapsed=True;e.timeline_toggle.configure(text='展开')

    def fit_fields(self,event=None):
        if hasattr(self,'layout'):self.layout.arrange()

    def restore_surfaces(self):
        if hasattr(self,'layout') and self.layout.drawer and self.layout.opened:self.e.browser_host.lift()

    def activate(self,key,title,command):
        self.e.set_tool(key)
        if not self.e.busy:self.e.status.set(title)
        command()
        self.restore_surfaces()


    def open_collage(self):
        self.e.collage_controller.open()

    def highlight(self,key):
        if key in ('template','effect'):key='catalog'
        for name,button in self.tool_buttons.items():button.state(['selected'] if name==key else ['!selected'])

    def toggle_refine(self):
        self.layout.hide() if self.layout.opened else self.layout.show(self.e.effects_host)

    def layers(self):
        self.e.animation_effects.hide();self.e.show_property(self.e.object_page);self.e.layers.focus_set()

    def open(self):
        e=self.e
        self.layout.show(e.effects_host)
        e.browser_tabs.select(e.effects_host)
        if not self.selected:e.show_property(e.object_page)
        elif self.selected.startswith('effect:'):e.show_property(e.animation_effects.page)
        else:
            self.save_form();self.show_template(self.current)
        if not e.busy:e.status.set('选择模板填写输入；选择动效预览当前图片图层。')
        self.restore_surfaces()

    def clear(self):
        self.query.set('');self.kind.set('全部');self.group.set('全部分类');self.only_favorites.set(False)

    def set_examples(self,updates=None):
        mode={'默认示例':'default','自选 A / B':'custom','最近使用':'recent'}[self.example_mode.get()]
        self.factory.live.examples([],{**self.factory.live.config,**(updates or {}),'mode':mode});self.custom_files={};self.images={};self.stop_hover();self.examples_requested=0

    def choose_example(self,slot):
        self.e.show_materials()
        if getattr(self,'example_action',None) and self.example_action.winfo_exists():self.example_action.destroy()
        def use():
            ident=self.e.material_panel.selected
            if not ident:return
            self.example_mode.set('自选 A / B');self.set_examples({slot:ident})
            self.e.show_browser(self.e.effects_host);self.e.show_property(self.example_page);self.example_action.destroy()
        self.example_action=ttk.Button(self.e.material_panel.actions,text='作为卡片示例 '+slot.upper(),command=use);self.example_action.pack(fill='x',pady=px(self.e.window,4))

    def swap_examples(self):
        cfg=self.factory.live.config;self.set_examples({'a':cfg.get('b',''),'b':cfg.get('a','')})

    def filter(self):
        if self.scope:self.scrolls[self.scope]=(self.page_number,self.scroll.canvas.yview()[0])
        self.scope=(self.query.get(),self.kind.get(),self.group.get(),self.only_favorites.get())
        self.filtered=select_rows(self.rows,*self.scope[:3],self.favorites if self.scope[3] else None)
        self.page_number,position=self.scrolls.get(self.scope,(0,0));self.populate(position)

    def resize(self,event):
        columns=max(2,min(5,event.width//px(self.e.window,136))) if self.layout.expanded else 2
        if columns!=self.columns:
            for col in range(max(columns,self.columns)):self.grid.columnconfigure(col,weight=1 if col<columns else 0)
            self.columns=columns
            for n,(card,_) in enumerate(self.cards.values()):card.grid_configure(row=n//columns,column=n%columns)

    def turn(self,delta):
        self.page_number=max(0,min((len(self.filtered)-1)//36,self.page_number+delta));self.populate()

    def populate(self,position=0):
        self.stop_hover()
        for child in self.grid.winfo_children():child.destroy()
        self.cards={};self.photos={};self.images={};self.jobs.clear_pending()
        self.page_number=min(self.page_number,max(0,(len(self.filtered)-1)//36))
        rows=self.filtered[self.page_number*36:(self.page_number+1)*36]
        for col in range(5):self.grid.columnconfigure(col,weight=1 if col<self.columns else 0,minsize=0)
        for n,row in enumerate(rows):
            card=tk.Canvas(self.grid,height=px(self.e.window,160),width=px(self.e.window,124),bg=BG,highlightthickness=0,takefocus=True,cursor='hand2')
            card.grid(row=n//self.columns,column=n%self.columns,sticky='ew',padx=px(self.e.window,4),pady=px(self.e.window,5));self.cards[row['key']]=(card,row)
            card.bind('<Button-1>',lambda ev,r=row:self.click(ev,r));card.bind('<Return>',lambda ev,r=row:self.choose(r));card.bind('<space>',lambda ev,r=row:(self.choose(r),'break')[1])
            card.bind('<ButtonRelease-1>',lambda ev:self.release_card())
            card.bind('<Enter>',lambda ev,r=row:self.start_hover(r));card.bind('<Leave>',lambda ev:self.stop_hover())
            card.bind('<FocusIn>',lambda ev,r=row:self.start_hover(r));card.bind('<FocusOut>',lambda ev:self.stop_hover())
            card.bind('<Configure>',lambda ev,k=row['key']:self.queue_draw(k))
            menu=tk.Menu(card,tearoff=False)
            if row['kind']=='template':menu.add_command(label='加入批量模板',command=lambda r=row:self.add_batch(r))
            menu.add_command(label='选择 / 预览',command=lambda r=row:self.choose(r))
            card.bind('<Button-3>',lambda ev,m=menu:m.tk_popup(ev.x_root,ev.y_root))
            self.draw(row['key'])
        if not rows:
            ttk.Label(self.grid,text='当前筛选没有匹配的模板或效果',style='Muted.TLabel',padding=px(self.e.window,16)).grid(row=0,column=0,columnspan=self.columns)
            ttk.Button(self.grid,text='清除筛选',command=self.clear).grid(row=1,column=0,columnspan=self.columns)
        self.scroll.attach()
        if getattr(self,'restore_idle',None):self.e.window.after_cancel(self.restore_idle)
        def restore():
            self.restore_idle=None
            if not self.closed:self.scroll.canvas.yview_moveto(position)
        self.restore_idle=self.e.window.after_idle(restore)
        self.count.set(f'{len(self.filtered)} 项 · {self.page_number+1}/{max(1,(len(self.filtered)+35)//36)}')

    def queue_draw(self,key):
        if not hasattr(self,'dirty_cards'):self.dirty_cards=set();self.draw_after=None
        self.dirty_cards.add(key)
        if self.draw_after is None:self.draw_after=self.e.window.after(16,self.flush_draws)

    def flush_draws(self):
        self.draw_after=None
        if self.closed:return
        pending=self.dirty_cards;self.dirty_cards=set()
        for key in pending:
            if key not in self.cards:continue
            card=self.cards[key][0]
            if card.winfo_y()+px(self.e.window,160)>=self.scroll.canvas.canvasy(0) and card.winfo_y()<=self.scroll.canvas.canvasy(self.scroll.canvas.winfo_height()):self.draw(key)
            else:card._paint_stale=True

    def draw(self,key):
        if key not in self.cards:return
        card,row=self.cards[key];card._paint_stale=False;width=max(124,round(card.winfo_width()/factor(self.e.window)));image=self.images.get(key)
        background=Image.new('RGB',(width,160),BG);d=ImageDraw.Draw(background)
        d.rounded_rectangle((1,1,width-2,158),10,fill='#353640' if getattr(self,'pressed',None)==key else '#2c2d34' if self.hover==key else SURFACE,outline=ACCENT if self.selected==key else '#303137')
        d.rounded_rectangle((7,7,width-8,116),7,fill='#24252b')
        if image is not None:
            image=image.copy().convert('RGBA');image.thumbnail((width-20,100),Image.Resampling.LANCZOS);background.paste(image,((width-image.width)//2,12+(100-image.height)//2),image)
        self.photos[key]=ImageTk.PhotoImage(background.resize((px(self.e.window,width),px(self.e.window,160)),Image.Resampling.LANCZOS));card.delete('all');card.create_image(px(self.e.window,0),px(self.e.window,0),image=self.photos[key],anchor='nw')
        name=row['name'];limit=max(7,(width-22)//13);shown=name if len(name)<=limit else name[:limit-1]+'…'
        card.create_text(px(self.e.window,10),px(self.e.window,130),text=shown,anchor='w',fill=INK,font=('Microsoft YaHei UI',10))
        card.create_text(px(self.e.window,10),px(self.e.window,148),text='模板 · 动图输入' if row.get('animation_policy')=='preserve' else ('模板' if row['kind']=='template' else '动效')+' · 示例',anchor='w',fill=MUTED,font=('Microsoft YaHei UI',9))
        card.create_text(px(self.e.window,width-17),px(self.e.window,148),text='★' if key in self.favorites else '☆',fill=INK,font=('Segoe UI',13))
        if key in self.applied:card.create_text(px(self.e.window,width-24),px(self.e.window,18),text='已应用',anchor='e',fill=INK,font=('Microsoft YaHei UI',8))
        if card.focus_get()==card:card.create_rectangle(*spacing(self.e.window,(4,4,width-5,155)),outline=ACCENT,width=px(self.e.window,1))
        if image is None:card.create_text(px(self.e.window,width/2),px(self.e.window,58),text='示例未就绪' if self.jobs.errors.get(key) or self.factory.live.outputs.get(key,{}).get('error') else '准备示例…' if row.get('verified') else '暂不可用',fill=MUTED)

    def click(self,event,row):
        self.pressed=row['key'];self.draw(row['key'])
        if event.y>=137 and event.x>=event.widget.winfo_width()-35:
            key=row['key'];self.favorites.symmetric_difference_update({key})
            try:prefs=json.loads(self.preferences.read_text('utf8')) if self.preferences.exists() else {};prefs['factory_favorites']=sorted(self.favorites);save_json(self.preferences,prefs)
            except OSError as exc:self.e.status.set('收藏未保存：'+str(exc))
            self.draw(key);return 'break'
        event.widget.focus_set();self.choose(row);return 'break'

    def release_card(self):
        old=getattr(self,'pressed',None);self.pressed=None
        if old:self.draw(old)

    def choose(self,row):
        if self.example_wait and self.progress.activity.get('active'):
            self.progress.finish(error=InterruptedError('已换选模板'))
        self.example_wait=None
        self.save_form();self.selected=row['key'];self.target_slot=None
        if row['kind']=='effect':
            self.e.set_tool('effect');self.e.animation_effects.choose(row['key'].split(':',1)[1])
        else:
            self.e.set_tool('template');self.show_template(row)
            if self.images.get(row['key']) is None:
                self.factory.live.examples([row['key']],retry=bool(self.factory.live.outputs.get(row['key'],{}).get('error')))
                with self.factory.live.lock:
                    if row['key'] in self.factory.live.gallery:self.factory.live.gallery.move_to_end(row['key'],last=False)
                self.example_wait=(row['key'],time.monotonic())
            state=self.forms[row['key']]
            if len(state['slots'])==1 and self.e.selected_layer:self.follow_selection()
        if not self.e.busy:self.e.status.set(('模板：' if row['kind']=='template' else '动效：')+row['name'])
        for key in self.cards:self.draw(key)

    def save_form(self):
        if not self.selected or self.selected.startswith('effect:') or not hasattr(self,'text_input'):return
        state=self.forms[self.selected];state['texts']=self.text_input.get('1.0','end-1c')
        state['parameters']={k:var.get() for k,(var,schema) in self.parameter_vars.items()}
        self.persist_forms()

    def follow_selection(self):
        if not self.selected or self.selected.startswith('effect:') or getattr(self.e,'active_tool',None)!='template':return
        if not self.e.doc or not self.e.selected_layer:return
        state=self.forms[self.selected]
        n=0 if len(state['slots'])==1 else getattr(self,'active_slot',None)
        if n is None or n>=len(state['slots']):return
        layer=self.e.doc._find(self.e.selected_layer)
        if state['slots'][n] and state['slots'][n].get('layer_id')==layer['id']:return
        self.save_form()
        state['slots'][n]={'layer_id':layer['id'],'label':layer.get('text','当前选中主体')[:32], 'animated':bool(layer.get('animation')),'frame':None}
        self.persist_forms();self.show_template(self.current)
        self.message.set('已跟随选中图层；点击生成时使用它的当前修改。')

    def activate_slot(self,n):
        self.active_slot=n;self.show_template(self.current)
        self.message.set('当前输入：图片 '+chr(65+n)+'；点击画布或图层列表选择主体。')

    def apply_subject_slot(self,n):
        from template_input_ui import current
        revision=self.e.doc.revision;self.e.subject_selection.finish()
        if self.e.busy:self.after_subject_slot=(self.selected,n)
        elif self.e.doc.revision!=revision:
            self.e.subject_selection.deactivate();current(self,n)

    def persist_forms(self):
        from copy import deepcopy
        if not hasattr(self.e,'editing_recipe'):self.e.editing_recipe={}
        self.e.editing_recipe['factory_forms']=deepcopy(self.forms)
        self.e.editing_recipe['factory_selected']=self.selected

    def show_template(self,row):
        e=self.e;e.animation_effects.hide();e.show_property(self.params)
        for child in self.fields.winfo_children():child.destroy()
        self.current=row;state=self.forms.setdefault(row['key'],{'slots':[None]*row['min_images'],'texts':'','parameters':{}})
        self.slot_photos=[];self.parameter_vars={}
        ttk.Label(self.fields,text=row['name'],style='Heading.TLabel').pack(anchor='w',pady=spacing(self.e.window,(0,6)))
        ttk.Label(self.fields,text='生成后作为独立图层加入当前作品，可撤销。',style='Muted.TLabel').pack(anchor='w')
        slotrow=ttk.Frame(self.fields);slotrow.pack(fill='x',pady=px(self.e.window,8))
        slots=[]
        for n,slot in enumerate(state['slots']):
            frame=ttk.Frame(slotrow);slots.append(frame)
            image=None
            if slot and slot.get('layer_id'):
                cached=e.layer_thumbnails.get(slot['layer_id'])
                if cached:
                    photo=ImageTk.PhotoImage(cached[1]);self.slot_photos.append(photo);ttk.Label(frame,image=photo).pack()
            elif slot:
                with Image.open(slot['thumbnail'] if slot.get('snapshot') else e.store.get(slot['id'])['thumbnail']) as im:image=im.convert('RGBA');image.thumbnail((100,72))
                photo=ImageTk.PhotoImage(image);self.slot_photos.append(photo)
                ttk.Label(frame,image=photo).pack()
            button=ttk.Button(frame,text=f'图片 {chr(65+n)} · '+('更换输入' if slot else '选择来源'))
            from template_input_ui import slot_menu
            button.configure(command=lambda i=n,b=button:slot_menu(self,i,b));button.pack()
            if len(state['slots'])>1:ttk.Button(frame,text=('当前槽：' if getattr(self,'active_slot',None)==n else '选入图片 ')+chr(65+n),command=lambda i=n:self.activate_slot(i),style='Selected.TButton' if getattr(self,'active_slot',None)==n else 'TButton').pack()
            if self.e.subject_selection.active and (self.e.subject_selection.points or self.e.subject_selection.prompts):ttk.Button(frame,text='应用选区并用于模板',command=lambda i=n:self.apply_subject_slot(i)).pack()
            if slot:ttk.Label(frame,text=slot.get('label','素材原件')+(' · 动态' if slot.get('animated') else ''),wraplength=px(self.e.window,180),style='Muted.TLabel').pack()
        def arrange(ev=None):
            columns=max(1,min(4,slotrow.winfo_width()//110))
            for n,frame in enumerate(slots):frame.grid(row=n//columns,column=n%columns,padx=spacing(self.e.window,(0,8)),pady=px(self.e.window,3),sticky='nw')
        slotrow.bind('<Configure>',arrange);arrange()
        if len(state['slots'])<min(8,row['max_images']):ttk.Button(self.fields,text='＋ 图片槽',command=self.more_slot).pack(anchor='w')
        if len(state['slots'])>1:ttk.Button(self.fields,text='交换图片顺序',command=self.swap_slots).pack(anchor='w')
        ttk.Label(self.fields,text=f'文案 · 每行一个文字槽（{row["min_texts"]}～{row["max_texts"]}）').pack(anchor='w')
        self.text_input=tk.Text(self.fields,height=3,wrap='word',undo=True);self.text_input.insert('1.0',state['texts'])
        if row['max_texts']:self.text_input.pack(fill='x',pady=spacing(self.e.window,(4,8)))
        if row.get('default_texts'):
            ttk.Button(self.fields,text='填入示例文案',command=lambda:(self.text_input.delete('1.0','end'),self.text_input.insert('1.0','\n'.join(row['default_texts'])))).pack(anchor='w')
        params=disclosure(self.fields,'模板选项')
        for key,schema in row.get('parameters',{}).get('properties',{}).items():
            if key=='user_infos' or schema.get('type') not in ('string','number','integer','boolean'):continue
            value=state['parameters'].get(key,schema.get('default',''))
            var=tk.BooleanVar(value=value) if schema['type']=='boolean' else tk.StringVar(value=value)
            self.parameter_vars[key]=(var,schema);ttk.Label(params,text=schema.get('description') or schema.get('title') or key).pack(anchor='w',pady=spacing(self.e.window,(6,0)))
            if schema.get('enum'):ttk.Combobox(params,textvariable=var,values=schema['enum'],state='readonly').pack(fill='x')
            elif schema['type']=='boolean':ttk.Checkbutton(params,text='启用',variable=var).pack(anchor='w')
            else:ttk.Entry(params,textvariable=var).pack(fill='x')
        self.message.set(row.get('error') or ('支持动态输入 · 使用快照版本；生成才会加入作品。' if row.get('animation_policy')=='preserve' else '静态输入模板 · 动图自动使用第一帧；生成才会加入作品。'))
        self.generate_button.configure(state='normal' if row.get('verified') else 'disabled');self.field_scroll.attach()
        from tkinterdnd2 import DND_FILES,DND_TEXT
        for n,frame in enumerate(slotrow.winfo_children()[:len(state['slots'])]):
            for widget in (frame,*frame.winfo_children()):
                widget.drop_target_register(DND_FILES,DND_TEXT)
                widget.dnd_bind('<<Drop>>',lambda event,i=n:self.drop_slot(event,i))

    def drop_slot(self,event,n):
        if self.e.busy:return 'refuse_drop'
        self.save_form();key=self.selected;data=str(event.data)
        if data.startswith('EmojiBridge:'):
            self.e.window.after_idle(lambda:self.assign_slot(key,n,data.split(':',1)[1]))
        else:
            paths=self.e.window.tk.splitlist(data)
            if len(paths)!=1:self.message.set('每个图片槽一次拖入一张图片。');return 'refuse_drop'
            def work():
                item,_=self.e.store.import_file(paths[0],kind='drop',cancel=self.e.save_cancel)
                return {'template_slot':(key,n,item['id'])}
            self.e.submit(work,'保存模板输入原件')
        return 'copy'

    def assign_slot(self,key,n,ident):
        item=self.e.store.get(ident);frame=None
        if is_dynamic(item['metadata']) and next(r for r in self.rows if r['key']==key).get('animation_policy')!='preserve':
            frame=0
        self.forms[key]['slots'][n]={'id':ident,'frame':frame,'animated':is_dynamic(item['metadata']) and frame is None}
        self.persist_forms()
        if self.selected==key:self.show_template(self.current)

    def more_slot(self):
        self.save_form();self.forms[self.selected]['slots'].append(None);self.show_template(self.current)

    def swap_slots(self):
        self.save_form();self.forms[self.selected]['slots'].reverse();self.show_template(self.current)

    def choose_slot(self,n):
        self.save_form();self.target_slot=(self.selected,n);self.e.show_materials()
        if getattr(self,'slot_action',None) and self.slot_action.winfo_exists():self.slot_action.destroy()
        self.e.material_panel.caption.set('选择素材后点“用于模板图片槽”；静态模板使用第一帧，支持动画的模板保留完整动画。')
        self.slot_action=ttk.Button(self.e.material_panel.actions,text='用于模板图片槽',style='Editor.Primary.TButton',command=self.use_slot)
        self.slot_action.pack(fill='x',pady=px(self.e.window,4))

    def use_slot(self):
        if not self.target_slot or not self.e.material_panel.selected:return
        key,n=self.target_slot;self.assign_slot(key,n,self.e.material_panel.selected)
        self.slot_action.destroy();self.target_slot=None;self.e.show_browser(self.e.effects_host);self.show_template(self.current)

    def generate(self,batch=False):
        e=self.e
        if e.busy or not e.doc:
            self.message.set('当前作品仍在处理，完成后即可生成。');return
        if not self.selected or self.selected.startswith('effect:'):
            self.batch_label.set('请先选择一个模板并填写图片、文案，再生成本批。');return
        self.save_form();state=self.forms[self.selected];row=self.current
        texts=[v for v in state['texts'].splitlines() if v.strip()]
        if any(slot is None for slot in state['slots']):self.message.set('请先选择所有图片槽的素材。');return
        if not row['min_texts']<=len(texts)<=row['max_texts']:self.message.set(f'需要 {row["min_texts"]}～{row["max_texts"]} 行文案；可明确填入示例。');return
        try:
            parameters={}
            for key,(var,schema) in self.parameter_vars.items():
                value=var.get()
                if value=='':continue
                if schema['type']=='integer':value=int(value)
                elif schema['type']=='number':value=float(value)
                parameters[key]=value
            self.pending=(row['key'],e.doc.revision,batch)
            self.example_wait=None
            from copy import deepcopy
            spec={'templates':self.batch or [row['key']] if batch else [row['key']],'slots':deepcopy(state['slots']),'texts':texts,'parameters':{row['key']:parameters},'name':e.name.get()}
            if batch:spec['lines']=[line for line in self.batch_lines.get('1.0','end-1c').splitlines() if line.strip()]
            from emoji_bridge.template_inputs import capture,persist
            captured=[]
            for n,slot in enumerate(spec['slots']):
                if not slot.get('layer_id'):continue
                doc=capture(e.doc,[slot['layer_id']]);frame=None
                if doc.animation and row.get('animation_policy')!='preserve':
                    frame=0
                captured.append((n,doc,frame,slot['label']))
            if captured:
                identity=self.pending
                def prepare():
                    for n,doc,frame,label in captured:
                        spec['slots'][n]=persist(doc,e.store.root/'template-inputs',revision=identity[1],label=label,frame=frame,cancel=e.save_cancel)
                    return {'prepared_template_spec':(identity,spec)}
                e.submit(prepare,'准备当前模板输入',xp=self.batch_progress if batch else self.progress)
            else:self.factory.generate(spec)
        except (ValueError,tk.TclError) as exc:self.message.set(str(exc));self.batch_label.set(str(exc))

    def add_batch(self,row):
        if row['key'] not in self.batch:self.batch.append(row['key'])
        self.batch_button.configure(text=f'批量任务与结果 · {len(self.batch)}')
        self.batch_label.set(f'已选择 {len(self.batch)} 个模板；使用当前模板的图片和文案，每项按各自输入条件校验。')

    def clear_batch(self):self.batch=[];self.batch_button.configure(text='批量任务与结果');self.batch_label.set('已清空本批模板选择；已生成的结果保留。')

    def show_batch(self):
        self.e.show_property(self.batch_page)
        if not self.batch_job and self.factory.jobs:self.batch_job=max(self.factory.jobs.values(),key=lambda j:j['created'])['id']
        self.refresh_results()

    def refresh_results(self):
        self.results.delete(*self.results.get_children())
        if not self.batch_job:return
        job=self.factory.jobs[self.batch_job]
        for row in job['items']:self.results.insert('', 'end',iid=row['id'],text=next(r['name'] for r in self.rows if r['key']==row['template']),values=({'ready':'生成成功','failed':'失败','cancelled':'取消','pending':'等待','running':'生成中'}[row['state']],))
        failures=[r.get('error','') for r in job['items'] if r['state']=='failed']
        if failures:self.batch_label.set(failures[0])

    def add_results(self):
        if not self.batch_job or self.e.busy:return
        chosen=[r for r in self.factory.jobs[self.batch_job]['items'] if r['id'] in self.results.selection() and r['state']=='ready']
        revision=self.e.doc.revision
        if chosen:self.e.submit(lambda:self.insert_rows(chosen,revision),'加入模板结果')

    def save_results(self):
        if not self.batch_job or not self.results.selection():return
        job=self.batch_job;ids=list(self.results.selection())
        self.e.submit(lambda:{'batch_saved':len(self.factory.save(job,ids))},'保存本批结果到素材库')

    def retry_batch(self):
        if self.batch_job and not self.e.busy:
            self.pending=(self.selected,self.e.doc.revision,True);self.factory.generate({},retry=self.batch_job)

    def cancel_front(self):
        if self.e.busy:self.e.cancel_processing();return
        if self.example_wait:
            key,_=self.example_wait
            with self.factory.live.lock:
                self.factory.live.gallery.pop(key,None)
                if getattr(self.factory.live,'active_template',None)==key:self.factory.live.cancel.set()
                self.factory.live.outputs[key]={'error':'已取消准备；重新选择可重试'}
            self.example_wait=None;self.progress.finish(error=InterruptedError('已取消准备'))
            self.message.set('已取消当前准备；作品保持不变。')

    def start(self,fn,label):
        self.example_wait=None
        e=self.e;key,revision,batch=self.pending;self.service.task={'active':True};self.message.set('生成中；当前作品保持不变。')
        def run():
            try:
                result=fn();job=self.factory.jobs[result['factory_job']];row=job['items'][0]
                if batch:return {'factory_batch':job['id']}
                if row['state']!='ready':raise ValueError(row.get('error') or '生成已取消；当前作品未变。')
                return self.insert_rows([row],revision)
            finally:self.service.task['active']=False
        accepted=e.submit(run,label,xp=self.batch_progress if batch else self.progress);return {'accepted':accepted}

    def insert_rows(self,rows,revision):
        e=self.e
        if e.closed or e.save_cancel.is_set() or e.doc.revision!=revision:raise InterruptedError('作品已变化，结果保留在本批记录中，未覆盖作品')
        base=e.doc._state.base;layers=list(e.doc.layers);parents=list(e.doc.source_ids)
        first_result=not layers
        for row in rows:
                file=Path(row['file']);animation=GifSource.read(file,cancel=e.save_cancel) if is_dynamic(row['metadata']) else None
                image=animation.frames[0] if animation else load_static(file)
                if e.save_cancel.is_set():raise InterruptedError('已取消，未加入作品')
                layer=dict(id=uuid4().hex,kind='sticker',image=image,size=image.size,position=(0,0),source_id=None,
                           template_recipe={k:row[k] for k in ('template','slots','texts','parameters')})
                if animation:layer['animation']=animation
                if not layers:base=Image.new('RGBA',image.size)
                else:
                    scale=min(1,base.width*.8/image.width,base.height*.8/image.height);layer['size']=tuple(max(1,round(v*scale)) for v in image.size)
                    layer['position']=((base.width-layer['size'][0])//2,(base.height-layer['size'][1])//2)
                layers.append(layer);parents.extend(row['source_ids'])
        if e.closed or e.save_cancel.is_set() or e.doc.revision!=revision:raise InterruptedError('已取消，未修改作品')
        e.doc.replace_scene(base,layers,list(dict.fromkeys(parents)),'生成模板图层')
        return {'factory_generated':rows[-1]['template'],'factory_layer':layers[-1]['id'],'factory_fit':first_result}

    def result(self,result):
        if result.get('prepared_template_spec'):
            identity,spec=result['prepared_template_spec']
            if self.pending==identity and self.selected==identity[0] and self.e.doc.revision==identity[1]:
                self.factory.generate(spec)
            else:
                self.message.set('作品或模板已改变；本次旧输入没有继续生成。');self.pending=None
                self.progress.finish(error=InterruptedError('模板输入已改变'))
                self.batch_progress.finish(error=InterruptedError('模板输入已改变'))
                self.e.activity.update(active=False,state='cancelled',continuation=False)
        if result.get('subject_repair') and getattr(self,'after_subject_slot',None):
            key,n=self.after_subject_slot;self.after_subject_slot=None;self.e.subject_selection.deactivate()
            if self.selected==key:
                from template_input_ui import current
                self.e.window.after_idle(lambda:current(self,n))
        if result.get('edited_template_slot'):
            key,n,slot=result['edited_template_slot'];self.forms[key]['slots'][n]=slot;self.persist_forms()
            if self.selected==key:self.show_template(self.current)
        if not self.forms and getattr(self.e,'editing_recipe',{}).get('factory_forms'):
            self.forms=self.e.editing_recipe['factory_forms']
            self.selected=self.e.editing_recipe.get('factory_selected')
            if self.selected:self.current=next(r for r in self.rows if r['key']==self.selected)
        if result.get('template_slot'):self.assign_slot(*result['template_slot'])
        if result.get('factory_batch'):
            self.batch_job=result['factory_batch'];self.show_batch()
        if result.get('batch_saved') is not None:
            self.batch_label.set(f'已保存 {result["batch_saved"]} 项到素材库。');self.e.material_panel.reload(preserve_scroll=True)
        if result.get('effect_applied'):
            self.applied.add('effect:'+result['effect_applied'])
            for key in self.cards:self.draw(key)
        if result.get('factory_generated'):
            self.e.selected_layer=result['factory_layer'];self.e.refresh_layers();self.applied.add(result['factory_generated'])
            notice='生成成功，已加入当前作品；可继续选动效或添加文字。'
            if self.selected==result['factory_generated']:self.message.set(notice)
            self.e.status.set(notice)
            if result.get('factory_fit'):self.e.zoom_by(None)
            else:self.e.paint(None,self.e.doc.size)

    def start_hover(self,row):
        if self.hover==row['key']:return
        self.stop_hover();self.hover=row['key'];self.hover_started=time.monotonic();self.draw(row['key'])
        self.hint.set(row['name']);self.next_frame_at=0
        if row['kind']=='template':
            file=self.custom_files.get(row['key']) or APP/'assets/factory/previews'/(row['key'].split(':',1)[1]+'.gif')
            if file.exists():self.stream=FrameStream(file,size=(132,100))

    def stop_hover(self):
        self.release_card()
        old=self.hover;self.hover=None
        if self.stream:self.stream.close();self.stream=None
        if old:
            stable=self.jobs.get(('template',old))
            if stable is not None:self.images[old]=stable
            self.draw(old)

    def poll(self):
        if self.closed:return
        self.generate_button.state(['disabled'] if self.e.busy else ['!disabled'])
        visible=self.e.view_active and self.e.effects_host.winfo_ismapped()
        if self.example_wait and not self.e.busy:
            key,started=self.example_wait
            error=self.factory.live.outputs.get(key,{}).get('error') or self.jobs.errors.get(key)
            if self.images.get(key) is not None or error:
                self.progress.finish(error=ValueError(error) if error else None);self.example_wait=None
                if error:
                    self.message.set(str(error)+'；作品保持不变。')
                    from component_settings import show_if_missing
                    show_if_missing(self.e.window,error)
            elif time.monotonic()-started>.15 and not self.progress.activity.get('active'):
                self.progress.begin('准备当前模板示例')
        if not visible:self.stop_hover()
        if self.e.doc and self.e.doc.revision!=getattr(self,'applied_revision',None):
            self.applied_revision=self.e.doc.revision
            applied=set()
            for layer in self.e.doc.layers:
                key=layer.get('template_recipe',{}).get('template')
                if key:applied.add(key)
                animation=layer.get('animation')
                while animation is not None:
                    applied.update('effect:'+effect['key'] for effect in getattr(animation,'recipe',{}).get('effects',[]))
                    animation=getattr(animation,'master',None)
            if applied!=self.applied:
                self.applied=applied
                for key in self.cards:self.draw(key)
        if visible:
            if time.monotonic()-self.examples_requested>.5:
                keys=[k for k,(c,r) in self.cards.items() if r['kind']=='template' and c.winfo_rooty()+160>=self.scroll.winfo_rooty() and c.winfo_rooty()<self.scroll.winfo_rooty()+self.scroll.winfo_height()]
                if self.example_wait:keys=list(dict.fromkeys([self.example_wait[0],*keys]))
                result=self.factory.live.examples(keys[:16]);self.examples_requested=time.monotonic()
                for k,v in result['items'].items():
                    if v.get('image'):
                        fingerprint=v['image'].split('/factory-live/')[-1].split('?')[0]
                        self.custom_files[k]=self.factory.live.root/fingerprint/'preview.webp'
            for key,(card,row) in self.cards.items():
                if card.winfo_rooty()+160<self.scroll.winfo_rooty() or card.winfo_rooty()>self.scroll.winfo_rooty()+self.scroll.winfo_height():
                    if self.hover==key:self.stop_hover()
                    continue
                if getattr(card,'_paint_stale',False):self.draw(key)
                if row['kind']=='template':
                    if key not in self.custom_files:
                        built=APP/'assets/factory/previews'/(key.split(':',1)[1]+'.png')
                        if built.is_file():self.custom_files[key]=built
                        else:
                            self.draw(key);continue
                    file=self.custom_files.get(key) or APP/'assets/factory/previews'/(key.split(':',1)[1]+'.png');cache=('template',key,str(file))
                    def render(p=file):
                        with Image.open(p) as im:im=im.convert('RGBA');im.thumbnail((144,104));return im
                else:
                    effect=key.split(':',1)[1];elapsed=(time.monotonic()-self.hover_started)*1000 if self.hover==key else 300
                    stamp=int(elapsed//80)*80;cache=('effect',effect,stamp)
                    def render(k=effect,t=stamp):
                        from emoji_bridge.animation_recipe import apply_effect
                        im=Image.new('RGBA',(90,80));d=ImageDraw.Draw(im);d.rounded_rectangle((16,10,74,70),14,fill='#b195db');d.ellipse((28,28,34,34),fill='#22232a');d.ellipse((55,28,61,34),fill='#22232a')
                        return apply_effect(im,{'key':k,'strength':.3,'motion_version':2},t,2000)
                self.jobs.request(key,cache,render);image=self.jobs.get(cache)
                if image is not None and self.images.get(key) is not image and not (self.stream and self.hover==key):
                    self.images[key]=image
                    if row['kind']=='template':self.jobs.request('stable-'+key,('template',key),lambda im=image:im)
                    self.draw(key)
                elif self.jobs.errors.get(key):self.draw(key)
            if self.stream and time.monotonic()>=getattr(self,'next_frame_at',0):
                try:
                    value=self.stream.frames.get_nowait()
                    if value[0] is not None:
                        self.images[self.hover]=value[0];self.draw(self.hover);self.next_frame_at=time.monotonic()+max(20,value[1])/1000
                except queue.Empty:pass
        if self.service.task.get('active'):
            text=self.service.task.get('text','正在生成表情…')
            for row in self.rows:
                if row['key'] in text:text=text.replace(row['key'],row['name']);break
            self.message.set(text)
        elif self.pending and self.e.status.get().startswith('未完成：'):self.message.set(self.e.status.get());self.pending=None
        self.poll_id=self.e.window.after(35 if self.stream else 90,self.poll)

    def close(self):
        self.closed=True;self.service.closed=True;self.jobs.close();self.factory.live.close();self.stop_hover()
        self.e.window.after_cancel(self.poll_id)
        if getattr(self,'draw_after',None):self.e.window.after_cancel(self.draw_after)
        if getattr(self,'restore_idle',None):self.e.window.after_cancel(self.restore_idle)
