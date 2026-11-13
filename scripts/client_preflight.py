"""Read-only client environment checks before source scanning or submission."""
from pathlib import Path
from emoji_bridge import windows as win
from emoji_bridge.client_sources import qq_profile, executable
from emoji_bridge.compatibility import require_version
from emoji_bridge.client_geometry import client_scale


def inspect_client(client):
    if client=='qq':
        config=qq_profile()
        exe=Path(config['exe']);kind='Chrome_WidgetWin_1';minimum=(600,450)
        dpi=config['dpi'];version=config['version'];size=tuple(config['window_size'])
    elif client=='wechat':
        exe=executable('wechat');kind='Qt51514QWindowIcon';minimum=(800,550)
        dpi=96;version=require_version('wechat',win.file_version(exe));size=None
    else:raise ValueError('unknown_target')
    if win.file_version(exe)!=version:raise win.StopAutomation('client_version_changed')
    candidates=[]
    for window in win.qq_windows(exe,include_inactive=True):
        if window.kind!=kind:continue
        rect=win.normal_bounds(window)
        width,height=rect[2]-rect[0],rect[3]-rect[1]
        if width<minimum[0] or height<minimum[1]:continue
        # A visible/minimized main takes precedence over dormant auxiliaries.
        visible=bool(win.user.IsWindowVisible(window.hwnd))
        # Hidden QQ identity is decided by native roles, never an old size.
        candidates.append((window,rect,visible))
    visible=[c for c in candidates if c[2]]
    if visible:candidates=visible
    if client=='qq':
        from emoji_bridge.qq_controls import select_main_candidate
        selected=select_main_candidate(exe,[c[0] for c in candidates])
        candidates=[c for c in candidates if (c[0].hwnd,c[0].pid)==(selected.hwnd,selected.pid)]
    if len(candidates)!=1:raise win.StopAutomation('client_main_window_missing_or_ambiguous')
    window,rect,_=candidates[0]
    scale=client_scale(window.dpi)
    if win.pid_of(window.hwnd)!=window.pid or win.process_path(window.pid)!=exe:
        raise win.StopAutomation('process_identity_changed')
    area=win.monitor_work_area(window.hwnd)
    if size:
        width=min(rect[2]-rect[0],area[2]-area[0]);height=min(rect[3]-rect[1],area[3]-area[1])
        if width<round(minimum[0]*scale) or height<round(minimum[1]*scale):
            raise win.StopAutomation('display_too_small_for_calibrated_window')
        rect=(rect[0],rect[1],rect[0]+width,rect[1]+height)
    fitted=win.fitted_window_rect(rect,area)
    return {'client':client,'window':vars(window),'work_area':area,
            'placement_needed':fitted!=rect,'client_version':version,'read_only':True}


from emoji_bridge.timing import measured

@measured("startup")
def check_clients(clients):
    checks=[]
    for client in dict.fromkeys(clients):
        try:checks.append(inspect_client(client))
        except Exception as exc:
            return {'ok':False,'client':client,'reason':str(exc),'checks':checks,'read_only':True}
    return {'ok':True,'checks':checks,'read_only':True}


def pause_if_blocked(plan,path,clients,check=check_clients):
    result=check(clients)
    plan['environment_check']=result
    if result['ok']:
        plan.pop('environment_block',None);return False
    # Environment failure belongs to the queue, never to an untouched asset.
    plan.update(run_state='paused',pause_reason=result['reason'],environment_block=result)
    from emoji_bridge.state import save_json
    save_json(path,plan);return True
