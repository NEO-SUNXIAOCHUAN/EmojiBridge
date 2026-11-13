"""Bounded, metadata-only active emoticon worker. Never closes client handles."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.active_emoticon import probe

if __name__=='__main__':
    try:
        candidates=json.loads(sys.stdin.read(128*1024))
        if not isinstance(candidates,list):raise ValueError('active_candidate_invalid')
        result=probe(candidates)
    except Exception as exc:
        code=str(exc)
        allowed={'active_process_unavailable','active_file_query_failed','wechat_process_not_unique_or_not_running',
                 'client_family_unadapted','active_candidate_invalid'}
        result={'state':'unverified','reason':code if code in allowed else 'active_file_query_failed'}
    print(json.dumps(result))
