"""Template catalog and cancellable batches using the existing material task."""
from pathlib import Path
from uuid import uuid4
import json,time,threading,hashlib,base64
from PIL import Image
from emoji_bridge.capabilities import worker,APP
from emoji_bridge.state import save_json
from emoji_bridge.materials import is_dynamic

class Factory:
    def __init__(self,service):
        self.service=service;self.root=service.store.root/'factory';self.root.mkdir(exist_ok=True)
        self.catalog=json.loads((APP/'assets/factory/catalog.json').read_text('utf-8'))
        from factory_animation_input import SUPPORTED
        for row in self.catalog:
            if row['key'] in SUPPORTED:row['animation_policy']='preserve'
        self.jobs={};self.current=None
        from factory_live_preview import LivePreview
        self.live=LivePreview(self);self.preview_state=self.live.state
        for path in self.root.glob('*/job.json'):
            try:
                job=json.loads(path.read_text('utf-8'));self.jobs[job['id']]=job
                for row in job['items']:
                    if row['state']=='running':row.update(state='failed',error='上次处理已中断，可重试')
            except (ValueError,KeyError):continue
    def listing(self):
        return {'catalog':self.catalog,'jobs':sorted(self.jobs.values(),key=lambda j:j['created'],reverse=True)[:20]}
    def preview(self,spec):return self.live.preview(spec)
    def plan(self,spec):
        templates=list(dict.fromkeys(spec.get('templates',[])));bykey={c['key']:c for c in self.catalog}
        rows=[];slots=list(spec.get('slots',[]));texts=spec.get('texts',[]);lines=spec.get('lines',[]) or [None]
        for key in templates:
            template=bykey[key]
            if not template.get('verified'):raise ValueError(template.get('error','该模板尚未通过验证'))
            images=spec.get('template_slots',{}).get(key,slots[:template['max_images']])
            if not template['min_images']<=len(images)<=template['max_images']:raise ValueError(template['name']+'需要 '+str(template['min_images'])+'～'+str(template['max_images'])+' 张图片')
            for line in lines:
                actual=[line] if line is not None else (texts or template['default_texts'])
                if not template['min_texts']<=len(actual)<=template['max_texts']:raise ValueError(template['name']+'的文字槽数量不符')
                rows.append({'id':uuid4().hex,'template':key,'slots':images,'texts':actual,'parameters':spec.get('parameters',{}).get(key,{}),'state':'pending'})
        if not rows:raise ValueError('请先选择模板')
        if len(rows)>200:raise ValueError('本批最多200项，请减少模板或文案；不会截断任务')
        return rows
    def generate(self,spec,retry=None):
        if self.service.task.get('active'):return {'accepted':False,'message':'请等待当前任务完成或取消'}
        self.preview(None)
        if retry:
            job=self.jobs[retry]
            for row in job['items']:
                if row['state'] in ('failed','cancelled'):row['state']='pending'
        else:
            job={'id':uuid4().hex,'created':time.time(),'items':self.plan(spec),'name':spec.get('name','表情作品')};self.jobs[job['id']]=job
        folder=self.root/job['id'];folder.mkdir(exist_ok=True);self.current=job['id']
        def persist():save_json(folder/'job.json',job)
        def run():
            service=self.service;completed=sum(row['state']=='ready' for row in job['items']);total=len(job['items'])
            for row in job['items']:
                if row['state']!='pending':continue
                if service.cancel.is_set():row['state']='cancelled';continue
                row.update(state='running',error=None);persist();service.task.update(completed=completed,total=total,text='生成 '+row['template'])
                try:
                    images=[];parents=[];workdir=folder/row['id'];workdir.mkdir(exist_ok=True)
                    for n,slot in enumerate(row['slots']):
                        if slot.get('example')=='thanos-v1':
                            from shutil import copyfile
                            source=workdir/f'example-{n}.png';copyfile(APP/'assets/factory/default-input.png',source)
                            from emoji_bridge.frame_store import inspect_local
                            metadata,_=inspect_local(source)
                        elif slot.get('snapshot'):
                            source=Path(slot['snapshot']).resolve()
                            if not source.is_relative_to(service.store.root.resolve()):raise ValueError('模板输入不在项目管理位置')
                            if not source.is_file():raise ValueError('模板输入快照缺失，请重新选择来源')
                            parents.extend(slot.get('source_ids',[]))
                            from emoji_bridge.frame_store import inspect_local
                            metadata,_=inspect_local(source)
                        else:
                            ident=slot['id'];parents.append(ident);item=service.store.get(ident);source=service.store.original(ident);metadata=item['metadata']
                        if is_dynamic(metadata):
                            template=next(c for c in self.catalog if c['key']==row['template'])
                            if slot.get('frame') is None and template.get('animation_policy')!='preserve':raise ValueError('此模板仅支持静态图片，请明确选帧；原动画保留')
                            if slot.get('frame') is not None:
                                from emoji_bridge.editing import load_static
                                image=load_static(source,int(slot['frame']));source=workdir/f'input-{n}.png';image.save(source)
                        images.append(str(source))
                    def progress(stage,done=0,size=0):
                        service.task.update(text=stage,stage=stage,stage_done=done,stage_total=size)
                    output=workdir/'output.media';worker('meme','factory_meme_worker.py',{'action':'generate','result':str(output),'key':row['template'],'images':images,'texts':row['texts'],'parameters':row['parameters']},workdir,service.cancel,progress=progress)
                    from emoji_bridge.frame_store import inspect_local
                    metadata,_=inspect_local(output)
                    suffix={'PNG':'.png','GIF':'.gif','WEBP':'.webp','JPEG':'.jpg'}[metadata['format']];final=output.with_suffix(suffix);output.replace(final)
                    row.update(state='ready',file=str(final),metadata=metadata,source_ids=parents)
                except InterruptedError:row['state']='cancelled'
                except Exception as exc:row.update(state='failed',error=str(exc))
                completed+=1;persist()
            persist();return {'text':f"生成完成：{sum(r['state']=='ready' for r in job['items'])}/{total}；选择结果加入素材库或继续编辑。",'factory_job':job['id'],'failed':any(r['state']=='failed' for r in job['items'])}
        persist();return self.service.start(run,'准备表情工厂')
    def save(self,job_id,ids,collection=''):
        job=self.jobs[job_id];results=[]
        for row in job['items']:
            if row['id'] not in ids or row['state']!='ready':continue
            if self.service.cancel.is_set():break
            self.service.task.update(text='保存 '+row['template'],completed=len(results),total=len(ids))
            if row.get('saved_id'):
                try:self.service.store.get(row['saved_id']);results.append(row['saved_id']);continue
                except (KeyError,ValueError):pass
            template=next(c for c in self.catalog if c['key']==row['template'])
            recipe={'type':'template','template_key':row['template'],'template_version':template['version'],'source':template['source'],'source_commit':template.get('source_commit'),'texts':row['texts'],'parameters':row['parameters'],'slots':row['slots'],'job_id':job_id}
            options=dict(name=job['name']+' · '+row['template'].split(':')[-1],source_ids=row['source_ids'],recipe=recipe)
            if is_dynamic(row['metadata']):item,_=self.service.store.save_animated_work(row['file'],**options)
            else:
                with Image.open(row['file']) as image:item,_=self.service.store.save_work(image,**options)
            row['saved_id']=item['id'];results.append(item['id'])
            save_json(self.root/job_id/'job.json',job)
        if collection and results:self.service.store.organize(results,add_collections=[collection])
        save_json(self.root/job_id/'job.json',job);return results
