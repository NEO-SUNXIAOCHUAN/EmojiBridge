"""A captured account context; reuses current read/import workflows, never submits media."""
import hashlib,json,os,sys,time
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
    started=time.perf_counter()
    kind=('更新' if request['action']=='refresh' else '原件入库' if request['action']=='import' else '本地预览')+(' QQ 收藏' if client=='qq' else '微信收藏')
    with task_scope(Path(request.get('request',request['status'])).parent.name,kind,cancel=cancel.exists,on_wait=waiting if request.get('manual') else None),single_instance(profile/'runtime-data/T005/collection.lock'):
        catalog.bootstrap()
        if request['action']=='enrich':
            from collection_enrich import enrich
            return enrich(catalog.PATH,client,request['ids'],cancel,progress,priority_file=Path(request['request']).with_name('priority.json'))
        if request['action']=='previews':
            if client!='wechat':raise ValueError('该预览不支持当前平台')
            from wechat_catalog import PreviewReader
            progress(stage='加载当前页预览；原件状态不变')
            value=PreviewReader().load(catalog.PATH,request['ids'][:18],cancel,repair_ids=request['ids'][:18] if request.get('retry') else (),update_catalog=False)
            return {'text':'当前页预览已检查；原件在入库时取得。'}
        if request['action']=='import':
            from client_material_import import create,run as import_run,summary
            store=MaterialStore(request['store']);plan=Path(request['plan']).resolve()
            if not plan.is_relative_to(profile/'runtime-data/T005'):raise ValueError('入库记录不属于当前账号')
            if not plan.exists():create(catalog.read(catalog.PATH),client,request['ids'],plan,{'acquire':True})
            value=import_run(plan,catalog.PATH,store,cancel,progress=progress)
            return {'text':summary(value),'counts':value['counts'],'items':[j['material_id'] for j in value['jobs'] if j.get('material_id')],
                    'failed':bool(value['counts'].get('failed') or value['counts'].get('waiting') or value['counts'].get('queued')),'seconds':time.perf_counter()-started}
        if client=='wechat':
            from wechat_prepare import prepare
            result=prepare(catalog.PATH,cancel,lambda n,t:progress(n,t,'读取已认证微信索引'),index_only=True,preview_first=False)
            if result['status']!='index_ready':raise ValueError(result.get('reason','微信索引未就绪'))
        else:
            from qq_catalog import scan,MAX_SCAN_VIEWS
            if request.get('manual'):
                progress(stage='打开 QQ 收藏并读取视图（不发送）')
                path,result=scan(MAX_SCAN_VIEWS,cancel,progress=lambda p,r:progress(len(r['items']),0,f'已读 {len(r["pages"])} 个收藏视图'))
            else:
                from qq_catalog import scan_visible
                progress(stage='检查 QQ 已打开的收藏首屏；不切窗口')
                try:path,result=scan_visible(cancel,request.get('visible_signature'))
                except Exception as exc:
                    if str(exc) not in ('qq_background_update_needs_visible_favorites','qq_background_update_needs_first_view',
                                         'foreground_changed','window_not_visible','qq_uia_personal_favorites_not_open','qq_uia_favorites_loading_timeout'):
                        raise
                    return {'needs_update':True,'text':'QQ 自动检查未取得新视图。请打开 QQ → 表情 → 我的收藏首屏；或点“更新”完整读取。',
                            'reason':str(exc),'seconds':time.perf_counter()-started}
                if result.get('unchanged'):return {'text':'QQ 已打开收藏首屏未变化；不代表云端全库。','visible_signature':result['visible_signature'],
                                                  'read_succeeded':True,'coverage':'当前已打开收藏首屏'}
            if cancel.exists():raise InterruptedError('已取消更新，保留上次读取结果')
            library=catalog.read(catalog.PATH)
            catalog.merge_qq(library,path,cancel=cancel.exists,match_originals=False,
                             progress=lambda n,t:progress(n,t,'整理已读收藏；原件按所选项校验'))
            catalog.save(library)
            if not result.get('items'):raise ValueError(result.get('reason','未读到收藏，保留旧数据'))
        side=catalog.read(catalog.PATH)['clients'][client]
        text=f'已读取 {len(side["items"])} 项；仅此账号的本地读取范围。'
        if client=='qq':text+=' 原件按当前页或所选项补齐，可直接选择互通。'
        if client=='qq' and not request.get('manual'):
            text=f'已检查收藏首屏；QQ 当前加载 {result.get("loaded_favorite_controls",0)} 条。其他位置请点“更新”补读。'
        return {'text':text,'seconds':time.perf_counter()-started,
                'read_succeeded':True,'coverage':('当前已打开收藏首屏' if client=='qq' and not request.get('manual') else side.get('scope')),
                'visible_signature':result.get('visible_signature'),
                'snapshot_at':side.get('snapshot_at'),
                'count':len(result['items']) if client=='qq' and not request.get('manual') else len(side['items']),
                'report':str(path) if client=='qq' else side.get('source_report')}


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
