"""QQ personal cache probe: local reads/copies and optional favorites-only verify.

No message composer, send, import or database-write path. Not wired into the
transfer picker until broader selected-item mapping has been validated.
"""
from datetime import datetime
from pathlib import Path
import argparse,json,re,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
from emoji_bridge.client_sources import qq_profile, executable
from emoji_bridge import qq_cache as cache
from emoji_bridge.state import save_json,single_instance


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def discover(ini=None):
    if ini is None:
        from emoji_bridge.client_sources import qq_configuration
        ini=qq_configuration()
    raw=Path(ini).read_bytes();base=None
    for encoding in ('utf-8-sig','utf-16','gb18030'):
        try:
            match=re.search(r'^\s*UserDataSavePath\s*=\s*(.*?)\s*$',raw.decode(encoding),re.M|re.I)
            if match:base=Path(match.group(1).strip().strip('"'));break
        except UnicodeError:continue
    if base is None or not base.is_absolute() or not base.is_dir():raise ValueError('configured_data_root_unavailable')
    accounts=sorted(p for p in base.iterdir() if p.is_dir() and p.name.isdecimal());roots=[]
    for account in accounts[:20]:
        for spelling in ('personal_emoji','personal-emoji'):
            path=account/'nt_qq/nt_data/Emoji'/spelling/'Ori'
            if path.is_dir():
                path=cache.personal_root(path)
                roots.append({'ori':str(path),'files':sum(p.is_file() for p in path.iterdir()),'current_account_binding':'unproven'})
    return {'configured_root':str(base),'numeric_roots_inspected':min(20,len(accounts)),
            'limit_reached':len(accounts)>20,'candidates':roots,'chat_data_read':False,'messages_sent':0}


def verify_samples(samples,scan_path,folder):
    """Freshly re-find each copied file in a selected current favorites viewport."""
    from PIL import Image
    from emoji_bridge.media import prepare_asset,references
    from emoji_bridge.recognition import find_in_cells
    from qq_import import QQ
    from qq_export import verify_source
    from local_bridge import handoff_to
    scan=read(scan_path)
    if scan.get('schema')!='qq-favorite-observations-v1' or len(samples)>10:raise ValueError('bounded_favorite_scan_required')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);results=[]
    for n,source in enumerate(samples):
        one={'sample':source.get('name',Path(source['file']).name),'file':source['file'],'status':'pending_confirmation',
             'messages_sent':0,'scope':'selected original versus bounded current personal-favorite UI; no full-collection claim'}
        target=folder/f'sample-{n}';target.mkdir(exist_ok=True)
        try:
            cache.validate_copy(source)
            asset,meta=prepare_asset(Path(source['file']),'qq',ROOT/'private/T006/assets',native=True)
            refs=references(meta);positions=set()
            for page in scan['pages']:
                grid=Image.open(page['image'])
                for hit in find_in_cells(grid,refs,[c['rect'] for c in page['cells']]):
                    for cell in page['cells']:
                        l,t,r,b=cell['rect']
                        if l<=hit.center[0]<r and t<=hit.center[1]<b:positions.add(cell['position'])
            one.update(scan=str(scan_path),positions=sorted(positions),asset=str(asset))
            if len(positions)!=1:raise ValueError('candidate_not_uniquely_mapped_in_scan')
            item=next(i for i in scan['items'] if i['position'] in positions)
            with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
                handoff_to('qq');q=QQ(qq_profile(),{});q.bind()
                proof=verify_source(q,scan,item,asset,target)
            one.update(status='source_favorite_verified',item_id=item['id'],verification=str(proof),cache_original_verified=True)
        except Exception as exc:one['reason']=str(exc)
        results.append(one);save_json(folder/'results.json',results)
        if one.get('reason') in ('foreground_changed','cancelled_escape'):break
    return results


def main():
    p=argparse.ArgumentParser(description='QQ 本地个人表情只读验证，不发送消息')
    sub=p.add_subparsers(dest='command',required=True)
    d=sub.add_parser('discover');d.add_argument('--ini')
    i=sub.add_parser('inventory');i.add_argument('--ori',required=True)
    c=sub.add_parser('copy');c.add_argument('--inventory',required=True);c.add_argument('--name',action='append',required=True)
    v=sub.add_parser('verify');v.add_argument('--samples',required=True);v.add_argument('--scan',required=True)
    args=p.parse_args();stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f');path=ROOT/'reports/T006'/f'{args.command}-{stamp}.json'
    if args.command=='discover':result=discover(args.ini)
    elif args.command=='inventory':result=cache.inventory(args.ori,ROOT/'private/T006/cache-previews'/stamp)
    elif args.command=='copy':
        report=read(args.inventory)
        if report.get('schema')!='qq-personal-cache-candidates-v1' or len(args.name)>10:raise ValueError('bounded_cache_selection_required')
        if len(set(args.name))!=len(args.name):raise ValueError('duplicate_selection')
        entries={i['name']:i for i in report['items']}
        result=[cache.copied_original(report['root'],entries[name],ROOT/'private/T006/sample-originals') for name in args.name]
    else:result=verify_samples(read(args.samples),args.scan,ROOT/'private/T006/verification'/stamp)
    save_json(path,result)
    print(json.dumps({'report':str(path),'messages_sent':0,'source_files_modified':False},ensure_ascii=False))


if __name__=='__main__':main()
