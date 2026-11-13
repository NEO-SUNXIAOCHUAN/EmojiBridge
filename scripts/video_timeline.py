"""Single video range on native Tk Canvas; FFmpeg thumbnail decoding stays off Tk."""
import math
import queue
import threading
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageTk,ImageOps
from ui_style import BG,INK,MUTED,ACCENT,FONT,TIMELINE,MIDNIGHT,BORDER


def clock(seconds, precision=1):
    # Tick precision follows the visible spacing, so short GIFs do not repeat labels.
    scale=10**precision;units=round(max(0,seconds)*scale)
    minutes,within=divmod(units,60*scale)
    return f'{minutes:02d}:{within/scale:0{3+precision}.{precision}f}'


class ClipTimeline(ttk.Frame):
    def __init__(self,parent,changed):
        super().__init__(parent);self.changed=changed;self.duration=1.;self.start=0.;self.end=1.;self.position=0.
        self.view_start=0.;self.span=1.;self.cache=None;self.dragging=None;self.enabled=True
        self.photos={};self.generation=0;self.jobs=queue.Queue(maxsize=1);self.results=queue.Queue();self.stop=threading.Event()
        self.canvas=tk.Canvas(self,height=150,bg=TIMELINE,highlightthickness=0,takefocus=1)
        self.canvas.pack(fill='x');self.scroll=ttk.Scrollbar(self,orient='horizontal',command=self.pan);self.scroll.pack(fill='x')
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',self.release);self.canvas.bind('<Motion>',self.hover)
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<Left>',lambda e:self.step(-.1));self.canvas.bind('<Right>',lambda e:self.step(.1))
        self.bind('<Destroy>',self.destroyed,add='+')
        threading.Thread(target=self.worker,daemon=True).start();self.poll_id=self.after(35,self.poll)

    @property
    def width(self):return max(100,self.canvas.winfo_width()-24)
    @property
    def band_top(self):return 40
    @property
    def band_bottom(self):return max(76,self.canvas.winfo_height()-34)
    @property
    def footer_offset(self):return 23
    def x(self,t):return 12+(t-self.view_start)/self.span*self.width
    def seconds(self,x):return max(0,min(self.duration,self.view_start+(x-12)/self.width*self.span))

    def set_source(self,cache,start=0,end=None):
        self.cache=cache;self.duration=cache.metadata['duration'];self.start=start;self.end=min(end or 2,self.duration)
        self.position=start;self.view_start=0.;self.span=self.duration;self.draw()

    def set_position(self,value):
        self.position=max(0,min(self.duration,value));self.overlay()

    def zoom(self,factor,anchor=None):
        anchor=anchor if anchor is not None else self.view_start+self.span/2
        fraction=(anchor-self.view_start)/self.span
        self.span=max(min(.25,self.duration),min(self.duration,self.span/factor))
        self.view_start=max(0,min(self.duration-self.span,anchor-fraction*self.span));self.draw()

    def fit(self,selection=False):
        self.span=min(self.duration,max(.25,(self.end-self.start)*1.3)) if selection else self.duration
        self.view_start=max(0,min(self.duration-self.span,(self.start+self.end-self.span)/2)) if selection else 0
        self.draw()

    def pan(self,*args):
        if args[0]=='moveto':position=float(args[1])*self.duration
        else:position=self.view_start+int(args[1])*self.span*(.8 if args[2]=='pages' else .1)
        self.view_start=max(0,min(self.duration-self.span,position));self.draw()

    def wheel(self,event):
        if event.state&1:self.pan('scroll',-1 if event.delta>0 else 1,'units')
        else:self.zoom(1.3 if event.delta>0 else 1/1.3,self.seconds(event.x))
        return 'break'

    def draw(self):
        self.generation+=1;self.photos={};c=self.canvas;c.delete('all');w=self.width
        self.scroll.set(self.view_start/self.duration,(self.view_start+self.span)/self.duration)
        if self.span<self.duration-.00001:
            if not self.scroll.winfo_manager():self.scroll.pack(side='bottom',fill='x',before=self.canvas)
        elif self.scroll.winfo_manager():self.scroll.pack_forget()
        raw=self.span/max(2,w/110);power=10**math.floor(math.log10(max(raw,.01)))
        step=next(v*power for v in (1,2,5,10) if v*power>=raw)
        t=math.ceil(self.view_start/step)*step
        precision=max(1,min(3,-math.floor(math.log10(step))))
        while t<=self.view_start+self.span+.0001:
            x=self.x(t);c.create_line(x,self.band_top-12,x,self.band_top-5,fill=MUTED);c.create_text(x,max(10,self.band_top-24),text=clock(t,precision),fill=MUTED,font=(FONT,9));t+=step
        count=max(2,math.ceil(w/106));segment=self.span/count;requests=[]
        for i in range(count):
            x=12+i*w/count;seconds=round(self.view_start+i*segment,2)
            c.create_rectangle(x,self.band_top,x+w/count,self.band_bottom,fill=BORDER if MIDNIGHT else '#dce3e9',outline=TIMELINE)
            requests.append((i,x,seconds,math.ceil(w/count),max(1,self.band_bottom-self.band_top-2)))
        self.overlay()
        if self.cache:
            try:self.jobs.get_nowait()
            except queue.Empty:pass
            self.jobs.put((self.generation,self.cache,requests))

    def overlay(self):
        c=self.canvas;c.delete('selection');right=12+self.width;top=self.band_top;bottom=self.band_bottom
        a=max(12,min(right,self.x(self.start)));b=max(12,min(right,self.x(self.end)))
        for x1,x2 in ((12,a),(b,right)):
            if x2>x1:c.create_rectangle(x1,top,x2,bottom,fill='#142538',stipple='gray50',outline='',tags='selection')
        if b>a:
            c.create_rectangle(a,top-1,b,bottom+1,outline=ACCENT,width=2,tags='selection')
            for time in (self.start,self.end):
                x=self.x(time)
                if 12<=x<=right:
                    c.create_rectangle(x-5,top-2,x+5,bottom+2,fill=ACCENT,outline='',tags='selection')
                    mid=(top+bottom)/2;c.create_line(x,mid-8,x,mid+8,fill='white',width=2,tags='selection')
        x=self.x(self.position)
        if 12<=x<=right:
            c.create_line(x,top-10,x,bottom+min(15,self.footer_offset-5),fill='#d85b43',width=2,tags='selection')
            c.create_polygon(x-5,top-10,x+5,top-10,x,top-3,fill='#d85b43',tags='selection')
        c.create_text(12,bottom+self.footer_offset,anchor='w',text=f'{clock(self.start)} — {clock(self.end)}',fill=INK,font=(FONT,9),tags='selection')
        c.create_text(right,bottom+self.footer_offset,anchor='e',text=f'选中 {self.end-self.start:.2f} 秒',fill=ACCENT,font=(FONT,9,'bold'),tags='selection')

    def hit(self,event):
        if self.band_top-5<=event.y<=self.band_bottom+4:
            for role,value in [('start',self.start),('end',self.end)]:
                if abs(event.x-self.x(value))<=9:return role
        if abs(event.x-self.x(self.position))<=6 or event.y<self.band_top-5 or event.y>self.band_bottom+4:return 'head'
        return 'range' if self.start<self.seconds(event.x)<self.end else 'head'

    def hover(self,event):
        role=self.hit(event);self.canvas.configure(cursor='sb_h_double_arrow' if role in ('start','end') else 'fleur' if role=='range' else 'crosshair')

    def press(self,event):
        if not self.enabled or not self.cache:return
        self.canvas.focus_set();self.dragging=(self.hit(event),self.seconds(event.x),self.start,self.end,self.position)
        self.motion(event)

    def motion(self,event):
        if not self.dragging:return
        role,origin,start,end,position=self.dragging;t=self.seconds(event.x);minimum=min(.05,self.duration)
        if role=='start':self.start=min(self.end-minimum,t);self.position=self.start
        elif role=='end':self.end=max(self.start+minimum,t);self.position=max(self.start,self.end-.001)
        elif role=='range':
            delta=max(-start,min(self.duration-end,t-origin));self.start=start+delta;self.end=end+delta
            self.position=max(self.start,min(self.end-.001,position+delta))
        else:self.position=t
        self.overlay();self.changed(self,False)

    def release(self,event):
        if self.dragging:self.motion(event);self.dragging=None;self.changed(self,True)

    def step(self,delta):
        self.set_position(self.position+delta);self.changed(self,True)

    def worker(self):
        while not self.stop.is_set():
            try:generation,cache,requests=self.jobs.get(timeout=.1)
            except queue.Empty:continue
            for i,x,seconds,width,height in requests:
                if self.stop.is_set() or generation!=self.generation:break
                try:
                    value=cache.get(seconds,160,self.stop)
                    value=ImageOps.fit(value,(width,height),Image.Resampling.LANCZOS)
                    self.results.put((generation,i,x,value))
                except Exception:pass # unavailable cover stays a placeholder; output errors use the normal task flow

    def poll(self):
        try:
            while True:
                generation,i,x,value=self.results.get_nowait()
                if generation!=self.generation:continue
                photo=ImageTk.PhotoImage(value);self.photos[i]=photo
                self.canvas.create_image(x,self.band_top+1,image=photo,anchor='nw');self.canvas.tag_raise('selection')
        except queue.Empty:pass
        self.poll_id=self.after(35,self.poll)

    def destroyed(self,event):
        if event.widget is self:
            self.stop.set();self.after_cancel(self.poll_id)
