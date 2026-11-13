"""Display-only facts from saved task evidence; never an import permission."""
from pathlib import Path
from . import catalog


def collect(root,library):
    # Called on startup/record refresh/task completion, never while scrolling.
    root=Path(root);known={(c,i['id']):i for c,s in library['clients'].items() for i in s['items']}
    facts={};assets={}
    for path in sorted((root/'runtime-data/T005/queues').glob('*.json')):
        try:plan=catalog.read(path)
        except (OSError,ValueError):continue
        client=plan.get('source_client')
        if plan.get('schema')!='selected-workflow-v1' or client not in ('wechat','qq'):continue
        for job in plan.get('jobs',[]):
            key=(client,job.get('item_id'));item=known.get(key)
            if not item or not item.get('source_sha256'):continue
            asset_path=job.get('target_asset')
            # WeChat -> QQ stores its target asset in a one-item child plan.
            # Use it only after binding the full original hash below.
            if not asset_path and job.get('child_plan'):
                try:
                    child=catalog.read(job['child_plan'])
                    if child.get('schema')!='selected-transfer-v1' or len(child.get('jobs',[]))!=1:continue
                    single=child['jobs'][0]
                    if single.get('source_sha256')!=item['source_sha256']:continue
                    asset_path=single.get('target_asset')
                except (OSError,ValueError):continue
            if not asset_path:continue
            try:
                if asset_path not in assets:assets[asset_path]=catalog.read(asset_path)
                asset=assets[asset_path]
            except (OSError,ValueError):continue
            target='wechat' if client=='qq' else 'qq'
            # New observations/reused ordinals must never inherit old badges.
            if asset.get('source_sha256')!=item['source_sha256'] or asset.get('target')!=target:continue
            confirmed=(job.get('status')=='desktop_confirmed'
                       or (job.get('status')=='already_exists' and job.get('collection_persisted') is True)
                       or (job.get('collection_verified') is True and job.get('status') in ('add_executed','already_exists'))
                       or job.get('reason')=='exact_file_in_authenticated_local_favorites_index')
            state='confirmed' if confirmed else 'action_only' if job.get('status')=='add_executed' else 'pending' if job.get('status')=='pending_confirmation' else None
            if not state:continue
            old=facts.get(key)
            if old and old['state']=='confirmed' and not confirmed:continue
            facts[key]={'state':state,'target':target,'at':plan.get('updated') or plan.get('created'),
                        'queue':str(path),'reason':job.get('reason'),
                        'scope':'saved confirmation; current membership not rechecked'}
    return facts


def label(fact):
    if not fact:return ''
    target='微信' if fact['target']=='wechat' else 'QQ'
    return {'confirmed':f'重复 · 已添加到{target}（曾确认）','action_only':f'已执行添加到{target} · 待确认',
            'pending':'上次未完成 · 查看详情可恢复'}.get(fact['state'],'')
