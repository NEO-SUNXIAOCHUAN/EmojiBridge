"""Bounded WeChat UI Automation bridge; only the user's File Transfer Assistant."""
import json
import os
from pathlib import Path
import subprocess
from .client_sources import powershell_executable
from .timing import measured
from .compatibility import require_version
from .client_geometry import client_scale
import time

from .windows import StopAutomation,qq_windows,activate,guard,file_version,capture,click,escape,restorable_main,user,pid_of,ensure_window_on_screen

ROOT=Path(__file__).resolve().parents[2]
LAST_UIA_DIAGNOSTIC={}


def empty_provider_failure(reason,report):
    startup=report.get('startup_accessibility',{})
    missing=report.get('last_uia_failure',{})
    return (reason=='wechat_control_missing' and
            type(startup.get('nodes_before')) is int and 0<=startup['nodes_before']<=2 and
            missing.get('matches')==0 and
            missing.get('control') in {'header','composer','messages','sessions'})


def safe_uia_diagnostic(action,data):
    """Only role/count codes, never names, values, handles or chat content."""
    allowed={'snapshot','prepare-accessibility','own-session-target','own-search-start','own-search-target',
             'message-rows','latest-messages','panel','panel-tab','menu','import-status','open-file','send','send-batch','toggle-panel','clear-staged'}
    out={'action':action if action in allowed else 'other','ok':data.get('ok') is True}
    reason=data.get('reason')
    if reason in {'wechat_control_missing','wechat_control_ambiguous','own_transfer_session_not_confirmed',
                  'own_transfer_entry_not_visible','own_transfer_search_not_empty','own_transfer_search_changed',
                  'own_transfer_search_layout_unsupported','own_transfer_search_result_unsupported',
                  'foreground_changed','uia_button_not_unique','wechat_header_layout_unsupported'}:out['reason']=reason
    failure=data.get('control_failure')
    if isinstance(failure,dict):
        if failure.get('control') in {'header','composer','sessions','messages','search_results','helper_function','favorites_grid','other'}:
            out['control']=failure['control']
        count=failure.get('matches')
        if type(count) is int and 0<=count<=1000:out['matches']=count
    probe=data.get('header_probe')
    if isinstance(probe,dict):
        for key in ('header_region_texts','header_semantic_matches','header_helper_matches'):
            count=probe.get(key)
            if type(count) is int and 0<=count<=1000:out[key]=count
    return out


