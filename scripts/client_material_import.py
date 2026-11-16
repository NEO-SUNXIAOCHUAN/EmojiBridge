"""Selected client originals into the SAME MaterialStore; never submit to a client."""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
from emoji_bridge import catalog
from emoji_bridge.state import save_json
from emoji_bridge.media import inspection_session


def binding(item):
    value=[item['id'],item.get('scan'),item.get('member',{}).get('md5')]
    if item.get('cache_file'):value.append(item.get('source_sha256'))
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def create(library,client,ids,path,options):
    known={i['id']:i for i in library['clients'][client]['items'] if not i.get('source_receipt_only')}
    if not ids or not set(ids)<=known.keys():raise ValueError('请选择当前列表中的素材')
    if Path(path).exists():raise ValueError('入库记录已存在，未覆盖')
    plan={'schema':'client-material-import-v1','client':client,'created':datetime.now().astimezone().isoformat(),
          'options':options,'jobs':[{'item_id':ident,'binding':binding(known[ident]),'status':'queued'} for ident in dict.fromkeys(ids)]}
    plan['counts']={'queued':len(plan['jobs'])};save_json(path,plan);return plan


def verified_original(client,item):
    asset,origin=catalog.valid_original(item['asset'])
    if asset['target']!=client or origin.get('export_source_client')!=client:raise ValueError('原件平台来源不匹配')
    if item.get('source_sha256')!=asset['source_sha256']:raise ValueError('所选条目与原件摘要不匹配')
    from emoji_bridge.originals import validate_receipt
    receipt=validate_receipt(origin['original_provenance'],asset['source_sha256'])
    if client=='qq':
        from qq_snapshot import lookup
        proof=lookup(item)
        if not proof:raise ValueError('QQ所选收藏与原件关联尚未核验')
        scope=proof['membership_scope'];receipt_path=proof['receipt']
    else:
        if receipt.get('member',{}).get('md5')!=item.get('member',{}).get('md5'):raise ValueError('微信所选索引与原件关联不一致')
        scope='authenticated_local_favorite_index';receipt_path=origin['original_provenance']
    provenance={'schema':'client-material-source-v1','client':client,'item_id':item['id'],
                'sha256':asset['source_sha256'],'scope':scope,'receipt':receipt_path,
                'source_binding':binding(item),
                'content_key':item.get('content_key'),
                'current_client_membership_rechecked':False}
    return Path(asset['original_copy']),asset['source_sha256'],provenance


def reusable_original(client,item,store,profile=None):
    """Verify existing bytes first; flags do not cause a second acquisition.

    Managed-library fallback requires the same account-scoped observation binding.
    No filename, thumbnail or platform tag is a source-to-record association.
    """
    if item.get('asset') and item.get('source_sha256'):
        try:return verified_original(client,dict(item,original_state='ready'))
        except (OSError,ValueError,KeyError):pass
    with store.connect() as conn:
        rows=conn.execute('SELECT material_id,value FROM sources WHERE kind=?',(client,)).fetchall()
    for digest,value in rows:
        try:
            source=json.loads(value)
            if client=='qq' and source.get('receipt'):
                from emoji_bridge.appearance_originals import POLICY
                receipt=catalog.read(source['receipt'])
                if receipt.get('schema')=='qq-appearance-original-v1' and receipt.get('policy')!=POLICY:continue
            if (source.get('item_id')!=item['id'] or source.get('source_binding')!=binding(item)
                    or source.get('profile_scope')!=str(Path(profile or catalog.ROOT).resolve()) or source.get('sha256')!=digest):continue
            store.get(digest)
            from emoji_bridge.state import sha
            original=store.original(digest)
            if sha(original)==digest:return original,digest,source
        except (OSError,ValueError,KeyError):continue
    return None


class Cancel:
    def __init__(self,path):self.path=Path(path)
    def is_set(self):return self.path.exists()


@inspection_session()
def run(path,library_path,store,cancel,*,progress=None,acquire=None,verify=None):
    path=Path(path);cancel=Path(cancel);token=Cancel(cancel);plan=catalog.read(path)
    library=catalog.read(library_path);client=plan['client'];options=plan['options']
    reused={}
    known={i['id']:i for i in library['clients'][client]['items']};last_flush=time.monotonic();changed=False
    def record():
        plan['counts']=dict(Counter(j['status'] for j in plan['jobs']));save_json(path,plan)
    plan['run_state']='running';record()
    for n,job in enumerate(plan['jobs']):
        if token.is_set():break
        if job['status'] in ('added','existing'):continue
        job.pop('reason',None)
        try:
            item=known.get(job['item_id'])
            if not item or binding(item)!=job['binding']:raise ValueError('所选收藏记录已改变，请从当前列表重新选择')
            from collection_files import original as selected_original
            original,digest,source=selected_original(client,item,library,Path(library_path).resolve().parents[2],cancel)
            source=dict(source,source_binding=binding(item),profile_scope=str(Path(library_path).resolve().parents[2]))
            from emoji_bridge.card_names import collection_name_origin
            material,duplicate=store.import_file(original,kind=client,name=item.get('label'),name_origin=collection_name_origin(item,client),source=json.dumps(source,ensure_ascii=False,sort_keys=True),expected_sha=digest,cancel=token)
            item.update(managed_original=str(store.original(material['id'])),original_state='ready',original_available=True,source_sha256=digest)
            if source.get('scope')=='saved_favorite_appearance_match':item['matching_basis']='appearance'
            else:item.pop('matching_basis',None)
            changed=True
            store.organize([material['id']],add_tags=options.get('tags',()),add_collections=options.get('collections',()))
            job.update(status='existing' if duplicate else 'added',material_id=material['id'])
        except InterruptedError:
            job['status']='queued';break
        except Exception as exc:job.update(status='failed',reason=str(exc))
        finally:
            if time.monotonic()-last_flush>1 or n%8==7:
                if changed:catalog.save(library,library_path);changed=False
                record();last_flush=time.monotonic()
            if progress:progress(n+1,len(plan['jobs']),'保存原件到素材库')
    if changed:catalog.save(library,library_path)
    plan['run_state']='cancelled' if token.is_set() else 'finished';record();return plan


def summary(plan):
    counts=plan.get('counts',{});total=len(plan['jobs'])
    text=f"素材入库：共 {total} 项；新增 {counts.get('added',0)}，已存在 {counts.get('existing',0)}，失败 {counts.get('failed',0)}，待取得原件 {counts.get('waiting',0)}，未处理 {counts.get('queued',0)}。"
    if plan.get('run_state')=='cancelled':text+=' 已取消；完成项保留。'
    details=[f"{j['item_id']}：{j.get('reason',j['status'])}" for j in plan['jobs'] if j['status'] not in ('added','existing')]
    return text+'\n未发送或修改客户端收藏。'+ ('\n'+'\n'.join(details[:30]) if details else '')
