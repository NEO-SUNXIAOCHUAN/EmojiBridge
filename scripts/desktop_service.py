"""Local presentation adapter over MaterialStore; no client APIs or second library."""
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from io import BytesIO
from concurrent.futures import CancelledError
from urllib.parse import urlsplit,parse_qs
import base64,json,mimetypes,os,queue,subprocess,sys,threading,time,uuid
from PIL import Image,ImageGrab,UnidentifiedImageError
from emoji_bridge.materials import MaterialStore
from emoji_bridge.material_preview import FrameStream
from emoji_bridge.state import save_json

APP=Path(__file__).resolve().parents[1]

def png_data(image):
    stream=BytesIO();image.save(stream,'PNG');return 'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')

class DesktopService:
    def __init__(self,root):
        self.store=MaterialStore(root);self.window=None;self.cancel=threading.Event();self.closed=False;self.closing=False
        self.task={'active':False,'text':'素材保存在本机','completed':0,'total':0};self.thread=None
        from media_drop import BrowserFiles
        self.browser_files=BrowserFiles(self)
        self.commands=queue.Queue();self.native_events=queue.Queue();self.native=None;self.native_ready=False;self.native_presented=False;self.preview=None;self.preview_id=None;self.preview_generation=0;self.preview_stopped=-1
        self.media_revision=0;self.drag_cache={};self.cover_revision=None;self.cover_cache=[];self.organize_undo=None
        self.preview_guard=threading.RLock();self.preview_streams=[]
        from emoji_bridge.thumbnail_cache import ThumbnailCache
        self.collection_thumbnails=ThumbnailCache(root=self.store.root/'cache/collection-previews')
        self.navigation={'pending':False,'text':''}
        self.editor_status={};self.editor_sequence=0;self.activities=[];self.activity_sequence=0;self.xp=None;self.xp_sequence=0
        from collection_service import Collections
        self.collections=Collections(self.store)
        self.transfer={'active':False,'text':''};self.transfer_command=None;self.transfer_sequence=0
        self.presentation_seq=0
        from factory_service import Factory
        self.factory=Factory(self)
        self.workspace=None;self.workspace_rect={'visible':False};self.native_view='editor';self.route_event=None;self.route_serial=0;self.saved_item=None;self.saved_serial=0
        self.hotkey=None;self.hotkey_key="";self.hotkey_error="";self.drawer=None;self.tray=None
        from pocket_service import PocketService
        self.pocket=PocketService(self)
        self.token=uuid.uuid4().hex;owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,body,kind='application/json'):
                if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False).encode('utf-8')
                self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',len(body));self.end_headers();self.wfile.write(body)
            def do_GET(self):
                request=urlsplit(self.path)
                if request.path=='/'+owner.token+'/commands':
                    supplied=parse_qs(request.query).get('pid')
                    try:pid=int(supplied[0]) if supplied else None
                    except ValueError:self.send_error(400);return
                    self.reply(owner.take_commands(pid));return
                route=self.path.split('?',1)[0]
                if route=='/factory-default.png':
                    self.reply((APP/'assets/factory/default-input.png').read_bytes(),'image/png');return
                if route=='/brand.png':
                    self.reply((APP/'assets/branding/EmojiBridge-64.png').read_bytes(),'image/png');return
                if route.startswith('/motion/'):
                    root=(APP/'assets/motion').resolve();file=(root/route.removeprefix('/motion/')).resolve()
                    if file.is_relative_to(root) and file.suffix in ('.png','.json','.wav') and file.is_file():
                        self.reply(file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
                    else:self.send_error(404)
                    return
                if route.startswith('/startup-v10/'):
                    name=route.removeprefix('/startup-v10/')
                    if name not in ('EmojiBridge-A.png','startup-v10-sfx.wav'):self.send_error(404);return
                    file=APP/'assets/startup-v10'/name
                    if file.is_file():self.reply(file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
                    else:self.send_error(404)
                    return
                if route.startswith('/'+owner.token+'/collection-thumbnail/'):
                    try:
                        file=owner.collections.files.get(route.rsplit('/',1)[1])
                        if not file:raise ValueError('preview_missing')
                        size=int(parse_qs(request.query).get('size',['384'])[0])
                        self.reply(owner.collection_thumbnails.read(file,size),'image/png')
                    except (OSError,ValueError):self.send_error(404)
                    return
                if route.startswith('/'+owner.token+'/thumbnail/'):
                    try:self.reply(owner.store.thumbnail_bytes(route.rsplit('/',1)[1]),'image/png')
                    except (OSError,ValueError):self.send_error(404)
                    return
                if route.startswith('/'+owner.token+'/draft-cover/'):
                    try:
                        from draft_catalog import cover
                        self.reply(cover(owner.store.root,route.rsplit('/',1)[1]),'image/png')
                    except (OSError,ValueError):self.send_error(404)
                    return
                if route.startswith('/'+owner.token+'/factory-preview/'):
                    key=route.rsplit('/',1)[1]
                    if not key.replace('_','').isalnum():self.send_error(404);return
                    suffix='.gif' if parse_qs(request.query).get('animate') else '.png'
                    file=APP/'assets/factory/previews'/(key+suffix)
                    current=APP/'assets/factory/previews'/(key+'.webp')
                    if suffix=='.gif' and current.exists():file=current
                    if file.is_file():self.reply(file.read_bytes(),{'.webp':'image/webp','.gif':'image/gif','.png':'image/png'}[file.suffix]);return
                if route.startswith('/'+owner.token+'/factory-result/'):
                    parts=route.split('/')
                    try:
                        job=owner.factory.jobs[parts[-2]];row=next(r for r in job['items'] if r['id']==parts[-1] and r['state']=='ready')
                        file=Path(row['file']);self.reply(file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'application/octet-stream');return
                    except (KeyError,StopIteration,OSError):self.send_error(404);return
                if route.startswith('/'+owner.token+'/factory-live/'):
                    key=route.rsplit('/',1)[1]
                    if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):self.send_error(404);return
                    suffix='.png' if parse_qs(request.query).get('poster') else '.webp'
                    file=owner.factory.live.root/key/('preview'+suffix)
                    if file.is_file():self.reply(file.read_bytes(),'image/png' if suffix=='.png' else 'image/webp');return
                    self.send_error(404);return
                if route in ('/','/main.js','/main.css','/pocket.html','/pocket.js','/pocket.css','/edge.html'):
                    file=APP/'assets/desktop'/('index.html' if route=='/' else route[1:])
                    if file.is_file():self.reply(file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'text/plain');return
                self.send_error(404)
            def do_POST(self):
                if self.path=='/'+owner.token+'/overlays':
                    try:
                        event=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
                        self.reply(owner.pocket.suspend(str(event['token']),bool(event['hide']),event.get('pid')))
                    except Exception as exc:self.send_error(503,str(exc))
                    return
                if self.path!='/'+owner.token+'/native':self.send_error(404);return
                event=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
                # Acknowledge receipt independently of WinForms/Tk mounting.
                # Mount completion still sets navigation ready in native_event.
                # Otherwise a busy UI can turn a delivered event into an IPC
                # timeout, causing the child to detach its unsaved workspace.
                owner.native_events.put(event)
                self.reply({'ok':True})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        os.environ['EMOJI_BRIDGE_OVERLAY_ENDPOINT']=self.url+'/'+self.token+'/overlays'
        os.environ['EMOJI_BRIDGE_OVERLAY_HOST_PID']=str(os.getpid())
        threading.Thread(target=self.server.serve_forever,daemon=True,name='desktop-resources').start()
        threading.Thread(target=self.process_native_events,daemon=True,name='desktop-native-events').start()
        saved_drawer=self.drawer_settings()
        if saved_drawer.get('key'):
            try:self.drawer_settings(saved_drawer['key'])
            except ValueError as exc:self.hotkey_error=str(exc);self.task['text']=str(exc)
        seed=self.store.root/'builtin-examples.json'
        from emoji_bridge.builtin_examples import needs_preparation
        if (APP/'assets/examples/manifest.json').exists() and needs_preparation(self.store):self.restore_examples(False)

    def process_native_events(self):
        while not self.closed:
            try:event=self.native_events.get(timeout=.2)
            except queue.Empty:continue
            try:self.native_event(event)
            except Exception as exc:
                if not self.closed:self.task.update(text='工作区通知未完成：'+str(exc),failed=True)

    def drawer_settings(self,key=None):
        path=self.store.root/'drawer.json'
        data=json.loads(path.read_text('utf-8')) if path.exists() else {'key':'Ctrl+Alt+E'}
        if key is not None:
            from emoji_bridge.global_hotkey import Hotkey
            key=key.strip()
            if key.upper()!=self.hotkey_key.upper() or (key and not self.hotkey):
                try:replacement=Hotkey(key,self.pocket.toggle) if key else None
                except ValueError as exc:self.hotkey_error=str(exc);raise
                previous=self.hotkey;self.hotkey=replacement;self.hotkey_key=key;self.hotkey_error=''
                if previous:previous.close()
            data={'key':key};save_json(path,data)
        return {**data,'enabled':bool(self.hotkey),'active_key':self.hotkey_key,'error':self.hotkey_error}
    def open_drawer(self):
        return self.pocket.open()

    def reclaim_stickers(self):return self.pocket.stickers.close_all()
    def recover_stickers(self):return self.pocket.stickers.recover_all()
    def adjust_stickers(self):return self.pocket.stickers.adjust_all()
    def open_drop_port(self):return self.pocket.open()

    def factory_listing(self):
        value=self.factory.listing()
        value=json.loads(json.dumps(value))
        for item in value['catalog']:
            if item['verified']:item['preview']=f'{self.url}/{self.token}/factory-preview/{item["key"].split(":")[1]}'
            if item.get('animated_preview'):item['animation_preview']=item['preview']+'?animate=1'
        for job in value['jobs']:
            for row in job['items']:
                if row['state']=='ready':row['preview']=f'{self.url}/{self.token}/factory-result/{job["id"]}/{row["id"]}'
        return value
    def factory_plan(self,spec):return {'count':len(self.factory.plan(spec))}
    def factory_preview(self,spec=None):return self.factory.preview(spec)
    def factory_preview_status(self):return dict(self.factory.preview_state)
    def factory_examples(self,keys,config=None,retry=False):return self.factory.live.examples(keys,config,retry)
    def factory_generate(self,spec,retry=None):return self.factory.generate(spec,retry)
    def factory_save(self,job,ids,collection=''):
        request_id=uuid.uuid4().hex
        def work():
            saved=self.factory.save(job,ids,collection)
            cancelled=self.cancel.is_set()
            return {'text':('已取消；' if cancelled else '')+f'已保存 {len(saved)} 项至素材库','completed':len(saved),'total':len(ids),'factory_save_id':request_id,'factory_saved_ids':saved,'factory_save_cancelled':cancelled}
        result=self.start(work,'保存表情作品')
        return dict(result,request_id=request_id)

    def restore_examples(self,restore=True):
        def work():
            from emoji_bridge.builtin_examples import install
            count=install(self.store,restore=restore,cancel=self.cancel,progress=lambda n,t,s:self.task.update(completed=n,total=t,text=s))
            # Only existing starter records are checked. Deleted items remain
            # deleted; personal and optional media are never reimported here.
            from emoji_bridge.library_repair import run
            receipt=json.loads((self.store.root/'builtin-examples.json').read_text('utf8'))
            live=set(self.store.matching_ids())
            ids=[v for k,v in receipt.items() if not k.startswith('__') and isinstance(v,str) and v in live]
            report=run(self.store,cancel=self.cancel,ids=ids)
            self.media_revision+=1;self.cover_revision=None
            return {'text':f'基础素材已准备 · 新增 {count} 项，恢复 {report["restored"]} 项。' if not report['issues'] else '部分基础素材暂不可读，可在设置中检查与修复。', 'errors':[v['reason'] for v in report['issues']]}
        return self.start(work,'正在准备随包示例…')

    def promo_status(self):
        from emoji_bridge.promo_assets import metadata
        return metadata()

    def install_promo_projects(self):
        def work():
            from emoji_bridge.promo_assets import install
            result=install(self.store,editable=True,cancel=self.cancel,progress=lambda n,t,s:self.task.update(completed=n,total=t,text=f'{s} {n}/{t}'))
            return {'text':f'可编辑示例新增 {result["drafts"]} 份草稿、{result["templates"]} 个本地模板。草稿在“创作”，模板在“模板包 / 体积”。', 'errors':result['errors']}
        return self.start(work,'准备宣传片可编辑示例…')

    def repair_library(self):
        def work():
            from emoji_bridge.library_repair import run
            report=run(self.store,cancel=self.cancel,
                       progress=lambda n,t:self.task.update(completed=n,total=t,text=f'检查素材 {n}/{t}'))
            self.media_revision+=1;self.cover_revision=None
            count=len(report['issues'])
            return {'text':f"{'已取消，已完成项保留；' if report['cancelled'] else '检查完成：'}可用 {report['healthy']}/{report['checked']}，恢复随包原件 {report['restored']}，重建预览 {report['covers_rebuilt']}，待处理 {count}。",
                    'errors':[r['id']+'：'+r['reason'] for r in report['issues']]}
        return self.start(work,'检查并修复素材；原件、草稿和账号保留…')

    def library_repair_report(self):
        file=self.store.root/'library-check.json'
        if not file.exists():return '尚未检查，请先点击“检查并修复素材”。'
        from emoji_bridge.pilot import BUILD
        return json.dumps({'build':BUILD,**json.loads(file.read_text('utf8'))},ensure_ascii=False,indent=2)

    def status(self):
        with self.collections.guard:
            try:
                context=self.collections.context()
                from material_transfer import account_label
                accounts={t:account_label(context[0],t,full=True) for t in ('qq','wechat')} if context else {}
            except (OSError,ValueError):accounts={};context=None
            if self.transfer.get('active') and self.transfer.get('profile') and not self.transfer.get('account_changed') and not self.transfer.get('awaiting_configuration'):
                if not context or str(context[0].resolve())!=self.transfer['profile'] or not context[1].get('read_authorized'):
                    self.transfer['account_changed']=True
                    self.cancel_transfer()
                    self.transfer['text']='账号配置已改变，已请求停止后续互通；已发生结果保留，请切回原账号查看记录。'
            self.collections.settle()
            if not self.transfer.get('active'):self.collections.tick()
            self.advance_transfer()
        if self.navigation['pending'] and self.native and self.native.poll() is not None:
            self.navigation={'pending':False,'text':'编辑窗口未能打开，可重试；已有素材与草稿保留。'}
        if self.native and self.native.poll() not in (None,0) and not self.task.get('active'):
            self.task['text']='原生编辑窗口未能打开，请查看素材目录中的 desktop-native.log；现有素材与草稿保留。'
        task=dict(self.task)
        from emoji_bridge.privacy_display import redact
        task['text']=redact(task.get('text',''),accounts.values())
        task['errors']=[redact(v,accounts.values()) for v in task.get('errors',[])]
        if task.get('active') and task.get('started'):task['elapsed']=time.monotonic()-task['started']
        if not task.get('active') and task.get('started'):task['end_age']=time.monotonic()-task['started']-task.get('elapsed',0)
        transfer=dict(self.transfer);transfer['text']=redact(transfer.get('text',''),accounts.values())
        for key in ('scene','request_error'):
            if transfer.get(key):transfer[key]={**transfer[key],'detail':redact(transfer[key].get('detail',''),accounts.values())}
        return dict(task=task,transfer=transfer,accounts=accounts,editor_status=dict(self.editor_status),activities=list(self.activities),xp=self.xp,closing=self.closing,revision=self.store.revision(),navigation=dict(self.navigation),native_open=bool(self.native and self.native.poll() is None),route_event=self.route_event,saved_item=self.saved_item,saved_serial=self.saved_serial)

    def take_commands(self,pid=None):
        # A request already in flight belongs to the process/queue it observed.
        # A retiring child's poll must never drain its replacement's queue.
        process,commands=self.native,self.commands
        if pid is not None and (process is None or int(pid)!=process.pid):return []
        values=[]
        while self.native is process and self.commands is commands:
            try:values.append(commands.get_nowait())
            except queue.Empty:break
        return values

    def native_event(self,event):
        process,commands=self.native,self.commands
        if not process or int(event.get('pid',0))!=process.pid:raise ValueError('不是本次启动的编辑工作区')
        kind=event.get('kind')
        def current():
            return not self.closed and self.native is process and self.commands is commands and (kind not in ('presented','navigation_error','return') or event.get('request_id',0)==getattr(self,'navigation_id',0))
        if not current():return
        if kind in ('close_ready','close_cancelled','close_interaction','close_draining','close_prompt_alive'):
            callback=getattr(self,'close_answer',None)
            if callback:callback(kind)
            return
        if kind=='accounts_ready':
            if event.get('request_id',0)!=getattr(self,'navigation_id',0):return
            returning=getattr(self,'transfer_return_view',None);self.transfer_return_view=None
            if returning=='editor':
                self.open_native('resume');return
            self.workspace_layout(dict(self.workspace_rect,visible=False))
            self.navigation={'pending':False,'text':'账号已确认，请点击平台更新读取收藏'}
            self.route_serial+=1;self.route_event={'serial':self.route_serial,'page':'bridge'}
            return
        if kind=='transfer_request':
            try:
                result=self.start_transfer(event.get('source','work'),event['target'],ids=event.get('ids'),revision=event.get('revision'))
                if not result.get('accepted'):self.commands.put({'kind':'transfer_notice','text':result['text']})
            except (ValueError,RuntimeError) as exc:self.commands.put({'kind':'transfer_notice','text':str(exc)})
            return
        if kind=='transfer_status':
            sequence=int(event.get('sequence',0))
            if sequence>self.transfer_sequence and event.get('token')==self.transfer.get('token'):
                incoming=dict(event.get('status',{}))
                if incoming.get('profile') and self.transfer.get('profile') and incoming['profile']!=self.transfer['profile']:return
                self.transfer_sequence=sequence
                if incoming.get('scene'):incoming['scene']=self.presentation(incoming['scene'])
                self.transfer.update(incoming)
                if self.transfer.get('scene',{}).get('phase')=='success':self.transfer.pop('request_error',None)
                self.collections.transfer_paused=bool(self.transfer.get('active'))
            return
        if kind=='transfer_setup':
            self.transfer_return_view=self.native_view if self.transfer.get('active') else None
            self.open_native('bridge');return
        if kind in ('presented','navigation_error') and event.get('request_id',0)!=getattr(self,'navigation_id',0):return
        if kind=='navigation_error':
            self.navigation={'pending':False,'text':'工作区未打开：'+event.get('error','请重试'),'request_id':self.navigation_id}
            return
        if kind=='editor_status':
            sequence=int(event.get('sequence',0))
            if sequence>self.editor_sequence:
                self.editor_sequence=sequence;self.editor_status=dict(event.get('status',{}))
            return
        if kind=='xp_status':
            sequence=int(event.get('sequence',0))
            if sequence>self.xp_sequence:
                self.xp_sequence=sequence;self.xp=event.get('value')
                if self.workspace:self.workspace.presentation_region(self.xp and self.xp['rect'])
            return
        if kind=='activity_status':
            sequence=int(event.get('sequence',0))
            if sequence>self.activity_sequence:self.activity_sequence=sequence;self.activities=event.get('activities',[])
            return
        if kind=='ready':self.native_ready=True
        if kind in ('ready','presented') and event.get('hwnd') and self.window:
            from native_workspace import NativeWorkspace
            if self.workspace is None:self.workspace=NativeWorkspace(self.window)
            try:
                # A ready HWND has not created its requested page yet. Keep the
                # web loading state visible until Tk has completed an idle pass.
                if not self.native_presented:self.workspace.layout(dict(self.workspace_rect,visible=False))
                if not current():return
                self.workspace.attach(int(event['hwnd']),int(event['pid']))
                if not current():return
                if kind=='presented':self.native_presented=True
                visible=bool(self.native_presented and self.workspace_rect.get('visible'))
                self.workspace.layout(dict(self.workspace_rect,visible=visible))
                if not current():return
                commands.put({'kind':'embedded','visible':visible})
            except Exception as exc:
                if not current():return
                self.navigation={'pending':False,'text':'工作区未能嵌入：'+str(exc)}
                self.task.update(text=self.navigation['text'],failed=True)
                commands.put({'kind':'detach','reason':'attach_failed:'+type(exc).__name__})
                return
        if not current():return
        if kind=='presented' and event.get('request_id',0)==getattr(self,'navigation_id',0):
            self.native_view=event.get('view','editor')
            self.navigation={'pending':False,'text':'工作区已就绪'}
        if kind=='return':
            self.workspace_layout(dict(self.workspace_rect,visible=False))
            self.route_serial+=1;self.route_event={'serial':self.route_serial,'page':'library'}
        if kind=='saved':self.saved_item=event.get('item_id');self.saved_serial+=1

    def workspace_layout(self,rect):
        previous=bool(self.native_presented and self.workspace_rect.get('visible',False))
        self.workspace_rect=dict(rect)
        visible=bool(self.native_presented and rect.get('visible'))
        if self.workspace:self.workspace.layout(dict(self.workspace_rect,visible=visible))
        if previous!=visible:self.commands.put({'kind':'visibility','visible':visible})
        return True

    def preferences(self,value=None):
        file=self.store.root/'desktop-ui.json'
        current=json.loads(file.read_text('utf-8')) if file.exists() else {'reduce_motion':False,'glass':True}
        if value is not None:
            if isinstance(value.get('factory_favorites'),list):current['factory_favorites']=[v for v in value['factory_favorites'] if isinstance(v,str) and len(v)<100][:1000]
            if isinstance(value.get('factory_recent'),list):current['factory_recent']=[v for v in value['factory_recent'] if isinstance(v,str) and len(v)<100][:30]
            current.update({k:bool(value[k]) for k in ('reduce_motion','glass','always_scrollbars','startup_motion','startup_sound','sound_muted') if k in value})
            for key in ('xp_volume','enderman_volume'):
                if key in value:current[key]=max(0,min(100,float(value[key])))
            choices={'palette':('midnight','neutral'),'material':('frost','refract','solid'),'motion':('ease','spring'),'dialog_style':('center','origin'),'collection_style':('stack','fan','arc')}
            current.update({k:value[k] for k,allowed in choices.items() if value.get(k) in allowed});save_json(file,current)
            self.commands.put({'kind':'scroll_preferences','value':current})
        if 'always_scrollbars' not in current:
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Control Panel\Accessibility') as key:current['always_scrollbars']=not bool(winreg.QueryValueEx(key,'DynamicScrollbars')[0])
            except (OSError,ImportError):current['always_scrollbars']=False
        return current

    def close_window(self):
        if getattr(self,'request_close',None):self.request_close()
        elif self.window:self.window.destroy()
        return True

    def dependency_status(self):
        from emoji_bridge.background_remove import cache_root,runtime_root,bundled_models
        from emoji_bridge.video import TOOLS_ROOT,bundled_tools
        import shutil
        default=bundled_tools() if all((bundled_tools()/n).is_file() for n in ('ffmpeg.exe','ffprobe.exe')) else TOOLS_ROOT
        folder=Path(os.environ.get('EMOJI_BRIDGE_FFMPEG_BIN',default))
        model=cache_root()/'models/u2net.onnx'
        if not model.is_file():model=bundled_models()/'u2net.onnx'
        return {'video':all((folder/name).is_file() or shutil.which(name) for name in ('ffmpeg.exe','ffprobe.exe')),
                'cutout':(runtime_root()/'onnxruntime/__init__.py').is_file(), 'model':model.is_file(),
                'model_path':str(model),'video_path':str(folder),'library':str(self.store.root)}

    def prepare_dependency(self,kind):
        if kind not in ('video','cutout'):raise ValueError('未知组件')
        def work():
            if kind=='video':
                from emoji_bridge.video import ensure_tools
                ensure_tools(cancel=self.cancel,progress=lambda stage,percent:self.task.update(text=stage,completed=percent,total=100))
            else:
                from emoji_bridge.background_remove import ensure_runtime,ensure_model,cache_root
                progress=lambda stage,done=0,total=0:self.task.update(text=stage,completed=done,total=total)
                ensure_runtime(self.cancel,progress);ensure_model(cache_root()/'models',self.cancel,progress)
            return {'text':'组件已准备好，可以继续创作。'}
        return self.start(work,'正在准备本地组件…')

    def listing(self,view='',collection='',media='',offset=0):
        rows,total=self.store.search(category=collection,view=view,media=media,offset=max(0,int(offset)),limit=48)
        items=[]
        for row in rows:
            item={k:row[k] for k in ('id','name','name_origin','display_name','tags','collections','favorite','metadata')}
            item['thumbnail']=f'{self.url}/{self.token}/thumbnail/{row["id"]}?repair={self.media_revision}';items.append(item)
        revision=self.store.revision();collections=self.store.categories()
        # Only the existing first six collection shortcuts need covers. Reuse
        # persisted thumbnails, never decode originals on a navigation request.
        if revision!=self.cover_revision:
            covers=[]
            for name in collections[:6]:
                members,count=self.store.search(category=name,limit=3)
                covers.append({'name':name,'count':count,'thumbnails':[
                    f'{self.url}/{self.token}/thumbnail/{member["id"]}?repair={self.media_revision}' for member in members]})
            self.cover_cache=covers;self.cover_revision=revision
        return {'items':items,'total':total,'collections':collections,'covers':self.cover_cache,'root':str(self.store.root),'revision':revision}

    def start(self,work,label):
        if self.closing:return {'accepted':False,'message':'正在退出，未开始新的操作。'}
        if self.task.get('active'):return {'accepted':False,'message':'正在处理，可继续浏览或取消当前任务。'}
        self.cancel=threading.Event();self.task={'id':uuid.uuid4().hex,'started':time.monotonic(),'state':'running','active':True,'text':label,'completed':0,'total':0,'errors':[]}
        def run():
            try:
                result=work();self.task.update(result or {})
                self.task['state']='cancelled' if self.cancel.is_set() else 'error' if self.task.get('failed') or self.task.get('errors') else 'success'
            except (CancelledError,InterruptedError):self.task.update(text='已取消，先前完成的文件保留。',state='cancelled')
            except Exception as exc:self.task.update(text=str(exc),failed=True,state='error')
            finally:self.task['active']=False;self.task['elapsed']=time.monotonic()-self.task['started']
        self.thread=threading.Thread(target=run,daemon=True,name='material-io');self.thread.start();return {'accepted':True}

    def cancel_task(self):
        self.cancel.set();self.task['text']='已取消，正在结束当前步骤…';return True

    def collection_listing(self):
        value=self.collections.listing()
        revision=self.store.revision()
        if getattr(self,'local_collection_revision',None)!=revision:
            items,total=self.store.search(limit=100000)
            self.local_collection_items=items;self.local_collection_revision=revision
        current=value['items'];local=[]
        from material_transfer import plan_stage
        plans=sorted((self.store.root/'tasks').glob('*.json'))
        stamps=[]
        for file in plans:
            try:stamps.append((file.name,file.stat().st_mtime_ns))
            except OSError:continue
        stamp=(str(self.collections.profile),tuple(stamps))
        if getattr(self,'local_receipt_stamp',None)!=stamp:
            receipts={}
            for file in plans:
                try:
                    plan=json.loads(file.read_text('utf8'))
                    if not self.collections.profile or plan.get('profile')!=str(self.collections.profile.resolve()):continue
                    for job in plan.get('jobs',[]):receipts.setdefault(job['item_id'],{})[plan['target']]=plan_stage(plan,job)
                except (ValueError,OSError,KeyError):continue
            self.local_receipt_stamp=stamp;self.local_receipts=receipts
        receipts=self.local_receipts
        by_sha={m['source_sha256']:r for r in current if r.get('identity_verified') for m in r['members'] if m.get('source_sha256')}
        for item in self.local_collection_items:
            ident=item['id'];row=by_sha.get(ident)
            if row:
                row['material_id']=ident;row['local']=True
                if item['name_origin']!='generated':
                    row.update({k:item[k] for k in ('name','display_name','name_origin')})
                if 'local' not in row['clients']:row['clients'].append('local')
                row['members'].append({'client':'local','id':ident,'name':item['name'],'original_label':'本地原件','original_ready':True})
            else:
                row={'id':'local:'+ident,'material_id':ident,'local':True,**{k:item[k] for k in ('name','display_name','name_origin')},'clients':['local'],
                     'members':[{'client':'local','id':ident,'name':item['name'],'original_label':'本地原件','original_ready':True}],
                     'source_count':0,'source_counts':{},'duplicate':False,'duplicate_labels':[],'states':['本地素材'],
                     'ready':True,'original_label':'本地原件','frames':item['metadata'].get('frames',1),'comparison':'local',
                     'has_preview':False,'preview_version':ident,'historical_only':False}
            row['target_states']=receipts.get(ident,{})
            # Listing a library is not a full-media verification operation.
            # One inaccessible file must not turn account discovery into error.
            try:
                path=Path(item['path'])
                if not path.is_file():raise FileNotFoundError()
                self.collections.files[row['id']]=str(path)
                row['has_preview']=True
            except OSError:
                reason='本地原件暂不可读，可在素材库重试'
                if row['clients']==['local']:
                    self.collections.files.pop(row['id'],None)
                    row['ready']=False;row['original_label']=reason
                for member in row['members']:
                    if member['client']=='local':member.update(original_ready=False,original_label=reason)
            row['preview_quality']='original_cover'
            try:
                cover=Path(item['thumbnail'])
                if not self.collections.files.get(row['id']) and cover.is_file():
                    self.collections.files[row['id']]=str(cover)
                    row['has_preview']=True;row['preview_quality']='cover'
            except OSError:pass
            local.append(row)
        value['local_items']=local;value['local_count']=len(local)
        for row in [*current,*value.get('history_items',[]),*local]:row['thumbnail']=f'{self.url}/{self.token}/collection-thumbnail/{row["id"]}?v={row.get("preview_version", "0")}'
        return value

    def collection_action(self,client,action='refresh',ids=None,retry=False):
        if action=='cancel':self.collections.cancel(client);return True
        if self.transfer.get('active'):raise ValueError('互通正在准备或占用客户端；请等待完成或先取消互通，再更新收藏。')
        return self.collections.request(client,action,ids or (),manual=True,retry=retry)

    def collection_enrich(self,scope,client,ids,retry=False,priority=False):
        with self.collections.guard:
            context=self.collections.context()
            if not context or context[0].name!=scope:raise ValueError('账号已改变；旧预览请求已丢弃')
            if self.transfer.get('active'):return False
            return self.collections.request(client,'enrich',ids,manual=False,retry=retry,priority=priority)

    def start_transfer(self,source,target,ids=None,scope=None,revision=None,source_client=None):
        try:
            result=self._start_transfer(source,target,ids,scope,revision,source_client)
            if not result.get('accepted'):self.transfer_feedback(target,result['text'])
            return result
        except (ValueError,RuntimeError,OSError) as exc:
            self.transfer_feedback(target,str(exc));raise

    def presentation(self,value):
        self.presentation_seq+=1
        return dict(value,taskId=self.transfer.get('presentation_id','idle'),attempt=self.transfer.get('attempt',0),seq=self.presentation_seq,newTask=True)

    def transfer_feedback(self,target,reason):
        from emoji_bridge.transfer_scene import scene
        if not self.transfer.get('presentation_id'):self.transfer['presentation_id']='request-'+uuid.uuid4().hex
        self.transfer['request_error']=self.presentation(scene({'created':'request-'+str(target)+'|'+reason,
            'target':target,'run_state':'paused','pause_reason':reason,'jobs':[]}))
        self.transfer['request_error']['detail']='本次请求未启动：'+reason

    def _start_transfer(self,source,target,ids=None,scope=None,revision=None,source_client=None):
        """Reserve once, then dispatch to the same native material task UI."""
        if target not in ('qq','wechat') or source not in ('library','collections','work','resume','refresh'):raise ValueError('请选择有效来源和目标')
        with self.collections.guard:
            if self.transfer.get('active'):return {'accepted':False,'text':'已有互通任务；请查看进度或取消，不会重复提交。'}
            context=self.collections.context();profile=context[0] if context else None
            token=uuid.uuid4().hex;path=self.store.root/'tasks'/(time.strftime('%Y%m%d-%H%M%S-')+token[:8]+'.json')
            if source=='collections':
                if not profile or scope!=profile.name:raise ValueError('账号或列表已改变，请重新选择表情')
                # Read cached observations only: accepting a transfer must not
                # trigger a second scan before original preparation.
                from emoji_bridge.collection_view import grouped
                from collection_transfer import create
                library=json.loads((profile/'runtime-data/T005/library.json').read_text('utf-8'))
                create(self.store,grouped(library),ids or [],target,profile,path,source_client=source_client)
            elif source=='library':
                from material_transfer import create
                plan=create(self.store,ids or [],target,path)
                if profile:
                    from collection_transfer import profile_binding
                    plan.update(profile=str(profile.resolve()),profile_binding=profile_binding(profile));save_json(path,plan)
            elif source in ('resume','refresh'):
                path=Path((ids or [''])[0]).resolve()
                if path.parent!=self.store.root/'tasks':raise ValueError('请选择本素材库的互通记录')
                plan=json.loads(path.read_text('utf-8'))
                if plan.get('target')!=target or plan.get('source_kind')!='local_material_library':raise ValueError('互通记录与目标不一致')
                if profile and plan.get('profile') and Path(plan['profile']).resolve()!=profile.resolve():raise ValueError('此记录属于另一账号，请切回创建任务时的账号')
            elif not self.native or self.native.poll() is not None:raise ValueError('请先打开当前作品')
            attempt=1
            if source!='work':
                plan=json.loads(path.read_text('utf8'));attempt=int(plan.get('presentation_attempt',0))+1
                plan['presentation_attempt']=attempt;save_json(path,plan)
                save_json(self.store.root/'last-task.json',{'plan':str(path)})
            from material_transfer import account_label
            self.transfer=dict(active=True,token=token,target=target,profile=str(profile.resolve()) if profile else None,path=str(path) if source!='work' else None,
                               presentation_id=str(profile or 'local')+'|'+str(path),attempt=attempt,
                               text=f'{"QQ" if target=="qq" else "微信"} · {account_label(profile,target) if profile else "待配置本人账号"} · 已接受，正在准备；自动化期间会占用前台，可随时取消。')
            self.collections.transfer_paused=True
            self.transfer['scene']=self.presentation(dict(phase='queued' if self.collections.active else 'working',source='local' if source!='collections' else ('qq' if target=='wechat' else 'wechat'),target=target,total=len(ids or []) if source!='work' else 1,completed=0,failed=0,waiting=0))
            self.collections.yield_to_transfer()
            self.transfer_command=dict(kind='transfer_start',token=token,target=target,source=source,path=str(path),revision=revision,
                                       profile=str(profile.resolve()) if profile else None)
            self.advance_transfer()
            # Return the accepted identity/direction with the receipt. The UI
            # must not animate an optimistic active flag on the previous task.
            return {'accepted':True,'text':self.transfer['text'],'transfer':dict(self.transfer)}

    def advance_transfer(self):
        if self.transfer_command:
            if self.collections.active:
                job=self.collections.active;client='QQ' if job['client']=='qq' else '微信'
                action='补齐清晰预览' if job['action']=='enrich' else '更新收藏' if job['action']=='refresh' else '准备原件'
                self.transfer['text']=(f'{client} 正在结束当前读取；互通已优先排队，'+('未完成的更新随后继续。' if job.get('resume_after_transfer') else '当前读取退出后开始。')+'可取消本次互通。' if job.get('yielded_to_transfer') else f'{client} 正在{action}，互通已排队；当前步骤收尾后继续，可取消本次互通。')
                self.transfer['scene']['detail']=self.transfer['text'];return
            command=self.transfer_command
            try:self.ensure_native()
            except OSError as exc:
                self.transfer.update(active=False,text='互通工作区未启动：'+str(exc));self.transfer_feedback(command['target'],str(exc));self.collections.transfer_paused=False;self.transfer_command=None;return
            self.transfer['scene']=self.presentation(dict(self.transfer['scene'],phase='working',detail=''))
            self.commands.put(command);self.transfer_command=None
        elif self.transfer.get('active') and self.native and self.native.poll() is not None:
            self.transfer.update(active=False,text='互通进程已结束；结果保留，请查看记录后恢复，未自动重发。')
            self.transfer_feedback(self.transfer['target'],self.transfer['text'])
            self.collections.transfer_paused=False

    def cancel_transfer(self):
        with self.collections.guard:
            self.transfer.pop('request_error',None)
            if self.transfer_command:
                path=self.transfer.get('path')
                if path:
                    value=json.loads(Path(path).read_text('utf-8'));value['run_state']='cancelled';save_json(path,value)
                self.transfer_command=None;self.transfer.update(active=False,text='已取消排队，未提交客户端。');self.collections.transfer_paused=False
                self.transfer['scene']=self.presentation({'phase':'cancelled','target':self.transfer['target'],'source':'local','total':0,'completed':0})
                self.commands.put({'kind':'transfer_notice','text':self.transfer['text']})
            else:
                path=self.transfer.get('path')
                if path and Path(path).resolve().parent==(self.store.root/'tasks').resolve():
                    # Deliver cancellation independently of the native UI poll.
                    # The executor still owns resources until it has stopped.
                    Path(path).with_suffix('.cancel').touch()
                self.commands.put({'kind':'cancel_transfer','token':self.transfer.get('token')})
                self.transfer['text']='已请求取消，停止后续提交；正在结束当前步骤。'
        return True

    def transfer_results(self):
        from material_transfer import plan_stage,recovery_text
        result=[]
        for path in sorted((self.store.root/'tasks').glob('*.json'),reverse=True)[:100]:
            try:
                plan=json.loads(path.read_text('utf8'))
                if plan.get('source_kind')!='local_material_library':continue
                result.append({'path':str(path),'target':plan['target'],'created':plan.get('created',''),
                    'text':recovery_text(plan),'state':plan.get('run_state',''),
                    'items':[{'id':j['item_id'],'name':j['name'],'state':plan_stage(plan,j)} for j in plan['jobs']]})
            except (OSError,ValueError,KeyError):continue
        return result

    def drop_begin(self,files):return self.browser_files.begin(files)
    def drop_chunk(self,token,index,offset,encoded):return self.browser_files.write(token,index,offset,encoded)
    def drop_finish(self,token,index,error=''):return self.browser_files.finish(token,index,error)
    def drop_notice(self,text):
        if not self.task.get('active'):self.task.update(text=str(text),failed=True)
        return True

    def import_records(self,records,total,kind='file'):
        from video_tools import VIDEO_EXTENSIONS,own_source
        added=duplicates=0;errors=[];videos=[];results=[]
        try:
            for i,(path,name,error,source) in enumerate(records):
                if self.cancel.is_set():break
                try:
                    if error:raise ValueError(error)
                    if Path(path).suffix.lower() in VIDEO_EXTENSIONS:
                        owned=own_source(self.store,path,self.cancel);videos.append(owned['path'])
                    else:
                        item,duplicate=self.store.import_file(path,kind=kind,cancel=self.cancel,name=Path(name).stem,source=source)
                        results.append({'name':name,'id':item['id'],'state':'existing' if duplicate else 'added'})
                        added+=not duplicate;duplicates+=duplicate
                except (CancelledError,InterruptedError):break
                except Exception as exc:
                    reason='无法读取图片格式，文件可能已损坏' if isinstance(exc,UnidentifiedImageError) else str(exc)
                    errors.append(name+'：'+reason);results.append({'name':name,'state':'failed','reason':reason})
                self.task.update(text=f'导入 {i+1}/{total}',completed=i+1,total=total)
        except (CancelledError,InterruptedError):pass
        if videos and not self.cancel.is_set():self.open_native('video',paths=videos)
        return {'text':f'{"已取消；" if self.cancel.is_set() else ""}新增 {added} · 已有 {duplicates} · 视频 {len(videos)} · 失败 {len(errors)}','errors':errors,'import_results':results}

    def import_paths(self,paths,kind='file'):
        records=((path,Path(path).name,'',None) for path in paths)
        return self.start(lambda:self.import_records(records,len(paths),kind),'正在保存原件…')

    def choose_import(self):
        import webview
        files=self.window.create_file_dialog(webview.FileDialog.OPEN,allow_multiple=True,file_types=('图片与视频 (*.png;*.apng;*.jpg;*.jpeg;*.gif;*.webp;*.mp4;*.mov;*.mkv;*.avi;*.webm)',))
        return self.import_paths(list(files)) if files else None

    def paste(self):
        value=ImageGrab.grabclipboard()
        if isinstance(value,list):return self.import_paths(value,'clipboard_files')
        if isinstance(value,Image.Image):
            def work():
                _,duplicate=self.store.import_bitmap(value,self.cancel)
                return {'text':'已有相同素材。' if duplicate else '截图已保存为PNG；剪贴板提供的是静态图像。'}
            return self.start(work,'正在保存剪贴板图片…')
        raise ValueError('剪贴板没有实际图片或媒体文件。链接和缩略图不能作为原视频导入。')

    def organize(self,ids,values):
        def work():
            name=values.pop('name',None)
            self.store.organize(ids,**values)
            if name and len(ids)==1:self.store.update(ids,name=name)
            return {'text':f'已更新 {len(ids)} 项；原文件保留。'}
        return self.start(work,'正在整理…')

    def collection(self,name,rename=None):
        self.store.collection(name,rename)
        return True

    def assign_collection(self,ids,name):
        def work():
            with self.store.connect() as conn:existing={r[0] for r in conn.execute('SELECT material_id FROM memberships WHERE name=?',(name,))}
            new=[i for i in dict.fromkeys(ids) if i not in existing]
            self.store.organize(ids,add_collections=[name]);self.organize_undo=(new,name)
            return {'text':f'{len(ids)} 项已归入「{name}」；原文件不移动。','undo_collection':True}
        return self.start(work,'正在加入合集…')

    def undo_collection(self):
        def work():
            change=self.organize_undo
            if change:self.store.organize(change[0],remove_collections=[change[1]])
            self.organize_undo=None
            return {'text':'已撤销本次归类；原有合集关系保留。','undo_collection':False}
        return self.start(work,'正在撤销归类…')

    def cancel_editor_save(self):
        self.commands.put({'kind':'cancel_editor_save'});return True

    def cancel_native_activity(self):
        self.commands.put({'kind':'cancel_native_activity'});return True

    def locate(self,ident):
        ids=self.store.matching_ids()
        if ident not in ids:raise ValueError('作品不在当前素材库中，请检查是否已移除。')
        return {'id':ident,'offset':ids.index(ident)//48*48}

    def choose_directory(self):
        import webview
        selected=self.window.create_file_dialog(webview.FileDialog.FOLDER)
        return selected[0] if selected else None

    def export(self,ids,directory,mode='original',options=None):
        def work():
            if mode=='original':
                files=self.store.export(ids,directory,cancel=self.cancel)
                return {'text':f'{"已取消；" if self.cancel.is_set() else ""}已导出 {len(files)} 个原文件','files':list(map(str,files))}
            if mode=='target':
                from emoji_bridge.target_size import batch_compress
                result=batch_compress(self.store,ids,directory,options or {},cancel=self.cancel,
                    progress=lambda n,total,phase:self.task.update(text=phase,completed=n,total=total))
                return {'text':f"体积副本：{result['passed']} 项达标，{result['unmet']} 项未达标，{result['failed']} 项失败，{result['pending']} 项未处理；原件保留。",'compression':result}
            from compatibility_dialog import generate
            result=generate(self.store,('qq',options,Path(directory)),ids=ids,cancel=self.cancel,
                progress=lambda n,total,phase:self.task.update(text=f'{phase} {n}/{total}',completed=n,total=total))
            return {'text':result}
        return self.start(work,'正在导出，原件保持不变…')

    def preview_start(self,ident,generation=None,size=None):
        return self._preview_start(ident,generation,size)

    def _preview_start(self,ident,generation=None,size=None):
        generation=int(generation) if generation is not None else max(self.preview_generation,self.preview_stopped)+1
        started=time.perf_counter()
        with self.preview_guard:
            if self.closed or generation<self.preview_generation or generation<=self.preview_stopped:return False
            if self.preview and self.preview_id==ident and self.preview_generation==generation:return True
            if self.preview:self.preview.close();self.preview=None
            self.preview_streams=[s for s in self.preview_streams if s.thread.is_alive()]
            if len(self.preview_streams)>=2:return False
            self.preview_generation=generation;self.preview_id=ident
        # Disk/manifest validation must not hold the stop/replace lock.
        try:source=self.preview_source(ident)
        except (ValueError,KeyError,OSError) as exc:
            self.preview_diagnostic(exc)
            if not ident.startswith('collection:') or ident.startswith('collection:local:'):
                return {'error':'原件暂不可用，请在素材详情重试；已有封面保留。'}
            with self.collections.guard:
                row=next((r for r in self.collections.rows_cache if r['id']==ident.removeprefix('collection:')),None)
                failed=[m.get('enrichment_at') for m in (row or {}).get('members',[]) if m.get('enrichment_state')=='failed']
            if row is None:return {'error':'此收藏已不在当前视图，请重新选择。'}
            return {'pending':True,'failure':max(filter(None,failed),default=0),'message':'正在准备原始预览…'}
        target=tuple(max(64,min(1920,int(n))) for n in (size or (960,720)))
        if len(target)!=2:target=(960,720)
        with self.preview_guard:
            if self.closed or self.preview_id!=ident or self.preview_generation!=generation or generation<=self.preview_stopped:return False
            stream=FrameStream(source,size=target,respect_loop=True)
            stream.resolve_ms=(time.perf_counter()-started)*1000
            self.preview_streams.append(stream);self.preview=stream
        return True

    def preview_source(self,ident):
        if not ident.startswith('collection:'):return self.store.original(ident)
        key=ident.removeprefix('collection:')
        if key.startswith('local:'):return self.store.original(key.removeprefix('local:'))
        with self.collections.guard:
            row=next((r for r in self.collections.rows_cache if r['id']==key),None)
            if not row:raise ValueError('此收藏视图已变化，请更新后重试')
            members=[dict(m) for m in row['members']]
        for m in members:
            sha=m.get('source_sha256')
            if sha:
                try:return self.store.original(sha)
                except (ValueError,KeyError,OSError):pass
            try:
                from emoji_bridge.preview_media import original_for_preview
                source=original_for_preview(m)
                if source:return source
            except (ValueError,KeyError,OSError) as exc:self.preview_diagnostic(exc)
        raise ValueError('完整原件尚未就绪；暂显示已有封面，可补齐原件后重试')

    def preview_frame(self,ident,generation=None):
        stream=self.preview
        if ident!=self.preview_id or stream is None or generation is not None and int(generation)!=self.preview_generation:return None
        try:
            frame,duration,index,count=stream.frames.get(timeout=.1)
            if frame is None:
                self.preview_diagnostic(duration)
                return {'error':'原件暂时无法播放，移开后重试；可在详情重新获取原件。'}
            try:
                started=time.perf_counter();data=png_data(frame)
                return {'image':data,'duration':duration,'index':index,'count':count,'timing':{'resolve_ms':stream.resolve_ms,'decode_ms':stream.first_frame_ms,'encode_ms':(time.perf_counter()-started)*1000},'size':frame.size}
            finally:frame.close()
        except queue.Empty:return {'ended':True} if stream.done.is_set() else None

    def preview_diagnostic(self,error):
        import logging
        from logging.handlers import RotatingFileHandler
        try:
            if not hasattr(self,'preview_log'):
                log=logging.getLogger('emoji_bridge.preview.'+str(id(self)));log.setLevel(logging.WARNING);log.propagate=False
                handler=RotatingFileHandler(self.store.root/'preview-diagnostics.log',maxBytes=256_000,backupCount=1,encoding='utf8')
                log.addHandler(handler);self.preview_log=log
            self.preview_log.warning('Preview decode/resolve: %s',error)
        except OSError:pass

    def preview_stop(self,generation=None):
        with self.preview_guard:
            self.preview_stopped=max(self.preview_stopped,int(generation) if generation is not None else self.preview_generation)
            if generation is not None and int(generation)!=self.preview_generation:return False
            if self.preview:self.preview.close();self.preview=None
            self.preview_id=None;return True

    def ensure_native(self):
        if not self.native or self.native.poll() is not None:
            self.native_ready=False;self.native_presented=False
            self.editor_status={};self.editor_sequence=0;self.activities=[];self.activity_sequence=0
            self.xp=None;self.xp_sequence=0
            self.transfer_sequence=0
            self.commands=queue.Queue()
            try:
                with (self.store.root/'desktop-native.log').open('a',encoding='utf-8') as log:
                    self.native=subprocess.Popen([sys.executable,'-X','utf8',str(APP/'scripts/desktop_native.py'),str(self.store.root),self.url+'/'+self.token],stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except OSError:
                self.navigation={'pending':False,'text':'编辑窗口未能打开，可重试。'}
                raise

    def open_native(self,kind='editor',ids=None,paths=None):
        if self.closing:raise ValueError('正在退出，未打开新的工作区')
        if kind=='draft':
            from draft_catalog import resolve
            resolve(self.store.root,(ids or [''])[0])
        request=(kind,tuple(ids or ()),tuple(map(str,paths or ())))
        if self.navigation['pending'] and getattr(self,'navigation_request',None)==request:
            return {'opened':False,'pending':True}
        self.navigation_id=getattr(self,'navigation_id',0)+1
        self.navigation_request=request;self.navigation={'pending':True,'text':'正在打开表情工厂…' if kind in ('editor','factory','resume') else '正在打开'+('视频选段' if kind in ('video','record') else '工作区')+'…','request_id':self.navigation_id}
        self.ensure_native()
        self.commands.put({'kind':kind,'ids':ids or [],'paths':paths or [],'request_id':self.navigation_id})
        self.route_serial+=1;self.route_event={'serial':self.route_serial,'page':'native','view':'editor' if kind in ('editor','factory','resume','draft') else 'video' if kind=='record' else 'bridge' if kind=='transfer_results' else kind}
        return {'opened':True,'route_serial':self.route_serial}

    def drafts(self,remove=None):
        from draft_catalog import listing,remove as delete
        if remove:
            delete(self.store.root,remove)
            self.commands.put({'kind':'draft_deleted','id':remove})
        return [dict(row,thumbnail=f'{self.url}/{self.token}/draft-cover/{row["id"]}?v={row["updated"]}') for row in listing(self.store.root)]

    def drag_files(self,ids):
        files=[]
        for ident in dict.fromkeys(ids):
            cached=self.drag_cache.get(ident);file=cached[0] if cached else None
            valid=file and file.is_file() and (file.stat().st_size,file.stat().st_mtime_ns)==cached[1]
            if not valid:
                copied=self.store.export([ident],self.store.root/'drag-out',threading.Event())
                if not copied:raise ValueError('原文件未准备好')
                file=copied[0];stat=file.stat();self.drag_cache[ident]=(file,(stat.st_size,stat.st_mtime_ns))
            files.append(str(file))
        return files

    def drag(self,ids,window=None):
        # Reuse the existing export-copy boundary: never expose managed originals
        # to a shell drop target which might move or modify the supplied files.
        from System import Action,Array,String
        from System.Windows.Forms import DataObject,DragDropEffects,Control,MouseButtons
        if self.task.get('active'):
            return False
        window=window or self.window
        files=self.drag_files(ids)
        def start():
            if self.closed:return
            if not Control.MouseButtons.HasFlag(MouseButtons.Left):
                if not self.task.get('active'):self.task['text']='拖出副本已准备好，请再次拖动缩略图。'
                return
            data=DataObject();data.SetData('FileDrop',Array[String](files))
            self.pocket.dragging=True
            try:effect=window.native.DoDragDrop(data,DragDropEffects.Copy)
            finally:self.pocket.dragging=False
            if effect==DragDropEffects.Copy:
                threading.Thread(target=self.store.mark_used,args=(ids,),daemon=True).start()
                if not self.task.get('active'):self.task['text']='文件已交给拖放目标，原件和拖出副本继续保留。'
        window.native.BeginInvoke(Action(start));return True

    def close(self):
        if self.closed:return
        self.closed=True;self.closing=True
        if hasattr(self,'preview_log'):
            for handler in self.preview_log.handlers[:]:handler.close();self.preview_log.removeHandler(handler)
        if self.tray:self.tray.close();self.tray=None
        self.pocket.close()
        if os.environ.get('EMOJI_BRIDGE_OVERLAY_ENDPOINT')==self.url+'/'+self.token+'/overlays':
            os.environ.pop('EMOJI_BRIDGE_OVERLAY_ENDPOINT',None);os.environ.pop('EMOJI_BRIDGE_OVERLAY_HOST_PID',None)
        self.factory.preview(None)
        self.factory.live.close()
        if self.hotkey:self.hotkey.close();self.hotkey=None
        self.collections.close()
        self.cancel.set();self.preview_stop();self.commands.put({'kind':'detach','reason':'host_closed'})
        def shutdown():
            deadline=time.monotonic()+2
            while self.native and self.native.poll() is None and not self.commands.empty() and time.monotonic()<deadline:
                time.sleep(.05)
            self.server.shutdown();self.server.server_close()
        threading.Thread(target=shutdown,daemon=True).start()