class WeChat:
    def __init__(self,exe,report):
        self.exe=Path(exe);self.report=report;self.window=None;self.worker=None;self.persistent=False
        self.cancel_check=None
        self.visual=None
        self.visual_trial=False

    def check_cancel(self):
        if self.cancel_check:self.cancel_check()

    def close(self):
        if self.worker is not None:self.worker.close();self.worker=None

    @measured('client_opening')
    def bind(self):
        self.check_cancel()
        version=file_version(self.exe)
        require_version('wechat',version)
        mains=[w for w in qq_windows(self.exe) if w.kind=='Qt51514QWindowIcon' and w.rect[2]-w.rect[0]>=800 and w.rect[3]-w.rect[1]>=550]
        if len(mains)==1:client_scale(mains[0].dpi)
        found=[w for w in mains if w.dpi in (96,120,144)]
        if not found:
            found=[restorable_main(self.exe,'Qt51514QWindowIcon',(800,550),None)]
            self.report['window_restored']=True
        if len(found)!=1:raise StopAutomation('wechat_main_window_not_unique_or_minimized')
        self.window=found[0]
        opened=[w for w in qq_windows(self.exe) if w.pid==self.window.pid and w.kind=='Qt51514QWindowToolSaveBits']
        if opened:
            if len(opened)!=1:raise StopAutomation('wechat_popup_not_unique')
            # Qt search menus are non-activating and may be destroyed on focus
            # change. Activate the owner, then re-enumerate instead of holding
            # a stale popup handle through activation.
            activate(self.window,self.exe,cancel_check=self.check_cancel,accessible_fallback=True)
            opened=[w for w in qq_windows(self.exe) if w.pid==self.window.pid and w.kind=='Qt51514QWindowToolSaveBits']
            if len(opened)>1:raise StopAutomation('wechat_popup_not_unique')
        if opened:
            # Startup search and emoji selection share the Qt popup class.
            # Recognize the exact built-in function before treating it as an
            # emoji panel. Never dismiss an unknown popup on resume.
            search=None
            try:search=self.uia('own-search-target',opened[0])
            except StopAutomation as exc:
                if str(exc) not in ('wechat_control_missing','own_transfer_search_changed','uia_button_not_unique'):raise
            if search is not None:
                if not search.get('available'):raise StopAutomation('own_transfer_search_result_not_found')
                self.click_own_target(opened[0],search['target'])
                opened=[]
        if opened:
            # Resume only the emoji popup with a recognized custom-favorites
            # tab, even if its default page is selected. Unknown modal states
            # are never dismissed as if they were this panel.
            self.uia('panel-tab',opened[0]);self.close_popup(opened[0])
        original=self.window
        self.window=ensure_window_on_screen(self.window,self.exe)
        if self.window.rect!=original.rect:
            self.report['window_position_adjustment']={'from':original.rect,'to':self.window.rect}
        activate(self.window,self.exe,cancel_check=self.check_cancel,accessible_fallback=True)
        self.report['client_version']=version
        self.report['window']=self.window.__dict__
        trial=(os.environ.get('EMOJI_BRIDGE_WECHAT_VISUAL_TRIAL')=='1' or
               (ROOT/'WECHAT_VISUAL_TRIAL').is_file())
        self.visual_trial=trial
        force=trial and os.environ.get('EMOJI_BRIDGE_WECHAT_VISUAL_FORCE_TEST')=='1'
        if force:
            self.report['visual_forced_test']=True
        else:
            try:return self.ensure_own_session(wait_ready=True)
            except StopAutomation as exc:
                # Only the proven empty provider, before any submit, can switch.
                # Permission/focus/ambiguity and unknown submission never do.
                if not (trial and str(exc)=='wechat_visual_empty_provider'):raise
        from .wechat_visual_bridge import VisualBridge
        self.visual=VisualBridge(self)
        return self.visual.bind()

    def ensure_own_session(self,wait_ready=False):
        """Navigate only at task start, to the exact native helper entry.

        Recheck the selected conversation before touching its composer. Never
        search by fuzzy contact name or navigate back during an active send.
        """
        try:
            result=self.ready_snapshot() if wait_ready else self.uia('snapshot')
            LAST_UIA_DIAGNOSTIC.clear();return result
        except StopAutomation as exc:
            failure=self.report.get('last_uia_failure',{})
            # With no selected conversation, the structural header fallback
            # reports a missing message list before reaching the title.
            # This permits only navigation to the built-in helper; the complete
            # identity and draft checks below still gate every file submission.
            missing_chat=(str(exc)=='wechat_control_missing' and failure.get('control') in ('header','messages')
                          and failure.get('matches')==0)
            # Navigation is not permission to send. An unknown title may still
            # enter the exact native helper; the resulting session MUST pass
            # the normal identity/draft checks before any staging or sending.
            if str(exc)!='own_transfer_session_not_confirmed' and not missing_chat:raise
        method='native_session_entry_then_identity_check'
        try:target=self.uia('own-session-target')['target']
        except StopAutomation as exc:
            if str(exc)=='own_transfer_entry_not_visible':
                self.search_own_session()
                target=None;method='native_helper_function_search_then_identity_check'
            elif str(exc)=='uia_control_not_unique':
                raise StopAutomation('own_transfer_entry_not_visible') from exc
            else:raise
        if target is not None:self.click_own_target(self.window,target)
        deadline=time.monotonic()+3
        while True:
            try:
                result=self.uia('snapshot')
                self.report['own_session_navigation']=method
                LAST_UIA_DIAGNOSTIC.clear()
                return result
            except StopAutomation as exc:
                if str(exc) not in ('own_transfer_session_not_confirmed','uia_control_not_unique','wechat_control_missing'):raise
                if time.monotonic()>=deadline:raise StopAutomation('own_transfer_navigation_not_confirmed')
                time.sleep(.08)

    def ready_snapshot(self):
        """Observe Qt's recovering tree only at bind, before any navigation.

        Restore/activation can finish before Qt publishes its chat controls.
        Only absent roles are transient here; ambiguity, focus, identity and
        draft guards are never retried and no input operation is replayed.
        """
        deadline=time.monotonic()+3
        waits=0
        while True:
            try:
                result=self.uia('snapshot')
                if waits:self.report['startup_control_observations']=waits+1
                return result
            except StopAutomation as exc:
                failure=self.report.get('last_uia_failure',{})
                if (str(exc)!='wechat_control_missing' or failure.get('matches')!=0
                        or failure.get('control') not in {'header','composer','messages','sessions'}
                        or time.monotonic()>=deadline):
                    if self.visual_trial and empty_provider_failure(str(exc),self.report):
                        raise StopAutomation('wechat_visual_empty_provider') from exc
                    raise
                self.check_cancel()
                if waits==0:
                    state=self.uia('prepare-accessibility')
                    self.report['startup_accessibility']={k:state.get(k) for k in ('requested','nodes_before','hresult','read_only')}
                    # The bounded helper can consume the initial observation
                    # interval. Allow Qt a fresh short interval after requesting.
                    deadline=time.monotonic()+3
                waits+=1;time.sleep(.08)

    def click_own_target(self,window,target):
        left,top,right,bottom=target
        if not (window.rect[0]<=left<right<=window.rect[2]
                and window.rect[1]<=top<bottom<=window.rect[3]):
            self.report['own_target_geometry']={'stage':'before_navigation_click','window':list(window.rect),
                                               'target':list(target),'dpi':window.dpi,'input_submitted':False}
            raise StopAutomation('own_transfer_entry_not_visible')
        self.check_cancel()
        owner=self.window if window is not self.window else None
        click(window,self.exe,round((left+right)/2)-window.rect[0],
              round((top+bottom)/2)-window.rect[1],**({'owner':owner} if owner else {}))

    def search_own_session(self):
        """Fallback only at startup. One empty search; one built-in result click."""
        self.uia('own-search-start')
        deadline=time.monotonic()+3
        while True:
            self.check_cancel()
            guard(self.window,self.exe,foreground=False)
            opened=[w for w in qq_windows(self.exe) if w.pid==self.window.pid and w.kind=='Qt51514QWindowToolSaveBits']
            if len(opened)>1:raise StopAutomation('wechat_popup_not_unique')
            if user.GetForegroundWindow() not in [self.window.hwnd]+[w.hwnd for w in opened]:
                raise StopAutomation('foreground_changed')
            if opened:
                try:
                    meta=self.uia('own-search-target',opened[0])
                    if meta['available']:
                        self.click_own_target(opened[0],meta['target']);return
                except StopAutomation as exc:
                    # Search results resize their popup while loading. The
                    # guarded click has not injected input on this exception.
                    # Re-resolve its native result; a moved MAIN still stops.
                    if str(exc)!='window_moved_or_resized':raise
                    guard(self.window,self.exe,foreground=False)
            if time.monotonic()>=deadline:raise StopAutomation('own_transfer_search_result_not_found')
            time.sleep(.08)

    def uia(self,action='snapshot',window=None):
        if self.visual is not None:return self.visual.request(action,window)
        return self.native_uia(action,window)

    def native_uia(self,action='snapshot',window=None):
        self.check_cancel()
        window=window or self.window
        guard(window,self.exe,owner=self.window if action in ('menu','menu-observe','own-search-target','import-status') else None)
        args=[str(powershell_executable()),'-NoProfile','-ExecutionPolicy','Bypass',
              '-File',str(ROOT/'scripts/wechat_uia.ps1'),'-WindowHandle',str(window.hwnd),
              '-ClientProcessId',str(self.window.pid),'-Executable',str(self.exe),'-Action',action,
              '-ParentHandle',str(self.window.hwnd)]
        if self.persistent:
            from .uia_worker import UIAWorker,UIA_FAILURES
            if self.worker is None:self.worker=UIAWorker(ROOT/'scripts/wechat_uia.ps1')
            try:
                data=self.worker.request(cancel_check=self.cancel_check,timeout_seconds=2 if action in ('import-status','menu-observe') else 15,
                    window=window.hwnd,pid=self.window.pid,exe=str(self.exe),action=action,parent=self.window.hwnd)
            except StopAutomation as exc:
                # A timed-out helper was closed by request(); no late reply may
                # be consumed by the next operation. Never retry an input here.
                self.worker=None
                if action=='import-status' and str(exc) in UIA_FAILURES:
                    return {'ok':True,'state':'unknown','read_only':True,'probe_timeout':True}
                raise
        else:
            result=subprocess.run(args,capture_output=True,encoding='utf-8',timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
            try:data=json.loads(result.stdout.lstrip('\ufeff'))
            except ValueError:raise StopAutomation('uia_bridge_failed')
        self.check_cancel()
        if not data.get('ok'):
            diagnostic=safe_uia_diagnostic(action,data)
            LAST_UIA_DIAGNOSTIC.clear();LAST_UIA_DIAGNOSTIC.update(diagnostic)
            self.report['last_uia_failure']=diagnostic
            raise StopAutomation(data.get('reason','uia_failed'))
        return data

    def frame(self):
        self.check_cancel()
        guard(self.window,self.exe);return capture(self.window)

    def control(self,action):
        data=self.uia(action)
        left,top,right,bottom=data['target']
        if not (self.window.rect[0]<=left<right<=self.window.rect[2] and self.window.rect[1]<=top<bottom<=self.window.rect[3]):
            raise StopAutomation('control_outside_window')
        self.check_cancel()
        click(self.window,self.exe,round((left+right)/2)-self.window.rect[0],round((top+bottom)/2)-self.window.rect[1])
        time.sleep(.4)
        return data

    def popup(self,menu=False,wait=True):
        deadline=time.monotonic()+(2 if wait else 0)
        while True:
            self.check_cancel()
            found=[w for w in qq_windows(self.exe) if w.pid==self.window.pid and w.kind=='Qt51514QWindowToolSaveBits']
            # An import toast can briefly coexist with the favorite panel.
            # Wait for one identifiable window; never choose an arbitrary one.
            if len(found)==1 or time.monotonic()>=deadline:break
            time.sleep(.1)
        if not found and menu:
            guard(self.window,self.exe)
            raise StopAutomation('wechat_context_menu_not_ready')
        if len(found)!=1:raise StopAutomation('wechat_popup_not_unique')
        guard(found[0],self.exe,owner=self.window if menu else None)
        return found[0]

    @measured('add_settle')
    def wait_for_import_settle(self,timeout=8,pending_timeout=60):
        """Read-only wait for the known add action's menu/toast to disappear."""
        started=time.monotonic();deadline=started+timeout
        trace={'limit_seconds':timeout,'states':[],'status':'waiting'}
        self.report['last_import_settle']=trace;previous=None;next_probe=started+.5;acknowledged=False
        try:
            while True:
                self.check_cancel()
                guard(self.window,self.exe,foreground=False)
                front=user.GetForegroundWindow();same_process=pid_of(front)==self.window.pid
                if not same_process:
                    trace['states'].append({'seconds':round(time.monotonic()-started,3),
                        'foreground':front,'same_client':False,'popups_not_read':True})
                    raise StopAutomation('foreground_changed')
                windows=[w for w in qq_windows(self.exe) if w.pid==self.window.pid]
                # A native rejection can replace the adding toast and become
                # foreground. Inspect that exact same-process window before
                # the main-window focus guard classifies it as user activity.
                if front!=self.window.hwnd:
                    modal=next((w for w in windows if w.hwnd==front and w.kind!='Qt51514QWindowToolSaveBits'),None)
                    if modal is not None:
                        status=self.uia('import-status',modal).get('state','unknown')
                        trace['native_state']=status
                        if status=='failed':
                            trace['rejection_window']=modal.hwnd
                            raise StopAutomation('wechat_add_rejected')
                opened=[w for w in windows if w.kind=='Qt51514QWindowToolSaveBits']
                state=(front,same_process,tuple((w.hwnd,tuple(w.rect)) for w in opened))
                if state!=previous:
                    trace['states'].append({'seconds':round(time.monotonic()-started,3),
                        'foreground':front,'same_client':same_process,
                        'popups':[{'hwnd':w.hwnd,'rect':w.rect} for w in opened]})
                    previous=state
                if not opened:
                    guard(self.window,self.exe);trace['status']='settled';return
                # Only an identified native "adding" toast may extend the
                # short menu transition wait. Unknown popups never gain time.
                if len(opened)==1 and time.monotonic()>=next_probe:
                    probe_started=time.monotonic()
                    status=self.uia('import-status',opened[0]).get('state','unknown')
                    trace['native_state']=status;next_probe=time.monotonic()+.5
                    trace.setdefault('probes',[]).append({'seconds':round(probe_started-started,3),
                        'duration':round(time.monotonic()-probe_started,3),'state':status})
                    trace['probes']=trace['probes'][-24:]
                    if status=='failed':
                        trace['rejection_window']=opened[0].hwnd
                        raise StopAutomation('wechat_add_rejected')
                    if status=='adding':
                        deadline=started+max(timeout,pending_timeout)
                        trace['limit_seconds']=max(timeout,pending_timeout)
                        trace['waiting_for_client']=True
                    elif status=='acknowledged':
                        # Native acknowledgement is not durable membership.
                        # Allow its brief toast to leave, then verify the index.
                        if not acknowledged:
                            deadline=min(started+max(timeout,pending_timeout),max(deadline,time.monotonic()+3))
                            acknowledged=True
                        trace['limit_seconds']=round(deadline-started,3)
                        trace['waiting_for_client']=False
                    else:
                        deadline=started+timeout
                        trace['limit_seconds']=timeout
                        trace['waiting_for_client']=False
                if time.monotonic()>=deadline:raise StopAutomation('wechat_add_settle_timeout')
                time.sleep(.1)
        except StopAutomation as exc:
            trace.update(status='paused',reason=str(exc));raise
        finally:trace['seconds']=round(time.monotonic()-started,3)

    def dismiss_import_rejection(self):
        """Acknowledge only the exact failed add observed by this operation."""
        trace=self.report.get('last_import_settle',{})
        if trace.get('reason')!='wechat_add_rejected':raise StopAutomation('wechat_rejection_not_proven')
        handle=trace.get('rejection_window');deadline=time.monotonic()+2;clicked=False
        while True:
            self.check_cancel()
            windows=[w for w in qq_windows(self.exe) if w.pid==self.window.pid and w.hwnd==handle]
            if not windows:
                guard(self.window,self.exe);return
            modal=windows[0]
            state=self.uia('import-status',modal)
            if state.get('state')!='failed':raise StopAutomation('wechat_rejection_not_proven')
            target=state.get('ack_target')
            if target and not clicked:
                left,top,right,bottom=target
                if not (modal.rect[0]<=left<right<=modal.rect[2] and modal.rect[1]<=top<bottom<=modal.rect[3]):raise StopAutomation('control_outside_window')
                click(modal,self.exe,round((left+right)/2)-modal.rect[0],round((top+bottom)/2)-modal.rect[1],owner=self.window)
                clicked=True
            if time.monotonic()>=deadline:raise StopAutomation('wechat_add_rejected')
            time.sleep(.1)

    def panel(self,open_if_closed=False):
        opened=[w for w in qq_windows(self.exe) if w.pid==self.window.pid and w.kind=='Qt51514QWindowToolSaveBits']
        if not opened and open_if_closed:self.control('toggle-panel')
        popup=self.popup(wait=bool(opened) or open_if_closed)
        # The default emoji page has no List. Resolve the unique custom tab
        # first; a missing favorites grid there is not a broken client.
        meta=self.uia('panel-tab',popup)
        tab=meta['tab']
        # A recognized custom tab is selected explicitly; no sticker is clicked.
        click(popup,self.exe,round((tab[0]+tab[2])/2)-popup.rect[0],round((tab[1]+tab[3])/2)-popup.rect[1])
        deadline=time.monotonic()+2
        while True:
            self.check_cancel()
            try:
                meta=self.uia('panel',popup);break
            except StopAutomation as exc:
                failure=self.report.get('last_uia_failure',{})
                if (str(exc)!='wechat_control_missing' or failure.get('control')!='favorites_grid'
                        or failure.get('matches')!=0 or time.monotonic()>=deadline):raise
                time.sleep(.1)
        self.last_tab=tuple(round(v-origin) for v,origin in zip(meta['tab'],popup.rect[:2]*2))
        grid=tuple(round(v-origin) for v,origin in zip(meta['grid'],popup.rect[:2]*2))
        self.last_cells=[tuple(round(v-origin) for v,origin in zip(cell['rect'],meta['grid'][:2]*2)) for cell in meta.get('cells',[])]
        return capture(popup).crop(grid),popup,grid

    def close_popup(self,popup):
        escape(popup,self.exe,owner=self.window);guard(self.window,self.exe)
