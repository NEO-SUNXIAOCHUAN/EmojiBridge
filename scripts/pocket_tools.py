"""Desktop annotations and cutouts are temporary overlays, never library imports."""
from pathlib import Path
from io import BytesIO
import base64, json, math, tempfile, threading, uuid
from PIL import Image
from pocket_service import on_window


class PocketTools:
    def __init__(self, pocket):
        self.pocket=pocket;self.owner=pocket.owner
        self.temp=tempfile.TemporaryDirectory(prefix='EmojiBridge-stickers-')
        self.root=Path(self.temp.name);self.windows={};self.contexts={}
        self.guard=threading.RLock();self.worker=None;self.cancel=threading.Event()
        self.job={'active':False,'text':''};self.closed=False;self.surfaces={}

    def _window(self, mode, context, bounds):
        import webview
        token=uuid.uuid4().hex;api=ToolAPI(self,token)
        self.contexts[token]=dict(context,mode=mode)
        window=webview.create_window('EmojiBridge · 桌面绘制' if mode=='draw' else 'EmojiBridge · 贴图工具',
            self.owner.url+'/overlay.html',js_api=api,width=300,height=120,min_size=(100,50),
            frameless=True,easy_drag=False,on_top=True,focus=mode=='draw',hidden=True,
            background_color='#111318',text_select=False)
        self.windows[token]=window
        def ready():
            if self.closed:return
            def place():
                from System.Drawing import Rectangle,Region,RectangleF
                from System.Drawing.Drawing2D import GraphicsPath
                window.native.ShowInTaskbar=False
                window.native.SetBounds(*bounds)
                if mode=='draw':
                    empty=Region();empty.MakeEmpty();window.native.Region=empty
                if mode!='draw':
                    width,height=window.native.ClientSize.Width,window.native.ClientSize.Height
                    d=round(24*window.native.DeviceDpi/96);p=GraphicsPath()
                    for x,y,a in ((0,0,180),(width-d,0,270),(width-d,height-d,0),(0,height-d,90)):
                        p.AddArc(RectangleF(x,y,d,d),a,90)
                    p.CloseFigure();window.native.Region=Region(p);p.Dispose()
                window.native.Show()
                if mode=='draw':window.native.Activate()
            on_window(window,place)
            if mode=='draw':
                from drawing_surface import DrawingSurface
                with self.guard:
                    if not self.closed and token in self.contexts:self.surfaces[token]=DrawingSurface(window,bounds)
        window.events.loaded+=ready
        window.events.closed+=lambda:self._forget(token)
        return {'opened':True,'token':token}

    def _forget(self, token):
        surface=self.surfaces.pop(token,None)
        if surface:surface.shutdown()
        self.windows.pop(token,None);context=self.contexts.pop(token,{})
        if context.get('mode')=='draw' and not self.closed and self.pocket.visible_requested:
            self.pocket.show(self.pocket.window)

    def dismiss(self, token):
        window=self.windows.get(token)
        if window:window.destroy()
        return True

    def draw(self, tool):
        if tool not in ('shape','arrow','text','pen'):raise ValueError('未知绘制工具')
        with self.guard:
            if self.closed or self.pocket.hidden_by:raise ValueError('当前正在互通，请完成后再绘制')
            if any(c['mode']=='draw' for c in self.contexts.values()):raise ValueError('桌面绘制已打开，请先完成或取消')
            window=self.pocket.window
            def area():
                from System.Windows.Forms import Screen
                a=Screen.FromControl(window.native).WorkingArea
                window.native.Hide()
                return (a.Left,a.Top,a.Width,a.Height)
            bounds=on_window(window,area)
            try:
                x,y,width,height=bounds
                if width*height>32_000_000:raise ValueError('当前屏幕尺寸过大，请在较小的显示器上绘制')
                return self._window('draw',{'tool':tool,'width':width,'height':height,'origin':[x,y]},bounds)
            except Exception:
                if self.pocket.visible_requested:self.pocket.show(window)
                raise

    def finish(self, token, encoded):
        with self.guard:
            context=self.contexts.get(token)
            if not context or context['mode']!='draw':raise ValueError('绘制窗口已关闭')
            if context.get('saving'):raise ValueError('正在生成贴图')
            context['saving']=True
        try:
            if not isinstance(encoded,str) or not encoded.startswith('data:image/png;base64,') or len(encoded)>48*1024*1024:
                raise ValueError('绘图结果过大或格式无效')
            raw=base64.b64decode(encoded.split(',',1)[1],validate=True)
            with Image.open(BytesIO(raw)) as source:
                if source.size!=(context['width'],context['height']):raise ValueError('绘制尺寸已变化，请重新绘制')
                image=source.convert('RGBA')
            box=image.getchannel('A').getbbox()
            if box is None:raise ValueError('先画一点内容，再点完成')
            path=self.root/(uuid.uuid4().hex+'.png');image.crop(box).save(path)
            origin=context['origin']
            result=self.pocket.stickers.show(path,placement=(origin[0]+box[0],origin[1]+box[1]))
            self.dismiss(token)
            return dict(result,temporary=True)
        finally:context.pop('saving',None)

    def actions(self, handle):
        try:
            with self.guard:
                if self.closed or self.pocket.hidden_by:return
                state=self.pocket.stickers.inspect(handle)
                if not state:return
                for token,context in list(self.contexts.items()):
                    if context['mode']=='sticker':self.dismiss(token)
                # Native coordinates are physical; do not apply WebView's logical move a second time.
                area=self.pocket.stickers._submit(lambda:self.pocket.stickers._workarea(state['x'],state['y']))
                dpi=self.pocket.stickers._submit(lambda:self.pocket.stickers._windows[handle]['dpi'])/96
                width,height=round(264*dpi),round(92*dpi)
                x=max(area.left,min(state['x']+(state['width']-width)//2,area.right-width))
                y=state['y']+state['height']+round(8*dpi)
                if y+height>area.bottom:y=max(area.top,state['y']-height-round(8*dpi))
                self._window('sticker',{'handle':handle},(x,y,width,height))
        except Exception as exc:self.job={'active':False,'text':str(exc),'failed':True}

    def cutout(self, path, handle=None):
        from emoji_bridge import background_remove as bg
        path=Path(path)
        with self.guard:
            if self.closed:raise ValueError('窗口已关闭')
            if self.worker and self.worker.is_alive():raise ValueError('正在抠主体，请等待完成或取消')
            if not path.is_file():raise ValueError('原图已不可用，请重新选择')
            self.cancel.clear();self.job={'active':True,'text':'正在使用本地自动模型…','handle':handle}
            def progress(stage,done=0,total=0):
                self.job.update(text=stage+(f' {done}/{total}' if total else ''))
            def run():
                try:
                    with Image.open(path) as source:
                        animated=getattr(source,'n_frames',1)>1
                        if not animated:
                            result=bg.remove_background(source,cancel=self.cancel,progress=progress,model_name=bg.MODEL)
                            output=self.root/(uuid.uuid4().hex+'.png');result['image'].save(output)
                    if animated:
                        from emoji_bridge.animated_edit import GifSource,export_gif
                        from emoji_bridge.dynamic_cutout import cutout_animation
                        from emoji_bridge.editing import EditDocument
                        animation=GifSource.read(path,cancel=self.cancel,progress=lambda d,t,s:progress(s,d,t))
                        result=cutout_animation(animation,cancel=self.cancel,progress=progress,model_name=bg.MODEL)
                        animation=result['animation'];doc=EditDocument(Image.new('RGBA',animation.frames[0].size))
                        doc.add_sticker(animation.frames[0]);layers=doc.layers;layers[0].update(animation=animation,role='subject')
                        doc.replace_scene(doc._state.base,layers,[],'临时贴图抠主体')
                        output=self.root/(uuid.uuid4().hex+'.gif')
                        export_gif(doc,output,cancel=self.cancel,progress=lambda d,t,s:progress('准备透明动图',d,t))
                    bg.check_cancel(self.cancel)
                    changed=self.pocket.stickers.replace(handle,output,path) if handle else self.pocket.stickers.show(output)
                    self.job.update(active=False,text='已抠主体 · 临时贴图，未加入素材库' if changed else '原贴图已关闭，未重新打开',failed=False)
                except Exception as exc:self.job.update(active=False,text=str(exc),failed=not isinstance(exc,InterruptedError))
            self.worker=threading.Thread(target=run,daemon=True,name='pocket-cutout');self.worker.start()
        return {'accepted':True,'message':'正在抠主体，原图保留'}

    def close(self):
        self.closed=True;self.cancel.set()
        for token in list(self.windows):self.dismiss(token)

    def cleanup(self):
        if self.worker:self.worker.join(timeout=2)
        if not self.worker or not self.worker.is_alive():self.temp.cleanup()


class ToolAPI:
    def __init__(self, tools, token):self._tools=tools;self._token=token
    def context(self):return dict(self._tools.contexts.get(self._token,{}))
    def finish(self, encoded):return self._tools.finish(self._token,encoded)
    def cancel(self):return self._tools.dismiss(self._token)
    def preview(self, encoded, regions, width, height):
        surface=self._tools.surfaces.get(self._token)
        if not surface:return False
        return surface.update(encoded,regions,width,height)
    def state(self):
        t=self._tools;c=t.contexts.get(self._token,{})
        state=t.pocket.stickers.inspect(c['handle']) if 'handle' in c else None
        if state:state={k:v for k,v in state.items() if k!='path'}
        return {'sticker':state,'job':dict(t.job)}
    def play(self):return self._tools.pocket.stickers.play(self.context()['handle'])
    def cutout(self):
        handle=self.context()['handle'];state=self._tools.pocket.stickers.inspect(handle)
        if not state:raise ValueError('这张贴图已关闭')
        return self._tools.cutout(state['path'],handle)
    def cancel_cutout(self):self._tools.cancel.set();return True
