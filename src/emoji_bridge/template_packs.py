"""Declarative scene templates. Packs contain JSON/media, never executable code."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import json,zipfile,shutil
from PIL import Image
from .editing import save_scene,load_scene,load_static
from .materials import is_dynamic
from .animated_edit import GifSource

def export_pack(document,path,slots,name='我的模板'):
    known={l['id']:l for l in document.layers}
    for slot in slots:
        if slot['layer'] not in known or slot['kind'] not in ('image','text'):raise ValueError('模板槽位无效')
        if (known[slot['layer']]['kind']=='text')!=(slot['kind']=='text'):raise ValueError('槽位与图层类型不符')
    with TemporaryDirectory(prefix='eb-template-') as folder:
        root=Path(folder);save_scene(document,root/'scene',name)
        document.render().save(root/'preview.png')
        manifest={'schema':'emoji-template-v1','id':uuid4().hex,'version':1,'name':str(name),'slots':slots,'fonts':['Windows 中文字体：微软雅黑 / 黑体 / 宋体，需在目标系统可用'],'origin':'user-created'}
        (root/'template.json').write_text(json.dumps(manifest,ensure_ascii=False),'utf-8')
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as out:
            for file in root.rglob('*'):
                if file.is_file():out.write(file,file.relative_to(root).as_posix())
    return manifest

def import_pack(path,library):
    root=Path(library)/'templates'/uuid4().hex;root.mkdir(parents=True)
    try:
        with zipfile.ZipFile(path) as archive:
            entries=archive.infolist()
            if len(entries)>20000 or sum(i.file_size for i in entries)>2*1024**3:raise ValueError('模板包超过2GiB / 20000文件预算')
            for entry in entries:
                file=root/entry.filename
                if not file.resolve().is_relative_to(root.resolve()):raise ValueError('模板资源路径无效')
                if entry.is_dir():continue
                if file.suffix.lower() not in ('.json','.png','.gif','.webp','.jpg','.jpeg','.mp4','.mov'):raise ValueError('模板只能包含声明数据与媒体资源')
                file.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(entry) as source,file.open('wb') as target:shutil.copyfileobj(source,target)
        manifest=json.loads((root/'template.json').read_text('utf-8')) if (root/'template.json').exists() else {}
        if manifest.get('schema')!='emoji-template-v1':
            from .petpet_templates import convert
            manifest=convert(root)
        doc,_=load_scene(root/'scene')
        if any(s['layer'] not in [l['id'] for l in doc.layers] for s in manifest['slots']):raise ValueError('模板缺少槽位图层')
        manifest['installed_id']=root.name;(root/'template.json').write_text(json.dumps(manifest,ensure_ascii=False),'utf-8');return root,manifest
    except Exception:
        # This fresh UUID folder is owned only by the failed import.
        shutil.rmtree(root);raise

def instantiate(folder,values,store):
    folder=Path(folder);manifest=json.loads((folder/'template.json').read_text('utf-8'));doc,_=load_scene(folder/'scene');parents=[]
    layers=[dict(l) for l in doc.layers]
    for slot in manifest['slots']:
        value=values.get(slot['key'],slot.get('default'))
        if value is None:raise ValueError('请填写 '+slot['key'])
        layer=next(l for l in layers if l['id']==slot['layer'])
        if slot['kind']=='text':layer['text']=str(value);layer.pop('colors',None)
        else:
            item=store.get(value);path=store.original(value);parents.append(value)
            if is_dynamic(item['metadata']):
                source=GifSource.read(path)
                # Petpet owns the template clock. A longer replacement GIF
                # must not lengthen that template or freeze its last pose.
                tracking=layer.get('tracking',{})
                if tracking.get('algorithm')=='Petpet declarative XYWH':
                    from .animated_edit import SubjectSource
                    times=[k['ms'] for k in tracking['keys']]+[tracking['duration']]
                    frames=tuple(source.frames[source.frame_at(t)[0]] for t in times[:-1])
                    source=SubjectSource(source.original,frames,tuple(b-a for a,b in zip(times,times[1:])),0,'.gif')
                layer['animation']=source;layer['image']=source.frames[0]
            else:layer['image']=load_static(path);layer.pop('animation',None)
            layer['source_id']=value
    # Templates own all default media already; stale source ids from the author's
    # machine are not presented as local library records in another installation.
    for layer in layers:
        if layer.get('source_id') not in parents:layer['source_id']=None
    doc.replace_scene(doc._state.base,layers,parents,'套用模板')
    return doc,{'type':'template','template_key':'user:'+manifest['id'],'version':str(manifest['version']),'values':values}
