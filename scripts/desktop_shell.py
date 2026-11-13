from emoji_bridge.materials import is_dynamic
"""Persistent Tk pages. Local work never requires client discovery at startup."""
import json
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox,filedialog

from emoji_bridge.materials import default_root
from emoji_bridge.state import single_instance
from material_library_ui import LibraryApp
from ui_style import apply, BG, FONT, GAP


class PageHost(tk.Frame):
    """Existing root-based views can live in a page without resizing the desktop."""
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.window_close = None
        self.page_bindings = {}

    def title(self, *args): pass
    def geometry(self, *args): pass
    def minsize(self, *args): pass
    def protocol(self, name, callback=None):
        if name == 'WM_DELETE_WINDOW': self.window_close = callback

    def bind(self, sequence=None, func=None, add=None):
        if sequence in ('<MouseWheel>', '<Control-v>'):
            self.page_bindings[sequence] = func
            return
        return super().bind(sequence, func, add)


class DesktopShell:
    def __init__(self, root, store, *, base=None, embedded=False):
        self.root=root;self.store=store;self.base=Path(base) if base else default_root().parent
        from ui_scroll import configure
        try:configure(root,json.loads((store.root/'desktop-ui.json').read_text('utf8')))
        except (OSError,ValueError):configure(root)
        self.embedded=embedded;self.view_active=True
        self.editor=None;self.bridge=None;self.profile=None;self.client_lock=None
        self.task=None;self.task_host=None;self.pending_plan=None;self.setup_started=False;self.output_transfer=None
        self.bridge_previous_pause=None
        self.closed=False;self.current='library';self.video_window=None;self.static_sessions=[]
        apply(root);root.title('EmojiBridge · 素材与创作');root.geometry('1400x940');root.minsize(1150,800)
        root.configure(bg=BG);root.protocol('WM_DELETE_WINDOW',self.close)
        self.sidebar=ttk.Frame(root,padding=(12,22));self.sidebar.pack(side='left',fill='y')
        self.brand=ttk.Label(self.sidebar,text='EmojiBridge',font=(FONT,14,'bold'));self.brand.pack(anchor='w',pady=(0,12))
        self.nav_collapsed=False
        self.nav_toggle=ttk.Button(self.sidebar,text='‹ 收起导航',command=self.toggle_navigation);self.nav_toggle.pack(fill='x',pady=(0,12))
        self.content=ttk.Frame(root);self.content.pack(side='left',fill='both',expand=True)
        self.content.rowconfigure(0,weight=1);self.content.columnconfigure(0,weight=1)
        self.transfer_status=tk.StringVar(value='本地素材与创作')
        footer=self.footer=ttk.Frame(self.content,padding=6);footer.grid(row=1,column=0,sticky='ew')
        ttk.Label(footer,textvariable=self.transfer_status,wraplength=750).pack(side='left')
        ttk.Button(footer,text='查看结果',command=self.show_results).pack(side='right')
        ttk.Button(footer,text='历史',command=self.choose_task).pack(side='right',padx=3)
        ttk.Button(footer,text='取消互通',command=self.cancel_transfer).pack(side='right',padx=4)
        self.pages={};self.nav={}
        for key,label in [('bridge','表情互通'),('library','素材库'),('editor','创作编辑'),('settings','设置')]:
            button=ttk.Button(self.sidebar,text=label,style='Nav.TButton',command=lambda k=key:self.show(k))
            button.pack(fill='x',pady=3);self.nav[key]=button
            page=PageHost(self.content);page.grid(row=0,column=0,sticky='nsew');self.pages[key]=page
        self.pages['video']=PageHost(self.content);self.pages['video'].grid(row=0,column=0,sticky='nsew')
        self.nav_footer=ttk.Label(self.sidebar,text='本地保存\n图片 / GIF / 视频转换',foreground='#506277');self.nav_footer.pack(side='bottom',anchor='w',pady=12)
        self.library=LibraryApp(self.pages['library'],store,navigate=self.show,edit_selected=self.edit,add_selected=self.add_to_editor,launch_plan=self.launch_plan,
                                can_transfer=self.can_transfer,cutout_selected=self.cutout_selected,open_video=self.open_video)
        self.editor_bar=ttk.Frame(self.pages['editor'],padding=12);self.editor_bar.pack(fill='x')
        ttk.Button(self.editor_bar,text='从素材库选择',command=lambda:self.show('library')).pack(side='left')
        ttk.Button(self.editor_bar,text='打开可编辑草稿…',command=self.choose_draft).pack(side='left',padx=8)
        ttk.Button(self.editor_bar,text='视频选段',command=self.open_video).pack(side='left',padx=4)
        self.editor_area=ttk.Frame(self.pages['editor']);self.editor_area.pack(fill='both',expand=True)
        self.editor_hint=ttk.Label(self.editor_area,text='在素材库勾选图片，点击“编辑 / 新建作品”。\n切换页面会保留正在编辑的内容。',padding=40)
        self.editor_hint.pack(anchor='nw')
        self.connection=ttk.Frame(self.pages['bridge'],padding=28);self.connection.pack(fill='both',expand=True)
        ttk.Label(self.connection,text='表情互通',style='Title.TLabel').pack(anchor='w',pady=GAP)
        ttk.Label(self.connection,text='连接前，请先登录 QQ 和微信，并打开两边的聊天窗口。\n微信建议停在「文件传输助手」，输入框请保持为空。\n素材库和创作编辑可独立使用；互通每批五张，可取消、继续并核验结果。',wraplength=750).pack(anchor='w',pady=GAP)
        ttk.Button(self.connection,text='连接微信 / QQ',command=self.connect).pack(anchor='w',pady=GAP)
        settings=self.pages['settings'];from emoji_bridge.pilot import BUILD
        ttk.Label(settings,text='设置',style='Title.TLabel',padding=24).pack(anchor='w')
        ttk.Button(settings,text='打开旧 miniPaint 草稿…',command=self.open_legacy_static).pack(anchor='w',padx=24)
        ttk.Label(settings,text=f'版本：{BUILD}\n\n素材与草稿保存在：\n{store.root}\n\nPNG 保存透明信息；支持多 GIF、动态主体与背景，均可叠文字和静态贴图（7 GIF组合已实测）。\nGIF 使用最多 256 色和全透明/不透明，半透明以 50% 为界；缺失或为 0 的帧时长按 100 毫秒处理。\n源GIF上限：1GiB、18000帧、30分钟、单帧3200万像素；帧磁盘预算8GiB。动态导出逐帧处理，单帧上限1600万像素；可明确选择原尺寸、50% 或 25% 输出，不改原件和画布。\n复制图片仅用于静态作品，GIF 请拖出或导出。\n旧扁平作品可作为图片使用，无法恢复原始图层。\n客户端兼容与诊断在“表情互通”内查看。',wraplength=850,padding=24).pack(anchor='w')
        root.bind('<Control-v>',lambda e:self.route('<Control-v>',e))
        root.bind('<MouseWheel>',lambda e:self.route('<MouseWheel>',e))
        root.bind('<ButtonPress-1>',self.focus_embedded_click,add='+')
        self.show('library')
        self.toggle_navigation()
        self.set_embedded(embedded)
        self.static_poll_id=self.root.after(200,self.poll_static)
        # Import-only warmup: no widgets, clients, images or models are opened.
        # File loading is paid off the event loop before the first edit click.
        threading.Thread(target=self.warm_editor_modules,daemon=True,name='editor-imports').start()

    def set_embedded(self, embedded):
        """The modern window supplies navigation; the editing engine is unchanged."""
        self.embedded=bool(embedded)
        if self.embedded:
            # The outer desktop owns minimum dimensions. A mapped Tk root's
            # standalone minimum otherwise clips the embedded page on resize.
            self.root.minsize(1,1)
            self.sidebar.pack_forget();self.footer.grid_remove()
        else:
            self.root.minsize(1150,800)
            self.sidebar.pack(side='left',fill='y',before=self.content);self.footer.grid()

    def focus_embedded_click(self, event):
        # After cross-process SetParent, Tk's default focus_set can leave the
        # WinForms/WebView control owning the keyboard. Transfer focus only in
        # response to a real click in this visible workspace, never on layout.
        if not self.embedded or not self.view_active:return
        widget=event.widget
        if widget.winfo_toplevel() is self.root and self.root.focus_get() is not widget:
            widget.focus_force()

    def set_view_active(self, active):
        self.view_active=bool(active)
        self.library.view_active=bool(active and self.current=='library')
        if self.editor and not self.editor.closed:self.editor.set_view_active(bool(active and self.current=='editor'))
        if self.video_window and not self.video_window.closed:
            self.video_window.set_view_active(bool(active and self.current=='video'))

    @staticmethod
    def warm_editor_modules():
        import importlib
        for module in ('layout_editor','editor_panels','editor_output','editor_icons','cutout_tools','editor_timeline'):
            importlib.import_module(module)

    def route(self, sequence, event):
        page=self.pages[self.current]
        if not str(event.widget).startswith(str(page)+'.'):return
        if self.current=='bridge' and self.task_host and self.task_host.winfo_ismapped():return
        handler=page.page_bindings.get(sequence)
        if handler:return handler(event)

    def toggle_navigation(self):
        self.nav_collapsed=not self.nav_collapsed
        self.brand.configure(text='EB' if self.nav_collapsed else 'EmojiBridge')
        self.nav_toggle.configure(text='›' if self.nav_collapsed else '‹ 收起导航')
        self.nav_footer.configure(text='本地' if self.nav_collapsed else '本地保存\n图片 / GIF')
        for key,full,short in [('bridge','表情互通','互通'),('library','素材库','素材'),('editor','创作编辑','创作'),('settings','设置','设置')]:
            self.nav[key].configure(text=short if self.nav_collapsed else full,width=4 if self.nav_collapsed else 12)

    def add_to_editor(self,ids):
        if not self.editor or self.editor.closed or not self.editor.doc:
            self.library.status.set('当前没有作品，请先使用“用所选新建作品”。');return
        if self.editor.busy:
            self.library.status.set('当前作品正在处理，请稍候再添加。');return
        self.show('editor');self.editor.add_materials(ids)

    def cutout_selected(self,ids):
        if len(ids)!=1:
            self.library.status.set('请选择一张图片或 GIF，再点击“抠主体”。');return
        item=self.store.get(ids[0])
        before=self.editor
        self.edit(ids)
        editor=self.editor
        if editor is None or editor is before or editor.closed:return
        def start():
            if self.editor is not editor or editor.closed:return
            if editor.busy: self.root.after(80,start);return
            editor.cutout.activate()
        self.root.after(80,start)

    def open_video(self,paths=()):
        from video_tools import VideoWindow
        if not paths:
            ids=self.library.selected_ids()
            if len(ids)==1 and is_dynamic(self.store.get(ids[0])['metadata']):paths=[self.store.original(ids[0])]
        if self.video_window and not self.video_window.closed:
            if self.embedded:self.show('video')
            else:self.video_window.window.deiconify();self.video_window.window.lift()
            if paths:self.video_window.open_file(paths[0])
        else:
            host=None
            if self.embedded:
                host=PageHost(self.pages['video']);host.pack(fill='both',expand=True)
            self.video_window=VideoWindow(self.root,self.store,paths,on_saved=self.saved,on_edit=self.open_draft,on_edit_materials=self.edit,
                                          host=host,on_return=lambda:self.show('editor' if self.editor and not self.editor.closed else 'library'))
            if self.embedded:self.show('video')
        if len(paths)>1:self.library.status.set('视频按一段一段处理，本次打开第一个；其余文件请分别选择。')

    def static_edit(self,ids):
        if not ids:
            self.library.status.set('请先选择静态图片；截图可先“粘贴图片”。');return
        def work():
            from minipaint_bridge import start_static_editor
            session=start_static_editor(self.store,ids,progress=lambda text:self.library.events.put(('progress',text)))
            self.static_sessions.append(session)
            return {'text':'静态画笔已在独立本地窗口打开；点“保存并返回素材库”即可继续使用成品。'}
        self.library.start(work)

    def open_legacy_static(self):
        path=filedialog.askopenfilename(parent=self.root,title='仅打开已有 miniPaint 草稿',initialdir=self.store.root/'external-drafts/minipaint',filetypes=[('旧草稿','project.json')])
        if not path:return
        try:
            data=json.loads(Path(path).read_text(encoding='utf-8'))
            if data.get('schema')!='emoji-bridge-minipaint-v1':raise ValueError('请选择原来保存的 miniPaint project.json')
            ident=data['material_id'];self.store.get(ident);self.static_edit([ident])
        except (ValueError,OSError,KeyError) as exc:messagebox.showerror('旧草稿未打开',str(exc),parent=self.root)

    def poll_static(self):
        if self.closed:return
        self.apply_catalog_refresh()
        for session in self.static_sessions:
            try:
                while True:
                    kind,value=session.events.get_nowait()
                    if kind=='saved':self.saved(self.store.get(value))
                    elif kind=='return':
                        self.show('library');self.root.deiconify();self.root.lift()
                        if value:self.library.status.set('静态作品与可编辑草稿已保存，可从素材缩略图拖出或继续编辑。')
                    elif kind=='error':self.library.status.set('静态编辑未完成：'+value)
            except queue.Empty:pass
        self.static_poll_id=self.root.after(200,self.poll_static)

    def show(self, key):
        self.current=key;self.pages[key].tkraise()
        self.library.view_active=key=='library'
        if key=='library' and getattr(self.library,'pending_reload',False):self.library.reload(preserve_scroll=True)
        if self.editor and not self.editor.closed:self.editor.set_view_active(key=='editor')
        if self.video_window and not self.video_window.closed:self.video_window.set_view_active(key=='video' and self.view_active)
        if key=='editor' and self.editor and not self.editor.closed:self.editor.material_panel.reload(preserve_scroll=True)
        for name,button in self.nav.items():button.state(['selected'] if name==key else ['!selected'])

    def saved(self, item):
        # Keep the library's search/page/selection; newly saved work can be found by name.
        if self.current=='library' and not self.embedded:self.library.reload(preserve_scroll=True)
        else:self.library.pending_reload=True
        self.library.status.set('作品已保存在素材库。原素材未覆盖；可导出或转移到收藏。')

    def replace_editor(self, ids=(), document=None, draft=None, document_loader=None):
        if self.output_transfer:self.cancel_transfer()
        if self.editor and not self.editor.closed and not self.editor.close():return False
        if self.editor_hint.winfo_exists():self.editor_hint.destroy()
        self.editor_bar.pack_forget()
        from layout_editor import LayoutEditor
        host=ttk.Frame(self.editor_area);host.pack(fill='both',expand=True)
        self.editor=LayoutEditor(self.root,self.store,list(ids),on_saved=self.saved,host=host,
                                 on_return=lambda:self.show('library'),document=document,document_loader=document_loader)
        if self.editor.closed:
            self.editor_bar.pack(fill='x',before=self.editor_area)
            return False
        from cutout_tools import attach
        self.editor.cutout=attach(self.editor)
        from ui_style import panel_surface
        panel_surface(self.editor.properties_host)
        self.editor.open_video=self.open_video
        self.editor.canvas_menu.add_command(label='视频选段…',command=self.open_video)
        self.editor.open_draft_dialog=self.choose_draft
        self.editor.transfer_targets=[(label,lambda t=target:self.request_work_transfer(t))
            for target,label in [('qq','转移到 QQ'),('wechat','转移到微信')]]
        e=self.editor
        transfer_bar=ttk.Frame(e.window);e.transfer_bar=transfer_bar;e.transfer_buttons={}
        for label,target in [('转到微信','wechat'),('转到 QQ','qq')]:
            button=ttk.Button(transfer_bar,text=label,width=9,command=lambda t=target:self.request_work_transfer(t))
            button.pack(side='right',padx=3);e.transfer_buttons[target]=button
        transfer_bar.pack(in_=e.output_area,side='right',padx=3)
        e.window.after_idle(e.fit_output_area)
        if draft:
            self.editor.draft_id=Path(draft).name
            self.editor.name.set(json.loads((Path(draft)/'scene.json').read_text(encoding='utf-8')).get('name','创作作品'))
        self.show('editor');return True

    def edit(self, ids):
        if not ids:
            if self.editor and not self.editor.closed:self.show('editor');return True
            from emoji_bridge.editing import EditDocument
            from PIL import Image
            return self.replace_editor(document=EditDocument(Image.new('RGBA',(640,480))))
        if len(ids)==1:
            for source in reversed(self.store.sources(ids[0])):
                if source['kind']!='edited':continue
                try:
                    ident=json.loads(source['value'])['recipe']['draft_id']
                    if not ident.isalnum():continue
                    directory=self.store.root/'drafts'/ident
                    if (directory/'scene.json').exists():return self.open_draft(directory)
                except (KeyError,ValueError):pass
        return self.replace_editor(ids)

    def open_draft(self, directory, *, prepared_document=None):
        from emoji_bridge.editing import load_scene
        try:
            if prepared_document is None:
                return self.replace_editor(draft=directory,document_loader=lambda **kwargs:load_scene(directory,**kwargs))
            else:
                # The video worker just saved these exact frames. Transfer its
                # finished document instead of decoding the same PNGs on Tk.
                document=prepared_document
                data=json.loads((Path(directory)/'scene.json').read_text(encoding='utf-8'))
                document._initial=document._state
                document._undo.clear();document._redo.clear();document.mark_saved()
            if self.replace_editor(document=document,draft=directory):
                self.editor.frame_history=data.get('extra',{}).get('extracted_frames',[])
                self.editor.editing_recipe={k:v for k,v in data.get('extra',{}).items() if k!='extracted_frames'}
                # A saved PNG keeps its own immutable scene snapshot. Continuing it
                # creates a new draft instead of changing what that PNG points to.
                if data.get('extra',{}).get('work_snapshot'):self.editor.draft_id=None
                return True
        except (ValueError,OSError,KeyError) as exc:messagebox.showerror('草稿未打开',str(exc),parent=self.root)
        return False

    def choose_draft(self):
        dialog=tk.Toplevel(self.root);dialog.title('可编辑草稿');dialog.transient(self.root)
        rows=[];box=tk.Listbox(dialog,width=60,height=15,exportselection=False);box.pack(padx=16,pady=16)
        for file in sorted((self.store.root/'drafts').glob('*/scene.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            if (file.parent/'deleted.json').exists():continue
            try:
                data=json.loads(file.read_text(encoding='utf-8'));box.insert('end',data.get('name','创作草稿'));rows.append(file.parent)
            except (OSError,ValueError):continue
        if not rows:box.insert('end','尚无草稿；编辑后点击“保存可编辑草稿”。')
        def choose():
            if rows and box.curselection():
                directory=rows[box.curselection()[0]];dialog.destroy();self.open_draft(directory)
        ttk.Button(dialog,text='打开',command=choose).pack(pady=12);box.bind('<Double-Button-1>',lambda e:choose())

    def connect(self):
        if self.setup_started:return
        # An idle editor/setup page is not a client operation. Actual scans,
        # acquisition and submission retain their existing OS resource locks.
        self.setup_started=True;self.connection.destroy()
        if self.task_host:self.task_host.pack_forget()
        from emoji_bridge.pilot import setup
        setup(self.pages['bridge'],self.base,on_ready=self.connected)

    def connected(self, profile):
        from emoji_bridge import paths
        paths.configure_data_root(profile);self.profile=profile
        if self.pending_plan:
            path,autostart=self.pending_plan;self.pending_plan=None
            try:
                from collection_transfer import complete_target_configuration
                from emoji_bridge.state import save_json
                plan=json.loads(Path(path).read_text('utf-8'));complete_target_configuration(plan,profile);save_json(path,plan)
                self.launch_plan(path,autostart=autostart)
                if self.embedded and getattr(self,'on_accounts_ready',None):self.on_accounts_ready()
            except (ValueError,OSError) as exc:self.transfer_status.set('互通未启动：'+str(exc))
        elif self.embedded and getattr(self,'on_accounts_ready',None):self.on_accounts_ready()
        else:self.open_bridge()

    def client_idle(self):
        return not self.bridge or not (self.bridge.busy or self.bridge.preview_busy or self.bridge.loading_previews or self.bridge.qq_cache_checking)

    def can_transfer(self):
        return self.client_idle() and not self.pending_plan and not self.output_transfer and not (self.task and self.task['state']['busy'])

    def request_work_transfer(self,target):
        self.transfer_work(target)

    def bind_saved_profile(self,target=None):
        from collection_service import Collections
        collections=Collections(self.store);collections.base=self.base
        context=collections.context()
        if not context or not context[1].get('read_authorized'):return False
        profile,choice=context
        if target:
            source=choice.get('qq_ori' if target=='qq' else 'wechat_emoticon_db')
            if not source or not Path(source).exists():return False
        if self.profile and Path(self.profile).resolve()!=profile.resolve():
            raise ValueError('当前账号已改变，请重新打开互通工作区后选择该账号；未执行旧配置。')
        from emoji_bridge import paths
        paths.configure_data_root(profile);self.profile=profile
        return True

    def transfer_work(self,target,captured=None):
        """Persist intent now; join the current output job, then use the same plan."""
        from copy import copy,deepcopy
        from datetime import datetime
        import uuid,threading
        from emoji_bridge.state import save_json
        editor=self.editor
        if not editor or not editor.doc or editor.busy or not self.can_transfer():
            self.transfer_status.set('当前作品尚未就绪或已有准备任务，请等待或先取消。')
            self.transfer_failure={'created':uuid.uuid4().hex,'target':target,'run_state':'paused','pause_reason':'work_not_ready','jobs':[]}
            return
        if not editor.finish_text():return
        snapshot=captured.document if captured else copy(editor.doc);revision=snapshot.revision;output_size=captured.output_size if captured else editor.output.output_size();frames=deepcopy(editor.frame_history)
        self.transfer_failure=None
        path=self.store.root/'tasks'/(datetime.now().strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:6]+'.json')
        name=captured.name if captured else editor.name.get().strip() or '创作作品'
        plan={'schema':'selected-transfer-v1','source_kind':'local_material_library','library_root':str(self.store.root),
              'created':datetime.now().astimezone().isoformat(),'target':target,'work_revision':revision,'run_state':'preparing_output',
              'jobs':[{'id':uuid.uuid4().hex,'item_id':revision,'name':name,'target':target,'status':'queued','attempts':0,'submission_state':'not_started'}]}
        if self.profile:
            plan['profile']=str(self.profile)
            if (Path(self.profile)/'runtime-data/client-sources.json').exists():
                from collection_transfer import profile_binding
                plan['profile_binding']=profile_binding(self.profile)
        save_json(path,plan);save_json(self.store.root/'last-task.json',{'plan':str(path)})
        token=threading.Event();reservation={'path':path,'cancel':token,'revision':revision,'editor':editor}
        self.output_transfer=reservation
        if self.task:self.task['close']();self.task=None
        if self.task_host:self.task_host.destroy();self.task_host=None
        if self.bridge:
            if self.bridge_previous_pause is None:self.bridge_previous_pause=self.bridge.auto_paused
            self.bridge.auto_paused=True;self.bridge_host.pack_forget()
        if not self.embedded:
            self.task_host=PageHost(self.pages['bridge']);self.task_host.pack(fill='both',expand=True)
        reservation['host']=self.task_host
        output_note=tk.StringVar(value=f'{name} → {target} · 正在准备本次成品；准备完成后自动转移。')
        if self.task_host:ttk.Label(self.task_host,textvariable=output_note,padding=24,wraplength=800).pack(anchor='w')
        self.transfer_status.set(output_note.get())
        def fail(exc):
            if self.output_transfer is not reservation:return
            cancelled=token.is_set()
            token.set()
            plan.update(run_state='cancelled' if cancelled else 'output_failed',pause_reason=str(exc))
            plan['jobs'][0].update(status='cancelled' if cancelled else 'failed',reason=str(exc))
            save_json(path,plan);self.output_transfer=None;self.transfer_failure=plan
            output_note.set('成品未转移：'+str(exc)+'。原件和编辑内容保留，可重新点击目标重试。')
            self.transfer_status.set(output_note.get())
        from emoji_bridge.scene_save import SceneSave
        saved=captured or SceneSave.capture(snapshot,name,output_size,{'extracted_frames':frames,**getattr(editor,'editing_recipe',{})},editor.work_id)
        saved.cancel=token
        # A transfer owns the click-time snapshot; preview invalidation and later
        # editing must neither replace this output nor cancel the accepted job.
        future=editor.pool.submit(saved.run,self.store,lambda *args:None)
        def finish():
            if self.closed or self.output_transfer is not reservation:return
            if not future.done():self.root.after(60,finish);return
            handoff=False
            try:
                item=future.result()
                if token.is_set():raise RuntimeError('已取消，成品已保留但未提交客户端')
                plan['jobs'][0].update(item_id=item['id'],source_sha256=item['id'])
                plan['run_state']='queued';plan['work_material']=item['id'];save_json(path,plan)
                self.saved(item)
                host=reservation['host']
                if host and host.winfo_exists():host.destroy()
                if self.task_host is host:self.task_host=None
                self.output_transfer=None;handoff=True
                self.launch_plan(path,autostart=True)
            except Exception as exc:
                if handoff and self.output_transfer is None:self.output_transfer=reservation
                fail(exc)
        finish()

    def cancel_transfer(self):
        if self.output_transfer:
            self.output_transfer['cancel'].set()
            self.output_transfer['editor'].output.cancel_prepare()
        elif self.pending_plan:
            from emoji_bridge.state import save_json
            path,_=self.pending_plan;value=json.loads(Path(path).read_text('utf-8'));value['run_state']='cancelled';save_json(path,value)
            self.pending_plan=None;self.transfer_status.set('已取消待配置任务，未提交客户端。')
        elif self.task:self.task['cancel']()

    def task_update(self,plan,message):
        from material_transfer import plan_stage,account_label
        from collections import Counter
        counts=Counter(plan_stage(plan,j) for j in plan['jobs'])
        detail='、'.join(f'{label} {n}' for label,n in counts.items())
        prefix={'wechat':'微信','qq':'QQ'}[plan['target']]
        account=account_label(self.profile,plan['target']) if self.profile else '待确认账号'
        self.transfer_status.set(f'{prefix}（{account}）· {len(plan["jobs"])} 张 · {detail}。'+message)
        refresh=plan.get('target_refresh',{})
        if refresh.get('state')=='done':
            # A manual rescan changes target_refresh, not the transfer's updated
            # timestamp. Busy views must also consume this completion later.
            key=(plan.get('target'),refresh.get('at'),repr(refresh.get('wechat_snapshot')),plan.get('updated'))
            if getattr(self,'refreshed_task',None)!=key:
                self.pending_catalog_refresh=(key,refresh)
                self.apply_catalog_refresh()

    def apply_catalog_refresh(self):
        pending=getattr(self,'pending_catalog_refresh',None)
        if not pending or not self.bridge or self.bridge.busy:return
        key,refresh=pending
        self.bridge.reload()
        if 'wechat_recent_ids' in refresh:
            from scan_view import snapshot_key
            if list(snapshot_key(self.bridge.library['clients']['wechat']))==refresh.get('wechat_snapshot'):
                recent=self.bridge.recent_wechat
                recent.recent=set(refresh['wechat_recent_ids']);recent.checked=True;recent.stale=False
                self.bridge.render()
        self.refreshed_task=key;self.pending_catalog_refresh=None

    def show_results(self):
        self.show('bridge')
        if self.task or self.output_transfer:return
        self.choose_task()

    def locate_materials(self,ids):
        # Explicit navigation may clear filters; automatic result callbacks never do.
        valid=[]
        for ident in ids:
            try:
                if self.store.get(ident):valid.append(ident)
            except (KeyError,ValueError):pass
        ids=valid
        if not ids:return
        library=self.library
        library.query.set(self.store.get(ids[0])['name']);library.category.set('全部分类')
        library.filters.view.set('全部素材');library.filters.source.set('全部来源');library.filters.media.set('全部格式')
        library.page=0;library.selected=set(ids);library.reload();self.show('library')
        library.status.set('已按本次首件作品名称定位并清除原筛选；原件、标签和合集保持不变。')

    def choose_task(self):
        dialog=tk.Toplevel(self.root);dialog.title('互通结果（仅查看，不自动重发）');dialog.transient(self.root)
        box=tk.Listbox(dialog,width=90,height=12);box.pack(padx=12,pady=12);files=[]
        from material_transfer import plan_stage
        for path in sorted((self.store.root/'tasks').glob('*.json'),reverse=True):
            try:
                value=json.loads(path.read_text(encoding='utf-8'))
                if value.get('source_kind')!='local_material_library':continue
                if self.profile and value.get('profile') and Path(value['profile'])!=self.profile:continue
                box.insert('end',f'{value["created"][:19]} · {value["target"]} · {len(value["jobs"])} 张 · '+', '.join(dict.fromkeys(plan_stage(value,j) for j in value['jobs'])))
                files.append(path)
            except (OSError,ValueError,KeyError):continue
        def choose():
            if box.curselection():
                path=files[box.curselection()[0]];dialog.destroy();self.launch_plan(path)
        ttk.Button(dialog,text='查看所选记录',command=choose).pack(pady=8)
        box.bind('<Double-Button-1>',lambda e:choose())
        if not files:box.insert('end','暂无互通记录。')

    def open_bridge(self):
        if self.output_transfer:
            self.transfer_status.set('成品正在准备；可切页浏览或取消，准备后自动执行。');return
        if self.task and self.task['state']['busy']:
            self.task['status'].set('任务仍在运行；切换素材库不受影响，返回互通列表前请等待或取消。');return
        hint=None
        if self.task:
            try:hint=json.loads(self.task['path'].read_text(encoding='utf-8')).get('target_refresh')
            except (OSError,ValueError):pass
            if self.task.get('close') and self.embedded:self.task['close']()
            else:self.task['state']['closed']=True
            if self.task_host:self.task_host.destroy()
            self.task=None;self.task_host=None
        if not self.bridge:
            from bridge_ui import App
            self.bridge_host=PageHost(self.pages['bridge']);self.bridge_host.pack(fill='both',expand=True)
            self.bridge=App(self.bridge_host,on_library=lambda:self.show('library'),material_store=self.store)
            self.pages['bridge'].page_bindings.update(self.bridge_host.page_bindings)
        else:
            self.bridge_host.pack(fill='both',expand=True)
            self.apply_catalog_refresh()
            if self.bridge_previous_pause is not None:
                self.bridge.auto_paused=self.bridge_previous_pause;self.bridge_previous_pause=None
                if self.bridge.auto_previews:
                    self.bridge.initial_qq_index();self.bridge.initial_wechat_prepare();self.bridge.schedule_previews()
        if hint and 'wechat_recent_ids' in hint:
            from scan_view import snapshot_key
            recent=self.bridge.recent_wechat;side=self.bridge.library['clients']['wechat']
            if list(snapshot_key(side))==hint.get('wechat_snapshot'):
                recent.recent=set(hint['wechat_recent_ids']);recent.checked=True;recent.stale=False
                self.bridge.render()

    def launch_plan(self, path, autostart=False):
        if not autostart and not self.embedded:self.show('bridge')
        if self.output_transfer:
            self.transfer_status.set('成品转移正在准备；请等待或先取消，再打开其他任务。');return
        if self.task and self.task['state']['busy']:
            self.task['status'].set('已有任务运行中，请先等待或取消。新任务尚未执行。');return
        if autostart:
            try:
                plan=json.loads(Path(path).read_text('utf-8'))
                bound=self.bind_saved_profile(plan['target'])
                if not bound and (self.base/'last-profile.json').exists():
                    self.pending_plan=(path,autostart);self.transfer_status.set('目标账号目录未就绪；请补全账号设置，完成后自动继续。')
                    self.show('bridge')
                    if getattr(self,'on_transfer_setup',None):self.on_transfer_setup()
                    self.setup_started=False;self.connect();return
                if self.profile:
                    from emoji_bridge.state import save_json
                    from collection_transfer import check_profile,profile_binding
                    if plan.get('profile') and Path(plan['profile']).resolve()!=Path(self.profile).resolve():raise ValueError('请使用创建本任务时的同一账号配置')
                    if (Path(self.profile)/'runtime-data/client-sources.json').exists():
                        check_profile(plan,self.profile)
                        plan.update(profile=str(Path(self.profile).resolve()),profile_binding=profile_binding(self.profile));save_json(path,plan)
            except (ValueError,OSError,RuntimeError) as exc:
                self.transfer_status.set('互通未启动：'+str(exc));return
        if not self.profile:
            if not autostart:
                self.open_history(path);return
            self.pending_plan=(path,autostart);self.transfer_status.set('本次目标尚未配置；完成本人账号设置后自动继续，可取消。')
            self.show('bridge')
            if getattr(self,'on_transfer_setup',None):self.on_transfer_setup()
            self.connect();return
        self.open_task(path,autostart=autostart)
        if not autostart and not self.embedded:self.show('bridge')

    def open_history(self,path):
        """Read saved evidence without binding workflow modules to an account."""
        from material_transfer import plan_stage,account_label
        try:plan=json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError,ValueError) as exc:
            messagebox.showerror('记录无法读取',str(exc),parent=self.root);return
        if self.task:self.task['state']['closed']=True
        if self.task_host:self.task_host.destroy()
        self.connection.pack_forget()
        self.task_host=PageHost(self.pages['bridge']);self.task_host.pack(fill='both',expand=True)
        frame=ttk.Frame(self.task_host,padding=20);frame.pack(fill='both',expand=True)
        account=account_label(Path(plan['profile']),plan['target']) if plan.get('profile') else '尚未连接账号'
        target={'qq':'QQ','wechat':'微信'}[plan['target']]
        ttk.Label(frame,text=f'{target} · {account} · {len(plan["jobs"])} 张',style='Title.TLabel').pack(anchor='w')
        status=tk.StringVar(value='正在查看已保存结果；未连接客户端，不会重发。')
        ttk.Label(frame,textvariable=status,wraplength=850).pack(anchor='w',pady=12)
        rows=ttk.Treeview(frame,columns=('name','stage'),show='headings')
        for col,title in [('name','本次作品'),('stage','真实状态')]:rows.heading(col,text=title)
        rows.pack(fill='both',expand=True)
        for job in plan['jobs']:rows.insert('', 'end',iid=job['id'],values=(job['name'],plan_stage(plan,job)))
        details='\n'.join(j.get('reason','') for j in plan['jobs'] if j.get('reason'))
        if plan.get('pause_reason'):details+='\n'+plan['pause_reason']
        refresh=plan.get('target_refresh',{})
        if refresh:details+='\n收藏列表刷新：'+{'done':'已完成','failed':'失败；原件及收藏结果保留','running':'上次尚未完成'}.get(refresh.get('state'),'未完成')
        ttk.Label(frame,text=details,wraplength=850).pack(anchor='w',pady=12)
        def resume():
            if getattr(self,'on_resume_transfer',None):self.on_resume_transfer(Path(path))
            else:self.launch_plan(Path(path),autostart=True)
        ttk.Button(frame,text='连接同一账号并继续 / 重试未完成',command=resume).pack(anchor='w')
        ttk.Button(frame,text='在素材库定位作品',command=lambda:self.locate_materials([j['item_id'] for j in plan['jobs'] if not rows.selection() or j['id'] in rows.selection()])).pack(anchor='w',pady=6)
        self.task={'state':{'busy':False,'closed':False},'path':Path(path),'status':status,
                   'cancel':lambda:status.set('此页只查看历史，没有正在运行的任务。'),'rows':rows}
        self.transfer_status.set(status.get());self.show('bridge')

    def open_task(self,path,autostart=False):
        if self.output_transfer:
            self.transfer_status.set('成品转移正在准备，未启动其他任务。');return
        if not self.client_idle():
            messagebox.showinfo('互通正在准备','请等当前准备结束或取消后，再从素材库开始添加。',parent=self.root);return
        if self.task:
            if self.task.get('close'):self.task['close']()
            else:self.task['state']['closed']=True
            self.task=None
        if self.task_host:self.task_host.destroy();self.task_host=None
        if self.bridge:
            if self.bridge_previous_pause is None:self.bridge_previous_pause=self.bridge.auto_paused
            self.bridge.auto_paused=True
            self.bridge_host.pack_forget()
        if not self.embedded:
            if self.connection.winfo_exists():self.connection.pack_forget()
            self.task_host=PageHost(self.pages['bridge']);self.task_host.pack(fill='both',expand=True)
        from material_transfer_ui import create_task
        try:self.task=create_task(self.root if self.embedded else self.task_host,Path(path),self.profile,on_close=(lambda:None) if self.embedded else self.open_bridge,can_start=lambda:self.client_idle() and not self.output_transfer,autostart=autostart,on_update=self.task_update,on_locate=self.locate_materials,on_resume=getattr(self,'on_resume_transfer',None),headless=self.embedded)
        except (ValueError,OSError) as exc:
            if self.task_host:self.task_host.destroy();self.task_host=None
            self.transfer_status.set('任务未打开：'+str(exc))
            messagebox.showerror('任务未打开',str(exc),parent=self.root)
            if not self.embedded:self.open_bridge()

    def close(self):
        if self.closed:return
        if self.output_transfer:
            self.cancel_transfer()
        if self.library.busy:
            self.library.stop()
        if self.task and self.task['state']['busy']:
            self.task['cancel']();self.root.after(100,self.close);return
        if not self.client_idle():
            self.bridge.stop();self.root.after(100,self.close);return
        if self.editor and not self.editor.closed and not self.editor.close():
            self.show('editor');return
        if self.video_window and not self.video_window.closed:self.video_window.close()
        for session in self.static_sessions:
            if not session.closed:
                threading.Thread(target=session.close,daemon=True).start()
        if self.task:self.task['state']['closed']=True
        if self.bridge:self.bridge.close()
        self.library.close();self.closed=True;self.root.after_cancel(self.static_poll_id)
        if self.client_lock:self.client_lock.__exit__(None,None,None);self.client_lock=None
        self.root.destroy()
