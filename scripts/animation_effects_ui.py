"""Two-column visual effects, current-frame background preview, original output."""
from io import BytesIO
from copy import copy
from collections import OrderedDict
import json,time
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageTk,ImageDraw
from ui_style import ScrollBody,BG,SURFACE,INK,MUTED,SELECTED,ACCENT,disclosure,entry_hint
from ui_dialogs import colorchooser
from emoji_bridge.animation_recipe import EFFECTS,TIMING,PALETTES,apply_recipe,apply_effect,effect_size
from emoji_bridge.animated_edit import GifSource
from emoji_bridge.interactive_preview import PreviewQueue
from ui_dpi import px,spacing
from editor_controls import ParameterBar

GROUPS={'动效':('squash','spin_bounce','jelly','glitch'),'轮廓':('outline','shadow','glow'),'风格':('crt','film','rgb','retro')}

def effect_viewport(image,region,scale,origin,viewport):
    """Bound sampling resolution independently of the editor's view transform."""
    import math
    x,y=origin[0]+region[0]*scale,origin[1]+region[1]*scale
    width,height=(region[2]-region[0])*scale,(region[3]-region[1])*scale
    left,top=max(0,math.floor(x)),max(0,math.floor(y))
    right,bottom=min(viewport[0],math.ceil(x+width)),min(viewport[1],math.ceil(y+height))
    if right<=left or bottom<=top:return None,(left,top)
    sx,sy=image.width/width,image.height/height
    crop=image.transform((right-left,bottom-top),Image.Transform.AFFINE,
        (sx,0,(left-x)*sx,0,sy,(top-y)*sy),Image.Resampling.BILINEAR)
    check=Image.new('RGBA',crop.size,'#24252b');draw=ImageDraw.Draw(check)
    for yy in range(0,crop.height,16):
        for xx in range(0,crop.width,16):
            if (xx//16+yy//16)%2:draw.rectangle((xx,yy,xx+15,yy+15),fill='#303139')
    check.alpha_composite(crop)
    return check,(left,top)

def placed_effect(document,target,image,source_size,result_size,recipe,animation=None,geometry_only=False):
    """Same layer geometry for preview and commit; pad, never crop, new motions."""
    from emoji_bridge.editing import _layer_size
    size=tuple(max(1,round(n*b/a)) for n,a,b in zip(target['size'],source_size,result_size))
    changed={**target,'image':image,'animation':animation,'size':size};changed.pop('mask',None)
    changed['position']=tuple(p-(b-a)//2 for p,a,b in zip(target['position'],target['size'],size))
    anchored=any(r.get('motion_version')==2 and r['key'] in ('squash','spin_bounce','jelly') for r in recipe.get('effects',[]))
    if anchored:
        # The stage has 10% transparent space below the original bottom anchor.
        changed['position']=(changed['position'][0],target['position'][1]-round(target['size'][1]*.4))
    layers=[changed if layer['id']==target['id'] else dict(layer) for layer in document.layers]
    base=document._state.base;left=top=0;right,bottom=base.size
    if anchored:
        x,y=changed['position'];w,h=_layer_size(changed)
        left,top=min(0,x),min(0,y);right,bottom=max(base.width,x+w),max(base.height,y+h)
        if (left,top,right,bottom)!=(0,0,base.width,base.height):
            if not geometry_only:
                padded=Image.new('RGBA',(right-left,bottom-top));padded.alpha_composite(base,(-left,-top));base=padded
            layers=[{**layer,'position':(layer['position'][0]-left,layer['position'][1]-top)} for layer in layers]
    if geometry_only:return base,layers,(left,top,right,bottom)
    return base,layers

class AnimationEffects:
    def __init__(self,e):
        self.e=e;self.active=False;self.closed=False;self.source=None;self.layer=None;self.key='outline'
        self.elapsed=0;self.started=time.monotonic();self.playing=True;self.jobs=PreviewQueue(8_000_000)
        self.photos={};self.cards={};self.hover=None;self.last_image=None;self.drawn={}
        self.page=ttk.Frame(e.tabs,padding=12);e.tabs.add(self.page,text='效果参数')
        actions=ttk.Frame(self.page);actions.pack(side='bottom',fill='x',pady=(8,0))
        self.target_text=tk.StringVar(value='目标：请选中图片 / GIF 图层')
        ttk.Label(actions,textvariable=self.target_text,style='Muted.TLabel').pack(anchor='w',pady=(0,4))
        self.apply_button=ttk.Button(actions,text='应用动效',command=self.apply_effect,style='Editor.Primary.TButton');self.apply_button.pack(fill='x',pady=(0,6))
        from xp_progress import XPProgress
        self.progress=XPProgress(actions,e,mode='indeterminate');self.progress.pack(fill='x',before=self.apply_button)
        self.prepare_signature=None;self.prepare_wait=None
        ttk.Button(actions,text='退出效果预览',command=self.hide).pack(fill='x')
        scroll=ScrollBody(self.page);scroll.pack(fill='both',expand=True);body=scroll.body
        self.title=ttk.Label(body,text='贴纸描边',style='Heading.TLabel');self.title.pack(anchor='w',pady=(0,16))
        self.effect=tk.StringVar(value='贴纸描边');self.strength=tk.DoubleVar(value=.3);self.color='#ffffff'
        self.width=tk.DoubleVar(value=6);self.blur=tk.DoubleVar(value=8);self.pixel=tk.DoubleVar(value=2)
        self.palette=tk.StringVar(value='gameboy');self.dither=tk.StringVar(value='floyd');self.rows={}
        for name,title,var,low,high in [('strength','强度',self.strength,0,1),('width','轮廓',self.width,0,100),('blur','柔化',self.blur,0,100),('pixel','像素',self.pixel,1,32)]:
            row=ttk.Frame(body);row.pack(fill='x',pady=(0,14));self.rows[name]=row
            head=ttk.Frame(row);head.pack(fill='x');ttk.Label(head,text=title).pack(side='left')
            ttk.Spinbox(head,from_=low,to=high,increment=.05 if name=='strength' else 1,textvariable=var,width=6,format='%.2f' if name=='strength' else '%.0f').pack(side='right')
            ttk.Button(head,text='↺',width=2,command=lambda v=var,d=var.get():v.set(d)).pack(side='right',padx=3)
            ttk.Scale(row,from_=low,to=high,variable=var).pack(fill='x',pady=(6,0))
        self.frequency=tk.DoubleVar(value=1);self.turn_speed=tk.DoubleVar(value=.5);self.source_speed=tk.DoubleVar(value=1)
        self.motion_rows={}
        for name,title,var,low,high in [('frequency','回弹频率 · 次/秒',self.frequency,.1,6),('turn_speed','转身速度 · 圈/秒',self.turn_speed,-3,3),('source_speed','源动画速度 · 倍',self.source_speed,.05,20)]:
            row=ttk.Frame(body);self.motion_rows[name]=row
            head=ttk.Frame(row);head.pack(fill='x');ttk.Label(head,text=title).pack(side='left')
            ttk.Spinbox(head,from_=low,to=high,increment=.1,textvariable=var,width=7).pack(side='right')
            ttk.Button(head,text='↺',width=2,command=lambda v=var,d=var.get():v.set(d)).pack(side='right',padx=3)
            ttk.Scale(row,from_=low,to=high,variable=var).pack(fill='x',pady=4)
        self.color_button=ttk.Button(body,text='效果颜色',command=self.choose_color);self.color_button.pack(fill='x',pady=4)
        self.retro=ttk.Frame(body);self.retro.pack(fill='x')
        for var,values in [(self.palette,list(PALETTES)),(self.dither,['floyd','bayer','atkinson','none'])]:ttk.Combobox(self.retro,textvariable=var,values=values,state='readonly').pack(fill='x',pady=4)
        self.note=tk.StringVar(value='选择图片或 GIF 图层，再试用效果。')
        self.parameter_end=ttk.Label(body,textvariable=self.note,wraplength=218,style='Muted.TLabel');self.parameter_end.pack(fill='x',pady=12)
        self.timing_page=ttk.Frame(e.tabs,padding=12);e.tabs.add(self.timing_page,text='时间 / 帧操作')
        self.timing_apply=ttk.Button(self.timing_page,text='应用帧操作',command=self.apply_timing,style='Editor.Primary.TButton')
        self.timing_apply.pack(side='bottom',fill='x',pady=(8,0))
        time_scroll=ScrollBody(self.timing_page);time_scroll.pack(fill='both',expand=True);timing=time_scroll.body
        ttk.Label(timing,text='时间 / 帧操作',style='Heading.TLabel').pack(anchor='w',pady=6)
        self.timing_note=tk.StringVar(value='选中一个动态图层，调整后点击应用。')
        ttk.Label(timing,textvariable=self.timing_note,wraplength=px(e.window,230),style='Muted.TLabel').pack(fill='x',pady=6)
        self.timing=tk.StringVar(value='倒放')
        ttk.Combobox(timing,textvariable=self.timing,values=list(TIMING.values()),state='readonly').pack(fill='x',pady=8)
        self.frames=tk.StringVar(value='1');self.ms=tk.IntVar(value=1000);self.speed=tk.DoubleVar(value=1)
        self.timing_fields=ttk.Frame(timing);self.timing_fields.pack(fill='x')
        self.frame_row=ttk.Frame(self.timing_fields)
        ttk.Label(self.frame_row,text='处理哪些帧').pack(anchor='w')
        ttk.Entry(self.frame_row,textvariable=self.frames).pack(fill='x',pady=spacing(e.window,(5,3)))
        ttk.Label(self.frame_row,text='例如 1, 3, 5；帧号从 1 开始',style='Muted.TLabel').pack(anchor='w')
        self.ms_bar=ParameterBar(self.timing_fields,'停留时长',self.ms,1,5000,step=10,suffix=' 毫秒',input_high=1800000)
        self.speed_bar=ParameterBar(self.timing_fields,'播放速度',self.speed,.05,4,step=.05,suffix='×',input_high=20)
        self.timing_help=tk.StringVar()
        ttk.Label(timing,textvariable=self.timing_help,wraplength=px(e.window,230),style='Muted.TLabel').pack(fill='x',pady=px(e.window,12))
        self.timing.trace_add('write',self.timing_fields_changed);self.timing_fields_changed()
        time_scroll.attach();scroll.attach()
        browse=e.effects_host;head=ttk.Frame(browse,padding=(12,6));head.pack(fill='x')
        search=ttk.Frame(head);search.pack(fill='x')
        self.query=tk.StringVar();query_entry=ttk.Entry(search,textvariable=self.query,width=14);query_entry.pack(side='left',fill='x',expand=True)
        entry_hint(query_entry,self.query,'查找效果名称')
        ttk.Button(search,text='清除',width=4,command=lambda:self.query.set('')).pack(side='right',padx=(4,0))
        self.group=tk.StringVar(value='全部');ttk.Combobox(head,textvariable=self.group,values=['全部',*GROUPS],state='readonly').pack(fill='x',pady=(8,0))
        self.catalog_scroll=ScrollBody(browse);self.catalog_scroll.pack(fill='both',expand=True);self.grid=self.catalog_scroll.body
        self.overlay=ttk.Frame(e.canvas,padding=0);self.canvas=tk.Canvas(self.overlay,background=BG,highlightthickness=0);self.canvas.pack(fill='both',expand=True)
        self.placeholder=ttk.Label(self.canvas,text='正在准备效果预览…',style='Muted.TLabel',padding=12)
        bottom=ttk.Frame(self.overlay);bottom.pack(fill='x',pady=(8,0));self.bottom=bottom
        self.play=ttk.Button(bottom,text='暂停 · 空格',command=self.toggle);self.play.pack(side='left')
        self.caption=ttk.Label(bottom,text='预览384px · 原尺寸输出',style='Muted.TLabel');self.caption.pack(side='left',padx=10)
        from playback_keys import PlaybackKeys
        self.keys=PlaybackKeys(self.overlay,self.play,self.toggle,lambda:self.active and self.source is not None)
        self.canvas.bind('<Configure>',lambda _:self.redraw());self.canvas.bind('<Button-1>',lambda _:self.canvas.focus_set())
        for var in (self.strength,self.width,self.blur,self.pixel,self.palette,self.dither,self.frequency,self.turn_speed,self.source_speed):var.trace_add('write',self.changed)
        for var in (self.query,self.group):var.trace_add('write',lambda *_:self.catalog())
        self.catalog();self.poll_id=e.window.after(25,self.poll)

    def recipe(self):return {'key':self.key,'strength':self.strength.get(),'width':round(self.width.get()),'blur':round(self.blur.get()),'pixel':round(self.pixel.get()),'color':self.color,'preset':self.palette.get(),'dither':self.dither.get(),'seed':1,'motion_version':2,'frequency':self.frequency.get(),'turn_speed':self.turn_speed.get()}

    def catalog(self):
        for child in self.grid.winfo_children():child.destroy()
        self.cards={};self.photos={};self.drawn={};self.hover=None
        keys=[k for k in EFFECTS if any(k in v for v in GROUPS.values()) and (self.group.get()=='全部' or k in GROUPS[self.group.get()]) and self.query.get().strip() in EFFECTS[k]]
        if not keys:ttk.Label(self.grid,text='没有匹配的效果\n可清除名称或切换分类。',style='Muted.TLabel',padding=12).grid(row=0,column=0,columnspan=2,sticky='ew')
        for n,key in enumerate(keys):
            card=tk.Canvas(self.grid,width=112,height=142,highlightthickness=0,bg=SURFACE,takefocus=1,cursor='hand2');card.grid(row=n//2,column=n%2,padx=5,pady=6,sticky='nsew');self.cards[key]=card
            for event in ('<Button-1>','<Return>','<space>'):card.bind(event,lambda ev,k=key:(self.choose(k),'break')[1])
            for event in ('<Enter>','<FocusIn>'):card.bind(event,lambda ev,k=key:self.set_hover(k))
            for event in ('<Leave>','<FocusOut>'):card.bind(event,lambda ev:self.set_hover(None))
            self.draw_card(key,None)
        self.grid.columnconfigure(0,weight=1);self.grid.columnconfigure(1,weight=1);self.catalog_scroll.attach()

    def set_hover(self,key):self.hover=key;self.hover_start=time.monotonic()

    def draw_card(self,key,image):
        card=self.cards[key];w=max(112,card.winfo_width());selected=self.active and key==self.key
        focused=card.focus_get()==card
        stamp=(id(image),w,selected,focused)
        if self.drawn.get(key)==stamp:return
        self.drawn[key]=stamp;card.delete('all');background=Image.new('RGB',(w,142),SURFACE);draw=ImageDraw.Draw(background)
        draw.rounded_rectangle((1,1,w-2,140),radius=12,fill=SELECTED if selected else '#24252b',outline=ACCENT if selected else '#303137')
        if image:
            image=image.copy();image.thumbnail((w-16,104),Image.Resampling.LANCZOS);background.paste(image,((w-image.width)//2,8+(104-image.height)//2),image)
        photo=ImageTk.PhotoImage(background);self.photos[key]=photo;card.create_image(0,0,image=photo,anchor='nw');card.create_text(9,126,text=EFFECTS[key],fill=INK,anchor='w',font=('Microsoft YaHei UI',10))
        if selected:card.create_text(w-12,13,text='✓',fill=INK,font=('Segoe UI',10))
        if focused:card.create_rectangle(5,5,w-6,136,outline=ACCENT,width=1)

    def open(self):
        e=self.e
        if not e.doc or e.busy:return
        layer=next((l for l in e.doc.layers if l['id']==e.selected_layer and l['kind']=='sticker'),None)
        e.show_browser(e.effects_host);e.show_property(self.page)
        if layer is None:
            self.hide();self.apply_button.configure(state='disabled');self.target_text.set('目标：请选中图片 / GIF 图层');self.note.set('请在画布或图层中明确选择一张图片 / GIF，再选择动效。');return
        self.target_text.set('目标：图层 '+str(next(n+1 for n,l in enumerate(e.doc.layers) if l['id']==layer['id']))+' · '+('动态素材' if layer.get('animation') else '静态图片'))
        self.apply_button.configure(state='normal')
        if not self.active or self.layer['id']!=layer['id'] or self.revision!=e.doc.revision:
            self.layer=dict(layer);self.revision=e.doc.revision;self.source=layer.get('animation');self.last_image=None;self.document=copy(e.doc)
            if self.source is None:
                raw=BytesIO();layer['image'].save(raw,'PNG');self.source=GifSource(raw.getvalue(),(layer['image'],),(100,),None)
            if layer.get('mask') is not None:
                from emoji_bridge.cutout_masks import MaskedFrames
                from emoji_bridge.animated_edit import SubjectSource
                self.source=SubjectSource(self.source.original,MaskedFrames(self.source.frames,[layer['mask']]*len(self.source.frames)),self.source.durations,self.source.loop,self.source.container_suffix)
            self.elapsed=sum(e.doc.animation.durations[:e.animation_frame]) if e.doc.animation else 0;self.started=time.monotonic()
        self.active=True;self.playing=True;e.playing=False;self.keys.set_active(True)
        e.play_button.configure(text='暂停 · 空格')
        if e.doc.animation:self.bottom.pack_forget()
        else:self.bottom.pack(fill='x',pady=(8,0))
        # Leave the last valid work visible while the first frame is prepared.
        # Only swap the overlay after a matching result exists.
        self.choose(self.key)
        if self.last_image is None:
            self.placeholder.configure(text='正在准备效果预览…');self.placeholder.place(relx=.5,rely=.5,anchor='center')

    def open_timing(self):
        """Use the same immutable source snapshot without starting an effect."""
        e=self.e;self.hide();e.show_property(self.timing_page)
        layer=next((l for l in e.doc.layers if l['id']==e.selected_layer and l.get('animation')),None) if e.doc else None
        self.layer=dict(layer) if layer else None
        self.timing_apply.configure(state='normal' if layer else 'disabled')
        if not layer:self.timing_note.set('先在画布或图层列表选中一张动图。');return
        self.source=layer['animation'];self.revision=e.doc.revision
        self.timing_note.set(f'{len(self.source.frames)} 帧 · {sum(self.source.durations)/1000:g} 秒；每次应用都可撤销。')

    def timing_fields_changed(self,*_):
        key=next(k for k,v in TIMING.items() if v==self.timing.get())
        for row in (self.frame_row,self.ms_bar,self.speed_bar):row.pack_forget()
        if key in ('freeze','delete','duplicate','duration'):self.frame_row.pack(fill='x',pady=px(self.e.window,6))
        if key in ('freeze','duration'):self.ms_bar.pack(fill='x',pady=px(self.e.window,8))
        if key=='speed':self.speed_bar.pack(fill='x',pady=px(self.e.window,8))
        self.timing_help.set({'reverse':'把当前动画从后向前播放。再次应用可恢复原方向。','pingpong':'先正放，再倒放，首尾衔接。','speed':'相对于当前动画调整；1×保持当前速度。','freeze':'让指定帧停留更久，再继续播放。','delete':'删除指定帧，至少保留一帧。','duplicate':'在指定帧后增加一份相同的帧。','duration':'统一设置指定帧的停留时长。'}[key])

    def choose(self,key):
        if key!=self.key:self.jobs.clear_pending();self.display_stamp=None
        self.key=key;self.effect.set(EFFECTS[key]);self.title.configure(text=EFFECTS[key])
        self.e.show_property(self.page)
        if not self.active:self.open();return
        show={'strength'}|({'width','blur'} if key in ('outline','shadow','glow') else {'pixel'} if key=='retro' else set())
        for name,row in self.rows.items():
            if name in show:row.pack(fill='x',pady=(0,14),before=self.parameter_end)
            else:row.pack_forget()
        ceiling=.65 if key in ('squash','spin_bounce','jelly') else 1
        for widget in self.rows['strength'].winfo_children():
            if isinstance(widget,ttk.Scale):widget.configure(to=ceiling)
            for child in widget.winfo_children():
                if isinstance(child,ttk.Spinbox):child.configure(to=ceiling)
        try:
            if self.strength.get()>ceiling:self.strength.set(ceiling)
        except tk.TclError:pass
        for widget,visible in [(self.retro,key=='retro'),(self.color_button,key in ('outline','shadow','glow'))]:
            if visible:widget.pack(fill='x',before=self.parameter_end)
            else:widget.pack_forget()
        for name,row in self.motion_rows.items():
            visible=(name=='source_speed' and self.source is not None and len(self.source.frames)>1) or (key in ('squash','spin_bounce','jelly') and (name!='turn_speed' or key=='spin_bounce'))
            if visible:row.pack(fill='x',pady=(0,12),before=self.parameter_end)
            else:row.pack_forget()
        self.changed()

    def changed(self,*_):
        if self.active:self.note.set('正在更新预览…');self.redraw()

    def choose_color(self):
        value=colorchooser.askcolor(self.color,parent=self.e.window)[1]
        if value:self.color=value;self.changed()

    def toggle(self):
        if self.playing:self.elapsed+=(time.monotonic()-self.started)*1000
        else:
            start,end,_=self.playback_bounds()
            if not start<=self.elapsed<end:self.elapsed=start
            self.started=time.monotonic()
        self.playing=not self.playing;self.play.configure(text='暂停 · 空格' if self.playing else '播放 · 空格')
        self.e.play_button.configure(text='暂停 · 空格' if self.playing else '播放 · 空格')

    def playback_bounds(self):
        animation=self.document.animation
        if hasattr(self,'source_speed') and getattr(self,'layer',None):
            try:
                clock=self.recipe_clock(self.recipe())
                from emoji_bridge.animated_edit import CompositeTimeline
                signature=(id(clock),self.document.revision)
                if signature!=getattr(self,'play_clock_key',None):
                    layers=[{**l,'animation':clock} if l['id']==self.layer['id'] else l for l in self.document.layers]
                    self.play_clock=CompositeTimeline([l for l in layers if l.get('animation')]);self.play_clock_key=signature
                animation=self.play_clock
            except (ValueError,tk.TclError):pass
        if animation:
            total=sum(animation.durations);start,end=self.e.doc.time_range or (0,total)
            start=min(start,max(0,total-1));end=max(start+1,min(end,total))
            return start,end,animation.loop
        return 0,2000,0

    def position(self):
        value=self.elapsed+((time.monotonic()-self.started)*1000 if self.playing else 0)
        start,end,loop=self.playback_bounds();span=end-start
        if not self.playing:return max(0,min(value,end-1))
        value=max(start,value);plays=1 if loop is None else loop+1
        if loop!=0 and value-start>=span*plays:
            self.elapsed=end-1;self.playing=False
            self.play.configure(text='播放 · 空格');self.e.play_button.configure(text='播放 · 空格')
            return self.elapsed
        return start+(value-start)%span

    def seek(self,milliseconds):
        self.elapsed=milliseconds;self.playing=False;self.play.configure(text='播放 · 空格');self.e.play_button.configure(text='播放 · 空格');self.redraw()

    def recipe_clock(self,recipe):
        rate=self.source_speed.get() if hasattr(self,'source_speed') else 1
        signature=(id(self.source),json.dumps(recipe,sort_keys=True),rate)
        # Use the output recipe's actual union of source and effect timestamps.
        # Unequal source frames and finite loops must not drift in the preview.
        if not hasattr(self,'recipe_clocks'):self.recipe_clocks=OrderedDict()
        clock=self.recipe_clocks.get(signature)
        if clock is None:
            clock=apply_recipe(self.source,{'effects':[recipe],'source_speed':rate});self.recipe_clocks[signature]=clock
            while len(self.recipe_clocks)>12:self.recipe_clocks.popitem(last=False)
        self.recipe_clocks.move_to_end(signature)
        return clock

    def frame_key(self,recipe,elapsed,edge):
        rate=self.source_speed.get() if hasattr(self,'source_speed') else 1
        signature=(id(self.source),json.dumps(recipe,sort_keys=True),rate)
        clock=self.recipe_clock(recipe)
        frame,_=clock.frame_at(elapsed);index=clock.frames.indices[frame]
        stamp=clock.frames.starts[frame];total=clock.frames.total
        key=(signature[0],signature[1]+str(signature[2]),index,stamp,edge);source=self.source
        def render():
            image=source.frames[index].copy();ratio=min(1,edge/max(image.size));image.thumbnail((edge,edge),Image.Resampling.LANCZOS);params=dict(recipe)
            for name in ('width','blur','pixel','offset'):
                if name in params:params[name]=round(params[name]*ratio)
            return apply_effect(image,params,stamp,total)
        return key,render

    def redraw(self):
        if not self.active or not self.source:return
        try:recipe=self.recipe()
        except (ValueError,tk.TclError):return
        try:elapsed=self.position();key,render_effect=self.frame_key(recipe,elapsed,384)
        except (ValueError,tk.TclError):return
        document=self.document;target=self.layer;source_size=target['image'].size
        base,staged,region=placed_effect(document,target,target['image'],source_size,effect_size(source_size,recipe),{'effects':[recipe]},geometry_only=True)
        size=(region[2]-region[0],region[3]-region[1]);scale=min(self.e.scale,960/max(size))
        frame=document.animation.frame_at(elapsed)[0] if document.animation else 0
        # Other layers may continue after the selected layer has looped.
        key=(*key,document.revision,round(scale,5),frame,int(elapsed//50))
        signature=(key[0],key[1],document.revision)
        if signature!=self.prepare_signature:
            if self.progress.activity.get('active'):self.progress.finish(error=InterruptedError('预览已更新'))
            self.prepare_signature=signature;self.prepare_wait=time.monotonic()
        def render():
            from layout_editor import preview_layer
            canvas=Image.new('RGBA',tuple(max(1,round(n*scale)) for n in size))
            canvas.alpha_composite(base.resize(tuple(max(1,round(n*scale)) for n in base.size),Image.Resampling.LANCZOS),(-round(region[0]*scale),-round(region[1]*scale)))
            for original in staged:
                layer=dict(original)
                if layer['id']==target['id']:
                    layer.update(image=render_effect(),animation=None,mask=None)
                elif layer.get('animation'):
                    source=layer['animation'];at=elapsed%sum(source.durations) if layer.get('role')=='background' else elapsed
                    layer['image']=source.frames[source.frame_at(at)[0]]
                if layer.get('tracking'):
                    from emoji_bridge.tracking import tracked_layer
                    layer=tracked_layer(layer,elapsed)
                if layer.get('text_motion'):layer['_elapsed']=elapsed
                canvas.alpha_composite(preview_layer(layer,scale),dest=tuple(round(n*scale) for n in layer['position']))
            return canvas
        self.jobs.request('central',key,render)
        if self.jobs.errors.get('central'):
            self.note.set('预览失败：'+self.jobs.errors['central'])
            self.progress.finish(error=ValueError('预览未完成'));self.prepare_wait=None
            if self.last_image is None:self.placeholder.configure(text='预览未完成，请调整参数后重试')
        image=self.jobs.get(key)
        completed=self.jobs.completed('central')
        if image is None and completed and completed[0][:2]==key[:2] and completed[0][4:7]==key[4:7]:image=completed[1]
        if image is not None:
            if self.prepare_wait is not None:self.progress.finish();self.prepare_wait=None
            self.last_image=image
            self.overlay.place(x=0,y=0,relwidth=1,relheight=1);self.overlay.lift()
            clock=self.recipe_clock(recipe);seconds=sum(clock.durations)/1000
            extended=sum(clock.durations)>sum(self.source.durations) and len(self.source.frames)>1
            warning=''
            if self.key in ('squash','spin_bounce','jelly') and clock.loop==0:
                cycles=[seconds*self.frequency.get()]
                if self.key=='spin_bounce':cycles.append(seconds*self.turn_speed.get())
                if any(abs(c-round(c))>.001 for c in cycles):warning=' 当前参数的公共周期超过10秒，保留原时长；首尾动效可能跳变，可调整频率或速度。'
            self.note.set(f'选中图片图层 · 成品 {seconds:g} 秒'+('；短源动画循环对齐动效。' if extended else '；应用后可撤销。')+(' 转身为薄片近似，没有真实侧面/背面。' if self.key=='spin_bounce' else '')+warning)
        elif self.prepare_wait is not None:
            if time.monotonic()-self.prepare_wait>.15 and not self.progress.activity.get('active'):
                self.progress.begin('准备当前效果预览')
            # Don't resize yesterday's frame using today's effect geometry.
            return
        image=self.last_image
        if image is not None:
            self.placeholder.place_forget()
            viewport=(self.canvas.winfo_width(),self.canvas.winfo_height())
            stamp=(id(image),viewport,self.e.scale,self.e.origin,region)
            if getattr(self,'display_stamp',None)==stamp:return
            self.display_stamp=stamp
            check,position=effect_viewport(image,region,self.e.scale,self.e.origin,viewport)
            self.canvas.delete('all')
            if check is not None:
                self.photo=ImageTk.PhotoImage(check);self.canvas.create_image(*position,image=self.photo,anchor='nw')

    def poll(self):
        if self.closed:return
        visible=self.e.view_active and self.e.effects_host.winfo_ismapped()
        if visible:
            if self.source is None:
                sample=Image.new('RGBA',(128,128));d=ImageDraw.Draw(sample);d.rounded_rectangle((28,15,100,98),18,fill='#b195db');d.polygon([(48,98),(78,98),(63,118)],fill='#e9c486');self.source=GifSource(b'',(sample,),(100,),None)
            for key,card in self.cards.items():
                if card.winfo_rooty()+142<self.catalog_scroll.winfo_rooty() or card.winfo_rooty()>self.catalog_scroll.winfo_rooty()+self.catalog_scroll.winfo_height():continue
                recipe={'key':key,'strength':.3,'width':6,'blur':8,'pixel':2,'seed':1};elapsed=(time.monotonic()-getattr(self,'hover_start',0))*1000 if self.hover==key else 400
                cache,render=self.frame_key(recipe,elapsed,96);self.jobs.request('card-'+key,cache,render);image=self.jobs.get(cache)
                if image is not None:self.draw_card(key,image)
        if self.active and self.e.view_active:self.redraw()
        self.poll_id=self.e.window.after(40,self.poll)

    def hide(self):
        if not self.active:return
        self.active=False;self.keys.set_active(False);self.overlay.place_forget();self.jobs.clear_pending();self.e.play_button.configure(text='播放动画');self.e.canvas.focus_set()
        if self.prepare_wait is not None:self.progress.finish(error=InterruptedError('预览已退出'));self.prepare_wait=None
        self.apply_button.configure(state='disabled');self.note.set('预览已退出；再次选择动效卡可预览当前选中图层。')

    def apply_effect(self):
        if not self.layer or not self.active:return
        try:self.apply({'effects':[self.recipe()],'source_speed':self.source_speed.get()})
        except (ValueError,tk.TclError) as exc:self.note.set(str(exc))

    def apply_timing(self):
        if self.e.busy:return
        # Resolve the selected layer now, including the result of the previous
        # operation or undo. A stale panel snapshot must never block the next edit.
        self.open_timing()
        if not self.layer:return
        try:
            key=next(k for k,v in TIMING.items() if v==self.timing.get())
            operation={'key':key}
            if key in ('freeze','delete','duplicate','duration'):
                operation['frames']=[int(n.strip())-1 for n in self.frames.get().replace('，',',').split(',') if n.strip()]
                if not operation['frames']:raise ValueError('请输入要处理的帧号。')
            if key in ('freeze','duration'):operation['ms']=self.ms.get()
            if key=='speed':operation['factor']=self.speed.get()
            self.apply({'timing':[operation]})
        except (ValueError,tk.TclError) as exc:self.timing_note.set(str(exc) or '请输入有效帧号、时长和速度。')

    def apply(self,recipe):
        e=self.e
        if not e.doc or not self.layer or e.busy:return
        layer=self.layer;source=self.source;revision=e.doc.revision
        if revision!=self.revision:self.note.set('作品已有新修改，请重新打开效果。');return
        self.hide()
        def work():
            result=apply_recipe(source,recipe);first=result.frames[0]
            if e.closed or e.doc.revision!=revision:raise InterruptedError('作品已改变，未替换图层')
            base,layers=placed_effect(e.doc,layer,first,source.frames[0].size,first.size,recipe,result)
            from emoji_bridge.animated_edit import check_cancel
            check_cancel(e.save_cancel)
            e.doc.replace_scene(base,layers,e.doc.source_ids,'添加动效 / 帧操作');return {'effect_applied':recipe.get('effects',[{}])[0].get('key'),'timing_applied':bool(recipe.get('timing'))}
        e.submit(work,'应用效果',xp=self.progress)

    def close(self):
        self.closed=True;self.jobs.close();self.keys.set_active(False)
        if self.poll_id:self.e.window.after_cancel(self.poll_id)
