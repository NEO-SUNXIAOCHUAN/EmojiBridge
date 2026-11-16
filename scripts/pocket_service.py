"""Secondary native windows over the desktop's existing MaterialStore."""
from pathlib import Path
import json, threading, time
from emoji_bridge.desktop_stickers import StickerManager
from concurrent.futures import Future

def on_window(window, action):
    """WinForms property setters must run on its owning UI thread."""
    if not window.native.InvokeRequired:return action()
    from System import Action
    result=Future()
    def invoke():
        try:result.set_result(action())
        except Exception as exc:result.set_exception(exc)
    window.native.BeginInvoke(Action(invoke))
    return result.result(timeout=5)


class PocketService:
    def __init__(self, owner):
        self.owner=owner;self.window=None;self.edge=None
        from pocket_tools import PocketTools
        self.tools=PocketTools(self)
        self.stickers=StickerManager(on_context=self.tools.actions)
        self.hidden_by=set();self.restore=[];self.opening=threading.Lock();self.closed=False;self.owners={}
        self.dragging=False;self.visible_requested=False;self.position=self.owner.store.root/'pocket-position.json'
        self.session=0;self.temporary=False;self.pinned=True;self.copy_guard=threading.Lock()
        threading.Thread(target=self._watch_owners,daemon=True,name='overlay-owners').start()

    def _watch_owners(self):
        from emoji_bridge.overlay_guard import process_alive
        while not self.closed:
            time.sleep(.5)
            for token,pid in list(self.owners.items()):
                if not process_alive(pid):self.suspend(token,False)

    def open(self, edge=False, temporary=False):
        import webview
        from webview.dom import DOMEventHandler
        self.visible_requested=True
        self.session+=1;self.temporary=bool(temporary)
        with self.opening:
            # Legacy callers resolve to the SAME collector, never a second port.
            edge=False;field='window';window=self.window
            if window:
                if self.hidden_by:
                    if window not in self.restore:self.restore.append(window)
                elif window.native:self.show(window)
                return True
            import ctypes
            previous_foreground=ctypes.windll.user32.GetForegroundWindow()
            api=PocketAPI(self,edge)
            window=webview.create_window('EmojiBridge · 收纳口' if edge else 'EmojiBridge · 随手素材',
                self.owner.url+('/edge.html' if edge else '/pocket.html'),js_api=api,
                width=144 if edge else 400,height=82 if edge else 582,
                min_size=(144,82) if edge else (320,58),frameless=True,easy_drag=False,
                on_top=True,focus=False,background_color='#111318',text_select=False,hidden=bool(self.hidden_by))
            api._window=window;setattr(self,field,window)
            if self.hidden_by:self.restore.append(window)
            def ready():
                if self.closed or self.window is not window:return
                def drop(event):
                    if self.dragging:return  # Internal original-file OLE drag.
                    from media_drop import receive
                    receive(self.owner,window,event,api.notice)
                window.dom.document.events.dragover+=DOMEventHandler(lambda e:None,True,True,debounce=100)
                window.dom.document.events.drop+=DOMEventHandler(drop,True,True)
                # A small tool window stays out of the taskbar; the main app is
                # still the taskbar drop activation target.
                from System import Action
                def size():
                    from System.Drawing import Region,RectangleF
                    from System.Drawing.Drawing2D import GraphicsPath
                    window.native.ShowInTaskbar=False
                    from System.Drawing import Icon
                    window.native.Icon=Icon(str(Path(__file__).resolve().parents[1]/'assets/branding/EmojiBridge.ico'))
                    def rounded(*unused):
                        diameter=round((16 if edge else 20)*2*window.native.DeviceDpi/96)
                        width,height=window.native.Width,window.native.Height
                        diameter=min(diameter,width,height)
                        path=GraphicsPath()
                        for x,y,angle in ((0,0,180),(width-diameter,0,270),(width-diameter,height-diameter,0),(0,height-diameter,90)):
                            path.AddArc(RectangleF(x,y,diameter,diameter),angle,90)
                        path.CloseFigure();old=window.native.Region;window.native.Region=Region(path);path.Dispose()
                        if old:old.Dispose()
                    window.native.SizeChanged+=rounded
                    window.resize(144 if edge else 400,82 if edge else 582)
                    rounded()
                on_window(window,size)
                try:
                    position=json.loads(self.position.read_text('utf8'))
                    window.move(int(position['x']),int(position['y']))
                except (OSError,ValueError,KeyError,TypeError):pass
                if self.visible_requested:self.show(window)
                else:on_window(window,lambda:window.native.Hide())
                # WinForms/WebView2 focuses its browser on the first Shown,
                # including focus=False tool windows. Restore only the window
                # that was active before THIS creation, and only if our new
                # tool window still owns focus. Never fight a user switch.
                def restore_source():
                    user=ctypes.windll.user32;handle=int(window.native.Handle.ToInt64())
                    if previous_foreground and user.IsWindow(ctypes.c_void_p(previous_foreground)) and user.GetForegroundWindow()==handle:
                        user.SetForegroundWindow(ctypes.c_void_p(previous_foreground))
                on_window(window,restore_source)
                if edge:
                    from System.Windows.Forms import Screen
                    area=Screen.FromControl(window.native).WorkingArea
                    window.move(area.Right-window.width-12,area.Top+max(20,(area.Height-window.height)//2))
            def closing():
                if not self.closed:self.hide();return False
                on_window(window,lambda:setattr(window,'on_top',False))
            def closed():
                if getattr(self,field) is window:setattr(self,field,None)
            window.events.loaded+=ready;window.events.closing+=closing;window.events.closed+=closed
            return True

    def show(self,window):
        def show():
            from System.Windows.Forms import Screen
            area=Screen.FromControl(window.native).WorkingArea
            native=window.native
            native.Left=max(area.Left,min(native.Left,area.Right-native.Width))
            native.Top=max(area.Top,min(native.Top,area.Bottom-native.Height))
            if self.visible_requested and not self.hidden_by:
                window.on_top=self.pinned
                import ctypes
                ctypes.windll.user32.ShowWindow(ctypes.c_void_p(int(native.Handle.ToInt64())),4)
        on_window(window,show)

    def hide(self):
        import ctypes
        if self.dragging or ctypes.windll.user32.GetAsyncKeyState(1)&0x8000:return {'hidden':False,'reason':'正在拖放，结束后可收起'}
        self.visible_requested=False
        window=self.window
        if window and window.native:
            position={}
            def hide():
                position.update(x=window.x,y=window.y)
                window.native.Hide()
            on_window(window,hide)
            # Bridge/hotkey worker persists after hiding, outside WinForms' loop.
            if position:
                from emoji_bridge.state import save_json
                save_json(self.position,position)
        self.restore=[w for w in self.restore if w is not window]
        return {'hidden':True}

    def toggle(self):
        if self.dragging:return False
        if self.visible_requested:return self.hide()
        return self.open(temporary=True)

    def suspend(self, token, value, pid=None):
        """Acknowledged before foreground automation; nested owners restore last."""
        if value:
            if token in self.hidden_by:return {'hidden':True}
            first=not self.hidden_by;self.hidden_by.add(token)
            if pid:self.owners[token]=int(pid)
            if first:
                for token in list(self.tools.windows):self.tools.dismiss(token)
                self.restore=[]
                for window in (self.window,self.edge):
                    if window and window.native and window.native.Visible:
                        self.restore.append(window);on_window(window,window.native.Hide)
                self.stickers.suspend(True)
        else:
            self.hidden_by.discard(token)
            self.owners.pop(token,None)
            if not self.hidden_by:
                self.stickers.suspend(False)
                for window in self.restore:
                    if window in (self.window,self.edge) and self.visible_requested:
                        # Restore without activating a keyboard target.
                        import ctypes
                        ctypes.windll.user32.ShowWindow(ctypes.c_void_p(int(window.native.Handle.ToInt64())),4)
                self.restore=[]
        return {'hidden':bool(self.hidden_by)}

    def close(self):
        if self.closed:return
        self.closed=True
        self.tools.close()
        for window in (self.window,self.edge):
            if window:
                on_window(window,lambda:setattr(window,'on_top',False));window.destroy()
        self.stickers.shutdown()
        self.tools.cleanup()


class PocketAPI:
    def __init__(self, service, edge=False):
        self._service=service;self._window=None;self._edge=edge

    def listing(self, query='', view='all', limit=80, revision=None):
        store=self._service.owner.store;current=store.revision()
        if current is not None and revision==current:return {'unchanged':True,'revision':current}
        rows,total=store.search(query,limit=24 if view=='recent' else max(40,min(100000,int(limit))),view='favorite' if view=='favorite' else '')
        if view=='recent':total=min(total,24)
        return {'revision':current,'total':total,'items':[dict(id=r['id'],name=r['name'],
            src=f'{self._service.owner.url}/{self._service.owner.token}/thumbnail/{r["id"]}',
            format='GIF' if r['metadata'].get('frames',1)>1 else r['metadata'].get('format','图片'),
            favorite=r['favorite'],addedAt=r['created'],tags=r['tags']) for r in rows]}

    def state(self):
        prefs=self._service.owner.preferences()
        return dict(task=dict(self._service.owner.task),revision=self._service.owner.store.revision(),
                    reduced_motion=bool(prefs.get('reduce_motion')),always_scrollbars=bool(prefs.get('always_scrollbars')),
                    pinned=self._service.pinned,session=self._service.session,hidden=bool(self._service.hidden_by),sticker_error=str(self._service.stickers._error or ''))

    def drawing(self, tool):return self._service.tools.draw(tool)
    def toolsState(self):return dict(self._service.tools.job)
    def cancelCutout(self):self._service.tools.cancel.set();return True
    def cutoutItem(self,item):
        row=self._service.owner.store.get(item['id'])
        return self._service.tools.cutout(row['path'])

    def setFavorite(self, ident, value):
        self._service.owner.store.organize([ident],favorite=bool(value));return {'ok':True}

    def chooseImport(self):
        import webview
        files=self._window.create_file_dialog(webview.FileDialog.OPEN,allow_multiple=True,
            file_types=('图片与媒体 (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.apng;*.mp4;*.mov;*.mkv;*.webm)',))
        return self._service.owner.import_paths(list(files),'file') if files else None

    def paste(self):return self._service.owner.paste()
    def drop_begin(self,files):return self._service.owner.drop_begin(files)
    def drop_chunk(self,token,index,offset,encoded):return self._service.owner.drop_chunk(token,index,offset,encoded)
    def drop_finish(self,token,index,error=''):return self._service.owner.drop_finish(token,index,error)
    def drop_notice(self,text):return self.notice(text)
    def cancel(self):return self._service.owner.cancel_task()
    def openEdge(self):return self._service.open(True)
    def hideAllStickers(self):return self._service.stickers.close_all()
    def recoverStickers(self):return self._service.stickers.recover_all()
    def adjustStickers(self):return self._service.stickers.adjust_all()
    def hide(self):return self._service.hide()

    def openSticker(self, item):
        row=self._service.owner.store.get(item['id'])
        result=self._service.stickers.show(row['path'],row['id'])
        self._service.owner.store.mark_used([row['id']]);return result

    def copyItem(self,item):
        from emoji_bridge.file_clipboard import copy_media_to_clipboard
        service=self._service
        if not service.copy_guard.acquire(blocking=False):raise ValueError('正在复制，请稍候')
        try:
            files=service.owner.drag_files([item['id']])
            result=copy_media_to_clipboard(Path(files[0]),int(self._window.native.Handle.ToInt64()))
            service.owner.store.mark_used([item['id']])
            return result
        finally:service.copy_guard.release()

    def dragItem(self,item):
        result=self._service.owner.drag([item['id']],self._window)
        if not result:raise ValueError('当前正在处理素材，请完成或取消后再拖出原件。')
        return result
    def prepareItem(self,item):return bool(self._service.owner.drag_files([item['id']]))

    def setPinned(self,value):
        self._service.pinned=bool(value)
        on_window(self._window,lambda:setattr(self._window,'on_top',bool(value)))
        return {'ok':True,'pinned':bool(value)}

    def setCollapsed(self,value):
        def change():
            from System.Drawing import Size
            scale=self._window.native.DeviceDpi/96
            self._window.native.MinimumSize=Size(round((224 if value else 320)*scale),round(58*scale))
            self._window.resize(224 if value else 400,58 if value else 582)
        on_window(self._window,change)
        return {'ok':True,'collapsed':bool(value)}

    def close(self):
        return self._service.hide()

    def notice(self,text):
        if self._window:self._window.evaluate_js('window.pocketNotice?.('+json.dumps(text)+')')
