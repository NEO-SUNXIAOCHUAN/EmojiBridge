"""Optional static miniPaint page backed by the existing managed material store.

The browser edits a native miniPaint JSON draft; PNG is its separate finished
artifact. The existing Tk/GIF editor is not replaced or asked to read that JSON.
"""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import mimetypes
from pathlib import Path
import queue
import tempfile
import threading
import urllib.parse
import urllib.request
import uuid
import webbrowser
import os
import subprocess
import zipfile

from PIL import Image
from emoji_bridge.materials import default_root
from emoji_bridge.state import save_json

COMMIT = 'a79733eb803fc97084ef0ee4faa96b031e69e1c0'
BUNDLE_SHA256 = 'd084e2659fa7dc1c125663d08e354ccfab3c0cfb78281716ff83b0a6b9283356'
ARCHIVE_SHA256 = '1d6038538cb221b4a9feb04398c35e98001ae97196064ab27e4d2f76e5115501'
WEB = Path(__file__).with_name('minipaint_static.html')


def ensure_editor(*, source=None, progress=None):
    """Cache the reviewed upstream distribution once; its MIT notices stay beside it."""
    def note(text):
        if progress:progress(text)
    cache = default_root().parent / 'tools/minipaint'
    directory = Path(source).resolve() if source else cache / ('miniPaint-' + COMMIT)
    bundle = directory / 'dist/bundle.js'
    if not bundle.exists():
        if source:raise ValueError('miniPaint资源不完整，请重新准备静态编辑器。')
        cache.mkdir(parents=True, exist_ok=True)
        note('首次准备静态编辑器（约4.5MB）…')
        with tempfile.TemporaryDirectory(prefix='minipaint-', dir=cache) as temporary:
            archive = Path(temporary) / 'source.zip'
            url = f'https://codeload.github.com/viliusle/miniPaint/zip/{COMMIT}'
            request = urllib.request.Request(url, headers={'User-Agent':'EmojiBridge-static-editor'})
            with urllib.request.urlopen(request, timeout=30) as remote, archive.open('wb') as local:
                size=0
                while chunk := remote.read(256 * 1024):
                    local.write(chunk);size+=len(chunk)
                    note(f'准备静态编辑器：{size / 1024 / 1024:.1f}MB')
            if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
                raise ValueError('静态编辑器下载不完整，请重试。')
            with zipfile.ZipFile(archive) as package:
                prefix='miniPaint-'+COMMIT+'/'
                if any(not name.startswith(prefix) or '..' in Path(name).parts for name in package.namelist()):
                    raise ValueError('静态编辑器资源目录无效。')
                package.extractall(cache)
    if hashlib.sha256(bundle.read_bytes()).hexdigest() != BUNDLE_SHA256:
        raise ValueError('静态编辑器资源版本不一致，请重新准备。')
    note('静态编辑器已就绪。')
    return directory


def saved_draft(store, ident):
    """Only this editor's explicit source record is a re-editable miniPaint work."""
    for source in reversed(store.sources(ident)):
        if source['kind'] != 'edited':continue
        try:
            recipe=json.loads(source['value'])['recipe']
            draft=recipe['minipaint_draft']
            if recipe.get('editor') != 'minipaint' or len(draft)!=32 or any(c not in '0123456789abcdef' for c in draft):continue
            path=store.root/'external-drafts/minipaint'/draft/'project.json'
            if path.exists():return json.loads(path.read_text(encoding='utf-8'))
        except (KeyError,ValueError,OSError,TypeError):continue
    return None


