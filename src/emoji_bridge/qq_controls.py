"""Bounded QQ readiness; native providers first, verified visual fallback last."""
from pathlib import Path
import time

from .paths import APP_ROOT
from .uia_worker import UIAWorker
from .windows import StopAutomation, user, pid_of,process_path,class_name,file_version,normal_bounds
from .compatibility import classify
from .client_geometry import client_scale

MAIN_DIAGNOSTICS={}


def select_main_candidate(exe,candidates,cancel=None,allow_pending=False):
    """Disambiguate eligible QQ windows by the same toolbar as source reads.

    A lone geometry candidate still needs control checks before actual input.
    Any verified chat in the same account process can host favorites. Prefer
    the foreground chat, otherwise keep the current top-to-bottom order.
    """
    MAIN_DIAGNOSTICS.clear()
    MAIN_DIAGNOSTICS.update(candidate_count=len(candidates),native_disambiguation=len(candidates)>1,selected=False)
    if not candidates:raise StopAutomation('client_main_window_missing_or_ambiguous')
    if cancel and Path(cancel).exists():raise StopAutomation('cancel_requested')
    chosen=candidates[0] if len(candidates)==1 else discover_main(exe,candidates,cancel,allow_pending=allow_pending)
    if not any((w.hwnd,w.pid)==(chosen.hwnd,chosen.pid) for w in candidates):
        raise StopAutomation('process_identity_changed')
    MAIN_DIAGNOSTICS['selected']=True
    return chosen


def explain_error(code):
    from .compatibility import REASONS
    return {
        'qq_chat_not_open':'QQ 尚未打开聊天输入区，未提交文件。请打开带表情按钮的任意聊天窗口后继续。',
        'qq_visual_chat_toolbar_not_unique':'未能唯一确认 QQ 聊天工具栏。请让带表情按钮的聊天窗口完整显示，移开遮挡后继续；未提交项已保留。',
        'qq_visual_favorite_panel_ambiguous':'QQ 收藏面板无法唯一确认。请移开遮挡并让收藏面板完整显示后继续。',
        'qq_visual_native_cell_unavailable':'视觉模式未取得可用的收藏位置，已保留结果，请重新打开收藏首屏后继续。',
        'heart_not_uniquely_identified':'未能确认 QQ 收藏入口；文件尚未提交。请打开“我的收藏”后继续。',
        'plus_not_uniquely_identified':'QQ 收藏导入按钮未唯一识别；请确保收藏首屏完整可见后继续，未提交项可安全重试。',
        'qq_uia_top_not_observed':'QQ 收藏导入入口未显示。请回到“我的收藏”顶部后继续。',
        'qq_favorite_scroll_no_progress':'QQ 收藏列表未继续向下移动，旧记录中的所选项尚未找到。已停止补读；这不代表原文件缺失，请更新收藏列表后再核对。',
        'qq_uia_favorites_loading_timeout':'QQ 收藏面板已打开，但条目尚未加载出来；已等待8秒并保留旧记录，请待QQ显示收藏后重试。',
        'qq_uia_favorite_list_changed':'读取时QQ收藏列表数量减少，已暂停并保留已读取项，请待列表稳定后刷新。',
        'qq_scan_view_limit_reached':'已达到本轮64个收藏视图的读取上限，已有结果保留，尚未证明读完。',
        'qq_uia_controls_not_ready':'QQ 窗口已恢复，但表情控件尚未就绪。请打开带表情按钮的 QQ 主窗口后重试，已有读取结果保留。',
        'qq_uia_hidden_main_not_ready':'QQ 窗口隐藏，暂时无法确认主窗口。请打开 QQ 主窗口后重试，已有读取结果保留。',
        'qq_uia_panel_not_observed_no_retry':'已请求打开 QQ 表情面板，但未等到面板出现；没有重复点击，请检查 QQ 窗口。',
        'qq_uia_favorite_tab_not_ready':'QQ 表情面板已打开，但尚未识别个人收藏入口；没有点击任何表情。',
        'qq_uia_grid_not_observed_no_retry':'已切换 QQ 个人收藏，列表尚未就绪；没有重复切换或发送。',
        'qq_uia_personal_favorites_not_open':'QQ 当前未显示个人收藏列表，请重新打开个人收藏后继续。',
        'qq_uia_provider_error':'QQ 控件读取暂时中断，已停止操作并保留已读结果。',
        'qq_msaa_tree_limit':'QQ 兼容控件读取超过本轮范围或时限，已停止并保留已有结果，请待窗口稳定后重试。',
        'qq_msaa_tree_changed':'QQ 兼容控件正在变化，已停止并保留已有结果，请待窗口稳定后重试。',
        'qq_msaa_cell_identity_unavailable':'QQ 未提供该表情的可核验控件标识，未点击表情，请更新后重试。',
        'qq_msaa_scroll_unavailable':'QQ 兼容接口无法定位该收藏项，已保留结果，请回到收藏顶部后重试。',
    }.get(code,REASONS.get(code,code))


