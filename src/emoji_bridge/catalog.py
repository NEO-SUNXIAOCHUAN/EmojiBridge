"""Library model: discovery, original acquisition and transfer are separate."""
from datetime import datetime
import json
from pathlib import Path
from .state import save_json
from .media import load_asset,prepare_asset
from .originals import origin_for_asset,attach_receipt

from . import paths

def __getattr__(name):
    # A launcher can import read-only checks before selecting an account.
    # Resolve defaults at use time; callers capture the path for each job.
    if name=='ROOT':return paths.DATA_ROOT
    if name=='PATH':return paths.DATA_ROOT/'runtime-data/T005/library.json'
    raise AttributeError(name)
LABELS={'discovered':'已发现 · 待获取原件','ready':'已取得原件','unavailable':'暂时无法获取',
        'downloaded':'原件已取 · 收藏待核验'}


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def valid_original(asset):
    a=load_asset(asset);origin=origin_for_asset(a)
    if not origin.get('exported_from_client'):raise ValueError('source_client_original_required')
    return a,origin


def attach_original(item,asset):
    a,origin=valid_original(asset)
    # A current QQ observation already has a tiny, correctly bound preview.
    # Do not replace it with a potentially large GIF decoded on the GUI thread.
    preview=item.get('preview') if item.get('scan') else None
    item.update(original_state='ready',original_available=True,asset=str(Path(asset).resolve()),preview=preview or a['original_copy'],
                format=a['original_metadata']['format'],frames=a['original_metadata']['frames'],
                source_sha256=a['source_sha256'],reason=None)
    if not preview:
        # A verified original replaces an earlier failed preview-only fetch.
        item.pop('preview_error',None);item.pop('preview_kind',None)
    for key in ('failure_kind','diagnostic','acquisition_report'):item.pop(key,None)
    # Collapse only decoded FULL media identity, not similar thumbnails.
    # Preserve each observation/receipt in storage for source validation.
    import hashlib
    from PIL import Image
    meta=a['original_metadata']
    with Image.open(a['original_copy']) as image:
        icc=image.info.get('icc_profile') or b''
        colour=[hashlib.sha256(icc).hexdigest(),image.info.get('gamma'),image.info.get('srgb')]
    key=[meta['oriented_size'],meta['frame_pixel_hashes'],
         meta['durations_ms'] if meta['frames']>1 else [],meta['loop'] if meta['frames']>1 else None,colour]
    item['content_key']=hashlib.sha256(json.dumps(key,sort_keys=True).encode()).hexdigest()


def apply_acquisition(item,result):
    if result.get('status')=='original_verified':
        attach_original(item,result['asset'])
        if (result.get('source_route')=='personal_cache_and_current_favorite_ui'
                and result.get('item_id')==item['id']):
            item.pop('matching_basis',None)
        if result.get('source_snapshot'):item['source_snapshot']=result['source_snapshot']
        return
    item.update(acquisition_report=result['report'],reason=result.get('reason','结果待确认'),
                failure_kind=result.get('failure_kind'),original_available=False)
    if result.get('status')=='downloaded_pending_verification':
        meta=result['metadata']
        item.update(original_state='downloaded',preview=result.get('display_preview') or result['downloaded_file'],
                    format=meta['format'],frames=meta['frames'],source_sha256=meta['sha256'])
    elif result.get('failure_kind')=='cancelled':
        # A cancelled acquisition is not evidence that the file is unavailable.
        item.setdefault('original_state','discovered')
    else:item['original_state']='unavailable'


def save(library,path=None,*,compact=False):
    path=path if path is not None else __getattr__('PATH')
    # Selection is deliberately transient; restarting never selects everything.
    for side in library['clients'].values():
        for item in side['items']:item.pop('selected',None)
        collapse_identical(side)
    library['updated']=datetime.now().astimezone().isoformat()
    options={'compact':True} if compact else {}
    save_json(path,library,**options)


def display_items(side):
    return [i for i in side['items'] if not i.get('source_receipt_only') and not i.get('duplicate_of')]


def collapse_identical(side):
    representatives={};count=0
    for item in side['items']:
        item.pop('duplicate_of',None);item.pop('duplicate_count',None)
        if item.get('source_receipt_only') or item.get('matching_basis')=='appearance' or item.get('original_state')!='ready' or not item.get('original_available') or item.get('transfer_block_reason'):continue
        key=item.get('content_key')
        if not key:continue  # Older/unverified entries are not guessed.
        if key in representatives:
            first=representatives[key];item['duplicate_of']=first['id'];count+=1
            first['duplicate_count']=first.get('duplicate_count',1)+1
        else:representatives[key]=item
    side['identical_entries_collapsed']=count