class StaticEditorSession:
    def __init__(self,store,ids,source):
        self.store=store;self.source=Path(source);self.ids=list(dict.fromkeys(ids));self.events=queue.Queue()
        if not self.ids:raise ValueError('先在素材库选一张或多张静态图片。截图可先粘贴进素材库。')
        items=[store.get(ident) for ident in self.ids]
        if any(item['metadata'].get('frames',1)>1 for item in items):
            raise ValueError('miniPaint入口只编辑静态图；动图请用“用所选新建作品”，不会提取首帧。')
        self.originals={ident:store.original(ident) for ident in self.ids}
        self.project=saved_draft(store,self.ids[0]) if len(self.ids)==1 else None
        self.name=items[0]['name'] if self.project else items[0]['name']+' · 静态作品'
        self.parents=self.project['source_ids'] if self.project else self.ids
        self.last_key=self.project.get('content_key') if self.project else None
        self.last_material=self.project.get('material_id') if self.project else None
        self.closed=False
        session=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,code,content,kind='application/json; charset=utf-8'):
                if isinstance(content,dict):content=json.dumps(content,ensure_ascii=False).encode('utf-8')
                self.send_response(code);self.send_header('Content-Type',kind)
                self.send_header('Content-Length',str(len(content)))
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Security-Policy',"default-src 'self' data: blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self' data:; worker-src 'self' blob:")
                self.end_headers();self.wfile.write(content)
            def valid_host(self):
                return self.headers.get('Host')==urllib.parse.urlsplit(session.url).netloc
            def do_GET(self):
                if not self.valid_host():return self.reply(403,{'error':'请从本机编辑器入口打开。'})
                route=urllib.parse.urlsplit(self.path).path
                if route=='/':return self.reply(200,WEB.read_bytes(),'text/html; charset=utf-8')
                if route=='/api/bootstrap':
                    return self.reply(200,{'name':session.name,'draft':session.project['draft'] if session.project else None,
                        'images':[] if session.project else [{'name':store.get(i)['name'],'url':'/material/'+i} for i in session.ids]})
                if route.startswith('/material/'):
                    ident=route.removeprefix('/material/');file=session.originals.get(ident)
                    if file:return self.reply(200,file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
                if route.startswith('/editor/'):
                    relative=urllib.parse.unquote(route.removeprefix('/editor/')) or 'index.html'
                    file=(session.source/relative).resolve()
                    if file.is_relative_to(session.source) and file.is_file():
                        return self.reply(200,file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
                self.reply(404,{'error':'本次素材或编辑资源不存在。'})
            def do_POST(self):
                if not self.valid_host() or self.headers.get('Origin') != session.url.rstrip('/'):
                    return self.reply(403,{'error':'只能由本机编辑页面保存。'})
                route=urllib.parse.urlsplit(self.path).path
                if route=='/api/return':
                    session.events.put(('return',session.last_material));return self.reply(200,{'returned':True})
                if route=='/api/close':
                    self.reply(200,{'closed':True});threading.Thread(target=session.close,daemon=True).start();return
                if route!='/api/save':return self.reply(404,{'error':'未知操作。'})
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if length<=0 or length>128*1024*1024:raise ValueError('作品数据过大或为空，请调整后重试。')
                    if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('保存格式不正确。')
                    value=json.loads(self.rfile.read(length).decode('utf-8'));item=session.save(value)
                    self.reply(200,{'material_id':item['id'],'name':item['name'],'saved':True})
                except Exception as exc:
                    session.events.put(('error',str(exc)));self.reply(400,{'error':str(exc)})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.url=f'http://127.0.0.1:{self.server.server_port}/'
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def save(self,value):
        draft=value['draft'];name=str(value.get('name') or self.name).strip()[:120]
        if not isinstance(draft,dict) or not draft.get('layers'):raise ValueError('没有可保存的图层。')
        png=value['png']
        if not isinstance(png,str) or not png.startswith('data:image/png;base64,'):raise ValueError('成品必须是透明PNG。')
        raw=base64.b64decode(png.split(',',1)[1],validate=True)
        with Image.open(BytesIO(raw)) as decoded:
            if decoded.format!='PNG' or decoded.width*decoded.height>32_000_000:raise ValueError('PNG尺寸超过现有画布上限。')
            if (draft['info']['width'],draft['info']['height'])!=decoded.size:raise ValueError('草稿和成品尺寸不一致，请重试保存。')
            decoded.load();image=decoded.convert('RGBA')
        content_key=hashlib.sha256(json.dumps({'name':name,'draft':draft},sort_keys=True,ensure_ascii=False).encode()+raw).hexdigest()
        if content_key==self.last_key and self.last_material:return self.store.get(self.last_material)
        ident=uuid.uuid4().hex;directory=self.store.root/'external-drafts/minipaint'/ident
        project={'schema':'emoji-bridge-minipaint-v1','upstream_commit':COMMIT,'name':name,
                 'source_ids':self.parents,'draft':draft,'content_key':content_key}
        save_json(directory/'project.json',project)
        item,_=self.store.save_work(image,name=name,source_ids=self.parents,
            recipe={'editor':'minipaint','minipaint_draft':ident,'upstream_commit':COMMIT})
        project['material_id']=item['id'];save_json(directory/'project.json',project)
        self.project=project;self.last_key=content_key;self.last_material=item['id'];self.name=name
        self.events.put(('saved',item['id']));return item

    def close(self):
        if not self.closed:
            self.closed=True;self.server.shutdown();self.server.server_close()


def open_desktop_editor(session):
    """Use installed Edge app mode, keeping the local editor's own window."""
    candidates=[Path(os.environ.get(key,''))/'Microsoft/Edge/Application/msedge.exe' for key in ('ProgramFiles(x86)','ProgramFiles')]
    browser=next((file for file in candidates if file.is_file()),None)
    if browser:
        profile=default_root().parent/'tools/minipaint-desktop-profile'
        subprocess.Popen([str(browser),'--app='+session.url,'--user-data-dir='+str(profile),'--window-size=1200,820','--no-first-run','--no-default-browser-check'],creationflags=subprocess.CREATE_NO_WINDOW)
        return 'desktop'
    webbrowser.open(session.url,new=2);return 'browser'


def start_static_editor(store,ids,*,progress=None,source=None,launch_browser=True):
    # Reject animation before preparing optional browser resources.
    selected=list(ids)
    if not selected:raise ValueError('先在素材库选择静态图片；截图可先粘贴入库。')
    if any(store.get(i)['metadata'].get('frames',1)>1 for i in selected):
        raise ValueError('miniPaint只处理静态图，GIF请使用现有创作编辑，不会静默取首帧。')
    session=StaticEditorSession(store,selected,ensure_editor(source=source,progress=progress))
    if launch_browser:session.presentation=open_desktop_editor(session)
    return session
