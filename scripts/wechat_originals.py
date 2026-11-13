"""Explicit-account emoticon-only reader. Never prints keys, URLs or DB rows."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
from emoji_bridge import wechat_index as index
from emoji_bridge.windows import file_version


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',required=True,type=Path)
    p.add_argument('--pid',required=True,type=int)
    p.add_argument('--exe',required=True,type=Path)
    p.add_argument('--report',required=True,type=Path)
    p.add_argument('--select',type=int,nargs='*',default=[],help='Explicit 1-based DB member ordinals, maximum 4 per acquisition')
    p.add_argument('--output',type=Path,default=ROOT/'private/T004-index/originals')
    args=p.parse_args()
    if len(args.select)>4 or len(set(args.select))!=len(args.select):p.error('choose at most four distinct members')
    target=args.report.resolve()
    if not target.is_relative_to(ROOT/'reports') or target.exists():
        p.error('report must be a new file in project reports')
    report={'at':datetime.now().astimezone().isoformat(),'status':'pending','scope':'emoticon database only',
            'source':str(args.db.resolve()),'secret_persisted':False,'memory_dump_written':False,
            'network_requests':0,'complete_collection_proven':False}
    key=plain=conn=None
    try:
        report['client_version']=file_version(args.exe)
        db,wal,report['snapshot']=index.snapshot(args.db)
        key,report['scan']=index.scan_key(args.pid,args.exe,db[:4096],progress=lambda event:print(json.dumps(event),flush=True))
        plain,report['wal']=index.decrypt_snapshot(db,wal,key)
        conn=index.open_index(plain)
        report['schema']=index.schema_summary(conn)
        members=index.favorites(conn)
        report['index_count']=len(members)
        report['index_members']=[index.public_item(i) for i in members]
        report['missing_original_url_count']=sum(not i['urls'] for i in members)
        checkpoint=report['snapshot']['checkpoint']
        report['snapshot_current_consistent']=bool(checkpoint.get('checked') and
            checkpoint['mx_frame']==report['wal']['valid_frames']-report['wal']['uncommitted_frames'])
        if args.select:
            if not report['snapshot_current_consistent']:raise index.IndexErrorSafe('snapshot_current_state_unproven')
            if any(n<1 or n>len(members) for n in args.select):raise index.IndexErrorSafe('selected_member_out_of_range')
            report['acquisitions']=[]
            for n in args.select:
                result=index.download_original(members[n-1],args.output)
                report['network_requests']+=len(result['attempts'])
                report['acquisitions'].append(result)
        report['status']='index_decrypted_and_integrity_verified'
    except Exception as exc:
        report['status']='failed'
        report['error']=str(exc) if isinstance(exc,index.IndexErrorSafe) else type(exc).__name__
    finally:
        if conn is not None:conn.close()
        if plain is not None:plain[:]=b'\0'*len(plain)
        key=None
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
    summary={k:v for k,v in report.items() if k not in ('source','index_members','acquisitions')}
    summary['acquisitions']=[{'ordinal':r['member']['ordinal'],'status':r['status'],
                             'format':r.get('metadata',{}).get('format'),'frames':r.get('metadata',{}).get('frames'),
                             'size':r.get('metadata',{}).get('size'),'attempts':r['attempts']}
                            for r in report.get('acquisitions',[])]
    print(json.dumps(summary,ensure_ascii=False))
    return 0 if report['status']!='failed' else 2

if __name__=='__main__':raise SystemExit(main())