class FavoriteControls:
    def __init__(self, window, exe, cancel=None, worker=None):
        self.window, self.exe, self.cancel = window, Path(exe), cancel
        self.worker = worker or UIAWorker(APP_ROOT / 'scripts/qq_favorites_uia.ps1')
        self.observations = 0
        self.actions = []
        self._visual = None

    def close(self):
        self.worker.close()

    def read(self, action='snapshot', foreground=True, runtime_id=None):
        def check_cancel():
            if self.cancel and Path(self.cancel).exists():raise StopAutomation('cancel_requested')
        check_cancel()
        if self._visual is not None:
            result=self._visual.read(action,foreground,runtime_id)
            self.observations+=1
            if result.get('performed'):self.actions.append(action)
            return result
        w = self.window
        result = self.worker.request(cancel_check=check_cancel,window=w.hwnd, pid=w.pid, exe=str(self.exe),
                                     rect=list(w.rect), dpi=w.dpi, action=action, foreground=foreground,
                                     runtime_id=runtime_id,
                                     cancel=str(self.cancel) if self.cancel else None)
        self.observations += 1
        if not result.get('ok'):
            raise StopAutomation(result.get('reason', 'qq_uia_provider_error'))
        if result.get('native_click_rect') is not None:
            # MSAA proved the exact tab and returned no attempted action.
            # Geometry-only grouping tabs use the existing guarded input path.
            if action!='select-favorites' or result.get('performed') or not result.get('panel_open'):
                raise StopAutomation('qq_msaa_favorite_tab_changed')
            box=result['native_click_rect'];panel=result['panel_rect']
            if len(box)!=4 or not (panel[0]<=box[0]<box[2]<=panel[2] and panel[1]<=box[1]<box[3]<=panel[3]):
                raise StopAutomation('favorite_panel_geometry_changed')
            from .windows import click
            check_cancel()
            click(w,self.exe,round((box[0]+box[2])/2-w.rect[0]),round((box[1]+box[3])/2-w.rect[1]))
            self.actions.append(action)
            time.sleep(.12)
            return self.read()
        if result.get('performed'):
            self.actions.append(action)
        # Both providers must lack the requested capability. A successfully
        # opened panel can need a visual tab; this never replays an action or
        # bypasses a failed/unknown action response.
        partial_tab=(result.get('visual_fallback_scope')=='favorite-tab' and result.get('panel_open')
                     and not result.get('favorite_tab_ready') and not result.get('favorites_open'))
        if (result.get('visual_fallback_eligible') is True and (not self.actions or partial_tab)
                and action in ('snapshot','panel','describe')
                and user.GetForegroundWindow()==w.hwnd):
            from .qq_visual import VisualControls
            visual=VisualControls(w,self.exe,self.cancel)
            observed=visual.read(action,foreground,runtime_id)
            self._visual=visual
            return observed
        return result

    def wait(self, predicate, reason, initial=None, timeout=4):
        deadline = time.monotonic() + timeout
        value = initial
        while True:
            if value is None:
                value = self.read()
            if predicate(value):
                return value
            if time.monotonic() >= deadline:
                raise StopAutomation(reason)
            time.sleep(.08)
            value = None

    def ready(self):
        return self.wait(lambda r: r['toolbar_ready'], 'qq_uia_controls_not_ready')

    def open(self):
        state = self.ready()
        deadline=time.monotonic()+8
        opens=0;selected=False;seen_open=state['panel_open']
        reason='qq_uia_favorite_tab_not_ready'
        while True:
            if state['favorites_open']:return state
            if time.monotonic()>=deadline:raise StopAutomation(reason)
            if not state['panel_open']:
                # Recover only a confirmed disappearance, not a slow opening.
                if opens==0 or (seen_open and opens<2):
                    state=self.read('open-panel');opens+=1
                    selected=False;seen_open=False
                    reason='qq_uia_panel_not_observed_no_retry'
                    continue
            else:
                seen_open=True
                if state['favorite_tab_ready'] and not selected:
                    state=self.read('select-favorites');selected=True
                    reason='qq_uia_grid_not_observed_no_retry'
                    continue
                if not selected:reason='qq_uia_favorite_tab_not_ready'
            time.sleep(.08);state=self.read()

    def close_panel(self):
        state = self.read()
        if state['panel_open']:
            state = self.read('close-panel')
            self.wait(lambda r: not r['panel_open'], 'qq_uia_panel_did_not_close', state)

    def top(self,state=None,timeout=4):
        """Restore the actual import tile, not just the first sticker below it."""
        from .windows import scroll
        state=state or self.read();deadline=time.monotonic()+self._settle_budget(state,timeout);steps=0;revealed=False
        if state.get('backend')=='visual':
            while not state.get('at_top'):
                if not state.get('favorites_open'):raise StopAutomation('qq_uia_personal_favorites_not_open')
                if time.monotonic()>=deadline or steps>=12:raise StopAutomation('qq_uia_top_not_observed')
                box=state['grid_rect'];x,y=self.window.rect[:2]
                scroll(self.window,self.exe,round((box[0]+box[2])/2-x),round((box[1]+box[3])/2-y),3)
                steps+=1;time.sleep(.12);state=self.read()
            return state
        while not state.get('at_top'):
            if not state.get('favorites_open'):raise StopAutomation('qq_uia_personal_favorites_not_open')
            if time.monotonic()>=deadline:raise StopAutomation('qq_uia_top_not_observed')
            first=next(iter(state.get('cells',[])),None)
            if not revealed and first and first.get('fully_visible') is False and first.get('runtime_id'):
                # A cancelled long read can leave us many pages down. Reveal
                # the current first native list item once, then expose the
                # import tile just above it with the existing bounded scroll.
                # This is ScrollIntoView, never a click/invoke on a sticker.
                revealed=True
                state=self.read('reveal-cell',runtime_id=first['runtime_id'])
                self.actions.append('reveal-favorites-first');continue
            if state.get('cells') and steps<3:
                box=state['grid_rect'];left,top,right,bottom=box;x,y=self.window.rect[:2]
                if not (x<=left<right<=self.window.rect[2] and y<=top<bottom<=self.window.rect[3]):
                    raise StopAutomation('favorite_panel_geometry_changed')
                # Scroll only this freshly identified favorites grid. A cell's
                # ScrollIntoView can leave the import tile just above the view.
                scroll(self.window,self.exe,round((left+right)/2-x),round((top+bottom)/2-y),3)
                self.actions.append('scroll-favorites-top');steps+=1
            time.sleep(.12);state=self.read()
        return state

    @staticmethod
    def viewport_signature(state):
        # Runtime IDs are ONLY short-lived motion anchors, never favorite IDs.
        return (tuple(state.get('grid_rect', ())), state.get('loaded_cells'),
                tuple((tuple(c['runtime_id']), tuple(c['rect']))
                      for c in state.get('cells', ()) if c['fully_visible']))

    def reveal(self, runtime_id, timeout=3):
        state = self.read('reveal-cell', runtime_id=runtime_id)
        return self.settled(state,timeout)

    def settled(self,state=None,timeout=3):
        state=state or self.read()
        deadline = time.monotonic() + self._settle_budget(state,timeout)
        signature = self.viewport_signature(state)
        same = 0
        while time.monotonic() < deadline:
            time.sleep(.08)
            following = self.read()
            if not following.get('favorites_open'):
                raise StopAutomation('qq_uia_personal_favorites_not_open')
            current = self.viewport_signature(following)
            same = same + 1 if current == signature else 0
            if same >= 2:
                return following
            state, signature = following, current
        raise StopAutomation('qq_uia_scroll_not_settled')

    @staticmethod
    def _settle_budget(state, timeout):
        # MSAA fetches properties through separate COM calls. Give its two
        # fresh stability observations time to complete, without adding sleeps
        # or changing the UIA fast path. Worker/cancel limits still apply.
        if state.get('backend') == 'msaa':
            return max(timeout,min(20,4*float(state.get('elapsed_seconds',0))))
        return timeout


