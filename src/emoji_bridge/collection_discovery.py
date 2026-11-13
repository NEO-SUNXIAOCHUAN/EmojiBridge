"""Small account-local discovery ledger. Never decodes originals or claims cloud time."""
from datetime import datetime
import json
from pathlib import Path
from .state import save_json


class Discovery:
    def __init__(self,path):
        self.path=Path(path)
        try:self.data=json.loads(self.path.read_text('utf-8'))
        except FileNotFoundError:self.data={'schema':'collection-discovery-v1','sources':{},'baselines':[],'last':{}}

    def reconcile(self,rows,sides):
        data=self.data;now=datetime.now().astimezone().isoformat();records=data['sources'];changed=False
        counts={'new_content':0,'new_sources':0,'original_updates':0,'new_observations':0}
        previous_content={tuple(k) for r in records.values() for k in r.get('keys',[])}
        fresh=[];groups=set()
        initial={c for c,s in sides.items() if c not in data['baselines'] and s.get('snapshot_at')}
        for row in rows:
            row['first_discovered_at']='';row['recent_kind']=''
            row_keys=[('content_key',m['content_key']) for m in row['members'] if row['identity_verified'] and m.get('content_key')]
            row_keys += [('sha256',m['source_sha256']) for m in row['members'] if row['identity_verified'] and m.get('source_sha256')]
            for m in row['members']:
                if m['unseen']:continue
                # QQ's scan ID is not a favorite ID. A presentation observation
                # token can link equal readings, but cannot prove duplication.
                key=m['client']+':'+m.get('observation_key',m['id'])
                record=records.get(key)
                if record is None:
                    baseline=m['client'] in initial
                    kind='' if baseline else 'source' if set(row_keys)&previous_content else 'content' if m['client']=='wechat' or row['identity_verified'] else 'observation'
                    record={'first_seen':now,'ready':m['original_ready'],'kind':kind,'keys':row_keys}
                    records[key]=record;changed=True
                    if kind:
                        fresh.append(key)
                        if kind=='source':counts['new_sources']+=1
                        elif kind=='observation':counts['new_observations']+=1
                        elif row['id'] not in groups:counts['new_content']+=1;groups.add(row['id'])
                else:
                    if not record['ready'] and m['original_ready']:counts['original_updates']+=1;changed=True
                    if not record.get('keys') and row_keys and record.get('kind') in ('content','observation') and set(row_keys)&previous_content:
                        record['kind']='source';counts['new_sources']+=1;fresh.append(key);changed=True
                    if record.get('keys')!=[list(k) for k in row_keys]:changed=True
                    record.update(ready=m['original_ready'],keys=[list(k) for k in row_keys])
                m['first_discovered_at']=record['first_seen'];m['discovery_kind']=record['kind']
                row['first_discovered_at']=max(row['first_discovered_at'],record['first_seen'])
            # A fresh original updates the old source, not its first-seen time.
        if initial:data['baselines'].extend(sorted(initial));changed=True
        signature={c:s.get('source_report',s.get('snapshot_at')) for c,s in sides.items()}
        if signature!=data.get('snapshots'):
            data['snapshots']=signature
            data['last']={'at':now,**counts,'sources':fresh,'baseline':bool(initial)};changed=True
        elif any(counts.values()):
            data['last']={'at':now,**counts,'sources':fresh,'baseline':False};changed=True
        recent=set(data.get('last',{}).get('sources',[]))
        for row in rows:
            row['recent_kind']=next((m['discovery_kind'] for m in row['members'] if not m['unseen'] and m['client']+':'+m.get('observation_key',m['id']) in recent),'')
        if changed:save_json(self.path,data)
        return dict(data.get('last',{}))
