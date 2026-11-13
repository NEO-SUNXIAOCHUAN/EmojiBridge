"""Offline-first material library; client work stays in an isolated existing profile."""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor,CancelledError
from datetime import datetime
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog
from ui_dialogs import messagebox, prepare_window
from ui_style import BG, MUTED, SUCCESS
import uuid
import time

APP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(APP / 'src'), str(APP / 'scripts'), str(APP / 'third_party/tkdnd')]
from PIL import Image, ImageGrab, ImageTk
from emoji_bridge.materials import MaterialStore, default_root
from emoji_bridge.material_preview import FrameStream, thumbnail
from emoji_bridge.state import save_json, single_instance

PAGE_SIZE = 40


def error_text(exc):
    return {'format_not_supported': '暂不支持这种格式；可导入 PNG、JPEG、GIF、APNG、WebP',
            'animated_non_gif_not_supported_no_first_frame_conversion': '暂不支持非 GIF 动图，未将它转成静态图',
            'local_decode_size_limit': '图片超过当前 160 MB 文件限制，未压缩或导入',
            'local_decode_budget_exceeded': '图片尺寸或帧数超出当前解码范围，未压缩或裁剪'}.get(str(exc), str(exc))


def create_root():
    # Bundled Windows x64 TkDND. Fail visibly if its runtime is missing.
    from ui_dpi import initialize_process, initialize_tk
    initialize_process()
    from tkinterdnd2 import TkinterDnD
    root=TkinterDnD.Tk()
    initialize_tk(root)
    icon=APP/'assets/branding/EmojiBridge.ico'
    if sys.platform=='win32' and icon.is_file():root.iconbitmap(default=str(icon))
    return root