def restore_hidden_candidates(exe,candidates,cancel,worker):
    """Show bounded QQ candidates without activation; identify before use."""
    hidden=[w for w in candidates if not user.IsWindowVisible(w.hwnd)]
    if not hidden or len(hidden)>3:return []
    found=[];shown=[]
    try:
        for window in hidden:
            if cancel and Path(cancel).exists():raise StopAutomation('cancel_requested')
            if (pid_of(window.hwnd)!=window.pid or process_path(window.pid)!=Path(exe)
                    or class_name(window.hwnd)!='Chrome_WidgetWin_1'
                    or classify('qq',file_version(exe))=='unsupported'):
                raise StopAutomation('process_identity_changed')
            client_scale(window.dpi)
            if user.GetDpiForWindow(window.hwnd)!=window.dpi:raise StopAutomation('client_display_scale_changed')
            if any(user.GetAsyncKeyState(k)&0x8000 for k in (1,2,16,17,18,27,91,92)):
                raise StopAutomation('user_input_in_progress')
            session=FavoriteControls(window,exe,cancel,worker)
            # The existing native guard also checks process/version before show.
            session.read('describe',foreground=False)
            shown.append(window)
            user.ShowWindowAsync(window.hwnd,4)  # SW_SHOWNOACTIVATE; no focus stealing.
            deadline=time.monotonic()+1.5
            while True:
                state=session.read('describe',foreground=False)
                if user.IsWindowVisible(window.hwnd) and state['toolbar_ready']:
                    found.append(window);break
                if time.monotonic()>=deadline:break
                time.sleep(.08)
            if window not in found:
                user.ShowWindowAsync(window.hwnd,0);shown.remove(window)
        if len(found)>1:raise StopAutomation('client_main_window_missing_or_ambiguous')
        shown.clear()  # The sole semantic match remains visible for fresh binding.
        return found
    finally:
        for window in shown:
            # Do not touch a recycled handle during failure cleanup.
            if pid_of(window.hwnd)==window.pid and process_path(window.pid)==Path(exe):
                user.ShowWindowAsync(window.hwnd,0)


