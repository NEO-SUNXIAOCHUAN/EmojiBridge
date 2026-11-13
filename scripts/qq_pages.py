"""Bounded QQ favorites viewport reading. No image here is called an original."""
import argparse
from datetime import datetime
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
from emoji_bridge.windows import StopAutomation,scroll,guard
from emoji_bridge.state import single_instance,save_json,sha
from local_bridge import handoff_to,read_json
from qq_import import QQ


def read_pages(max_views=3):
    """Compatibility view for old membership receipts, using measured scrolling."""
    if not 1<=max_views<=5:raise ValueError('at_most_five_views')
    from qq_catalog import scan
    path,report=scan(max_views)
    report['status']='bounded_views_captured' if len(report['pages'])==max_views and not report.get('reason') and report.get('returned_to_first_view') else 'incomplete'
    report['target']='qq';report['total_collection_count']=None
    save_json(path,report)
    return path,report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--views',type=int,default=3);args=p.parse_args()
    path,report=read_pages(args.views)
    import json
    print(json.dumps({'report':str(path),'status':report['status'],'views':len(report['pages']),'complete':False,'reason':report.get('reason')},ensure_ascii=False))
