"""One bounded source-only completion pass for unresolved observed favorites."""
from datetime import datetime
from pathlib import Path
from emoji_bridge import catalog
from emoji_bridge.state import save_json
import qq_snapshot
from qq_variant_probe import observe
from qq_resolve_variants import resolve,discover_from_hovers


def complete_observed(library_path=None,cancel=None,progress=None):
    library_path=Path(library_path) if library_path is not None else catalog.PATH
    from qq_appearance_prepare import prepare as prepare_appearance
    appearance=prepare_appearance(library_path,cancel)
    # A new, local-only correspondence route runs before any native hover.
    # Its unchanged pending results are cached; it never repeats a window scan.
    from qq_thumb_prepare import prepare as prepare_thumbnails
    thumbnails=prepare_thumbnails(library_path,cancel)
    library=catalog.read(library_path);side=library['clients']['qq'];source=side.get('source_report')
    prior=side.get('variant_preparation',{})
    if prior.get('scan')==source:
        if thumbnails.get('results') or appearance.get('results'):
            prior.update(ready=sum(qq_snapshot.reusable(i) for i in side['items']),observed=len(side['items']),
                         thumbnail_preparation=thumbnails,appearance_preparation=appearance)
            if prior['ready']==prior['observed']:
                prior['state']='finished';prior.pop('reason',None)
            catalog.save(library,library_path)
        return prior
    pending=[i for i in side['items'] if not qq_snapshot.reusable(i)]
    result={'scan':source,'at':datetime.now().astimezone().isoformat(),'state':'preparing',
            'attempted':len(pending),'processed':0,'messages_sent':0,'reports':[],
            'thumbnail_preparation':thumbnails,'appearance_preparation':appearance}
    side['variant_preparation']=result;catalog.save(library,library_path)
    try:
        for start in range(0,len(pending),6):
            chosen=pending[start:start+6]
            if progress:progress(f'补读 QQ 原件对应：{start+1}～{start+len(chosen)} / {len(pending)}；仅操作收藏面板，不发送。')
            probe=observe(source,[i['position'] for i in chosen],cancel)
            result['reports'].append(probe['report'])
            if probe['status']!='observed_only':raise ValueError(probe.get('reason','variant_observation_stopped'))
            missing=[]
            for item in chosen:
                path=item.get('candidate_evidence')
                candidates=catalog.read(path).get('candidates',{}) if path else {}
                if not candidates:
                    missing.append(item['position'])
            if missing:
                if progress:progress(f'共用一次本地文件搜索，对应 {len(missing)} 项 QQ 收藏；不会发消息。')
                discover_from_hovers(library_path,probe['report'],missing,cancel)
            resolve(library_path,probe['report'],cancel)
            result['processed']+=len(chosen)
        result['state']='finished'
    except Exception as exc:
        result.update(state='stopped',reason=str(exc))
    library=catalog.read(library_path);side=library['clients']['qq']
    result.update(ready=sum(qq_snapshot.reusable(i) for i in side['items']),observed=len(side['items']))
    side['variant_preparation']=result;catalog.save(library,library_path)
    return result