def discover_main(exe, windows, cancel=None,restore_hidden=False,allow_pending=False):
    """Read semantic toolbar before restoring a hidden window; never guess size."""
    if cancel and Path(cancel).exists():raise StopAutomation('cancel_requested')
    # A minimized Chromium window has a tiny offscreen current rectangle.
    # Its saved normal rectangle is only an eligibility filter; the fresh
    # semantic toolbar below still identifies the main among image viewers.
    large = []
    for w in windows:
        if w.kind != 'Chrome_WidgetWin_1':continue
        rect=normal_bounds(w)
        if rect[2]-rect[0]>=600 and rect[3]-rect[1]>=450:large.append(w)
    visible_large=[w for w in large if user.IsWindowVisible(w.hwnd)]
    hidden_large=[w for w in large if not user.IsWindowVisible(w.hwnd)] if visible_large else []
    if visible_large:large=visible_large
    candidates = [w for w in large if w.dpi in (96,120,144)]
    if not candidates:
        # Reject unsupported scale before UIA or input, but do not misreport
        # the excluded windows as absent. This does not select/restore one.
        if large:raise StopAutomation('client_display_scale_unsupported')
        raise StopAutomation('client_main_window_missing_or_ambiguous')
    # Dormant Chromium windows can retain an old DPI until shown. They are not
    # alternate mains while a visible main candidate exists. This also matches
    # the preflight selection policy and avoids reading an unrelated old tree.
    visible_candidates=[w for w in candidates if user.IsWindowVisible(w.hwnd)]
    if visible_candidates:candidates=visible_candidates
    hidden_candidates=[w for w in hidden_large if w.dpi in (96,120,144)]
    worker = UIAWorker(APP_ROOT / 'scripts/qq_favorites_uia.ps1')
    try:
        deadline = time.monotonic() + 4
        restored=False;activated=False
        while True:
            found = [];empty_visible=[]
            for window in candidates:
                session = FavoriteControls(window, exe, cancel, worker)
                try:
                    observation=session.read('describe', foreground=False)
                    if observation['toolbar_ready']:
                        found.append(window)
                    elif observation.get('visual_fallback_eligible') is True and user.IsWindowVisible(window.hwnd) and not user.IsIconic(window.hwnd):
                        empty_visible.append(window)
                except StopAutomation as exc:
                    # A foreground photo viewer may contain a screenshot of
                    # a chat. Its failed visual chat proof is not a failure
                    # of the other independently checked QQ windows.
                    if str(exc)!='qq_visual_chat_toolbar_not_unique':raise
            if len(found) > 1:
                front=user.GetForegroundWindow()
                current=[w for w in found if w.hwnd==front]
                visible=[w for w in found if user.IsWindowVisible(w.hwnd) and not user.IsIconic(w.hwnd)]
                if len({w.pid for w in found})==1 and (visible or restore_hidden or allow_pending):
                    return current[0] if current and current[0] in visible else (visible or found)[0]
                raise StopAutomation('client_main_window_missing_or_ambiguous')
            if found:
                return found[0]
            # A visible image viewer must not suppress the hidden/tray main.
            # Prefer an already identified visible chat, otherwise inspect
            # hidden candidates without activating or closing any viewer.
            for window in hidden_candidates:
                session=FavoriteControls(window,exe,cancel,worker)
                if session.read('describe',foreground=False)['toolbar_ready']:found.append(window)
            if len(found)>1:raise StopAutomation('client_main_window_missing_or_ambiguous')
            if found:return found[0]
            if allow_pending and empty_visible and len({w.pid for w in candidates})==1:
                # Read-only preflight may defer identity to bind_window. It
                # must not reject the whole job before foreground pixel proof
                # can run. This candidate alone never authorizes client input.
                MAIN_DIAGNOSTICS['pending_visual_confirmation']=True
                return empty_visible[0]
            if restore_hidden and not restored and not empty_visible:
                restored=True
                found=restore_hidden_candidates(exe,candidates+hidden_candidates,cancel,worker)
                if found:return found[0]
            # Chromium may withhold its accessibility tree while backgrounded.
            # Only an unambiguous visible candidate may be raised at this task
            # boundary; no content input is allowed until semantic re-discovery.
            if restore_hidden and not activated:
                activated=True
                visible_candidates=[w for w in candidates if user.IsWindowVisible(w.hwnd) and not user.IsIconic(w.hwnd)]
                if empty_visible and len({w.pid for w in candidates})==1:
                    from .windows import activate
                    expected=user.GetForegroundWindow()
                    for candidate in empty_visible[:3]:
                        if user.GetForegroundWindow()!=expected:raise StopAutomation('foreground_changed')
                        def check_cancel():
                            if cancel and Path(cancel).exists():raise StopAutomation('cancel_requested')
                        activate(candidate,exe,cancel_check=check_cancel,accessible_fallback=True)
                        expected=candidate.hwnd
                        try:
                            observed=FavoriteControls(candidate,exe,cancel,worker).read('describe')
                            if observed['toolbar_ready']:return candidate
                        except StopAutomation as exc:
                            if str(exc)!='qq_visual_chat_toolbar_not_unique':raise
                    raise StopAutomation('qq_chat_not_open')
                if len(visible_candidates)==1:
                    from .windows import activate
                    def check_cancel():
                        if cancel and Path(cancel).exists():raise StopAutomation('cancel_requested')
                    activate(visible_candidates[0],exe,cancel_check=check_cancel,accessible_fallback=True)
                    deadline=time.monotonic()+4
                    continue
            if time.monotonic() >= deadline:
                raise StopAutomation('qq_uia_controls_not_ready' if any(user.IsWindowVisible(w.hwnd) for w in candidates) else 'qq_uia_hidden_main_not_ready')
            time.sleep(.1)
    finally:
        worker.close()