def normalize_qq_snapshot(library):
    if library.get('clients',{}).get('qq',{}).get('source_kind')=='personal_cache_directory':return False
    """Migrate old saved originals out of the latest observed-favorites list.

    An absent item may be on an unread page; archive it, never call it deleted.
    The cache inventory cannot establish membership and is never merged here.
    """
    side=library.get('clients',{}).get('qq',{});source=side.get('source_report')
    if not source or side.get('current_snapshot_only'):return False
    report=read(source)
    if report.get('schema')!='qq-favorite-observations-v1':raise ValueError('not_qq_favorite_scan')
    observed={i['id'] for i in report['items']};items=[];archive=list(side.get('retained_originals',[]))
    for item in side['items']:
        if item['id'] in observed and not item.get('source_receipt_only'):items.append(item)
        elif item.get('original_state')=='ready':archive.append(dict(item,source_receipt_only=True))
    unique={i['asset']:i for i in archive}
    side.update(items=items,retained_originals=list(unique.values()),retained_originals_count=len(unique),
                observations_count=len(items),current_snapshot_only=True)
    return True


def bootstrap(path=None):
    path=Path(path) if path is not None else __getattr__('PATH')
    ROOT=path.parent.parent.parent
    if path.exists():
        library=read(path)
        if library.get('clients',{}).get('qq',{}).get('source_kind')=='personal_cache_directory':return library
        if normalize_qq_snapshot(library):save(library,path)
        return library
    library={'schema':'bridge-library-v1','clients':{}}
    reports=[]
    for p in (ROOT/'reports/T004-index').glob('*.json'):
        r=read(p)
        if isinstance(r,dict) and r.get('status')=='index_decrypted_and_integrity_verified' and r.get('index_members'):
            reports.append((p,r))
    if reports:
        p,r=max(reports,key=lambda pr:pr[1].get('at',''))
        items=[{'id':'wechat:'+m['md5'],'label':'微信收藏 '+m['md5'][:8],'name_origin':'generated','member':m,
                'original_state':'discovered','preview':None} for m in r['index_members']]
        library['clients']['wechat']={'complete':False,'scope':'本地收藏索引快照；云端完整性未证明',
                                      'source_report':str(p),'items':items,'snapshot_at':r.get('at')}
        assets=ROOT/'private/T004-index/assets.json'
        for entry in read(assets) if assets.exists() else []:
            if entry['target']!='wechat':continue
            a,origin=valid_original(entry['asset']);receipt=read(origin['original_provenance'])
            found=next((x for x in items if x['member']['md5']==receipt['member']['md5']),None)
            if found:attach_original(found,entry['asset'])
    else:library['clients']['wechat']={'complete':False,'scope':'尚未读取','items':[]}
    library['clients']['qq']={'complete':False,'scope':'尚未读取','items':[]}
    # Historical scan receipts stay on disk; new reads use the selected cache.
    save(library,path);return library


