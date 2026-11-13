"""Internal task-start helper. No clicks, text, messages or collection actions."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.windows import Window,StopAutomation
from emoji_bridge.source_focus import _activate_linked

if __name__=='__main__':
    try:
        request=json.loads(sys.stdin.readline())
        data=request['window'];data['rect']=tuple(data['rect'])
        _activate_linked(Window(**data),Path(request['exe']),previous=request['previous'])
        result={'ok':True}
    except StopAutomation as exc:result={'ok':False,'reason':str(exc)}
    except Exception:result={'ok':False,'reason':'foreground_handoff_unavailable'}
    print(json.dumps(result),flush=True)
