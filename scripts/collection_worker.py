"""A captured account context; reuses current read/import workflows, never submits media."""
import hashlib,json,os,sys,time
from contextlib import nullcontext
from pathlib import Path
APP=Path(__file__).resolve().parents[1];sys.path[:0]=[str(APP/'src'),str(APP/'scripts')]


def run(request):
    from emoji_bridge import paths
    profile=Path(request['profile']).resolve()
    choice=json.loads((profile/'runtime-data/client-sources.json').read_text('utf-8'))
    identity='\0'.join(str(Path(choice[k]).resolve()).casefold() if choice.get(k) else 'disabled:'+k for k in ('wechat_emoticon_db','qq_ori'))
    if hashlib.sha256(identity.encode()).hexdigest()[:24]!=profile.name:raise ValueError('账号路径已变化，请重新选择')
    paths.configure_data_root(profile)
    from emoji_bridge import catalog
    from emoji_bridge.state import save_json,single_instance,task_scope,task_progress,waiting_text
    from emoji_bridge.materials import MaterialStore
    cancel=Path(request['cancel']);status=Path(request['status']);client=request['client']
    def progress(n=0,total=0,stage='读取收藏'):
        task_progress(stage)
        save_json(status,{'active':True,'text':stage,'completed':n,'total':total})
    def waiting(owner):
        if owner:save_json(status,{'active':True,'text':waiting_text(owner),'waiting_for':owner})
    # Published catalogs are atomic snapshots. Copying already available files
    # is read-only: never take the scanner's write lock or save a stale snapshot.
    if request['action']=='copy':
        from collection_files import local_original
        library=catalog.read(catalog.PATH)
        item=next((i for i in library['clients'][client]['items'] if i['id']==request['ids'][0]),None)
        if not item:raise ValueError('读取条目已变化，请重新选择')
        available=local_original(client,item,profile,cancel)
        if available:
            file,digest,source=available
            return dict(file=str(file),sha256=digest,text='复制文件已准备')
    started=time.perf_counter()
    kind=('更新' if request['action']=='refresh' else '原件入库' if request['action']=='import' else '本地预览')+(' QQ 收藏' if client=='qq' else '微信收藏')
    cache_read=client=='qq' and request['action']=='refresh'
    lock=profile/'runtime-data/T005/collection.lock'
    with task_scope(Path(request.get('request',request['status'])).parent.name,kind,cancel=cancel.exists,on_wait=waiting if request.get('manual') else None), (nullcontext() if cache_read else single_instance(lock)):
        with single_instance(lock) if cache_read else nullcontext():catalog.bootstrap()
        if request['action']=='copy':
            from collection_files import original
            library=catalog.read(catalog.PATH)
            item=next((i for i in library['clients'][client]['items'] if i['id']==request['ids'][0]),None)
            if not item:raise ValueError('读取条目已变化，请重新选择')
            file,digest,source=original(client,item,library,profile,cancel)
            catalog.save(library)
            return dict(file=str(file),sha256=digest,text='复制文件已准备')
        if client=='qq' and request['action']=='refresh':
            from emoji_bridge.cache_listing import scan,catalog_side
            root=choice.get('qq_ori')
            if not root:raise ValueError('请先选择 QQ 个人表情缓存目录')
            index=scan(root,profile/'runtime-data/cache-read/qq.json',cancel=cancel.exists,
                progress=lambda n,t,c:progress(n,t,f'读取本地缓存 {n}/{t} · 完整 {c["ready"]} · 失败 {c["failed"]} · 等待稳定 {c["waiting"]}'))
            with single_instance(lock):
                library=catalog.read(catalog.PATH)
                previous=library['clients'].get('qq',{})
                if previous and previous.get('source_kind')!='personal_cache_directory':
                    archive=profile/'runtime-data/T005/legacy-qq-before-cache.json'
                    if not archive.exists():save_json(archive,previous)
                library['clients']['qq']=catalog_side(index)
                catalog.save(library)
            count=len(library['clients']['qq']['items']);counts=index['counts']
            return dict(text=f'本地缓存 {count} 项；未加入素材库。失败 {counts["failed"]}，等待稳定 {counts["waiting"]}。',
                read_succeeded=index['state']=='complete',count=count,counts=counts,
                coverage='整个所选缓存目录',report=str(profile/'runtime-data/cache-read/qq.json'),seconds=time.perf_counter()-started)
        if request['action']=='import':
            from collection_files import original
            from client_material_import import Cancel
            store=MaterialStore(request['store']);library=catalog.read(catalog.PATH)
            known={i['id']:i for i in library['clients'][client]['items']}
            requested=list(dict.fromkeys(request['ids']))
            if not requested or not set(requested)<=known.keys():raise ValueError('请重新选择当前列表中的表情')
            plan_path=Path(request['plan']).resolve()
            if not plan_path.is_relative_to(profile/'runtime-data/T005'):raise ValueError('入库记录路径无效')
            plan=catalog.read(plan_path) if plan_path.exists() else {'jobs':[]}
            completed={j['item_id'] for j in plan['jobs'] if j.get('material_id')}
            for n,ident in enumerate(requested):
                if cancel.exists():break
                if ident in completed:continue
                item=known[ident];job={'item_id':ident}
                try:
                    file,digest,source=original(client,item,library,profile,cancel)
                    material,duplicate=store.import_file(file,kind=client,name=item.get('label'),
                        source=json.dumps(source,ensure_ascii=False,sort_keys=True),expected_sha=digest,cancel=Cancel(cancel))
                    job.update(material_id=material['id'],status='restored' if material.get('restored') else 'existing' if duplicate else 'added')
                except InterruptedError:break
                except (OSError,ValueError) as exc:job.update(status='failed',reason=str(exc))
                plan['jobs']=[j for j in plan['jobs'] if j['item_id']!=ident]+[job]
                save_json(plan_path,plan);catalog.save(library)
                progress(n+1,len(requested),'仅将选中项加入素材库')
            items=[j['material_id'] for j in plan['jobs'] if j.get('material_id')]
            return dict(text=f'已处理选中项 {len(plan["jobs"])} / {len(requested)}；未操作客户端。',items=items,
                        failed=any(j.get('status')=='failed' for j in plan['jobs']))
        if client=='qq':return {'text':'本地缓存预览已准备；无需来源窗口操作。'}
        if request['action']=='enrich':
            from collection_enrich import enrich
            return enrich(catalog.PATH,client,request['ids'],cancel,progress,priority_file=Path(request['request']).with_name('priority.json'))
        if request['action']=='previews':
            if client!='wechat':raise ValueError('该预览不支持当前平台')
            from wechat_catalog import PreviewReader
            progress(stage='加载当前页预览；原件状态不变')
            value=PreviewReader().load(catalog.PATH,request['ids'][:18],cancel,repair_ids=request['ids'][:18] if request.get('retry') else (),update_catalog=False)
            return {'text':'当前页预览已检查；原件在入库时取得。'}
        from wechat_prepare import prepare
        result=prepare(catalog.PATH,cancel,lambda n,t:progress(n,t,'读取已认证微信索引'),index_only=True,preview_first=False)
        if result['status']!='index_ready':raise ValueError(result.get('reason','微信索引未就绪'))
        side=catalog.read(catalog.PATH)['clients']['wechat']
        return dict(text=f'已读取 {len(side["items"])} 项；未加入素材库。',seconds=time.perf_counter()-started,
                    read_succeeded=True,coverage=side.get('scope'),count=len(side['items']),report=side.get('source_report'))



def execute(request):
    from emoji_bridge.state import ResourceBusy
    try:return run(request)
    except ResourceBusy as exc:
        owner=exc.owner
        return {'deferred':True,'waiting_for':owner,'reason':'client_resource_in_use',
                'text':'正在执行'+(owner.get('kind') or '另一项客户端操作')+'；本次检查未完成，任务结束后可点更新，原列表保留。'}
    except Exception as exc:
        from emoji_bridge.compatibility import failure_text
        reason=str(exc)
        return {'failed':True,'reason':reason,'text':failure_text(request['client'],reason)}


if __name__=='__main__':
    from emoji_bridge.state import save_json
    request=json.loads(Path(sys.argv[1]).read_text('utf-8'))
    result=execute(request)
    save_json(request['status'],dict(result,active=False))
