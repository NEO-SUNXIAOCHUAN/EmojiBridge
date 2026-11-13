"""Bounded independent GIF copies; preserve the full clock and source document."""
from pathlib import Path
from time import monotonic
from .animated_edit import export_gif,selected_document,GifSource,check_cancel
from .compatibility_copy import sample_timing
from .frame_store import inspect_local
from concurrent.futures import CancelledError

def compress(document,directory,target_bytes,*,min_edge=96,min_fps=8,min_colors=32,max_attempts=8,max_seconds=120,cancel=None,progress=None):
    if target_bytes<1024:raise ValueError('目标体积至少1KiB')
    source=selected_document(document)
    if not source.animation:raise ValueError('当前体积搜索用于动态作品')
    root=Path(directory);root.mkdir(parents=True,exist_ok=True);tick=monotonic();results=[];largest=max(source.size)
    edge_floor=min(largest,max(16,int(min_edge)));fps_floor=max(1,min(30,float(min_fps)));colors_floor=max(2,min(255,int(min_colors)))
    class Deadline:
        def is_set(self):return (cancel is not None and cancel.is_set()) or monotonic()-tick>=max_seconds
    for index in range(max(1,min(12,int(max_attempts)))):
        check_cancel(cancel)
        if index and monotonic()-tick>=max_seconds:break
        fraction=index/max(1,max_attempts-1);edge=round(largest*(1-fraction)+edge_floor*fraction);colors=round(255*(1-fraction)+colors_floor*fraction)
        fps=None if index==0 else 30*(1-fraction)+fps_floor*fraction
        indices,durations=sample_timing(source.animation.durations,fps);size=tuple(max(1,round(n*edge/largest)) for n in source.size)
        class Sampled:
            animation=GifSource(b'',range(len(durations)),durations,source.animation.loop)
            size=source.size
            def render(self,animation_frame=0):return source.render(animation_frame=indices[animation_frame])
        output=root/f'copy-{index}.gif'
        if progress:progress(index,max_attempts,'搜索体积副本')
        try:export_gif(Sampled(),output,output_size=size,colors=colors,cancel=Deadline())
        except CancelledError:
            check_cancel(cancel)
            if not results:raise ValueError('本次体积搜索达到耗时上限，尚无完整副本；可减少输出尺寸后重试。原件保留')
            break
        info,_=inspect_local(output);row={'path':str(output),'bytes':output.stat().st_size,'size':size,'frames':info['frames'],'duration_ms':info['duration_ms'],'colors':colors,'fps':info['frames']/max(.001,info['duration_ms']/1000)};results.append(row)
        if row['bytes']<=target_bytes:return {'met':True,'selected':row,'attempts':results,'seconds':monotonic()-tick}
    return {'met':False,'selected':min(results,key=lambda r:r['bytes']),'attempts':results,'seconds':monotonic()-tick,'reason':'在尝试次数、耗时和质量底线内未达到目标；原件及完整质量输出保留'}


def batch_compress(store,ids,directory,options,*,cancel=None,progress=None):
    """Sequential per-item copies with durable results; no originals are rewritten."""
    from PIL import Image
    from .editing import EditDocument,load_static
    from .materials import is_dynamic
    from .file_io import copy_file
    from .state import save_json
    from uuid import uuid4
    folder=Path(directory)/('体积副本-'+uuid4().hex[:8]);folder.mkdir(parents=True)
    rows=[];items=list(dict.fromkeys(ids));target=int(options.get('target_kib',1024))*1024
    for index,ident in enumerate(items):
        if cancel is not None and cancel.is_set():break
        if progress:progress(index,len(items),f'处理体积副本 {index+1}/{len(items)}')
        row={'id':ident,'state':'failed'}
        try:
            item=store.get(ident);path=store.original(ident)
            if not is_dynamic(item['metadata']):raise ValueError('目标体积搜索当前用于动态素材；静态原件可从原文件入口导出')
            source=GifSource.read(path,cancel=cancel);image=source.frames[0]
            doc=EditDocument(Image.new('RGBA',image.size),[ident]);layer=doc.add_sticker(image,(0,0),source_id=ident)
            doc.replace_scene(doc._state.base,[dict(l,animation=source) for l in doc.layers],doc.source_ids)
            result=compress(doc,folder/ident,target,min_edge=int(options.get('min_edge',128)),min_fps=float(options.get('min_fps',8)),min_colors=int(options.get('min_colors',32)),cancel=cancel)
            destination=folder/(f'{index+1:03d}-'+ident[:8]+'.gif');copy_file(result['selected']['path'],destination,cancel=cancel)
            row.update(state='passed' if result['met'] else 'unmet',file=str(destination),result=result)
        except (CancelledError,InterruptedError):break
        except Exception as exc:row['error']=str(exc)
        rows.append(row);save_json(folder/'结果.json',{'target_bytes':target,'items':rows})
    return {**{name:sum(r['state']==name for r in rows) for name in ('passed','unmet','failed')},'pending':len(items)-len(rows),'items':rows,'folder':str(folder)}
