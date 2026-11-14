"""Selected catalog originals feed the existing material transfer plan.

This is preparation, not a second sender. No thumbnail can satisfy an original.
"""
import hashlib
import json
from pathlib import Path
import uuid
import time

from emoji_bridge import catalog
from emoji_bridge.materials import now
from emoji_bridge.state import save_json, single_instance
from client_material_import import binding, create as create_import, run as import_originals


def profile_binding(profile):
    choice = json.loads((Path(profile) / 'runtime-data/client-sources.json').read_text('utf-8'))
    return hashlib.sha256(json.dumps(choice, sort_keys=True).encode()).hexdigest()


def check_profile(plan, profile):
    if not plan.get('profile_binding'): return
    profile = Path(profile).resolve()
    pointer = json.loads((profile.parent.parent / 'last-profile.json').read_text('utf-8'))
    if pointer.get('profile') != profile.name or profile_binding(profile) != plan['profile_binding']:
        raise ValueError('账号配置已经改变；请切回本任务账号，或重新选择素材和目标。未继续提交。')


def complete_target_configuration(plan, profile):
    """Only complete an unset destination; never retarget an existing account."""
    previous=plan.get('profile')
    if not previous or Path(previous).resolve()==Path(profile).resolve():return
    old=json.loads((Path(previous)/'runtime-data/client-sources.json').read_text('utf-8'))
    new=json.loads((Path(profile)/'runtime-data/client-sources.json').read_text('utf-8'))
    target_key='qq_ori' if plan['target']=='qq' else 'wechat_emoticon_db'
    source_key='wechat_emoticon_db' if plan['target']=='qq' else 'qq_ori'
    def same(a,b):return (str(Path(a).resolve()).casefold() if a else None)==(str(Path(b).resolve()).casefold() if b else None)
    if (old.get(target_key) or not new.get(target_key) or not same(old.get(source_key),new.get(source_key))
            or not new.get('read_authorized') or any(j.get('attempts') or j.get('submission_state','not_started')!='not_started' for j in plan['jobs'])):
        raise ValueError('已有账号或提交状态改变，请重新选择素材和目标；本任务未继续执行。')
    if plan.get('source_selection'):
        plan['source_profile']=str(Path(previous).resolve())
    plan.update(profile=str(Path(profile).resolve()),profile_binding=profile_binding(profile))


def create(store, rows, ids, target, profile, path, *, source_client=None):
    if target not in ('qq', 'wechat') or not ids: raise ValueError('请先选择表情和目标')
    opposite='wechat' if target=='qq' else 'qq'
    if source_client not in (None,opposite,'local'):
        raise ValueError('来源与目标相同；请在当前来源页选择另一端，不会重复导入本端收藏。')
    known = {row['id']: row for row in rows}
    if not {i for i in ids if not i.startswith('local:')} <= known.keys(): raise ValueError('所选列表已经改变，请重新选择')
    library = catalog.read(Path(profile) / 'runtime-data/T005/library.json')
    jobs = []
    for ident in dict.fromkeys(ids):
        if ident.startswith('local:'):
            if source_client not in (None,'local'):raise ValueError('所选项不属于当前来源页，请重新选择')
            item=store.get(ident[6:])
            jobs.append(dict(id=uuid.uuid4().hex,item_id=item['id'],source_sha256=item['id'],name=item['name'],target=target,status='queued',attempts=0,submission_state='not_started'))
            continue
        row = known[ident]
        members = [m for m in row['members'] if not m.get('unseen') and m['client']==opposite]
        # An exact cross-platform group still uses the explicitly selected
        # source. Never silently substitute a ready target-side original.
        if not members or source_client=='local':
            raise ValueError('所选项不属于当前转移来源，请重新选择；不会把目标端收藏再导入本端。')
        members.sort(key=lambda m:not m.get('original_ready'))
        ref = None
        if members:
            member = members[0]
            item = next(i for i in library['clients'][member['client']]['items'] if i['id'] == member['id'])
            ref = dict(client=member['client'], item_id=item['id'], binding=binding(item))
        jobs.append(dict(id=uuid.uuid4().hex, item_id='catalog:' + ident, name=row['name'],
                         target=target, source_ref=ref, status='queued', attempts=0, submission_state='not_started'))
    from emoji_bridge.compatibility_copy import settings
    plan = dict(schema='selected-transfer-v1', source_kind='local_material_library',
                library_root=str(store.root), target=target, profile=str(Path(profile).resolve()),
                profile_binding=profile_binding(profile), jobs=jobs, created=now(),
                compatibility=settings(store.root, target), source_selection=True,source_client=source_client or 'mixed_explicit',
                scope='explicit selected catalog originals; target membership requires separate evidence')
    if Path(path).exists(): raise ValueError('任务记录已存在，未覆盖')
    save_json(path, plan)
    return plan


