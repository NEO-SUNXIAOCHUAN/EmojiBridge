"""Persistent native workspace attached to the modern library, sharing all data."""
from pathlib import Path
import json,os,queue,sys,threading,time,urllib.request
APP=Path(__file__).resolve().parents[1];sys.path[:0]=[str(APP/'src'),str(APP/'scripts')]
os.environ['EMOJI_BRIDGE_DESKTOP_STYLE']='midnight'

class IdlePresentation:
    """Coalesce page construction and command acknowledgement after Tk layout."""
    def __init__(self,root,callback):
        self.root=root;self.callback=callback;self.pending=None
    def request(self):
        if self.pending is None:self.pending=self.root.after_idle(self.notify)
    def notify(self):
        self.pending=None
        # Notebook/page children schedule their own geometry work from idle.
        # Do not announce the native surface while these children are still 1x1.
        self.root.update_idletasks()
        self.callback()

def main():
    from ui_dpi import initialize_process
    initialize_process()
    from emoji_bridge.process_storage import configure
    configure()
    from material_library_ui import create_root
    from emoji_bridge.materials import MaterialStore
    from desktop_shell import DesktopShell
    root=create_root();root.withdraw()
    store=MaterialStore(sys.argv[1]);endpoint=sys.argv[2];events=queue.Queue();stop=threading.Event()
    shell=DesktopShell(root,store,base=store.root.parent,embedded=True);show_original=shell.show
    # This entry belongs to the modern host. Stay hidden until it reparents the
    # HWND; command delivery must never briefly lift a second top-level window.
    attached=[True];active=[False];embedded=[True];request_id=[0]
    # Tk must map its inner client HWND while it still owns a top-level wrapper.
    # ShowWindow on a reparented, withdrawn wrapper alone leaves that client HWND
    # at 1x1 and unmapped. Realize transparently before the host takes ownership.
    root.attributes('-alpha',0)
    root.deiconify()
    root.update_idletasks()
    # Process the first MapNotify before the host hides/reparents the wrapper.
    # Layout alone can leave Tk's inner client HWND withdrawn at 1x1.
    root.update()
    hwnd=int(root.wm_frame(),16)
    # The bridge is loopback HTTP only; never route it through a system proxy.
    opener=urllib.request.OpenerDirector()
    for handler in (urllib.request.HTTPHandler(),urllib.request.HTTPDefaultErrorHandler(),urllib.request.HTTPErrorProcessor()):opener.add_handler(handler)
    def local_detach(stage,exc):
        events.put({'kind':'detach','reason':stage+':'+type(exc).__name__})
    def post(kind,**extra):
        try:
            data={'kind':kind,'hwnd':hwnd,'pid':os.getpid(),'view':shell.current,**extra}
            request=urllib.request.Request(endpoint+'/native',json.dumps(data).encode(),{'Content-Type':'application/json'})
            with opener.open(request,timeout=2) as reply:reply.read()
        except OSError as exc:local_detach('post_'+kind,exc)
    def presented():
        if not shell.closed and embedded[0] and attached[0]:
            threading.Thread(target=post,args=('presented',),kwargs={'view':shell.current,'request_id':request_id[0]},daemon=True).start()
    presentation=IdlePresentation(root,presented)
    def show(key):
        if key=='library' and attached[0] and active[0]:
            shell.set_view_active(False)
            if not embedded[0]:root.withdraw()
            threading.Thread(target=post,args=('return',),kwargs={'request_id':request_id[0]},daemon=True).start();return
        show_original(key)
        if embedded[0] and attached[0]:
            presentation.request()
    shell.show=show
    def accounts_ready():
        shell.set_view_active(False)
        threading.Thread(target=post,args=('accounts_ready',),kwargs={'request_id':request_id[0]},daemon=True).start()
    shell.on_accounts_ready=accounts_ready
    saved_original=shell.saved
    def saved(item):
        saved_original(item)
        threading.Thread(target=lambda:post('saved',item_id=item['id']),daemon=True).start()
    shell.saved=saved
    transfer_token=[None];last_transfer=[None];transfer_sequence=[0]
    pending_work={}
    def request_transfer(target):
        if not shell.editor or not shell.editor.doc:return
        if not shell.editor.finish_text():return
        if pending_work:return
        from emoji_bridge.scene_save import SceneSave
        e=shell.editor;e.factory_workspace.save_form()
        pending_work[e.doc.revision]=SceneSave.capture(e.doc,e.name.get().strip() or '创作作品',e.output.output_size(),{'extracted_frames':e.frame_history,**getattr(e,'editing_recipe',{})},e.work_id)
        shell.transfer_status.set('已接受转移请求，正在检查当前作品与队列…')
        threading.Thread(target=post,args=('transfer_request',),kwargs={'target':target,'revision':shell.editor.doc.revision},daemon=True).start()
    shell.request_work_transfer=request_transfer
    def request_resume(path,refresh=False):
        plan=json.loads(Path(path).read_text('utf-8'))
        threading.Thread(target=post,args=('transfer_request',),kwargs={'source':'refresh' if refresh else 'resume','target':plan['target'],'ids':[str(path)]},daemon=True).start()
    shell.on_resume_transfer=request_resume
    shell.on_transfer_setup=lambda:threading.Thread(target=post,args=('transfer_setup',),daemon=True).start()
    def receive():
        post('ready')
        while not stop.is_set():
            try:
                with opener.open(endpoint+'/commands?pid='+str(os.getpid()),timeout=2) as reply:commands=json.load(reply)
                for command in commands:events.put(command)
            except OSError as exc:local_detach('commands_get',exc);return
            stop.wait(.15)
    threading.Thread(target=receive,daemon=True,name='desktop-navigation').start()
    last_editor=[None];editor_sequence=[0];last_activity=[None];activity_sequence=[0]
    def poll():
        try:poll_once()
        except Exception:
            import logging
            logging.getLogger(__name__).exception('native_workspace_poll_failed')
        finally:
            if not shell.closed:
                try:publish_status()
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception('native_workspace_status_failed')
                root.after(50,poll)

    def publish_status():
        if shell.closed:stop.set();return
        if transfer_token[0]:
            value={'active':not shell.can_transfer(),'text':shell.transfer_status.get(),
                   'can_resume':bool(shell.task and shell.task['state'].get('plan',{}).get('run_state') in ('paused','cancelled')),
                   'profile':str(Path(shell.profile).resolve()) if shell.profile else None,
                   'awaiting_configuration':bool(shell.pending_plan),
                   'path':str(shell.pending_plan[0]) if shell.pending_plan else str(shell.output_transfer['path']) if shell.output_transfer else str(shell.task['path']) if shell.task else None}
            from emoji_bridge.transfer_scene import scene
            if shell.output_transfer:value['scene']=scene(json.loads(shell.output_transfer['path'].read_text('utf8')),True)
            elif getattr(shell,'transfer_failure',None):value['scene']=scene(shell.transfer_failure,False)
            elif shell.task:value['scene']=scene(shell.task['state'].get('plan',{}),value['active'])
            signature=json.dumps(value,sort_keys=True)
            if signature!=last_transfer[0]:
                last_transfer[0]=signature;transfer_sequence[0]+=1
                threading.Thread(target=post,args=('transfer_status',),kwargs={'token':transfer_token[0],'sequence':transfer_sequence[0],'status':value},daemon=True).start()
        editor=shell.editor
        xp=None
        if editor and not editor.closed and active[0] and shell.current=='editor':
            for slot in getattr(editor,'xp_slots',[]):
                value=slot.presentation(root)
                if value and value.get('eligible'):xp=value
        xp_signature=json.dumps(xp,sort_keys=True)
        if xp_signature!=getattr(shell,'last_xp',None):
            shell.last_xp=xp_signature
            shell.xp_sequence=getattr(shell,'xp_sequence',0)+1
            threading.Thread(target=post,args=('xp_status',),kwargs={'value':xp,'sequence':shell.xp_sequence},daemon=True).start()
        from emoji_bridge.task_activity import snapshot
        activities=[snapshot(getattr(owner,'activity',{})) for owner in (shell.video_window,getattr(editor,'output',None)) if owner and not getattr(owner,'closed',False)]
        signature=json.dumps(activities,sort_keys=True)
        if signature!=last_activity[0]:
            last_activity[0]=signature;activity_sequence[0]+=1
            threading.Thread(target=post,args=('activity_status',),kwargs={'sequence':activity_sequence[0],'activities':activities},daemon=True).start()
        if editor and not editor.closed:
            for button in getattr(editor,'transfer_buttons',{}).values():
                button.state(['!disabled'] if editor.doc and not editor.busy and shell.can_transfer() else ['disabled'])
        if editor and not editor.closed and editor.doc:
            state=dict(getattr(editor,'save_state',{}))
            state.update(current_revision=editor.doc.revision,dirty=editor.doc.dirty,work_id=editor.work_id,activity=dict(getattr(editor,'activity',{})))
            if state.get('state')=='saving' and state.get('started'):state['elapsed']=round(time.monotonic()-state['started'],1)
            if state['activity'].get('active'):state['activity']['elapsed']=round(time.monotonic()-state['activity']['started'],1)
            elif state['activity'].get('started'):state['activity']['end_age']=min(3,round(time.monotonic()-state['activity']['started']-state['activity'].get('elapsed',0),1))
            if state.get('started') and state.get('state')!='saving':state['end_age']=min(3,round(time.monotonic()-state['started']-state.get('elapsed',0),1))
            if state.get('state') not in ('saving','error') and editor.doc.dirty:
                state.update(state='dirty',text='有未保存修改')
            elif state.get('state')=='idle':
                state.update(state='saved',text='草稿已打开；没有未保存修改')
            signature=json.dumps(state,sort_keys=True)
            if signature!=last_editor[0]:
                last_editor[0]=signature;editor_sequence[0]+=1
                threading.Thread(target=post,args=('editor_status',),kwargs={'sequence':editor_sequence[0],'status':state},daemon=True).start()
    def poll_once():
        if shell.closed:stop.set();return
        try:
            while True:
                command=events.get_nowait();kind=command['kind']
                if kind=='prepare_close':
                    editor=shell.editor
                    def finish_close(editor=editor):
                        if editor and not editor.closed and editor.doc and (editor.doc.dirty or editor.unsaved_output):
                            if not active[0] or not editor.window.winfo_viewable():
                                root.after(50,finish_close);return
                            shell.close_prompt=True
                            def prompt_alive():
                                if shell.close_prompt and editor.window.winfo_viewable():
                                    threading.Thread(target=post,args=('close_prompt_alive',),daemon=True).start()
                                    root.after(500,prompt_alive)
                            prompt_alive()
                            try:accepted=editor.close()
                            finally:shell.close_prompt=False
                            if not accepted:
                                if getattr(editor,'return_after_save',False):
                                    def after_save():
                                        if editor.closed or (editor.doc and not editor.doc.dirty and not editor.save_waiting):
                                            finish_close();return
                                        if not editor.save_waiting:post('close_cancelled');return
                                        post('close_prompt_alive');root.after(150,after_save)
                                    root.after(150,after_save)
                                else:post('close_cancelled')
                                return
                        post('close_draining');shell.close()
                        def await_closed():
                            if shell.closed:post('close_ready')
                            else:root.after(50,await_closed)
                        await_closed()
                    if editor and not editor.closed and editor.doc and (editor.doc.dirty or editor.unsaved_output):
                        show_original('editor');post('close_interaction')
                    root.after_idle(finish_close)
                    continue
                if command.get('request_id'):
                    # Drain only consecutive navigation commands. Visibility,
                    # cancellation and save messages retain their own order.
                    while not events.empty():
                        following=events.queue[0]
                        if not following.get('request_id'):break
                        command=events.get_nowait();kind=command['kind']
                    request_id[0]=command['request_id']
                if kind=='embedded':
                    embedded[0]=True;shell.set_embedded(True)
                    root.attributes('-alpha',1)
                    shell.set_view_active(command.get('visible',True));continue
                if kind=='visibility':
                    shell.set_view_active(command.get('visible',False));continue
                if kind=='scroll_preferences':
                    from ui_scroll import configure
                    configure(root,command['value']);continue
                if kind=='transfer_notice':pending_work.clear();shell.transfer_status.set(command['text']);continue
                if kind=='draft_deleted':
                    if shell.editor and shell.editor.draft_id==command['id']:shell.editor.draft_id=None
                    continue
                if kind=='cancel_transfer':
                    if command.get('token')==transfer_token[0]:shell.cancel_transfer()
                    continue
                if kind=='transfer_start':
                    transfer_token[0]=command['token'];last_transfer[0]=None
                    if not shell.can_transfer():
                        pending_work.clear()
                        shell.transfer_status.set('已有原生互通操作进行中，本次未启动。请等待完成后从互通记录重试本任务。')
                        shell.transfer_failure={'created':command['token'],'target':command['target'],'run_state':'paused','pause_reason':'another_client_run_is_active','jobs':[]}
                        continue
                    shell.transfer_failure=None
                    try:
                        if command['source']=='work':
                            shell.bind_saved_profile()
                            if command.get('profile') and (not shell.profile or str(Path(shell.profile).resolve())!=command['profile']):
                                raise ValueError('目标账号已改变；未提交，请重新选择目标。')
                            captured=pending_work.pop(command.get('revision'),None)
                            if captured is None:raise ValueError('本次作品快照已失效，请重新点击转移；尚未提交。')
                            shell.transfer_work(command['target'],captured=captured)
                        elif command['source']=='refresh':
                            shell.bind_saved_profile(command['target'])
                            if not shell.profile:raise ValueError('请先配置本人账号')
                            shell.launch_plan(Path(command['path']),autostart=False)
                            if shell.task:shell.task['refresh']()
                        else:shell.launch_plan(Path(command['path']),autostart=True)
                    except Exception as exc:
                        pending_work.clear();shell.transfer_status.set('互通未启动：'+str(exc))
                        shell.transfer_failure={'created':command['token'],'target':command['target'],'run_state':'paused','pause_reason':str(exc),'jobs':[]}
                    continue
                if kind=='cancel_editor_save':
                    if shell.editor and shell.editor.save_task:
                        shell.editor.save_task.cancel.set()
                        shell.editor.status.set('已取消保存；正在结束当前步骤。')
                    continue
                if kind=='cancel_native_activity':
                    if shell.editor and not shell.editor.closed:
                        if getattr(shell.editor,'activity',{}).get('active'):shell.editor.save_cancel.set()
                        if getattr(getattr(shell.editor,'output',None),'activity',{}).get('active'):shell.editor.output.cancel_prepare()
                        shell.editor.status.set('已取消后续处理，正在收尾；原件和已保存结果保留。')
                    if shell.video_window and not shell.video_window.closed and shell.video_window.busy:shell.video_window.cancel_processing()
                    continue
                if kind=='detach':
                    # This diagnostic contains stage/type only, never file,
                    # account or document contents. Distinguish IPC from attach.
                    print(json.dumps({'event':'workspace_detach','pid':os.getpid(),
                                      'reason':command.get('reason','host_request')},ensure_ascii=False),flush=True)
                    attached[0]=False;shell.show=show_original
                    embedded[0]=False;shell.set_embedded(False);shell.set_view_active(True)
                    # A hidden unsaved draft must remain recoverable after the library closes.
                    if active[0]:root.deiconify()
                    if command.get('reason')=='host_closed' or not active[0]:
                        shell.close()
                        if shell.closed:return
                    continue
                active[0]=True;shell.set_view_active(True)
                if not embedded[0]:root.deiconify();root.lift()
                try:
                    if kind=='editor':shell.edit(command.get('ids',[]))
                    elif kind=='draft':
                        from draft_catalog import resolve
                        shell.open_draft(resolve(store.root,command['ids'][0]))
                    elif kind in ('resume','factory'):shell.edit([])
                    elif kind=='video':shell.open_video(command.get('paths',[]))
                    elif kind=='record':
                        shell.open_video();shell.video_window.record_region()
                    elif kind=='settings':show_original('settings')
                    elif kind=='bridge':show_original('bridge')
                    elif kind=='transfer_results':shell.show_results()
                except Exception as exc:
                    threading.Thread(target=post,args=('navigation_error',),kwargs={'request_id':request_id[0],'error':str(exc)},daemon=True).start()
                    continue
                root.title('EmojiBridge · 表情工厂')
                # The child intentionally remains hidden until this notification;
                # acknowledge created/layout-ready widgets, not Map visibility.
                presentation.request()
        except queue.Empty:pass
    root.after(50,poll);root.mainloop();stop.set();post('close_ready')

if __name__=='__main__':main()