def launch_library():
    return subprocess.Popen([sys.executable, '-X', 'utf8', str(APP / 'scripts/material_library_ui.py')],
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


class Preview:
    def __init__(self, parent, item):
        self.window = tk.Toplevel(parent)
        self.window.title(item['name'] + ' · 预览')
        self.window.geometry('820x690');prepare_window(self.window,parent)
        self.closed = False; self.paused = False; self.photo = None
        self.stream = FrameStream(item['path'])
        self.label = ttk.Label(self.window, anchor='center'); self.label.pack(fill='both', expand=True, padx=12, pady=12)
        self.caption = tk.StringVar(value='正在加载…')
        ttk.Label(self.window, textvariable=self.caption).pack()
        ttk.Button(self.window, text='暂停 / 播放', command=self.toggle).pack(pady=10)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.after = self.window.after(20, self.tick)

    def toggle(self):
        self.paused = not self.paused

    def tick(self):
        if self.closed:
            return
        delay = 30
        if not self.paused:
            try:
                frame, duration, n, count = self.stream.frames.get_nowait()
                if frame is None:
                    self.caption.set('预览未完成：' + str(duration))
                else:
                    self.photo = ImageTk.PhotoImage(frame)
                    self.label.configure(image=self.photo)
                    self.caption.set(f'{n+1} / {count} 帧' + (' · 循环预览，原文件不变' if count > 1 else ' · 静态图'))
                    delay = duration
            except queue.Empty:
                pass
        self.after = self.window.after(delay, self.tick)

    def close(self):
        if self.closed:
            return
        self.closed = True; self.stream.close()
        self.window.after_cancel(self.after); self.window.destroy()


class LibraryApp:
    def __init__(self, root, store, *, navigate=None, edit_selected=None, add_selected=None, launch_plan=None, can_transfer=None, cutout_selected=None, open_video=None, static_edit=None):
        self.root = root; self.store = store
        self.navigate=navigate;self.edit_selected=edit_selected;self.launch_plan=launch_plan;self.add_selected=add_selected
        self.can_transfer=can_transfer
        self.open_video=open_video
        self.events = queue.Queue(); self.cancel = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='material-thumbnails')
        self.busy = False; self.closed = False; self.page = 0; self.generation = 0
        self.items = []; self.selected = set(); self.photos = {}; self.cards = {}; self.preview = None
        self.total=0
        self.thumb_futures = []
        self.details = ''; self.transfer_process = None; self.drag_files = ()
        self.drag_cache={};self.drag_pending=set();self.last_revision=store.revision();self.last_watch=0
        self.drag_stop=threading.Event();self.thumbnail_labels={};self.populate_after=None;self.pending_scroll=None;self.thumbnails_loaded=set()
        self.pointer_down=False;self.native_drag=False;self.deferred_reload=None;self.deferred_query=None
        self.editor = None
        root.title('EmojiBridge · 素材库与静态编辑'); root.geometry('1120x820'); root.minsize(860, 620)
        root.protocol('WM_DELETE_WINDOW', self.close)
        from ui_style import apply
        apply(root)
        top = ttk.Frame(root, padding=(22, 18)); top.pack(fill='x')
        ttk.Label(top, text='素材库', style='LibraryTitle.TLabel').pack(side='left')
        ttk.Label(top, text='原件保存在本机 · 无需启动微信 / QQ', foreground=MUTED).pack(side='left', padx=20)
        if not navigate:ttk.Button(top, text='微信 / QQ 互通', command=self.open_bridge).pack(side='right')
        bar = ttk.Frame(root, padding=(22, 0, 22, 10)); bar.pack(fill='x')
        ttk.Button(bar, text='导入图片 / 视频…' if open_video else '导入图片…', command=self.choose_files,style='Editor.Primary.TButton').pack(side='left')
        ttk.Button(bar, text='粘贴', command=self.paste).pack(side='left', padx=6)
        if cutout_selected:
            ttk.Button(bar,text='抠主体',command=lambda:cutout_selected(self.selected_ids())).pack(side='left')
        if open_video or static_edit:
            more=ttk.Menubutton(bar,text='更多 ▾',width=7);more.pack(side='left',padx=4)
            menu=tk.Menu(more,tearoff=False);more.configure(menu=menu)
            if static_edit:menu.add_command(label='静态画笔 / 滤镜（miniPaint）',command=lambda:static_edit(self.selected_ids()))
            if open_video:menu.add_command(label='视频 / 格式转换…',command=lambda:open_video(()))
            menu.add_command(label='兼容副本设置 / 导出…',command=self.compatibility_copy)
        self.query = tk.StringVar(); self.category = tk.StringVar(value='全部分类')
        self.search_box = ttk.Entry(bar, textvariable=self.query, width=27)
        self.search_box.pack(side='left', padx=(16, 6)); self.search_box.bind('<Return>', lambda e: self.search())
        ttk.Button(bar, text='搜索', command=self.search).pack(side='left')
        self.category_box = ttk.Combobox(bar, textvariable=self.category, state='readonly', width=17)
        self.category_box.pack(side='right'); self.category_box.bind('<<ComboboxSelected>>', lambda e: self.search())
        hint = ttk.Frame(root, padding=(22, 0, 22, 10)); hint.pack(fill='x')
        from material_organizer_ui import Filters
        self.filters=Filters(hint,self.search);self.filters.pack(fill='x',pady=(0,5))
        ttk.Label(hint, text='截图可“粘贴图片”或 Ctrl+V；双击放大 / 播放 GIF。拖动缩略图可输出原件，首次准备稍等。', foreground=MUTED).pack(anchor='w')
        ttk.Label(hint,text='选中素材后点“编辑 / 新建作品”。视频可拖入选段；聊天表情无法拖入时，可先收藏再刷新列表。',foreground=MUTED).pack(anchor='w')
        ttk.Label(hint,text='转移到微信使用本人文件传输助手，每批 5 张；兼容版本可能缩到 320 像素并转 GIF，原件不变。',foreground=MUTED).pack(anchor='w')
        bottom = ttk.Frame(root, padding=(22, 12)); bottom.pack(side='bottom', fill='x')
        actions = ttk.Frame(bottom); actions.pack(fill='x')
        ttk.Button(actions, text='选择可见项', command=self.select_page).pack(side='left')
        ttk.Button(actions, text='选择全部匹配项', command=self.select_all).pack(side='left',padx=3)
        ttk.Button(actions, text='清空', command=self.clear_selection).pack(side='left', padx=4)
        ttk.Button(actions, text='名称 / 标签 / 合集', command=self.edit).pack(side='left', padx=4)
        from material_organizer_ui import manage_collections
        ttk.Button(actions,text='管理合集',command=lambda:manage_collections(root,store,self.reload)).pack(side='left')
        ttk.Button(actions, text='导出原文件…', command=self.export).pack(side='left', padx=4)
        self.drag_button = ttk.Button(actions, text='拖出所选', command=self.prepare_drag)
        self.drag_button.pack(side='left', padx=4)
        self.drag_button.drag_source_register(1, 'DND_Files')
        self.drag_button.dnd_bind('<<DragInitCmd>>', self.drag_start)
        self.drag_button.dnd_bind('<<DragEndCmd>>',self.drag_end)
        clientrow = ttk.Frame(bottom); clientrow.pack(fill='x', pady=8)
        ttk.Button(clientrow, text='转移到 QQ', command=lambda: self.transfer('qq')).pack(side='left')
        ttk.Button(clientrow, text='转移到微信', command=lambda: self.transfer('wechat')).pack(side='left', padx=6)
        ttk.Button(clientrow, text='查看互通结果', command=self.resume_transfer).pack(side='left', padx=6)
        ttk.Button(clientrow, text='编辑 / 新建作品', command=self.open_editor,style='Editor.Primary.TButton').pack(side='left', padx=6)
        if add_selected:ttk.Button(clientrow,text='添加到当前作品',command=self.add_to_editor).pack(side='left')
        ttk.Button(clientrow, text='取消导入 / 导出', command=self.stop).pack(side='right')
        ttk.Button(clientrow, text='查看详情', command=self.show_details).pack(side='right', padx=6)
        self.status = tk.StringVar(value='导入图片开始使用；支持 PNG、JPEG、GIF、APNG、WebP。')
        ttk.Label(bottom, textvariable=self.status, wraplength=1040).pack(anchor='w', pady=4)
        self.selection_label = tk.StringVar(value='已选 0 张')
        nav = ttk.Frame(root, padding=(22, 6)); nav.pack(side='bottom', fill='x')
        ttk.Label(nav, textvariable=self.selection_label, foreground=MUTED).pack(side='left')
        ttk.Button(nav, text='上一页', command=lambda: self.turn(-1)).pack(side='right')
        self.page_label = ttk.Label(nav); self.page_label.pack(side='right', padx=10)
        ttk.Button(nav, text='下一页', command=lambda: self.turn(1)).pack(side='right')
        area = ttk.Frame(root, padding=(22, 0)); area.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(area, bg=BG, highlightthickness=0)
        from ui_scroll import OverlayScrollbar
        self.scroll=OverlayScrollbar(self.canvas)
        self.canvas.pack(fill='both', expand=True)
        self.grid = ttk.Frame(self.canvas); self.window_id = self.canvas.create_window(0, 0, window=self.grid, anchor='nw')
        self.canvas.bind('<Configure>', self.resize)
        self.grid.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.drop_target_register('DND_Files'); self.canvas.dnd_bind('<<Drop>>', self.drop)
        self.root.drop_target_register('DND_Files'); self.root.dnd_bind('<<Drop>>', self.drop)
        root.bind('<Control-v>', self.paste_key)
        root.bind('<MouseWheel>', lambda e: self.canvas.yview_scroll(-int(e.delta / 120), 'units'))
        self.poll_id = root.after(60, self.poll)
        self.reload()

    def resize(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)
        cols = max(3, event.width // 188)
        for n, frame in enumerate(self.cards.values()):
            frame.grid(row=n // cols, column=n % cols, sticky='nsew', padx=4, pady=5)
        for n in range(cols):
            self.grid.columnconfigure(n, weight=1)

    def search(self):
        self.page = 0; self.selected.clear();self.reload()

    def turn(self, delta):
        value = self.page + delta
        if 0 <= value < max(1, (self.total + PAGE_SIZE - 1) // PAGE_SIZE):
            self.page = value; self.reload()

    def reload(self,preserve_scroll=False):
        if not getattr(self,'view_active',True):
            self.pending_reload=True;return
        self.pending_reload=False
        if self.pointer_down or self.native_drag:
            self.deferred_reload=preserve_scroll;return
        scroll=(self.pending_scroll[1] if self.pending_scroll else self.canvas.yview()[0]) if preserve_scroll else 0
        if self.populate_after:self.root.after_cancel(self.populate_after);self.populate_after=None
        self.generation += 1; generation = self.generation
        self.pending_scroll=(generation,scroll)
        for future in self.thumb_futures:
            future.cancel()
        self.thumb_futures.clear()
        options=self.search_options();offset=self.page*PAGE_SIZE
        store=self.store;events=self.events
        def query():
            try:
                items,total=store.search(offset=offset,limit=PAGE_SIZE,**options)
                events.put(('query',generation,items,total,store.categories(),scroll))
            except Exception as exc:events.put(('query_error',generation,str(exc)))
        self.thumb_futures.append(self.pool.submit(query))

    def search_options(self):
        return dict(text=self.query.get(),category='' if self.category.get()=='全部分类' else self.category.get(),**self.filters.values())

    def populate(self,generation,items,total,categories,scroll=0):
        if self.pointer_down or self.native_drag:
            self.deferred_query=(generation,items,total,categories,scroll);return
        self.items=items;self.total=total
        if self.page and self.page*PAGE_SIZE>=total:self.page=max(0,(total-1)//PAGE_SIZE);self.reload();return
        self.category_box['values']=['全部分类',*categories]
        for child in self.grid.winfo_children():
            child.destroy()
        self.cards.clear(); self.photos.clear();self.thumbnail_labels={};self.thumbnails_loaded=set();events=self.events
        self.page_label.configure(text=f'{self.page+1} / {max(1, (self.total+PAGE_SIZE-1)//PAGE_SIZE)} 页 · 共 {self.total} 张')
        self.selection_label.set(f'已选 {len(self.selected)} 张')
        if not items:
            ttk.Label(self.grid, text='这里还没有素材。导入图片，或换一个搜索条件。', padding=40).grid()
        self.populate_batch(generation,items,0,scroll)

    def populate_batch(self,generation,items,offset,scroll):
        self.populate_after=None
        if self.closed or generation!=self.generation:return
        events=self.events
        for item in items[offset:offset+4]:
            ident = item['id']; frame = ttk.Frame(self.grid, width=196,height=238,padding=8, relief='solid', borderwidth=1)
            # Fixed thumbnail slots keep scroll geometry stable as images arrive.
            frame.pack_propagate(False)
            self.cards[ident] = frame
            variable = tk.BooleanVar(value=ident in self.selected)
            check = ttk.Checkbutton(frame, text=item['name'][:18], variable=variable,
                                    command=lambda i=ident, v=variable: self.select(i, v.get()))
            check.pack(anchor='w')
            label = ttk.Label(frame, text='加载预览…', anchor='center', width=21)
            self.thumbnail_labels[ident]=label
            label.pack(fill='both', expand=True, pady=6)
            label.bind('<Double-Button-1>', lambda e, i=item: self.open_preview(i))
            label.bind('<Button-1>', lambda e, i=ident, v=variable: (v.set(True), self.select(i, True)))
            label.bind('<ButtonPress-1>',lambda e:setattr(self,'pointer_down',True),add='+')
            label.bind('<ButtonRelease-1>',self.pointer_release,add='+')
            label.bind('<Enter>',lambda e,i=ident:self.prepare_drag([i]))
            label.drag_source_register(1,'DND_Files')
            label.dnd_bind('<<DragInitCmd>>',lambda e,i=ident:self.drag_start(e,[i] if i not in self.selected else None))
            label.dnd_bind('<<DragEndCmd>>',lambda e:self.drag_end(e))
            for widget in (frame, label, check):
                widget.drop_target_register('DND_Files'); widget.dnd_bind('<<Drop>>', self.drop)
            meta = item['metadata']
            ttk.Label(frame, text=f"{meta['format']} · {meta['oriented_size'][0]} × {meta['oriented_size'][1]}" + (' · 动图' if meta['frames'] > 1 else ''), foreground=SUCCESS).pack(anchor='w')
            ttk.Label(frame,text=('★ ' if item['favorite'] else '')+(' · '.join([*item['collections'],*item['tags']]))[:24] or '未分类',foreground=MUTED).pack(anchor='w')
            def work(i=item):
                try:
                    image = thumbnail(i['thumbnail'])
                    events.put(('thumb', generation, i['id'], image))
                except Exception:
                    events.put(('thumb', generation, i['id'], None))
            self.thumb_futures.append(self.pool.submit(work))
        self.resize(type('Event', (), {'width': self.canvas.winfo_width()})())
        if offset+4<len(items):self.populate_after=self.root.after(10,lambda:self.populate_batch(generation,items,offset+4,scroll))
        else:self.populate_after=self.root.after_idle(lambda:self.restore_view(generation,scroll))

    def restore_view(self,generation,scroll):
        self.populate_after=None
        if not self.closed and generation==self.generation and len(self.thumbnails_loaded)==len(self.items):
            self.canvas.yview_moveto(scroll);self.pending_scroll=None

    def select(self, ident, selected):
        if selected:
            self.selected.add(ident)
        else:
            self.selected.discard(ident)
        self.drag_files = (); self.selection_label.set(f'已选 {len(self.selected)} 张')
        if selected:self.prepare_drag()

    def select_page(self):
        self.selected.update(i['id'] for i in self.items); self.reload(preserve_scroll=True);self.prepare_drag()

    def select_all(self):
        options=self.search_options()
        def work():return {'text':'已选择当前条件下全部匹配项；整理前可清空重新选择。','select_all':self.store.matching_ids(**options),'filter':options}
        self.start(work)

    def clear_selection(self):
        self.selected.clear(); self.reload()

    def selected_ids(self):
        # Page order first, then stable IDs from earlier pages.
        visible = [i['id'] for i in self.items if i['id'] in self.selected]
        return visible + sorted(self.selected.difference(visible))

    def start(self, work):
        if self.busy:
            self.status.set('当前导入 / 导出尚未结束；可继续浏览，或先取消。'); return False
        self.busy = True; self.cancel.clear()
        def task():
            try:
                result = work()
                self.events.put(('done', result))
            except Exception as exc:
                self.events.put(('error', error_text(exc)))
        threading.Thread(target=task, daemon=True, name='material-io').start()
        return True

    def choose_files(self):
        files = filedialog.askopenfilenames(parent=self.root, title='导入图片 / 视频，原文件保持不变', filetypes=[('图片 / 视频', '*.png *.jpg *.jpeg *.gif *.webp *.mp4 *.mov *.mkv *.avi *.webm *.m4v'), ('全部文件', '*.*')])
        if files:
            self.import_paths(files)

    def import_paths(self, paths, kind='file'):
        paths = tuple(paths)
        if self.open_video:
            from video_tools import VIDEO_EXTENSIONS
            videos=[p for p in paths if Path(p).suffix.lower() in VIDEO_EXTENSIONS]
            if videos:
                self.open_video(videos)
                paths=tuple(p for p in paths if p not in videos)
                if not paths:return True
        def work():
            added = duplicates = 0; errors = []
            for n, path in enumerate(paths):
                if self.cancel.is_set():
                    break
                try:
                    _, duplicate = self.store.import_file(path, kind=kind, cancel=self.cancel)
                    duplicates += int(duplicate); added += int(not duplicate)
                except (InterruptedError,CancelledError):
                    break
                except Exception as exc:
                    errors.append(f'{Path(path).name}：{error_text(exc)}')
                self.events.put(('progress', f'导入 {n+1}/{len(paths)} · 新增 {added} · 重复 {duplicates}'))
            return {'text': f'{"已取消；" if self.cancel.is_set() else ""}导入结束：新增 {added}，重复 {duplicates}，失败 {len(errors)}。原件已保存在素材库。', 'details': '\n'.join(errors)}
        return self.start(work)

    def drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        return 'copy' if self.import_paths(paths, 'drop') else 'refuse_drop'

    def paste_key(self, event):
        if isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox)):
            return
        self.paste(); return 'break'

    def paste(self):
        if self.busy:
            self.status.set('请等当前导入完成后再粘贴。'); return
        try:
            value = ImageGrab.grabclipboard()
            if isinstance(value, list):
                self.import_paths(value, 'clipboard_files')
            elif isinstance(value, Image.Image):
                def work():
                    _, duplicate = self.store.import_bitmap(value, self.cancel)
                    return {'text': ('重复，未新增副本。' if duplicate else '已保存。') + '剪贴板仅提供静态图像，按 PNG 保存；不代表原 GIF。'}
                self.start(work)
            else:
                self.status.set('剪贴板没有图片或图片文件。可以复制文件后粘贴，GIF 请复制原文件。')
        except Exception as exc:
            self.status.set('剪贴板暂不可读：' + str(exc))

    def open_preview(self, item):
        if self.preview:
            self.preview.close()
        self.preview = Preview(self.root, item)

    def add_to_editor(self):
        ids=self.selected_ids()
        if ids and self.add_selected:self.add_selected(ids)
        elif not ids:self.status.set('先勾选要添加的素材。')

    def open_editor(self):
        ids = self.selected_ids()
        if not ids:
            self.status.set('单选一张进入编辑，多选进入拼图。'); return
        if self.edit_selected:
            self.edit_selected(ids);return
        if self.editor and not self.editor.closed:
            self.editor.window.lift(); return
        from material_editor_ui import EditorWindow
        def saved(item):
            self.selected = {item['id']}; self.page = 0; self.query.set(''); self.category.set('全部分类')
            self.reload(); self.status.set('作品已另存回素材库，原素材保留；可预览、导出或添加收藏。')
        self.editor = EditorWindow(self.root, self.store, ids, on_saved=saved)

    def edit(self):
        ids = self.selected_ids()
        if not ids:
            self.status.set('先勾选要管理的素材。'); return
        from material_organizer_ui import organize
        organize(self.root,self.store,ids,lambda:self.reload(preserve_scroll=True),submit=self.start);return

    def export(self):
        ids = self.selected_ids()
        if not ids:
            self.status.set('先勾选要导出的素材。'); return
        destination = filedialog.askdirectory(parent=self.root, title='导出原文件到文件夹')
        if destination:
            def work():
                files = self.store.export(ids, destination, self.cancel)
                return {'text': f'{"已取消；" if self.cancel.is_set() else ""}已导出 {len(files)} / {len(ids)} 个原文件；没有加入客户端收藏。'}
            self.start(work)

    def compatibility_copy(self):
        if self.busy:return
        from compatibility_dialog import configure,generate
        ids=self.selected_ids();choice=configure(self.root,self.store,bool(ids))
        if not choice:return
        self.status.set('正在后台生成兼容副本，可取消；原件不变。')
        def work():
            detail=generate(self.store,choice,ids=ids,cancel=self.cancel,
                progress=lambda n,total,phase:self.events.put(('progress',f'{phase} {n}/{total}')))
            return {'text':detail,'details':detail}
        self.start(work)

    def prepare_drag(self,ids=None):
        ids = ids or self.selected_ids()
        if not ids:
            self.status.set('先勾选素材，再点击“拖出所选”准备。'); return
        missing=[i for i in ids if not self.drag_valid(i) and i not in self.drag_pending]
        if not missing:
            self.drag_files=tuple(str(self.drag_cache[i][0]) for i in self.selected_ids() if self.drag_valid(i));return
        self.drag_pending.update(missing)
        store=self.store;events=self.events;stop=self.drag_stop
        def work():
            for ident in missing:
                if stop.is_set():return
                try:
                    files=store.export([ident],store.root/'drag-out',stop)
                    if not files:return
                    file=files[0];stat=file.stat();events.put(('drag_ready',ident,file,(stat.st_size,stat.st_mtime_ns)))
                except Exception as exc:events.put(('drag_error',ident,str(exc)))
        self.pool.submit(work)

    def drag_valid(self,ident):
        value=self.drag_cache.get(ident)
        if not value:return False
        try:stat=value[0].stat();return (stat.st_size,stat.st_mtime_ns)==value[1]
        except OSError:return False

    def drag_start(self, event, ids=None):
        ids=ids or self.selected_ids()
        if not ids or not all(self.drag_valid(i) for i in ids):
            self.prepare_drag(ids);self.status.set('原件正在后台准备拖出，请稍候再拖；不必先添加客户端收藏。')
            return ('refuse_drop', 'DND_Files', ())
        # Export copies only. The shell can never move/delete the library originals.
        self.dragging_ids=list(ids);self.drag_files=tuple(str(self.drag_cache[i][0]) for i in ids)
        self.native_drag=True
        return ('copy', 'DND_Files', self.drag_files)

    def drag_end(self,event):
        self.native_drag=False;self.pointer_release()
        if getattr(event,'action','')=='copy':self.store.mark_used(getattr(self,'dragging_ids',[]))
        self.status.set('拖放结束，原件保留；接收、发送和收藏需分别确认。')

    def pointer_release(self,event=None):
        self.pointer_down=False
        if self.native_drag:return
        # Apply the latest pending refresh after OLE releases the source widget.
        if self.deferred_reload is not None:
            preserve=self.deferred_reload;self.deferred_reload=None;self.deferred_query=None
            self.root.after_idle(lambda:self.reload(preserve_scroll=preserve))
        elif self.deferred_query:
            value=self.deferred_query;self.deferred_query=None
            self.root.after_idle(lambda:self.populate(*value) if value[0]==self.generation else None)

    def transfer(self, target):
        ids = self.selected_ids()
        if not ids:
            self.status.set('先勾选要添加的素材。'); return
        if self.can_transfer and not self.can_transfer():
            self.status.set('已有互通准备或任务运行中，请等待或取消后再添加；本次尚未创建任务。');return
        if self.transfer_process and self.transfer_process.poll() is None:
            self.status.set('素材搬运窗口仍在运行，请在该窗口查看或取消任务。'); return
        from material_transfer import create
        plan = self.store.root / 'tasks' / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6] + '.json')
        create(self.store, ids, target, plan)
        save_json(self.store.root / 'last-task.json', {'plan': str(plan)})
        self.launch_transfer(plan, autostart=True)

    def launch_transfer(self, plan, autostart=False):
        if self.launch_plan:
            self.launch_plan(plan, autostart=autostart);return
        command=[sys.executable, '-X', 'utf8', str(APP / 'scripts/material_transfer_ui.py'), str(plan)]
        if autostart:command.append('--start')
        self.transfer_process = subprocess.Popen(command, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.status.set('任务已启动；首次需确认账号，随后自动继续。浏览素材库无需客户端。' if autostart else '已打开历史结果，未自动重发。')

    def resume_transfer(self):
        if self.transfer_process and self.transfer_process.poll() is None:
            self.status.set('请在已打开的素材搬运窗口继续或取消。'); return
        try:
            self.launch_transfer(Path(json.loads((self.store.root / 'last-task.json').read_text(encoding='utf-8'))['plan']))
        except (OSError, ValueError, KeyError):
            self.status.set('没有可恢复的素材任务。')

    def open_bridge(self):
        if self.navigate:
            self.navigate('bridge');return
        subprocess.Popen([sys.executable, '-X', 'utf8', str(APP / 'scripts/pilot_launcher.py'), '--bridge'], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def stop(self):
        self.cancel.set(); self.status.set('正在停止；已导入 / 导出的文件保留。客户端任务请在搬运窗口取消。')

    def show_details(self):
        messagebox.showinfo('素材库详情', self.details or ('原件位置：' + str(self.store.root) + '\nGIF 仅在放大预览窗口播放。导出不代表收藏成功。'), parent=self.root)

    def poll(self):
        if self.closed:
            return
        deadline=time.perf_counter()+.012
        for _ in range(100):
            if time.perf_counter()>deadline:break
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event[0] == 'thumb':
                _, generation, ident, frame = event;label=self.thumbnail_labels.get(ident)
                if generation == self.generation and label and label.winfo_exists():
                    if frame is None:
                        label.configure(text='预览不可用')
                    else:
                        photo = ImageTk.PhotoImage(frame); self.photos[ident] = photo
                        label.configure(image=photo, text='')
                    self.thumbnails_loaded.add(ident)
                    if self.pending_scroll and len(self.thumbnails_loaded)==len(self.items):
                        if self.populate_after:self.root.after_cancel(self.populate_after)
                        _,scroll=self.pending_scroll
                        self.populate_after=self.root.after_idle(lambda g=generation,s=scroll:self.restore_view(g,s))
            elif event[0]=='query':
                if not getattr(self,'view_active',True):self.pending_reload=True
                elif event[1]==self.generation:self.populate(*event[1:])
            elif event[0]=='query_error':
                if event[1]==self.generation:self.status.set(event[2])
            elif event[0]=='drag_ready':
                _,ident,path,stat=event;self.drag_pending.discard(ident);self.drag_cache[ident]=(path,stat)
                if self.selected and self.selected<=self.drag_cache.keys():
                    self.drag_files=tuple(str(self.drag_cache[i][0]) for i in self.selected_ids());self.drag_button.configure(text=f'拖出所选（{len(self.drag_files)}）')
            elif event[0]=='drag_error':
                self.drag_pending.discard(event[1]);self.status.set('拖出未就绪：'+event[2])
            elif event[0] == 'progress':
                self.status.set(event[1])
            elif event[0] == 'error':
                self.busy = False; self.details = event[1]; self.status.set('操作未完成：' + event[1]); self.reload()
            elif event[0] == 'done':
                self.busy = False; result = event[1]; self.status.set(result['text']); self.details = result.get('details', '')
                if 'select_all' in result and result['filter']==self.search_options():self.selected=set(result['select_all'])
                self.reload(preserve_scroll=True)
        if time.monotonic()-self.last_watch>.9:
            self.last_watch=time.monotonic();revision=self.store.revision()
            if revision is not None and revision!=self.last_revision:
                self.last_revision=revision;self.reload(preserve_scroll=True)
        self.poll_id = self.root.after(60, self.poll)

    def close(self):
        if self.closed:return
        if self.editor and not self.editor.closed and not self.editor.close():
            return
        self.closed = True
        self.cancel.set()
        self.drag_stop.set()
        if self.populate_after:self.root.after_cancel(self.populate_after);self.populate_after=None
        self.root.after_cancel(self.poll_id)
        if self.preview:
            self.preview.close()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--library-dir', type=Path)
    args = parser.parse_args(); store = MaterialStore(args.library_dir or default_root())
    root = create_root()
    try:
        with single_instance(store.root / 'library-ui.lock'):
            from desktop_shell import DesktopShell
            app = DesktopShell(root, store); root.mainloop()
    except RuntimeError as exc:
        messagebox.showinfo('素材库', '素材库已打开，请切回已有窗口。\n' + str(exc), parent=root); root.destroy()


if __name__ == '__main__':
    main()