def prepare(plan, path, profile, store, cancel, save, *, runner=import_originals):
    """Acquire/persist originals with existing receipts and retryable import jobs."""
    source_profile=Path(plan.get('source_profile') or profile)
    library_path = source_profile / 'runtime-data/T005/library.json'
    from qq_appearance_prepare import preparation_session
    from emoji_bridge.appearance_originals import evidence_session
    from emoji_bridge.media import inspection_session
    with single_instance(source_profile / 'runtime-data/T005/collection.lock'), preparation_session(), evidence_session(), inspection_session():
        check_profile(plan, profile)
        if runner is import_originals:
            library=catalog.read(library_path)
            known={i['id']:i for i in library['clients']['qq']['items']}
            requested=[]
            for job in plan['jobs']:
                ref=job.get('source_ref') or {}
                item=known.get(ref.get('item_id'))
                if (job['item_id'].startswith('catalog:') and ref.get('client')=='qq'
                        and plan['target']!='qq' and item and binding(item)==ref.get('binding')
                        and not item.get('original_available')):
                    requested.append(item['id'])
            if requested and not cancel.exists():
                from qq_selected_prepare import complete_selected
                try:complete_selected(library_path,list(dict.fromkeys(requested)),cancel)
                except (ValueError,OSError) as exc:
                    # Ready subset results have already been merged. Preserve
                    # the source failure for remaining items and never resend.
                    plan['selected_preparation_reason']=str(exc)
                    save()
        for job in plan['jobs']:
            if cancel.exists(): return
            if not job['item_id'].startswith('catalog:'): continue
            ref = job.get('source_ref')
            if (ref and ref.get('client')==plan['target'] and not job.get('attempts')
                    and job.get('submission_state','not_started')=='not_started'):
                job.update(status='failed',preparation_error='来源与目标相同，请在来源页选择另一端',reason='来源与目标相同，该项未提交')
                save();continue
            if not ref:
                job.update(status='waiting_original', preparation_error='本次未读到所选来源，请更新该来源后重新选择', reason='本次未读到所选来源，请更新该来源后重新选择')
                save(); continue
            try:
                check_profile(plan, profile)
                sub = path.parent / (path.stem + '-originals') / (job['id'] + '.json')
                if not sub.exists():
                    library = catalog.read(library_path)
                    item = next((i for i in library['clients'][ref['client']]['items'] if i['id'] == ref['item_id']), None)
                    if not item or binding(item) != ref['binding']: raise ValueError('所选收藏记录已变化，请重新选择')
                    create_import(library, ref['client'], [ref['item_id']], sub, {'acquire': True, 'allow_source_ui': False})
                else:
                    # Existing transfer plans retain their source identities
                    # and completed results. Preparation no longer opens QQ
                    # once per missing original before visiting the target.
                    original_plan=catalog.read(sub)
                    original_plan['options']['allow_source_ui']=False
                    save_json(sub,original_plan)
                job.update(status='acquiring_original', reason='正在校验并复用所选原件')
                save()
                started = time.perf_counter()
                def original_progress(n,t,message):
                    job['reason'] = message
                    job['original_preparation_seconds'] = round(time.perf_counter()-started,3)
                    save()
                result = runner(sub, library_path, store, cancel, progress=original_progress)
                job['original_preparation_seconds'] = round(time.perf_counter()-started,3)
                value = result['jobs'][0]
                if value.get('material_id'):
                    item = store.get(value['material_id'])
                    job.update(item_id=item['id'], source_sha256=item['id'], status='queued')
                    job.pop('preparation_error', None); job.pop('reason', None)
                elif cancel.exists():
                    job.update(status='queued', reason='原件准备已取消，未提交')
                else:
                    reason = value.get('reason', '原件待取得；请在来源客户端打开该收藏后重试')
                    job.update(status='waiting_original' if value['status']=='waiting' else 'failed', preparation_error=reason, reason=reason)
            except (ValueError, OSError) as exc:
                job.update(status='failed', preparation_error=str(exc), reason='原件获取失败：'+str(exc))
            save()
