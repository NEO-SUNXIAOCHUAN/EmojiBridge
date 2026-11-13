"""Latest central preview + bounded visible-card queue, shared persistent engine."""
from pathlib import Path
from collections import OrderedDict
import json,hashlib,threading,time,subprocess
from PIL import Image,ImageDraw
from emoji_bridge.capabilities import ensure,APP
from emoji_bridge.background_remove import _python
from emoji_bridge.state import save_json

class LivePreview:
    def __init__(self,factory):
        self.factory=factory;self.service=factory.service;self.root=factory.root/'preview-v2';self.root.mkdir(exist_ok=True)
        self.central=None;self.gallery=OrderedDict();self.outputs={};self.serial=0;self.thread=None;self.process=None;self.closed=False;self.lock=threading.Lock()
        self.state={'active':False,'image':None,'error':''};self.last_used=time.monotonic();self.config={'mode':'default','a':'','b':''};self.cancel=threading.Event()
        settings=factory.root/'examples.json'
        if settings.exists():self.config.update(json.loads(settings.read_text('utf8')))
    def url(self,key,poster=False):return f'{self.service.url}/{self.service.token}/factory-live/{key}'+('?poster=1' if poster else '')
    def preview(self,spec):
        with self.lock:
            self.serial+=1;serial=self.serial
            if spec is None:self.central=None;self.gallery.clear();self.state['active']=False;return serial
            row=self.factory.plan(spec)[0];self.central=(serial,row);self.state.update(active=True,error='',serial=serial,template=row['template'])
            self.start()
        return serial
    def examples(self,keys,config=None,retry=False):
        with self.lock:
            if retry:
                for key in keys:self.outputs.pop(key,None)
            if config is not None and config!=self.config:
                self.config={k:config.get(k,'') for k in ('mode','a','b')};save_json(self.factory.root/'examples.json',self.config);self.outputs={};self.gallery.clear()
            catalog={t['key']:t for t in self.factory.catalog}
            for key in keys[:16]:
                if key in self.outputs or key in self.gallery or key not in catalog or not catalog[key].get('verified'):continue
                t=catalog[key];ids=[self.config.get('a'),self.config.get('b')]
                if self.config.get('mode')=='recent':
                    ids=[r['id'] for r in self.service.store.search(recent=True,limit=2)[0]]
                if self.config.get('mode')=='default':ids=[]
                slots=[{'id':ids[n%len(ids)] if ids and ids[n%len(ids)] else None,'frame':0} for n in range(t['min_images'])]
                texts=list(t['default_texts'])
                while len(texts)<t['min_texts']:texts.append('一起出发')
                self.gallery[key]={'template':key,'slots':slots,'texts':texts,'parameters':{},'example':True,'config':dict(self.config)}
            visible=set(keys);self.gallery=OrderedDict((k,v) for k,v in self.gallery.items() if k in visible)
            self.start()
            return {'config':dict(self.config),'items':dict(self.outputs)}
    def start(self):
        if not self.thread or not self.thread.is_alive():
            self.thread=threading.Thread(target=self.run,daemon=True,name='factory-display');self.thread.start()
    def render(self,row):
        template=next(t for t in self.factory.catalog if t['key']==row['template'])
        fingerprint={k:row[k] for k in ('template','slots','texts','parameters')};fingerprint.update(version=template['version'],display='thanos-v1',edge=160 if row.get('example') else 384)
        key=hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest();folder=self.root/key;folder.mkdir(exist_ok=True)
        output=folder/'preview.webp';meta=output.with_suffix('.json')
        if meta.exists() and json.loads(meta.read_text('utf8')).get('ok') and output.exists():return key,json.loads(meta.read_text('utf8'))
        if row.get('example') and self.config.get('mode')=='default':
            # Shipped examples were generated from the exact designated input.
            # They require neither the optional engine nor a first-use download.
            built=APP/'assets/factory/previews'/row['template'].removeprefix('meme:')
            if built.with_suffix('.webp').is_file() and built.with_suffix('.json').is_file():
                import shutil
                for suffix in ('.webp','.png','.json'):shutil.copyfile(built.with_suffix(suffix),output.with_suffix(suffix))
                return key,json.loads(meta.read_text('utf8'))
            if built.with_suffix('.png').is_file():
                # Text-only templates ship a poster, not a WebP+JSON bundle.
                # Display that actual poster without starting an engine install.
                # It is explicitly a still example, never a generated animation.
                import shutil
                shutil.copyfile(built.with_suffix('.png'),output.with_suffix('.png'))
                with Image.open(built.with_suffix('.png')) as image:
                    size=image.size
                    image.save(output,'WEBP',lossless=True)
                data={'ok':True,'poster_only':True,'size':size,'frames':1}
                save_json(meta,data)
                return key,data
        from emoji_bridge.task_budget import admission
        with admission('模板示例预览',cancel=self.cancel,priority=10):
            return self.render_uncached(row,fingerprint,folder,output,meta,key)

    def render_uncached(self,row,fingerprint,folder,output,meta,key):
        images=[]
        from emoji_bridge.editing import load_static
        for n,slot in enumerate(row['slots']):
            if slot.get('id'):
                from emoji_bridge.materials import is_dynamic
                item=self.service.store.get(slot['id'])
                if not row.get('example') and is_dynamic(item['metadata']) and slot.get('frame') is None:raise ValueError('请选择用于模板的动画帧；原动画保留')
                image=load_static(self.service.store.original(slot['id']),slot.get('frame') or 0)
            else:
                with Image.open(APP/'assets/factory/default-input.png') as im:image=im.convert('RGBA')
            image.thumbnail((384,384),Image.Resampling.LANCZOS);file=folder/f'{n}.png';image.save(file);images.append(str(file))
        if not self.process or self.process.poll() is not None:
            target=ensure('meme',cancel=self.cancel);self.log=(self.root/'worker.log').open('a',encoding='utf8')
            self.process=subprocess.Popen([_python(),'-X','utf8',str(APP/'scripts/factory_preview_worker.py'),'--dependencies',str(target)],stdin=subprocess.PIPE,stdout=self.log,stderr=self.log,text=True,encoding='utf8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        meta.unlink(missing_ok=True)
        request={'key':row['template'],'images':images,'texts':row['texts'],'parameters':row['parameters'],'result':str(output),'edge':fingerprint['edge']}
        self.process.stdin.write(json.dumps(request,ensure_ascii=False)+'\n');self.process.stdin.flush();start=time.monotonic()
        checked=0
        while not meta.exists():
            from emoji_bridge.task_budget import foreground_waiting
            now=time.monotonic()
            if self.closed or self.cancel.is_set() or (now-checked>.2 and foreground_waiting()):
                self.stop_process();raise InterruptedError('预览已暂停，为主动处理让位；可重新选择预览')
            if now-checked>.2:checked=now
            if self.process.poll() is not None:raise RuntimeError('预览组件退出，可重新选择效果重试')
            if time.monotonic()-start>90:
                self.stop_process();raise RuntimeError('该模板预览超过90秒，已停止；可使用正式生成查看详细结果')
            time.sleep(.04)
        data=json.loads(meta.read_text('utf8'))
        if not data['ok']:raise ValueError(data['error'])
        return key,data
    def run(self):
        while not self.closed and not self.service.closed:
            with self.lock:
                if self.central:serial,row=self.central;self.central=None;kind='central'
                elif self.gallery:_,row=self.gallery.popitem(last=False);serial=None;kind='gallery'
                else:row=None
            if row is None:
                if time.monotonic()-self.last_used>60:self.stop_process()
                time.sleep(.08);continue
            self.last_used=time.monotonic()
            self.cancel.clear();self.active_template=row['template']
            try:
                key,data=self.render(row)
                with self.lock:
                    if kind=='central' and serial==self.serial:self.state.update(active=False,error='',image=self.url(key),metadata=data,template=row['template'])
                    elif kind=='gallery' and row.get('config')==self.config:self.outputs[row['template']]={'image':self.url(key,True),'animation':self.url(key),'metadata':data}
            except Exception as exc:
                with self.lock:
                    if kind=='central' and serial==self.serial:self.state.update(active=False,error=str(exc))
                    elif kind=='gallery' and row.get('config')==self.config:self.outputs[row['template']]={'error':str(exc)}
            self.trim()
            self.active_template=None
        self.stop_process()
    def trim(self):
        # Only this owned preview cache is reclaimed; originals/jobs never enter it.
        import shutil
        folders=sorted((p for p in self.root.iterdir() if p.is_dir()),key=lambda p:p.stat().st_mtime,reverse=True);total=0
        for n,folder in enumerate(folders):
            total+=sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
            if n>=96 or total>192*1024**2:
                if folder.resolve().parent==self.root.resolve():
                    with self.lock:self.outputs={k:v for k,v in self.outputs.items() if folder.name not in v.get('image','')}
                    shutil.rmtree(folder)
    def stop_process(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=1)
        self.process=None
        if getattr(self,'log',None):self.log.close();self.log=None
    def close(self):
        self.closed=True;self.cancel.set()
        # The rendering thread owns its child until termination is acknowledged.
        # A UI close never waits on that process or gives its lease away early.
        if not self.thread or not self.thread.is_alive():self.stop_process()