def merge_qq(library,report_path,*,cancel=None,progress=None,match_originals=True):
    ROOT=paths.DATA_ROOT
    from PIL import Image
    from .media import references
    from .recognition import find_in_cells,FrameMatcher
    r=read(report_path)
    if r.get('schema')!='qq-favorite-observations-v1':raise ValueError('not_qq_favorite_scan')
    previous=library['clients'].get('qq',{})
    if previous.get('snapshot_at') and r.get('at','')<previous['snapshot_at']:return
    if not r.get('items'):
        side=library['clients'].setdefault('qq',{'complete':False,'scope':'尚未读取','items':[]})
        side['last_read_failure']={'report':str(report_path),'reason':r.get('reason','没有可确认的新条目')}
        return
    old=[*previous.get('items',[]),*previous.get('retained_originals',[])]
    # Old originals remain as source receipts, not guessed onto a new position.
    retained=list({i['asset']:i for i in old if i.get('original_state')=='ready' and i.get('asset')}.values())
    items=[dict(i,scan=str(Path(report_path).resolve())) for i in r['items']]
    from .state import sha
    # Presentation keys describe a position + exact observed cover, NOT full
    # media identity. They never participate in duplicate/transfer evidence.
    def observation(item):
        if item.get('observation_key'):return item['observation_key']
        try:return str(item['position'])+':'+sha(item['preview'])
        except (OSError,KeyError,TypeError):return item['id']
    for item in items:item['observation_key']=observation(item)
    def viewport(item):
        # The stable observation key may belong to its older position after a
        # newly inserted favorite. Compare today's position and captured cover
        # for refresh no-ops, without resetting an already verified original.
        try:return (item.get('display_position',item['position']),sha(item['preview']))
        except (KeyError,OSError,TypeError):return observation(item)
    if (len(items)<=len(previous.get('items',[])) and (r.get('passive') or len(items)==len(previous.get('items',[]))) and
            [viewport(i) for i in items]==[viewport(i) for i in previous.get('items',[])[:len(items)]]):
        previous.update(last_checked_at=r['at'],last_checked_report=str(report_path))
        if not r.get('passive'):previous['snapshot_at']=r['at']
        previous.pop('last_read_failure',None)
        return
    seen={i.get('source_sha256') for i in retained}
    for p in ((ROOT/'private/T004-originals/assets').glob('*/qq-edge0/asset.json') if match_originals else ()):
        try:
            a,origin=valid_original(p)
            if a['source_sha256'] in seen:continue
            item={'id':'qq:original:'+a['source_sha256'],'label':'QQ 已取得原件 '+a['source_sha256'][:8],
                  'source_receipt_only':True};attach_original(item,p);retained.append(item);seen.add(a['source_sha256'])
        except ValueError:continue
    # An unchanged captured cover can carry a candidate path across a moved
    # viewport. This is only an appearance hint, never current membership or
    # full-animation identity. Ambiguous covers keep the ordinary matching path.
    def cover(item):
        try:return sha(item['preview'])
        except (OSError,KeyError,TypeError):return None
    new_covers={};old_covers={}
    for item in items:
        key=cover(item)
        if key:new_covers.setdefault(key,[]).append(item)
    for item in old:
        key=cover(item)
        if key and item.get('asset'):old_covers.setdefault(key,set()).add(item['asset'])
    unbound=[]
    def check_cancel():
        if cancel and cancel():raise InterruptedError('已取消原件关联，保留上次读取结果')
    # A reference's normalized frames are independent of the viewport. Reuse
    # its bounded matcher across pages instead of decoding/resizing it per page.
    for number,original in enumerate(retained):
        check_cancel()
        if progress and (match_originals or number%32==0):progress(number,len(retained))
        key=cover(original);unchanged=new_covers.get(key,[])
        if len(unchanged)==1 and old_covers.get(key)=={original['asset']}:
            # Do not re-hash and decode the whole old library just to show new
            # observations. The original-acquisition path must validate this
            # candidate before use; no ready/target receipt is inherited here.
            unchanged[0].update({k:original[k] for k in ('asset','format','frames','source_sha256','content_key') if k in original})
            unchanged[0].update(matching_basis='appearance',original_state='downloaded',original_available=False)
            unbound.append(dict(original,source_receipt_only=True));continue
        if not match_originals:
            # A directory refresh must not decode every historical animation
            # against every new viewport. Keep the complete old receipts;
            # visible/selected-item acquisition validates originals on demand.
            unbound.append(dict(original,source_receipt_only=True));continue
        try:a,_=valid_original(original['asset'])
        except (OSError,ValueError):
            unbound.append(dict(original,source_receipt_only=True));continue
        refs=references(a);positions=set();matcher=FrameMatcher(refs)
        for page in r['pages']:
            check_cancel()
            with Image.open(page['image']) as image:
                hits=find_in_cells(image,refs,[c['rect'] for c in page['cells']],matcher=matcher)
            for hit in hits:
                for cell in page['cells']:
                    l,t,rr,b=cell['rect']
                    if l<=hit.center[0]<rr and t<=hit.center[1]<b:positions.add(cell['position'])
        if len(positions)==1:
            match=next((i for i in items if i['position']==next(iter(positions))),None)
            if match:
                # A visual hit in a new scan is a lead; the old receipt does
                # not bind this new observation. Acquisition must prove it.
                attach_original(match,original['asset'])
                match.update(matching_basis='appearance',original_state='downloaded',original_available=False)
                unbound.append(dict(original,source_receipt_only=True));continue
        unbound.append(dict(original,source_receipt_only=True))
    check_cancel()
    if progress:progress(len(retained),len(retained))
    coverage=None
    from .collection_view import extend_visible_qq
    extension=extend_visible_qq(previous,items)
    if extension and r.get('passive'):items,coverage=extension
    library['clients']['qq']={'complete':False,'scope':f'本次读取 {len(r["pages"])} 个收藏视图；未读到的不显示，非全库',
        'source_report':str(report_path),'items':items,'observations_count':len(items),
        'retained_originals':unbound,'current_snapshot_only':True,
        'retained_originals_count':len(unbound),'snapshot_at':r['at'],'read_reason':r.get('reason')}
    if coverage:
        library['clients']['qq'].update(observations_count=len(items),visible_update=coverage,
            scope=f'本次首屏 {coverage["visible"]} 项；另保留以前读到的 {coverage["preserved"]} 项，未重新核验尾部；非云端全库')
    # Every caller (including post-transfer refresh) must retain observations.
    # Keeping this only in collection_worker dropped history after a successful
    # transfer, even though both paths used the same scanner.
    from .collection_view import retain_unseen
    retain_unseen(previous,library['clients']['qq'])
    if len(items)<previous.get('observations_count',0):
        library['clients']['qq']['previous_larger_snapshot']={
            'report':previous.get('source_report'),'observations_count':previous['observations_count'],
            'snapshot_at':previous.get('snapshot_at'),'meaning':'historical read retained, not evidence of deletion'}


