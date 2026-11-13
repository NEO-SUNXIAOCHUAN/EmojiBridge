"""Local Tk desktop picker. Selection is explicit; client work uses existing queue."""
import argparse,json,queue,sys,threading,time,traceback
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
import tkinter as tk
from tkinter import ttk
from ui_dialogs import messagebox, prepare_window, details_window
from ui_style import BG,SURFACE,INK,MUTED,ACCENT,SELECTED,BORDER,SUCCESS,WARNING,DUPLICATE,DISABLED,MIDNIGHT
from PIL import Image,ImageTk,ImageOps
from emoji_bridge import catalog
from emoji_bridge.state import save_json,single_instance
from emoji_bridge.transfer import make_export_plan,run_plan
from scan_view import RecentWechatScan,retained_scroll_top


def decode_preview(path,key,events):
    # Worker owns only image data and its result queue, never the Tk App.
    # Closing a window while decoding must not release Tk objects off-thread.
    try:
        with Image.open(path) as im:
            im.thumbnail((80,66));frame=im.convert('RGBA')
        events.put((key,frame))
    except (OSError,ValueError):events.put((key,None))


class App:
    def __init__(self,root,auto_previews=True,on_library=None,material_store=None):
        self.root=root;self.library=catalog.bootstrap();self.selected={'wechat':set(),'qq':set()}
        self.recent_wechat=RecentWechatScan(self.library['clients']['wechat']);self.wechat_refresh_pending=False
        self.rendered_ids={}
        self.events=queue.Queue();self.busy=False;self.stopping=False;self.images=[];self.page={'wechat':0,'qq':0}
        self.filters={};self.panes={};self.stats={};self.page_labels={};self.plan=None;self.read_details={}
        self.read_headers={};self.header_align_after=None
        self.canvases={};self.preview_reader=None;self.preview_tried=set();self.preview_busy=False;self.preview_after=None
        self.card_windows={};self.visible_cards={'wechat':{},'qq':{}};self.image_cache=OrderedDict();self.row_height=174
        self.auto_previews=auto_previews
        self.auto_paused=False;self.summary_after=None;self.last_detail='';self.progress_total=0
        from emoji_bridge.transfer_history import collect
        self.transfer_facts=collect(ROOT,self.library)
        from emoji_bridge.collection_overlap import collect as overlap
        self.overlap_facts=overlap(self.library)
        self.wechat_prepare_pending=auto_previews
        self.draw_after={};self.pending_scroll={}
        self.thumb_pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='display-preview')
        self.thumb_events=queue.Queue();self.thumb_pending=set();self.thumb_failed=set();self.destroyed=False
        self.preview_invalid=set();self.pending_resume=False
        root.bind('<Destroy>',self.destroy_preview_workers,add='+')
        self.pending_transfer=None;self.pending_plan=None;self.deferred_event=None;self.record_read_retries=0
        from emoji_bridge.materials import MaterialStore,default_root
        self.material_store=material_store or MaterialStore(default_root());self.pending_library_import=None
        self.preview_redirect=False;self.loading_previews=False
        self.preview_loading_ids=set()
        self.qq_cache_hint='';self.qq_cache_checking=False
        self.cancel=ROOT/'runtime-data/T005/current.cancel'
        # Keep task controls on-screen on smaller 100% displays. The canvas
        # takes the remaining height; client calibration is checked separately.
        from emoji_bridge.windows import monitor_work_area
        root.update_idletasks()
        area=monitor_work_area(root.winfo_id())
        available_width=max(600,area[2]-area[0]-24);available_height=max(500,area[3]-area[1]-56)
        width=min(1220,available_width);height=min(880,available_height)
        root.title('表情互通 · 本地选择');root.geometry(f'{width}x{height}')
        root.minsize(min(1000,width),min(680,height))
        root.configure(bg=BG);root.protocol('WM_DELETE_WINDOW',self.close)
        from ui_style import apply
        apply(root)
        top=ttk.Frame(root,padding=(22,16));top.pack(fill='x')
        ttk.Label(top,text='表情互通',style='Title.TLabel').pack(side='left')
        from material_library_ui import launch_library
        ttk.Button(top,text='素材库',command=on_library or launch_library).pack(side='right',padx=6)
        ttk.Label(top,text='本地运行  /  仅搬运你勾选的项目',foreground=MUTED).pack(side='left',padx=20)
        ttk.Button(top,text='刷新记录',command=self.reload).pack(side='right')
        ttk.Button(top,text='导出反馈',command=self.export_feedback).pack(side='right',padx=5)
        ttk.Button(top,text='兼容能力',command=self.compatibility_info).pack(side='right',padx=5)
        ttk.Label(root,text='先浏览、勾选，再准备所选原件并搬运。原平台收藏保留；未取得的项目会说明原因。',foreground=MUTED).pack(anchor='w',padx=24,pady=(0,10))
        middle=ttk.Frame(root,padding=(18,0));middle.pack(fill='both',expand=True)
        for n,client in enumerate(('wechat','qq')):
            panel=ttk.Frame(middle,padding=8);panel.grid(row=0,column=n,sticky='nsew',padx=4)
            middle.columnconfigure(n,weight=1,uniform='halves')
            header=ttk.Frame(panel);header.pack(fill='x');header.pack_propagate(False)
            header_body=ttk.Frame(header);header_body.pack(fill='x')
            self.read_headers[client]=(header,header_body)
            color=SUCCESS if client=='wechat' else ACCENT
            heading=ttk.Frame(header_body);heading.pack(fill='x')
            ttk.Label(heading,text=('微信' if client=='wechat' else 'QQ'),font=('Microsoft YaHei UI',16,'bold'),foreground=color).pack(side='left')
            ttk.Button(heading,text='读取详情',command=lambda c=client:details_window(self.root,('微信' if c=='wechat' else 'QQ')+' · 读取详情',self.read_details.get(c,'尚无读取记录。'))).pack(side='right')
            self.stats[client]=ttk.Label(header_body,wraplength=540,foreground=MUTED);self.stats[client].pack(anchor='w',pady=(5,8))
            row=ttk.Frame(header_body);row.pack(fill='x')
            self.filters[client]=tk.StringVar(value='全部')
            combo=ttk.Combobox(row,textvariable=self.filters[client],values=['全部','可搬运','暂不可搬运','已添加到微信'] if client=='qq' else ['全部','已取得原件','待获取原件','原件已取待核验','暂时无法获取','已添加到QQ'],state='readonly',width=14)
            combo.configure(values=[*combo.cget('values'),'两边都有','重复／已添加','未标重复'])
            if client=='wechat':combo.configure(values=[*combo.cget('values'),'本次新出现'])
            combo.pack(side='left');combo.bind('<<ComboboxSelected>>',lambda e,c=client:self.filter(c))
            more=ttk.Menubutton(row,text='更多',width=5);more.pack(side='right')
            extra=tk.Menu(more,tearoff=False);more.configure(menu=extra)
            if client=='qq':
                extra.add_command(label='准备全部原件',command=self.prepare_qq)
                extra.add_command(label='继续读取更多',command=self.read_qq)
                ttk.Button(row,text='刷新 QQ 收藏',command=lambda:self.read_qq(expand=False)).pack(side='right',padx=4)
            else:
                extra.add_command(label='准备全部原件',command=lambda:self.refresh_wechat(full=True))
                ttk.Button(row,text='更新微信收藏',command=self.refresh_wechat).pack(side='right')
                # Retain the complete hint for details and existing observers;
                # do not add a one-sided extra row above the material grid.
                self.recent_wechat_hint=ttk.Label(header_body,wraplength=355,foreground=MUTED)
                self.recent_wechat_button=ttk.Button(heading,text='定位新增',command=self.locate_recent_wechat)
                self.recent_wechat_button.pack(side='right',padx=(4,0))
            area=ttk.Frame(panel);area.pack(fill='both',expand=True,pady=10)
            canvas=tk.Canvas(area,bg=BG,highlightthickness=0,width=420,height=400)
            from ui_scroll import OverlayScrollbar
            bar=OverlayScrollbar(canvas,command=lambda *args,c=client:self.scroll_to(c,*args))
            canvas.pack(side='left',fill='both',expand=True)
            # A single drawing surface: scrolling native child windows causes
            # stale WM_PAINT regions during rapid scrollbar motion on Windows.
            self.panes[client]=canvas;self.canvases[client]=canvas
            canvas.bind('<Button-1>',lambda e,c=client:self.click_card(c,e))
            canvas.bind('<space>',lambda e,c=client:self.toggle_focused(c))
            canvas.bind('<Button-3>',lambda e,c=client:self.library_menu(c,e))
            canvas.configure(takefocus=True,yscrollincrement=44)
            canvas.bind('<Configure>',lambda e,c=client:self.resize_cards(c,e.width))
            nav=ttk.Frame(panel);nav.pack(side='bottom',fill='x',before=area)
            ttk.Button(nav,text='回到顶部',command=lambda c=client:self.scroll_to(c,'moveto',0)).pack(side='left')
            self.page_labels[client]=ttk.Label(nav);self.page_labels[client].pack(side='left',padx=5)
            ttk.Button(nav,text='清空勾选',command=lambda c=client:self.clear(c)).pack(side='right')
            ttk.Button(nav,text='全选匹配项',command=lambda c=client:self.select_matching(c)).pack(side='right')
            actions=ttk.Frame(panel);actions.pack(side='bottom',fill='x',pady=(8,0),before=nav)
            ttk.Button(actions,text='搬运所选 → '+('QQ' if client=='wechat' else '微信'),command=lambda c=client:self.transfer(c),style='Editor.Primary.TButton').pack(side='right')
            ttk.Button(actions,text='加入素材库',command=lambda c=client:self.import_materials(c)).pack(side='right',padx=3)
            extra.add_command(label='重试上次入库未完成项',command=lambda c=client:self.retry_materials(c))
            panel.bind('<Configure>',lambda e,c=client:self.resize_read_header(c,e.width),add='+')
        middle.rowconfigure(0,weight=1)
        bottom=ttk.Frame(root,padding=(24,12));bottom.pack(side='bottom',fill='x',before=middle)
        ttk.Label(bottom,text='原件就绪后可加入素材库或搬运。QQ不发消息；微信通过文件传输助手，每批最多5张。',foreground=MUTED,wraplength=1080).pack(anchor='w',pady=(0,10))
        self.status=tk.StringVar(value='就绪。未勾选任何项目，不会自动发送或添加。')
        self.task_result=tk.StringVar(value='')
        messages=ttk.Frame(bottom);messages.pack(side='left',fill='x',expand=True)
        self.progress_bar=ttk.Progressbar(messages,mode='determinate',maximum=1,value=0)
        self.progress_bar.pack(fill='x',pady=(0,5),padx=(0,12))
        ttk.Label(messages,textvariable=self.task_result,wraplength=680).pack(anchor='w')
        ttk.Label(messages,textvariable=self.status,wraplength=680).pack(anchor='w')
        ttk.Button(bottom,text='取消当前任务',command=self.stop).pack(side='right')
        ttk.Button(bottom,text='继续上次队列',command=self.resume).pack(side='right',padx=5)
        ttk.Button(bottom,text='查看详情',command=self.show_details).pack(side='right',padx=5)
        self.root.after(150,self.poll);self.render()
        self.root.bind('<MouseWheel>',self.wheel)
        self.root.after(900,self.schedule_previews)
        if auto_previews:
            self.root.after(500,self.check_qq_cache)
            self.root.after(650,self.initial_wechat_prepare)
        previous=ROOT/'runtime-data/T005/last-queue.json'
        if previous.exists():
            try:self.last_detail='上次任务：'+self.queue_summary(catalog.read(catalog.read(previous)['plan']))
            except (OSError,ValueError,KeyError):self.status.set('未勾选任何项目；上次队列记录无法读取，未执行操作。')

    def export_feedback(self):
        from tkinter import filedialog
        from emoji_bridge.pilot import feedback
        file=filedialog.asksaveasfilename(parent=self.root,title='保存不含个人内容的反馈',defaultextension='.json',initialfile='表情互通-反馈.json',filetypes=[('反馈摘要','*.json')])
        if file:
            save_json(file,feedback(self.library,data_root=ROOT))
            self.status.set('反馈已保存在你选择的位置，未上传；仅含版本、数量、耗时和错误分类。')

    def compatibility_info(self):
        if self.busy or self.preview_busy:
            messagebox.showinfo('兼容能力','请等待当前任务停止后查看只读能力检查。',parent=self.root);return
        from emoji_bridge.pilot import compatibility_text
        messagebox.showinfo('兼容能力（只读）',compatibility_text(),parent=self.root)

    def filtered(self,c):
        if c=='wechat' and self.filters[c].get()=='本次新出现':
            return self.recent_wechat.items(self.library['clients'][c])
        if self.filters[c].get()=='两边都有':
            return [i for i in catalog.display_items(self.library['clients'][c]) if (c,i['id']) in self.overlap_facts]
        if self.filters[c].get() in ('重复／已添加','未标重复'):
            repeated=self.filters[c].get()=='重复／已添加'
            return [i for i in catalog.display_items(self.library['clients'][c]) if bool(self.duplicate_fact(c,i['id']))==repeated]
        if self.filters[c].get() in ('已添加到微信','已添加到QQ'):
            return [i for i in catalog.display_items(self.library['clients'][c]) if self.transfer_facts.get((c,i['id']),{}).get('state')=='confirmed']
        if c=='qq' and self.filters[c].get() in ('可搬运','暂不可搬运'):
            ready=self.filters[c].get()=='可搬运'
            return [i for i in catalog.display_items(self.library['clients'][c]) if self.qq_ready(i)==ready]
        state={'已取得原件':'ready','待获取原件':'discovered','原件已取待核验':'downloaded','暂时无法获取':'unavailable'}.get(self.filters[c].get())
        return [i for i in catalog.display_items(self.library['clients'][c]) if state is None or i['original_state']==state]

    @staticmethod
    def qq_ready(item):
        return (item.get('original_state')=='ready' and item.get('original_available') is True
                and bool(item.get('asset')) and not item.get('transfer_block_reason'))

    def render(self):
        for c in ('wechat','qq'):
            side=self.library['clients'][c];counts=catalog.counts(side);items=self.filtered(c)
            self.selected[c].intersection_update(i['id'] for i in catalog.display_items(side))
            count_text=f'发现记录 {counts["discovered"]} · 原件 {counts["ready"]} · 待获取 {counts["waiting"]} · 暂无法 {counts["unavailable"]}'
            if counts.get('downloaded_pending'):count_text+=f' · 原件待核验 {counts["downloaded_pending"]}'
            if c=='qq':
                ready=sum(self.qq_ready(i) for i in side['items'])
                count_text=f'已读取 {len(side["items"])} 项 · 可搬运 {ready} · 暂不可搬运 {len(side["items"])-ready}'
                if side.get('index_build',{}).get('state')=='building':count_text+=' · 正在自动准备'
                count_text+='\n上次读取的收藏 · '+side['scope']
                stamp=side.get('snapshot_at')
                if stamp:
                    try:stamp=datetime.fromisoformat(stamp).strftime('%m-%d %H:%M')
                    except ValueError:pass
                    count_text+=' · 读取于 '+stamp
                if side.get('last_read_failure'):
                    count_text+=('\n上次读取未完成，仍显示旧快照；请刷新确认。' if side['items']
                                 else '\n尚无成功读取的 QQ 快照；请处理下方原因后刷新。')
                elif side.get('read_reason'):count_text+='\n本次读取中断，仅列出已读到的收藏。'
                if side.get('retained_originals_count'):count_text+=f'\n另存 {side["retained_originals_count"]} 份未定位原件，不列入本次收藏。'
                if self.qq_cache_hint:count_text+='\n'+self.qq_cache_hint
            else:count_text+='\n'+side['scope']
            from emoji_bridge.compatibility import REASONS
            from emoji_bridge.client_sources import settings
            issue=side.get('last_read_failure') or side.get('preparation',{}).get('reason') or settings().get('disabled_sources',{}).get(c)
            if isinstance(issue,dict):issue=issue.get('reason')
            if isinstance(issue,str) and issue in REASONS:count_text+='\n'+REASONS[issue]
            if side.get('identical_entries_collapsed'):count_text+=f' · 已合并 {side["identical_entries_collapsed"]} 项相同内容'
            count_text+=f' · 已勾选 {len(self.selected[c])}'
            self.read_details[c]=count_text
            if MIDNIGHT:
                compact=count_text.split('\n')[0]+f' · 已选 {len(self.selected[c])}'
                if side.get('last_read_failure'):compact+='\n上次刷新未完成；保留已读取内容，请查看读取详情。'
                elif isinstance(issue,str) and issue in REASONS:compact+='\n'+REASONS[issue]
                else:compact+='\n显示已读取记录；完整范围与读取时间见详情。'
                self.stats[c].configure(text=compact)
            else:self.stats[c].configure(text=count_text)
            self.page_labels[c].configure(text=f'已载入 {len(items)} 项')
            cv=self.canvases[c];height=max(1,((len(items)+2)//3)*self.row_height)
            identifiers=[i['id'] for i in items];previous=self.rendered_ids.get(c,identifiers)
            top=retained_scroll_top(previous,identifiers,max(0,cv.canvasy(0)),self.row_height)
            cv.configure(scrollregion=(0,0,cv.winfo_width(),height))
            if identifiers!=previous:cv.yview_moveto(max(0,min(top,max(0,height-cv.winfo_height())))/height)
            self.rendered_ids[c]=identifiers
            self.draw_cards(c)
        side=self.library['clients']['wechat']
        self.recent_wechat_hint.configure(text=self.recent_wechat.hint(side))
        self.read_details['wechat']+='\n'+self.recent_wechat.hint(side)
        self.recent_wechat_button.configure(state='normal' if self.recent_wechat.items(side) else 'disabled')
        if self.header_align_after is None:
            self.header_align_after=self.root.after_idle(self.align_read_headers)

    def locate_recent_wechat(self):
        items=self.recent_wechat.items(self.library['clients']['wechat'])
        if not items:self.status.set(self.recent_wechat.hint(self.library['clients']['wechat']));return
        self.filters['wechat'].set('本次新出现');self.filter('wechat')
        self.status.set('已定位本次新出现项目；请核对并勾选“加入素材库”。待取得或待核验项会保留原因。')

    def resize_read_header(self,client,width):
        self.stats[client].configure(wraplength=max(220,width-20))
        if self.header_align_after is None:
            self.header_align_after=self.root.after_idle(self.align_read_headers)

    def align_read_headers(self):
        self.header_align_after=None
        height=max((body.winfo_reqheight() for _,body in self.read_headers.values()),default=1)
        for header,_ in self.read_headers.values():
            if int(str(header.cget('height')))!=height:header.configure(height=height)

    def resize_cards(self,c,width):
        self.draw_cards(c)

    def visible_range(self,c,buffer=0):
        cv=self.canvases[c];top=max(0,cv.canvasy(0));height=max(1,cv.winfo_height())
        start=max(0,int(top//self.row_height)-buffer)*3
        end=(int((top+height)//self.row_height)+1+buffer)*3
        return start,min(end,len(self.filtered(c)))

    def preview_image(self,path):
        if not path:return None
        try:
            stat=Path(path).stat();key=(str(path),stat.st_mtime_ns,stat.st_size)
            if key in self.image_cache:self.image_cache.move_to_end(key);return self.image_cache[key]
            # Compressed byte size does not bound decoded pixel cost. All
            # decoding stays off Tk, including highly compressed small files.
            if key not in self.thumb_pending and key not in self.thumb_failed and len(self.thumb_pending)<18:
                self.thumb_pending.add(key)
                self.thumb_pool.submit(decode_preview,path,key,self.thumb_events)
            return None
        except (OSError,ValueError):
            self.preview_invalid.add(str(path));return None

    def destroy_preview_workers(self,event):
        if event.widget==self.root and not self.destroyed:
            self.destroyed=True;self.thumb_pool.shutdown(wait=False,cancel_futures=True)

    def poll_thumbnails(self):
        changed=set()
        while not self.thumb_events.empty():
            key,frame=self.thumb_events.get_nowait();self.thumb_pending.discard(key);changed.add(key[0])
            if frame is None:self.thumb_failed.add(key);self.preview_invalid.add(key[0])
            else:
                self.preview_invalid.discard(key[0]);self.image_cache[key]=ImageTk.PhotoImage(frame)
        while len(self.image_cache)>128:self.image_cache.popitem(last=False)
        if changed:
            for c,entries in self.visible_cards.items():
                for entry in entries.values():
                    if entry.get('signature',(None,None))[1] in changed or not entry.get('image'):entry.pop('signature',None)
                self.draw_cards(c)
            self.schedule_previews()

    def draw_cards(self,c):
        items=self.filtered(c);start,end=self.visible_range(c,buffer=1)
        cv=self.canvases[c]
        visible={item['id'] for item in items[start:end]};cards=self.visible_cards[c]
        for ident in list(cards):
            if ident not in visible:
                for node in cards.pop(ident)['nodes']:cv.delete(node)
        width=max(1,cv.winfo_width())/3
        for n in range(start,end):
            item=items[n];ident=item['id'];entry=cards.get(ident)
            if entry is None:
                tag='entry:'+ident
                box=cv.create_polygon(0,0,1,1,2,2,fill=SURFACE,outline=BORDER,smooth=True,splinesteps=16,tags=(tag,))
                check=cv.create_text(0,0,anchor='nw',font=('Microsoft YaHei UI',9),tags=(tag,))
                picture=cv.create_image(0,0,anchor='center',tags=(tag,))
                placeholder=cv.create_text(0,0,fill=MUTED,font=('Microsoft YaHei UI',9),tags=(tag,))
                state=cv.create_text(0,0,anchor='n',font=('Microsoft YaHei UI',8),tags=(tag,))
                detail=cv.create_text(0,0,anchor='n',fill=WARNING,font=('Microsoft YaHei UI',8),tags=(tag,))
                entry={'id':ident,'nodes':(box,check,picture,placeholder,state,detail)};cards[ident]=entry
            box,check,picture,placeholder,state_node,detail=entry['nodes']
            x=n%3*width+3;y=(n//3)*self.row_height+3;w=max(1,width-6)
            geometry=(x,y,w)
            if entry.get('geometry')!=geometry:
                r=min(12,w/4);h=168
                cv.coords(box,x+r,y,x+w-r,y,x+w,y,x+w,y+r,x+w,y+h-r,x+w,y+h,x+w-r,y+h,x+r,y+h,x,y+h,x,y+h-r,x,y+r,x,y)
                cv.coords(check,x+10,y+9)
                cv.coords(picture,x+w/2,y+63);cv.coords(placeholder,x+w/2,y+63)
                cv.coords(state_node,x+w/2,y+104);cv.coords(detail,x+w/2,y+122)
                cv.itemconfigure(state_node,width=w-12);cv.itemconfigure(detail,width=w-12)
                entry['geometry']=geometry
            selected=ident in self.selected[c]
            from emoji_bridge.transfer_history import label as history_label
            fact=self.transfer_facts.get((c,ident),{});badge=history_label(fact)
            overlap=self.overlap_facts.get((c,ident))
            if overlap:badge='重复 · 两边都有（读取时）'
            ready=c!='qq' or self.qq_ready(item)
            selectable=True  # Unready items can be selected for acquisition/library import.
            enabled=(not self.busy or self.preview_busy) and selectable
            name=item['label'];name_budget=max(8,int((w-30)/11))
            if len(name)>name_budget:name=name[:name_budget-1]+'…'
            cv.itemconfigure(check,text=('☑ ' if selected else '☐ ' if selectable else '— ')+name,fill=INK if enabled else DISABLED)
            cv.itemconfigure(box,outline=ACCENT if selected else BORDER,fill=SELECTED if selected else SURFACE)
            is_loading=c=='wechat' and self.loading_previews and ident in self.preview_loading_ids
            signature=tuple(item.get(k) for k in ('label','preview','original_state','frames','preview_error','reason','transfer_block_reason','duplicate_count','content_equivalent_variants','matching_basis'))+(is_loading,badge)
            if entry.get('signature')!=signature:
                entry['signature']=signature
                image=self.preview_image(item.get('preview'));entry['image']=image
                cv.itemconfigure(picture,image=image or '')
                invalid=str(item.get('preview')) in self.preview_invalid
                cv.itemconfigure(placeholder,text='' if image else '预览待修复' if invalid else '加载预览中' if item.get('preview') or is_loading else '预览暂不可用' if item.get('preview_error') else '预览待加载')
                state=item['original_state'];color={'ready':SUCCESS,'discovered':MUTED,'unavailable':WARNING,'downloaded':WARNING}[state]
                text=catalog.LABELS[state]
                if c=='qq':
                    text='可搬运' if ready else '暂不可搬运' if item.get('index_reason') or item.get('transfer_block_reason') else '选中后准备'
                    if not ready:color=WARNING
                    elif item.get('matching_basis')=='appearance':text+=' · 外观匹配'
                if item.get('frames',0)>1:text+=' · 动图'
                cv.itemconfigure(state_node,text=text,fill=color)
                detail_text=item.get('transfer_block_reason') or item.get('preview_error') or item.get('reason') or ''
                if ready and item.get('duplicate_count',0)>1:detail_text=f'相同内容 {item["duplicate_count"]} 项，合并显示；原收藏保留。'
                elif ready and item.get('content_equivalent_variants',0)>1:detail_text='多个文件的完整内容相同，已合并对应。'
                if badge:detail_text=badge
                cv.itemconfigure(detail,fill=DUPLICATE if overlap or fact.get('state')=='confirmed' else WARNING)
                budget=max(12,int((w-12)/12)*2)
                cv.itemconfigure(detail,text=detail_text if len(detail_text)<=budget else detail_text[:budget-1]+'…')

    def click_card(self,c,event,select_only=False):
        cv=self.canvases[c];cv.focus_set()
        # Resolve the actually drawn card, never a stale list ordinal.
        x,y=cv.canvasx(event.x),cv.canvasy(event.y)
        for node in reversed(cv.find_overlapping(x,y,x,y)):
            for tag in cv.gettags(node):
                if tag.startswith('entry:'):
                    ident=tag[6:]
                    if ident in self.visible_cards[c]:
                        self.focused_card=(c,ident);self.choose(c,ident,True if select_only else ident not in self.selected[c]);return 'break'

    def toggle_focused(self,c):
        focused=getattr(self,'focused_card',None)
        if focused and focused[0]==c and focused[1] in self.visible_cards[c]:
            self.choose(c,focused[1],focused[1] not in self.selected[c])
        return 'break'

    def choose(self,c,ident,value):
        if self.busy and not self.preview_busy:return
        if value:self.selected[c].add(ident)
        else:self.selected[c].discard(ident)
        fact=self.transfer_facts.get((c,ident),{})
        detail=(f" 此项在 {fact.get('at') or '此前'} 已确认添加；标记是历史结果，不代表刚刚重新检查。" if fact.get('state')=='confirmed' else '')
        overlap=self.overlap_facts.get((c,ident))
        if overlap:detail+=f" 两端读取记录中的完整原件相同（目标读取时间：{overlap.get('target_at') or '未记录'}）；不代表实时重查。"
        if self.duplicate_fact(c,ident):detail+=' 搬运时会按该记录跳过，避免重复上传；收藏变化后请先更新读取记录。'
        self.status.set(f'已勾选：微信 {len(self.selected["wechat"])} 项，QQ {len(self.selected["qq"])} 项。尚未开始搬运。'+detail)
        self.root.after_idle(self.render)
    def clear(self,c):
        if not self.busy or self.preview_busy:self.selected[c].clear();self.render()
    def filter(self,c):
        self.render();self.scroll_to(c,'moveto',0)
    def turn(self,c,step):self.scroll_to(c,'scroll',step,'pages')
    def scroll_to(self,c,*args):
        # Queue movement AND paint together. Moving the viewport before an idle
        # redraw otherwise exposes the gap between recycled rows for one frame.
        commands=self.pending_scroll.setdefault(c,[])
        if args[0]=='moveto':commands[:]=[args]
        elif commands and commands[-1][0]=='scroll' and commands[-1][2]==args[2]:
            commands[-1]=('scroll',int(commands[-1][1])+int(args[1]),args[2])
        else:commands.append(args)
        if c not in self.draw_after:
            self.draw_after[c]=self.root.after_idle(lambda:self.flush_draw(c))

    def flush_draw(self,c):
        self.draw_after.pop(c,None)
        for args in self.pending_scroll.pop(c,[]):self.canvases[c].yview(*args)
        self.draw_cards(c)
        if c=='wechat' and self.preview_busy and self.loading_previews:
            start,end=self.visible_range(c)
            onscreen={i['id'] for i in self.filtered(c)[start:end]}
            # Small wheel motions must not discard useful in-flight work.
            if not onscreen.intersection(self.preview_loading_ids):
                self.preview_redirect=True;self.cancel.parent.mkdir(parents=True,exist_ok=True);self.cancel.touch()
        self.schedule_previews()
    def wheel(self,event):
        for c,canvas in self.canvases.items():
            x,y=canvas.winfo_rootx(),canvas.winfo_rooty()
            if x<=event.x_root<x+canvas.winfo_width() and y<=event.y_root<y+canvas.winfo_height():
                self.scroll_to(c,'scroll',-1 if event.delta>0 else 1,'units');return 'break'
    def visible_wechat_ids(self):
        start,end=self.visible_range('wechat');ids=[]
        for item in self.filtered('wechat')[start:end]:
            path=item.get('preview')
            if (not path or str(path) in self.preview_invalid or not Path(path).is_file()) and item['id'] not in self.preview_tried:ids.append(item['id'])
        return ids[:18]
    def schedule_previews(self):
        if not self.auto_previews or self.auto_paused:return
        if self.preview_after:self.root.after_cancel(self.preview_after)
        self.preview_after=self.root.after(350,self.load_visible_previews)
    def load_visible_previews(self):
        self.preview_after=None
        if self.auto_paused or self.busy or getattr(self,'wechat_prepare_pending',False):return
        ids=self.visible_wechat_ids()
        if not ids or not self.library['clients']['wechat'].get('source_report'):return
        self.preview_busy=True;self.loading_previews=True;self.plan=None
        self.preview_loading_ids=set(ids)
        repair=[i['id'] for i in self.filtered('wechat') if i['id'] in ids and str(i.get('preview')) in self.preview_invalid]
        def work():
            if self.preview_reader is None:
                from wechat_catalog import PreviewReader
                self.preview_reader=PreviewReader()
            result=self.preview_reader.load(catalog.PATH,ids,self.cancel,on_item=lambda ident:self.events.put(('preview_item',ident)),repair_ids=repair)
            return f'本次预览加载 {result["loaded"]} 项，未取得 {result["failed"]} 项。未发送或添加；滚动可继续加载。'
        self.start('正在加载当前可见微信预览，可继续浏览',work)
    def refresh_wechat(self,full=False):
        if self.busy:return
        self.recent_wechat.begin(self.library['clients']['wechat']);self.wechat_refresh_pending=True
        self.auto_paused=False
        self.wechat_prepare_pending=False
        self.preview_reader=None;self.preview_tried.clear();self.thumb_failed.clear();self.plan=None
        self.preview_busy=True
        def work():
            from wechat_prepare import prepare
            result=prepare(catalog.PATH,self.cancel,lambda n,total:self.events.put(('wechat_prepare_progress',(n,total))),
                           index_only=not full,preview_first=not full)
            if not full:
                if result.get('status')!='index_ready':
                    return '微信读取未完成，已取得结果保留：'+str(result.get('reason',result.get('status','未知原因')))
                return '微信索引和首屏预览已读取；可直接勾选搬运，只准备所选原件。'
            ready=result['counts'].get('ready',0);total=result.get('total')
            if result.get('all_indexed_originals_ready'):
                return f'微信本地索引 {total} 项原件已全部备好，可勾选搬运；云端完整性尚未证明。'
            return f'微信已备好 {ready} / {total if total is not None else "未知"} 项；其余保留原因，可更新后继续。'+str(result.get('reason',''))
        self.start('后台准备微信原件' if full else '读取微信索引和预览，可勾选优先搬运',work,local_only=True)

    def initial_wechat_prepare(self):
        if self.destroyed or not self.wechat_prepare_pending or getattr(self,'auto_paused',False) is True:return
        if self.busy:
            self.root.after(400,self.initial_wechat_prepare);return
        # One attempt per launch; failure/cancel is never a retry loop.
        self.wechat_prepare_pending=False
        self.refresh_wechat()
    def prepare_wechat_before_qq_variants(self):
        # Called by the SAME preparation worker between easy and hard QQ
        # stages. No competing library writers or simultaneous client input.
        if not self.wechat_prepare_pending:return
        self.wechat_prepare_pending=False
        from wechat_prepare import prepare
        self.events.put(('preparation_stage','QQ 易读取项目已保存，先准备微信；疑难 QQ 项随后单独处理。'))
        prepare(catalog.PATH,self.cancel,lambda n,total:self.events.put(('wechat_prepare_progress',(n,total))))
    def reload(self):
        if not self.busy:
            self.library=catalog.read(catalog.PATH)
            self.recent_wechat.observe(self.library['clients']['wechat'])
            self.refresh_transfer_facts()
            for c in self.selected:self.selected[c].intersection_update(i['id'] for i in catalog.display_items(self.library['clients'][c]))
            self.render()
            self.check_qq_cache()
    def check_qq_cache(self):
        # Diagnostic fixtures disable all automatic local loading together.
        if not self.auto_previews or self.auto_paused or self.qq_cache_checking or self.busy or self.destroyed:return
        self.qq_cache_checking=True
        def work():
            try:
                from qq_cache_changes import check,label
                def cancelled():
                    if self.auto_paused:raise RuntimeError('cancel_requested')
                value=label(check(cancel_check=cancelled))
            except (OSError,ValueError,KeyError,RuntimeError):
                value='缓存变化暂未能检查；仍显示旧收藏快照。'
            self.events.put(('qq_cache',value))
        threading.Thread(target=work,daemon=True).start()
    def initial_qq_index(self):
        if getattr(self,'auto_paused',False) is True or getattr(self,'destroyed',False) is True:return
        side=self.library['clients']['qq']
        if self.busy:
            self.root.after(400,self.initial_qq_index);return
        if side.get('items'):
            return  # Saved observations remain usable; prepare the selection on demand.
        if (not side.get('initial_index_attempted') and self.wechat_prepare_pending is True
                and not self.library['clients']['wechat']['items']):
            self.wechat_prepare_pending=False;self.plan=None;self.preview_busy=True
            def work():
                from startup_prepare import run
                result=run(catalog.PATH,self.cancel,lambda:self.events.put(('startup_progress',None)))
                counts=result['counts'];q=counts['qq'];w=counts['wechat']
                errors=[('微信' if c=='wechat' else 'QQ')+'：'+s['reason']
                        for c,s in result['clients'].items() if s.get('reason')]
                return (f'读取已结束：微信 {w["ready"]}/{w["observed"]} 项、QQ {q["ready"]}/{q["observed"]} 项原件就绪。'
                        +(' 已取消，已读结果保留。' if result['cancelled'] else
                          (' 停止原因：'+'；'.join(errors) if errors else ' 未发送或添加。')))
            self.start('两边同时准备完整原件；预览先显示，后台完成前不算全部就绪',work)
            return
        # Failed native activation needs an explicit refresh; do not loop it.
        if not side.get('initial_index_attempted'):self.read_qq(expand=False)
    def prepare_qq(self):
        if self.busy:return
        self.preview_busy=True
        def work():
            from qq_offline_index import build,needs_prepare
            from qq_cache_acquire import current_inventory
            library=catalog.read(catalog.PATH);side=library['clients']['qq'];built=None
            inventory,_=current_inventory(self.cancel)
            if needs_prepare(side,inventory.get('directory_fingerprint')):
                built=build(catalog.PATH,self.cancel,lambda n,total:self.events.put(('index_progress',(n,total))),
                      stage=lambda label:self.events.put(('preparation_stage',label)),
                      after_basic=self.prepare_wechat_before_qq_variants,practical_first=True)
                side=catalog.read(catalog.PATH)['clients']['qq']
            completion=self.finish_qq_preparation(built)
            side=catalog.read(catalog.PATH)['clients']['qq']
            ready=sum(self.qq_ready(i) for i in side['items'])
            return f'QQ 已准备：可直接勾选搬运 {ready} 项；暂不可搬运 {len(side["items"])-ready} 项已注明。未发送或添加。'+('补读停止：'+completion['reason'] if completion.get('reason') else '')
        self.start('正在自动准备 QQ 收藏，已有结果会复用，可继续浏览',work,local_only=True)
    def finish_qq_preparation(self,built):
        side=catalog.read(catalog.PATH)['clients']['qq']
        results=(built or {}).get('items',[])
        # Only an in-memory completed build can bypass the unresolved pass.
        # Existing catalogs and a later transfer still validate their receipts.
        if (results and {r['id'] for r in results}=={i['id'] for i in side['items']}
                and all(r['status'] in ('ready','reused') for r in results)):
            return {'ready':sum(self.qq_ready(i) for i in side['items']),
                    'state':'prepared_in_this_run','extra_source_pass':False}
        from qq_prepare_remaining import complete_observed
        return complete_observed(catalog.PATH,self.cancel,lambda label:self.events.put(('preparation_stage',label)))
    def start(self,label,work,local_only=False):
        if self.busy:return
        self.material_import_path=None
        if self.summary_after:self.root.after_cancel(self.summary_after);self.summary_after=None
        self.busy=True;self.stopping=False;self.cancel.unlink(missing_ok=True)
        self.progress_bar.configure(maximum=max(1,self.progress_total),value=0)
        self.task_result.set('')
        self.status.set(label+('；取消按钮可停止。' if self.preview_busy or local_only else '；请勿切换客户端窗口，Esc 可停止。'));self.render()
        def task():
            try:
                if self.cancel.exists():self.events.put(('done','任务已取消；尚未开始执行。'))
                else:
                    from emoji_bridge.timing import session
                    timing_path=ROOT/'reports/T006'/('task-timing-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
                    with single_instance(ROOT/'runtime-data/T005/collection.lock'),session(timing_path):result=work()
                    self.events.put(('done',result))
            except Exception as exc:
                from emoji_bridge.qq_controls import explain_error
                self.events.put(('error',explain_error(str(exc))))
        self.root.after(200,lambda:threading.Thread(target=task,daemon=True).start())
    def poll(self):
        kind=value=None
        try:
            self.poll_thumbnails()
            if self.deferred_event:
                kind,value=self.deferred_event;self.deferred_event=None
            else:kind,value=self.events.get_nowait()
            if self.stopping and kind in ('progress','index_progress','preparation_stage','wechat_prepare_progress','startup_progress'):
                return  # Old progress must not replace the cancellation receipt.
            if kind=='qq_cache':
                self.qq_cache_checking=False
                if not self.auto_paused:self.qq_cache_hint=value;self.render()
                return
            if kind=='startup_progress':
                while not self.events.empty():
                    following=self.events.get_nowait()
                    if following[0]!='startup_progress':self.deferred_event=following;break
                self.library=catalog.read(catalog.PATH);self.record_read_retries=0
                sides=self.library['clients']
                labels=[]
                for client,name in (('wechat','微信'),('qq','QQ')):
                    items=sides[client]['items']
                    ready=sum(i.get('original_state')=='ready' and not i.get('transfer_block_reason') for i in items)
                    previews=sum(bool(i.get('preview')) for i in items)
                    labels.append(f'{name}：预览 {previews} 项，原件 {ready}/{len(items)} 项')
                    reason=sides[client].get('last_read_failure')
                    if reason:labels[-1]+=f'（读取已停：{reason}）'
                self.status.set('；'.join(labels)+'。可勾选搬运，优先准备所选项目。')
                self.render();return
            if kind=='qq_scan_progress':
                if self.stopping:return
                while not self.events.empty():
                    following=self.events.get_nowait()
                    if following[0]!='qq_scan_progress':self.deferred_event=following;break
                    kind,value=following
                # Display observations during the very first scan, without
                # mutating the source report or granting original readiness.
                self.library['clients']['qq']=value
                self.status.set(f'正在读取 QQ 收藏：已发现 {len(value["items"])} 项，继续向下读取；预览先显示，随后准备原件。')
                self.render();return
            if kind=='index_progress':
                while not self.events.empty():
                    following=self.events.get_nowait()
                    if following[0]!='index_progress':self.deferred_event=following;break
                    kind,value=following
                self.status.set(f'正在准备 QQ 收藏：{value[0]} / {value[1]}；已准备项目先显示，疑难项继续处理。')
                self.library=catalog.read(catalog.PATH);self.record_read_retries=0;self.render();return
            if kind=='preparation_stage':
                self.status.set(value+' 可浏览已读取项目；取消可保留进度。')
                self.library=catalog.read(catalog.PATH);self.record_read_retries=0;self.render();return
            if kind=='wechat_prepare_progress':
                # Coalesce progress so a large prepared library cannot delay
                # the completion event by a timer tick for every favorite.
                while not self.events.empty():
                    following=self.events.get_nowait()
                    if following[0]!='wechat_prepare_progress':
                        self.deferred_event=following;break
                    kind,value=following
                self.status.set(f'正在后台准备微信原件：{value[0]} / {value[1]}；不会发送或添加。')
                self.library=catalog.read(catalog.PATH);self.record_read_retries=0;self.render();return
            if kind=='progress':
                names={'acquisition':'准备原件','source_group':'准备原件','prepared':'原件已备好','transfer':'添加中','sending_group':'发送本批图片','group_done':'本批添加结束','waiting_send':'等待发送','waiting_media':'等待图片可添加','checking_result':'确认本机收藏记录','done':'整理结果'}
                names.update(opening_qq='正在打开 QQ 窗口',opening_favorites='正在打开 QQ 个人收藏',
                             checking_duplicates='检查已添加记录',opening_wechat='正在打开微信文件传输助手')
                completed=value.get('completed',value.get('confirmed',0));total=value['total']
                self.progress_bar.configure(maximum=max(1,total),value=completed)
                self.task_result.set(f'已处理 {completed}/{total}')
                label=names.get(value['stage'],value['stage']);group=value.get('send_group')
                if group:label=f"第 {group['number']}/{group['total']} 批（{group['size']} 张） · {label}"
                self.status.set(label)
                return
            if kind=='preview_item':
                self.preview_tried.add(value)
                # Drain consecutive completed previews in one render; do not
                # build a 150ms-per-item backlog when downloads finish together.
                while not self.events.empty():
                    kind,value=self.events.get_nowait()
                    if kind=='qq_cache':
                        self.qq_cache_checking=False;self.qq_cache_hint=value
                        kind='preview_item';break
                    if kind!='preview_item':break
                    self.preview_tried.add(value)
            # Atomic replacement may briefly deny a read on Windows. Keep the
            # event (including a drained completion) and retry on another tick,
            # without blocking the UI or starting a second worker.
            self.library=catalog.read(catalog.PATH);self.record_read_retries=0
            if kind in ('done','error') and getattr(self,'wechat_refresh_pending',False) is True:
                self.recent_wechat.observe(self.library['clients']['wechat'],finished=True,
                    failed=kind=='error' or self.cancel.exists() or (isinstance(value,str) and value.startswith('微信读取未完成')))
                self.wechat_refresh_pending=False
            for c in self.selected:self.selected[c].intersection_update(i['id'] for i in catalog.display_items(self.library['clients'][c]))
            self.render()
            if kind=='preview_item':return
            was_preview=self.preview_busy;self.busy=False;self.preview_busy=False;self.loading_previews=False
            if kind=='done' and isinstance(value,dict):self.present_result(value)
            else:self.status.set(value if kind=='done' else '任务停止：'+value+'。没有自动重试。')
            if not was_preview and kind=='done' and isinstance(value,str) and value.startswith('队列结果：'):
                self.task_result.set(value)
                self.status.set('结果已保存；再次继续时已完成项会跳过，未知提交不会自动重发。')
            if self.stopping:
                self.finish_cancel();self.stopping=False
            self.render()
            if was_preview and self.pending_transfer:
                c,ids=self.pending_transfer;self.pending_transfer=None;self.transfer(c,ids)
            elif was_preview and self.pending_library_import:
                c,ids,options,path=self.pending_library_import;self.pending_library_import=None
                self.import_materials(c,ids,options,path)
            elif getattr(self,'pending_resume',False):
                self.pending_resume=False;self.resume()
            elif was_preview and self.preview_redirect:
                self.preview_redirect=False;self.schedule_previews()
            elif was_preview and kind=='done' and not self.cancel.exists():self.schedule_previews()
        except queue.Empty:pass
        except PermissionError:
            self.record_read_retries+=1
            if kind is not None and self.record_read_retries<=10:
                # Coalescing may already have saved a completion after this
                # progress event. Never replace it with an older progress tick.
                if self.deferred_event is None:self.deferred_event=(kind,value)
            else:
                self.status.set('记录暂时无法读取；搬运选择已保存，未自动重发。请稍后刷新。')
                if kind in ('done','error'):self.busy=False;self.preview_busy=False;self.loading_previews=False
        finally:
            if not self.destroyed:self.root.after(80,self.poll)
    def read_qq(self,expand=True):
        if self.busy:return
        self.auto_paused=False
        self.plan=None
        from qq_catalog import MAX_SCAN_VIEWS
        self.preview_busy=True
        def work():
            from qq_catalog import scan
            library=catalog.read(catalog.PATH)
            fresh=not library['clients']['qq'].get('items')
            library['clients']['qq']['initial_index_attempted']=True;catalog.save(library)
            def show_observations(path,report):
                self.events.put(('qq_scan_progress',dict(complete=False,
                    scope=f'正在读取 {len(report["pages"])} 个收藏视图；尚未读完',
                    initial_index_attempted=True,source_report=str(path),snapshot_at=report['at'],
                    items=[dict(i,scan=str(Path(path).resolve())) for i in report['items']])))
            path,r=scan(MAX_SCAN_VIEWS,self.cancel,
                        **({'progress':show_observations} if fresh else {}))
            library=catalog.read(catalog.PATH);catalog.merge_qq(library,path,cancel=self.cancel.exists,match_originals=False)
            library['clients']['qq']['initial_index_attempted']=True;catalog.save(library)
            if not r['items']:raise ValueError(r.get('reason','未读到收藏，保留旧索引；请用“刷新 QQ 收藏”重试。'))
            return f'QQ 已读取 {len(r["items"])} 项；勾选搬运时只准备所选原件，完整性尚未证明。'+('停止原因：'+r['reason'] if r.get('reason') else '')
        self.start('首次建立或显式更新 QQ 索引，保存后后续直接使用（不发送）',work)
    def acquire(self,c):
        if self.busy:return
        self.plan=None
        ids=list(self.selected[c])
        if not ids:self.status.set('请先勾选需要取得原件的条目。');return
        if len(ids)!=1:self.status.set('本阶段原件获取一次选择一项，逐项保留来源证据。');return
        item=next(i for i in self.library['clients'][c]['items'] if i['id']==ids[0])
        if item['original_state']=='ready':self.status.set('这项已有原件，无需再次获取。');return
        source_report=self.library['clients'][c].get('source_report')
        def work():
            if c=='qq':
                from qq_cache_acquire import acquire_or_resume
                result=acquire_or_resume(item,self.cancel)
            else:
                from wechat_acquire import acquire_selected
                result=acquire_selected(item,source_report,self.cancel)
            library=catalog.read(catalog.PATH);entry=next(i for i in library['clients'][c]['items'] if i['id']==item['id'])
            catalog.apply_acquisition(entry,result)
            catalog.save(library);return '原件已取得并核对源收藏。尚未搬运。' if result.get('status')=='original_verified' else result.get('reason','原件获取结果待确认。')
        self.start('读取 QQ 本地个人表情原件并核验收藏（不发送）' if c=='qq' else '获取所选微信原件并核验个人收藏（不发送、不添加）',work)

    def select_matching(self,client):
        if self.busy and not self.preview_busy:return
        self.selected[client].update(i['id'] for i in self.filtered(client));self.render()
        self.status.set(f'已选择当前筛选下全部 {len(self.selected[client])} 项；仅点击加入素材库才会开始入库。')

    def library_menu(self,client,event):
        if self.busy:return
        self.click_card(client,event,select_only=True)
        menu=tk.Menu(self.root,tearoff=False);menu.add_command(label='将勾选项目加入素材库',command=lambda:self.import_materials(client));menu.tk_popup(event.x_root,event.y_root)

    def retry_materials(self,client):
        try:
            pointer=catalog.read(ROOT/f'runtime-data/T005/last-material-{client}.json');path=Path(pointer['path']);plan=catalog.read(path)
            self.import_materials(client,[j['item_id'] for j in plan['jobs']],plan['options'],path)
        except (OSError,ValueError,KeyError):self.status.set('没有可重试的入库任务。')

    def import_materials(self,client,ids=None,options=None,path=None):
        if self.busy and not self.preview_busy:self.status.set('当前任务仍在运行，请结束或取消后再入库。');return
        ids=ids or [i['id'] for i in self.filtered(client) if i['id'] in self.selected[client]]
        if not ids:self.status.set('先勾选要保存到素材库的表情。');return
        if options is None:options={'acquire':True,'tags':[],'collections':[]}
        if self.busy:
            self.pending_library_import=(client,list(ids),options,path);self.auto_paused=True;self.cancel.touch()
            self.status.set('正在结束后台准备，随后仅将所选表情加入素材库。');return
        from client_material_import import create,run,summary
        if path is None:
            path=ROOT/'runtime-data/T005'/('material-import-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
            create(self.library,client,ids,path,options)
            save_json(ROOT/f'runtime-data/T005/last-material-{client}.json',{'path':str(path)})
        self.plan=None;self.progress_total=len(ids)
        def work():
            result=run(path,catalog.PATH,self.material_store,self.cancel,
                       progress=lambda n,total,stage:self.events.put(('progress',{'completed':n,'total':total,'stage':stage})))
            return result
        self.start('将所选完整原件加入素材库；未取得的先获取，不发送或添加',work,local_only=True)
        self.material_import_path=path
    def transfer(self,c,ids=None):
        if self.busy and self.preview_busy is not True:return
        chosen=set(self.selected[c] if ids is None else ids)
        ids=[i['id'] for i in catalog.display_items(self.library['clients'][c]) if i['id'] in chosen]
        if not ids:self.status.set('请先勾选要搬运的项目，默认不全选。');return
        if c=='qq':
            known={i['id']:i for i in self.library['clients'][c]['items']}
            unavailable=[ident.rsplit(':',1)[-1] for ident in ids if ident not in known or known[ident].get('transfer_block_reason')]
            if unavailable:
                self.status.set('尚未开始搬运；以下项目未准备好：'+', '.join(unavailable)+'。请取消这些勾选，其他可搬运项目不受影响。');return
        self.refresh_transfer_facts()
        skipped=[{'item_id':ident,**fact} for ident in ids if (fact:=self.duplicate_fact(c,ident))]
        omitted={j['item_id'] for j in skipped};ids=[ident for ident in ids if ident not in omitted]
        if not ids:
            self.last_detail=f'所选 {len(skipped)} 项均按已保存的收藏/添加记录标为重复，已跳过；本次没有发送或添加。\n标记不是实时成员检查；两边都有仅指已读取范围，收藏变化后可更新读取记录。'
            self.status.set(f'已跳过 {len(skipped)} 项重复，没有发送或添加。依据可在“查看详情”查看。')
            if self.summary_after:self.root.after_cancel(self.summary_after);self.summary_after=None
            self.task_result.set('无需重复搬运');return
        try:
            from selected_transfer import create
            if self.pending_plan and self.pending_plan[1:]==(c,tuple(ids)):
                plan=self.pending_plan[0]
            else:
                plan=ROOT/'runtime-data/T005/queues'/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
                create(self.library,c,ids,plan)
                if skipped:
                    data=catalog.read(plan);data['skipped_duplicates']=skipped;save_json(plan,data)
                save_json(ROOT/'runtime-data/T005/last-queue.json',{'plan':str(plan),'selected_ids':ids,'source_client':c})
            self.plan=plan
        except Exception as exc:self.status.set('不能搬运：'+str(exc)+'。未发送或添加。');return
        self.task_result.set(f'本次搬运：已保存 {len(ids)} 项，尚未开始添加。')
        if self.preview_busy is True:
            self.wechat_prepare_pending=False
            self.pending_transfer=(c,list(ids));self.pending_plan=(plan,c,tuple(ids))
            self.cancel.parent.mkdir(parents=True,exist_ok=True);self.cancel.touch()
            self.status.set(f'已保存 {len(ids)} 项搬运任务；正在停止后台读取，随后优先准备所选。取消可撤回。');return
        self.pending_plan=None
        self.progress_total=len(ids)
        self.start(f'搬运 {len(ids)} 项'+(f'；按记录跳过重复 {len(skipped)} 项' if skipped else '')+'（微信仅用文件传输助手）',lambda:self.run_queue(plan))
    def run_queue(self,plan,resume=False):
        from local_bridge import execute,recheck_source
        with single_instance(ROOT/'runtime-data/T004/queue.lock'):
            if catalog.read(plan).get('schema')=='selected-workflow-v1':
                from selected_transfer import run
                r=run(plan,catalog.PATH,ROOT/'private/T005/assets',resume,progress=lambda p:self.events.put(('progress',dict(p))),clear_cancel=False)
            else:r=run_plan(plan,execute,recheck_source,clear_cancel=False)
        return r

    def show_details(self):
        details_window(self.root,'任务详情',self.last_detail or '暂无任务记录。选择素材并执行后，可在这里查看进度和结果。')

    def present_result(self,result):
        if result.get('schema')=='client-material-import-v1':
            from client_material_import import summary
            self.last_detail=summary(result);self.task_result.set(self.last_detail.split('\n')[0])
            counts=result.get('counts',{});total=len(result['jobs'])
            self.progress_bar.configure(maximum=max(1,total),value=total-counts.get('queued',0))
            completed=counts.get('added',0)+counts.get('existing',0)
            self.status.set((f'{completed} 项已在素材库。' if completed else '尚无素材成功入库。')+
                            ('未完成项可重试，已完成项会跳过。' if completed<total else '可在素材库查看。'));return
        from emoji_bridge.task_view import summary
        self.refresh_transfer_facts()
        view=summary(result);self.last_detail=self.queue_summary(result)
        self.progress_bar.configure(maximum=max(1,view['total']),value=view['completed'])
        self.task_result.set(view['label'])
        self.status.set('查看详情可了解未完成原因。' if view['needs_attention'] else '')
        if not view['needs_attention']:self.schedule_summary_clear()

    def schedule_summary_clear(self):
        if self.summary_after:self.root.after_cancel(self.summary_after)
        def clear():
            self.summary_after=None
            if not self.busy:
                self.task_result.set('');self.status.set('就绪。可选择下一批。')
                self.progress_bar.configure(value=0)
        self.summary_after=self.root.after(6000,clear)
    def refresh_transfer_facts(self):
        from emoji_bridge.transfer_history import collect
        self.transfer_facts=collect(ROOT,self.library)
        from emoji_bridge.collection_overlap import collect as overlap
        self.overlap_facts=overlap(self.library)
    def duplicate_fact(self,c,ident):
        fact=self.transfer_facts.get((c,ident),{})
        if fact.get('state')=='confirmed':return {'basis':'confirmed_transfer_history','evidence':fact}
        overlap=self.overlap_facts.get((c,ident))
        if overlap:return {'basis':'complete_original_in_both_saved_snapshots','evidence':overlap}
        return None
    def queue_summary(self,r):
        from collections import Counter
        names={'desktop_confirmed':'收藏已确认','already_exists':'已存在','add_executed':'已执行添加（未复核）','failed':'失败','pending_confirmation':'待确认','paused_before_submit':'未提交，已暂停','queued':'尚未执行','cancelled':'已取消','waiting_original':'待取得原件','acquiring_original':'正在取得原件'}
        counts=Counter('desktop_confirmed' if j.get('status')=='add_executed' and j.get('collection_verified') else j['status'] for j in r.get('jobs',[]))
        text=f'队列结果：共 {sum(counts.values())} 项，'+'，'.join(f'{names.get(k,k)} {v}' for k,v in counts.items())+'。'
        if r.get('skipped_duplicates'):text+=f'另按已保存记录跳过重复 {len(r["skipped_duplicates"])} 项，未上传；未作实时成员重查。'
        located=sum(j.get('collection_persisted',False) and j['status']=='pending_confirmation' for j in r.get('jobs',[]))
        if located:text+=f'其中 {located} 项已确认收藏重开保留，动画等后续核验待确认。'
        local=sum(j.get('collection_verified',False) and j.get('completion_check')=='confirmed_in_local_index' for j in r.get('jobs',[]))
        if local:text+=f'其中 {local} 项已由本机收藏记录确认；未做重开或手机复核。'
        if r.get('run_state')=='paused':
            text+=('本组来源核验未完成，尚未新添加；原件和进度已保留。' if r.get('pause_reason')=='source_group_pending'
                   else '任务已暂停；已完成进度保留，具体阶段和原因如下。')
        if r.get('run_state')=='cancelled':text+='本次任务已取消，进度已保留；已发送但结果未知的项目不会自动重发或重加。'
        if r.get('environment_block'):
            block=r['environment_block'];client='微信' if block['client']=='wechat' else 'QQ'
            reason=block['reason']
            help={'client_display_scale_changed':'窗口缩放发生变化，请稳定后重试',
                  'client_display_scale_unsupported':'本版客户端支持100%、125%和150%缩放',
                  'display_too_small_for_calibrated_window':'当前屏幕容不下已校准窗口，请移到更大的屏幕',
                  'client_main_window_missing_or_ambiguous':'请打开唯一主窗口',
                  'target_window_ambiguous_or_layout_changed':'请取消最大化并保留主窗口',
                  'client_version_changed':'任务期间客户端版本改变，请重新检测',
                  'client_family_unadapted':'此客户端架构尚未适配；可导出兼容反馈，不必降级'}
            text+=f' 开始前检查：{client}，{help.get(reason,reason)}；尚未读取来源或新增收藏。'
        if r.get('batch_reason')=='originals_not_all_prepared_no_new_submission':text+='原件尚未全部备齐，本轮没有新提交 QQ。'
        pending=[j for j in r.get('jobs',[]) if j['status'] in ('pending_confirmation','failed','paused_before_submit','waiting_original')]
        if pending:
            details=[]
            for j in pending[:3]:
                label=j.get('item_id','').rsplit(':',1)[-1]
                reason=j.get('reason') or '本项未保存具体失败原因，请导出反馈；不要据此重复发送'
                if '本地原件暂未' in reason:reason='原件未唯一匹配'
                elif reason=='selected_favorite_original_not_matched_in_cache':reason='文件尚未与这张收藏对应，未发送'
                elif reason=='saved_source_invalid':reason='保存的原件或对应记录已失效，本项未发送；其他正常项继续'
                elif reason=='source_preparation_failed':reason='本项原件检查或转换失败，未发送；其他正常项继续'
                elif reason=='file_dialog_not_found':reason='未识别到 QQ 导入文件窗口'
                elif reason=='file_dialog_unexpected_foreground':reason='出现非预期前台窗口，本次尚未选入文件；回到客户端后继续'
                elif reason=='file_name_control_unavailable':reason='无法定位已就绪的文件名输入框，本次尚未选入文件'
                elif reason=='file_dialog_resume_unproven':reason='已有文件窗口无法证明属于本次任务；请关闭该窗口后继续，未自动选入文件'
                elif reason=='file_dialog_existing_selection':reason='文件窗口已有内容，已保留；请关闭该窗口后继续，未自动提交'
                elif reason=='wrong_dialog_owner':reason='文件窗口不属于本次客户端主窗口，已停止操作'
                elif reason=='absolute_existing_file_required':reason='本次目标文件不存在或不是有效绝对路径，请重新准备素材'
                elif reason=='file_path_readback_mismatch':reason='文件名输入框读回内容与本批路径不符，尚未提交'
                elif reason=='file_dialog_not_ready':reason='文件选择窗口尚未就绪，本次尚未选入文件'
                elif reason=='file_dialog_selection_not_accepted':reason='文件窗口尚未接受本批文件，未点击微信发送；请导出反馈'
                elif reason=='composer_media_loading_timeout':reason='微信输入框仍未加载齐本批图片，未点击发送；保留草稿，请导出反馈'
                elif reason in ('prepared_file_changed','staged_file_copy_mismatch'):reason='本批文件内容检查未通过，本次尚未选入文件；请重新准备所选素材'
                elif reason=='multiple_file_dialogs':reason='QQ 打开了多个文件窗口，未能确定导入目标'
                elif reason=='calibration_template_changed':reason='界面识别资源校验未通过'
                elif reason=='panel_did_not_close':reason='QQ 表情面板未按预期关闭；请先核验结果，不要重复添加'
                elif reason=='wechat_media_not_ready_no_resend':reason='等待消息可添加已超时，保留进度；继续时仅处理已有消息，不重发'
                elif reason=='wechat_submitted_messages_not_found_no_resend':reason='未在近期消息中找到本次已发送图片，保留进度，不重发'
                elif reason=='saved_original_match_not_strong_enough':reason='完整文件与收藏预览仍有差异，未发送'
                elif reason=='原件已保存但源收藏动画待确认':reason='源动画对应待确认'
                elif reason=='foreground_changed':reason='切换了前台窗口，任务已暂停；回到文件传输助手后点继续，先核验待确认项，已成功项不重发'
                elif reason=='wechat_add_settle_timeout':reason='已点击添加，但弹窗尚未消失；任务已暂停，继续时先核验收藏，不重发或重复添加'
                elif reason=='wechat_add_rejected':reason='微信提示添加失败；关闭微信提示后点继续，先核验收藏，再处理已有消息，不重发'
                elif reason=='client_display_scale_changed':reason='客户端跨屏后缩放变化，请在窗口稳定后继续'
                elif reason=='client_main_window_missing_or_ambiguous':reason='未找到唯一可操作的客户端主窗口'
                elif reason=='current_favorite_content_ambiguous':reason='当前收藏画面存在多个相似匹配'
                elif reason=='selected_original_not_found_in_bounded_current_favorites':reason='本轮读取范围内未找到对应收藏，其余项目继续'
                elif reason=='sent_media_not_unique_no_resend':reason='已发送，未定位到唯一图片，收藏待确认'
                elif reason=='composer_not_empty':reason='文件传输助手输入框已有草稿，本次尚未发送；保留并清空草稿后可继续'
                elif reason=='staged_batch_item_not_unique':reason='输入框中的本批图片未能完整对应，尚未点击发送；草稿已保留'
                elif reason=='wechat_group_incomplete_no_next_send':reason='本批尚未完成，后续批次未发送；已保存进度'
                elif reason in ('prior_batch_attempt_no_automatic_resend','prior_unsent_draft_requires_confirmation'):
                    reason='旧任务记录需处理；点“继续上次队列”，可确认并恢复未发送项'
                elif reason=='prior_sent_batch_add_only':reason='上次已经发送；继续原队列只补添加，不重发'
                elif reason=='prior_add_result_unknown':reason='上次可能已点添加；结果待确认，不自动重复添加'
                elif reason in ('cancel_requested','cancelled_escape'):reason='已停止；已发送或已点添加的结果待确认，不自动重试'
                elif reason in ('own_transfer_entry_not_visible','own_transfer_navigation_not_confirmed','own_transfer_session_not_confirmed'):
                    reason='暂未能自动进入文件传输助手；请打开该会话后继续，已有任务不会重发'
                elif reason in ('own_transfer_search_not_empty','own_transfer_search_changed'):
                    reason='微信搜索框已有内容或搜索被改动；请结束搜索并打开文件传输助手后继续，草稿已保留'
                elif reason in ('own_transfer_search_result_not_found','own_transfer_search_result_unsupported','own_transfer_search_layout_unsupported'):
                    reason='暂未识别到微信内置助手入口；请结束搜索并打开文件传输助手后继续，不会按同名联系人发送'
                elif reason in ('wechat_control_missing','wechat_control_ambiguous'):
                    reason='微信必要控件缺失或不唯一，已暂停；请导出反馈，其中会说明具体控件及匹配数量'
                elif reason=='wechat_header_layout_unsupported':
                    reason='微信聊天区结构暂未通过检查，已暂停；请导出反馈，不会跳过会话身份核对'
                else:
                    from emoji_bridge.qq_controls import explain_error
                    reason=explain_error(reason)
                step={'opening':'打开文件窗口','filling':'填写本批文件','waiting_composer':'等待图片选入','sending':'提交发送'}.get(j.get('file_selection_step'))
                details.append(f'{label}：'+('失败：' if j['status']=='failed' else '')+(step+'：' if step else '')+reason)
            text+=' 未完成条目 '+ '；'.join(details)+(' 等。' if len(pending)>3 else '。')
        feedback=[j for j in r.get('jobs',[]) if j.get('manual_animation_feedback')]
        if feedback:
            text+='已保留用户动画反馈。'
            if any(j['status']=='pending_confirmation' for j in feedback):text+='自动动画核验仍待确认，未重发。'
        return text
    def resume(self):
        if self.busy:
            if self.stopping:
                self.pending_resume=True
                self.status.set('已收到继续请求；当前操作停止并保存结果后，会继续原队列。已完成项跳过，未知提交不重发。')
            elif self.preview_busy:
                self.pending_resume=True;self.cancel.parent.mkdir(parents=True,exist_ok=True);self.cancel.touch()
                self.status.set('已收到继续请求；停止预览后恢复队列，已完成项跳过，未知提交不重发。')
            else:self.status.set('当前任务正在执行；请等待结果或取消。')
            return
        p=ROOT/'runtime-data/T005/last-queue.json'
        if not p.exists():self.status.set('没有待继续的队列。');return
        self.plan=Path(catalog.read(p)['plan'])
        from wechat_retry import candidates,approve
        retry=candidates(catalog.read(self.plan),ROOT)
        if retry:
            ids=[x['item_id'] for x in retry];labels='、'.join(i.rsplit(':',1)[-1] for i in ids)
            if not messagebox.askyesno('恢复发送前中断的项目',
                f'以下 {len(ids)} 项的旧记录停在点击发送之前：\n{labels}\n\n'
                '请确认：你没有手动发送这些项目，且已移除输入框中的旧草稿。\n'
                '确认后仅恢复这些项目，每批最多5张；已完成项跳过。\n'
                '若已经手动发送过，请选“否”，避免重复发送。',parent=self.root):
                self.status.set('保留旧记录，未重发。已发送项目需从已有消息继续处理。');return
            approve(self.plan,ids,confirmed=True,root=ROOT)
        self.progress_total=len(catalog.read(self.plan).get('jobs',[]))
        # Clear old cancellation synchronously, before exposing the new task to
        # Cancel. The worker must never erase a newly clicked cancellation.
        for token in self.queue_cancel_paths():token.unlink(missing_ok=True)
        self.start('继续上次队列；已完成项跳过，未知提交不重发',lambda:self.run_queue(self.plan,True))
    def queue_cancel_paths(self):
        if not self.plan:return []
        paths=[self.plan.with_suffix('.cancel')]
        if self.plan.exists():
            r=catalog.read(self.plan)
            children=[j['child_plan'] for j in r.get('jobs',[]) if j.get('child_plan')]
            if r.get('batch_plan'):children.append(r['batch_plan'])
            paths.extend(Path(p).with_suffix('.cancel') for p in children)
        return paths
    def finish_cancel(self):
        # Called only when this UI's worker has exited, or on an idle task.
        # Preserve per-item submission evidence, including unknown results.
        path=getattr(self,'material_import_path',None)
        if path and path.exists():
            result=catalog.read(path)
            if result.get('run_state')!='finished':
                result['run_state']='cancelled';save_json(path,result)
            self.present_result(result)
            self.status.set('入库已停止，完成项保留；可点击“重试上次入库未完成项”。');return
        if self.plan and self.plan.exists():
            r=catalog.read(self.plan)
            if any(j['status'] not in ('desktop_confirmed','already_exists','add_executed') for j in r.get('jobs',[])):
                r['run_state']='cancelled';r['updated']=datetime.now().astimezone().isoformat();save_json(self.plan,r)
                self.present_result(r)
                self.status.set('任务已取消，进度已保存；不会自动继续。');return
        self.status.set('当前没有仍在执行的搬运；已停止后台准备，已有结果保留。')
        self.schedule_summary_clear()
    def stop(self):
        self.auto_paused=True
        self.wechat_prepare_pending=False
        self.pending_transfer=None;self.pending_plan=None;self.pending_resume=False;self.preview_redirect=False
        self.pending_library_import=None
        if self.preview_after:self.root.after_cancel(self.preview_after);self.preview_after=None
        self.cancel.parent.mkdir(parents=True,exist_ok=True);self.cancel.touch()
        if self.plan:self.plan.with_suffix('.cancel').touch()
        self.stopping=self.busy
        self.status.set('正在停止；不再开始下一项，已发生的操作与进度会保留。')
        try:
            for token in self.queue_cancel_paths():token.touch()
        except OSError:
            # The primary token is already durable. The worker may be doing
            # an atomic plan replacement; don't lose the cancellation receipt.
            pass
        if not self.busy:self.finish_cancel()
    def close(self):
        if self.busy:self.stop();self.status.set('正在停止，请待当前步骤结束后再关闭。');return
        if self.preview_after:self.root.after_cancel(self.preview_after)
        if self.summary_after:self.root.after_cancel(self.summary_after)
        self.root.destroy()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--smoke',action='store_true');a=p.parse_args()
    root=tk.Tk();app=App(root)
    if a.smoke:
        root.update();assert not any(app.selected.values())
        save_json(ROOT/'reports/T005/ui-smoke.json',{'default_selected':0,'clients':{k:catalog.counts(v) for k,v in app.library['clients'].items()},'widgets_rendered':True})
        root.after(1500,root.destroy)
    root.mainloop()