def counts(side):
    states=[i['original_state'] for i in display_items(side)]
    result={'discovered':side.get('observations_count',len(states)),'ready':states.count('ready'),'waiting':states.count('discovered'),
            'unavailable':states.count('unavailable'),'complete':side.get('complete') is True}
    if 'downloaded' in states:result['downloaded_pending']=states.count('downloaded')
    return result


def merge_wechat(library,report_path):
    report=read(report_path)
    if (report.get('status')!='index_decrypted_and_integrity_verified' or not report.get('snapshot_current_consistent')
            or len(report.get('index_members',[]))!=report.get('index_count')):
        raise ValueError('full_authenticated_local_index_required')
    previous=library['clients']['wechat']
    if previous.get('snapshot_at') and report.get('at','')<previous['snapshot_at']:return
    old={r['item']['id']:r['item'] for r in previous.get('unseen_observations',[])}
    old.update({i['id']:i for i in previous['items']});items=[];seen=set()
    for member in report['index_members']:
        ident='wechat:'+member['md5']
        if ident in seen:raise ValueError('duplicate_member_identity')
        seen.add(ident)
        item=dict(old.get(ident,{'id':ident,'label':'微信收藏 '+member['md5'][:8],'name_origin':'generated',
                               'original_state':'discovered','preview':None}))
        item['member']=member;items.append(item)
    summary=report.get('membership_summary',{})
    scope='已认证本地收藏索引；云端完整性未证明'
    if summary.get('builtin_actions_count'):
        scope+=f"；另有 {summary['builtin_actions_count']} 项内置互动表情（骰子/猜拳），不作为图片搬运"
    library['clients']['wechat']={'complete':False,'scope':scope,'membership_summary':summary,
        'source_report':str(Path(report_path).resolve()),'snapshot_at':report['at'],'items':items,
        'previous_items_absent_from_snapshot':len(set(old)-seen)}
    from .collection_view import retain_unseen
    retain_unseen(previous,library['clients']['wechat'])


def transfer_selection(library,client,ids,storage):
    if client not in ('qq','wechat') or not ids:raise ValueError('explicit_nonempty_selection_required')
    items={x['id']:x for x in display_items(library['clients'][client])}
    if len(set(ids))!=len(ids):raise ValueError('duplicate_selection')
    selected=[]
    for ident in ids:
        item=items.get(ident)
        if not item or item.get('original_state')!='ready':raise ValueError('selected_original_not_ready')
        a,origin=valid_original(item['asset'])
        if a['target']!=client:raise ValueError('source_client_mismatch')
        target='wechat' if client=='qq' else 'qq'
        path,_=prepare_asset(Path(a['original_copy']),target,storage)
        attach_receipt(path,origin['original_provenance'])
        selected.append({'source_asset':item['asset'],'target_asset':str(path)})
    return selected
