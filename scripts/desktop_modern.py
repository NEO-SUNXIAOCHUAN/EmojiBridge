"""Windows desktop library with the existing native editor; all data stays local."""
from pathlib import Path
import argparse,sys,json,os
APP=Path(__file__).resolve().parents[1];sys.path[:0]=[str(APP/'src'),str(APP/'scripts')]

def main():
    from emoji_bridge.process_storage import configure
    configure()
    from emoji_bridge.task_budget import initialize
    initialize()
    from emoji_bridge.instance_job import install
    install()
    if os.name=='nt':
        # A stable desktop identity keeps the host separate from unrelated
        # Python windows when files are hovered over its taskbar button.
        import ctypes
        identify=ctypes.WinDLL('shell32').SetCurrentProcessExplicitAppUserModelID
        identify.argtypes=[ctypes.c_wchar_p];identify.restype=ctypes.c_long
        identify('EmojiBridge.Desktop')
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path);parser.add_argument('--debug-port',type=int);parser.add_argument('--design-preview',action='store_true')
    args=parser.parse_args()
    from desktop_runtime import activate
    activate()
    import webview
    # Local, user-configurable sound only. This enables the approved cold-start
    # track before a click, without disabling certificate or origin checks.
    browser_args=os.environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS','')
    if '--autoplay-policy=' not in browser_args:
        os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=browser_args+' --autoplay-policy=no-user-gesture-required'
    webview.settings['OPEN_DEVTOOLS_IN_DEBUG']=False
    from webview.dom import DOMEventHandler
    from desktop_service import DesktopService
    from emoji_bridge.materials import default_root
    service=DesktopService(args.data_dir/'material-library' if args.data_dir else default_root())
    # Do not expose implementation helpers through the JS API.
    class API:pass
    api=API()
    api.close_window=service.close_window
    api.drafts=service.drafts
    api.promo_status=service.promo_status
    api.install_promo_projects=service.install_promo_projects
    api.collection_enrich=service.collection_enrich
    for name in ('drop_begin','drop_chunk','drop_finish','drop_notice'):setattr(api,name,getattr(service,name))
    for name in ('repair_library','library_repair_report','drawer_settings','open_drawer','reclaim_stickers','adjust_stickers','recover_stickers','open_drop_port','factory_listing','factory_plan','factory_generate','factory_preview','factory_preview_status','factory_examples','factory_save','status','preferences','listing','cancel_task','choose_import','paste','organize','collection','locate','choose_directory','export','preview_start','preview_frame','preview_stop','open_native','drag','workspace_layout','dependency_status','prepare_dependency','collection_listing','collection_action','start_transfer','cancel_transfer','transfer_results','cancel_editor_save','cancel_native_activity','restore_examples','assign_collection','undo_collection'):
        setattr(api,name,getattr(service,name))
    if args.debug_port:webview.settings['REMOTE_DEBUGGING_PORT']=args.debug_port
    tokens=json.loads((APP/'assets/ui-midnight.json').read_text('utf-8'))
    window=webview.create_window('EmojiBridge',service.url+('?designlab=1' if args.design_preview else ''),js_api=api,width=1380,height=900,min_size=(980,660),background_color=tokens['background'],text_select=True)
    service.window=window
    def ready():
        # A launcher may hide its console via STARTUPINFO/SW_HIDE, which can
        # also suppress WinForms' initial Show. The requested main GUI must be
        # discoverable in the taskbar; never restore a user-minimized window.
        from pocket_service import on_window
        def reveal():
            import ctypes
            native=window.native;native.ShowInTaskbar=True
            handle=ctypes.c_void_p(int(native.Handle.ToInt64()))
            user=ctypes.windll.user32
            if not user.IsWindowVisible(handle) and not user.IsIconic(handle):
                # Show through WinForms as well as Win32 so the shell receives
                # the normal taskbar registration after a hidden first Show.
                native.Hide();native.Show()
        on_window(window,reveal)
        from desktop_tray import DesktopTray
        try:service.tray=DesktopTray(service)
        except Exception as exc:service.task["text"]="托盘未启动："+str(exc)
        def dropped(event):
            if service.pocket.dragging:return
            from media_drop import receive
            receive(service,window,event,service.drop_notice)
        window.dom.document.events.dragover+=DOMEventHandler(lambda e:None,True,True,debounce=150)
        window.dom.document.events.drop+=DOMEventHandler(dropped,True,True)
    import threading,time
    closing={'started':False,'detached':False,'generation':0,'interactive':False}
    def close_answer(kind):
        if not closing['started']:return
        if kind=='close_interaction':
            closing['interactive']=False;closing['deadline']=time.monotonic()+6
            service.route_serial+=1;service.route_event={'serial':service.route_serial,'page':'native','view':'editor'}
            # Return to the actual editor before its unsaved sheet can ask a
            # question. A hidden sheet must never disable the exit deadline.
            def reveal():
                try:
                    from pocket_service import on_window
                    on_window(window,lambda:window.native.Show())
                    service.workspace_layout(dict(service.workspace_rect,visible=True))
                except Exception:pass
            threading.Thread(target=reveal,daemon=True).start();return
        if kind=='close_prompt_alive':
            closing['deadline']=time.monotonic()+6;return
        if kind=='close_draining':closing['interactive']=False;closing['deadline']=time.monotonic()+6;return
        if kind=='close_cancelled':
            closing['generation']+=1;closing['started']=False;closing['interactive']=False;service.closing=False
            window.evaluate_js("window.__emojiClosing=false;window.dispatchEvent(new Event('emoji-closing-cancelled'))")
            return
        closing['detached']=True
        window.destroy()
    service.close_answer=close_answer
    def before_close():
        if closing['detached']:return True
        if closing['started']:return False
        closing['started']=True;closing['generation']+=1;generation=closing['generation'];closing['deadline']=time.monotonic()+6;service.closing=True;service.cancel.set()
        def silence():
            try:window.evaluate_js("window.__emojiClosing=true;window.dispatchEvent(new Event('emoji-closing'))")
            except Exception:pass
        threading.Thread(target=silence,daemon=True,name='stop-instance-sound').start()
        def cancel_work():
            if service.transfer.get('active') or service.transfer_command:service.cancel_transfer()
            for client in ('qq','wechat'):service.collections.cancel(client)
        threading.Thread(target=cancel_work,daemon=True,name='desktop-close-request').start()
        # Request closure while the editor is still attached. Its existing
        # unsaved-work choice remains authoritative; no orphan Tk window.
        if service.native and service.native.poll() is None:service.commands.put({'kind':'prepare_close'})
        else:close_answer('close_ready')
        def deadline():
            while closing['started'] and closing['generation']==generation:
                if time.monotonic()>=closing['deadline']:
                    # Independent of both UI loops; only this instance's tree.
                    os._exit(2)
                time.sleep(.1)
        threading.Thread(target=deadline,daemon=True,name='instance-close-deadline').start()
        return False
    service.request_close=before_close
    def host_visibility(hidden):
        # WebView2 can keep document.hidden=false in a minimized WinForms host.
        # Forward the actual host lifecycle; no timer or fake playback delay.
        try:window.evaluate_js("window.__emojiHostHidden="+('true' if hidden else 'false')+";window.dispatchEvent(new CustomEvent('emoji-host-hidden',{detail:window.__emojiHostHidden}))")
        except Exception:pass  # The document can already be closing/not yet loaded.
    window.events.minimized+=lambda:host_visibility(True)
    window.events.restored+=lambda:host_visibility(False)
    window.events.maximized+=lambda:host_visibility(False)
    window.events.shown+=lambda:host_visibility(False)
    window.events.loaded+=ready;window.events.closing+=before_close
    window.events.closed+=lambda:threading.Thread(target=service.close,daemon=True,name='instance-cleanup').start()
    webview.start(gui='edgechromium',private_mode=True,debug=bool(args.debug_port),icon=str(APP/'assets/branding/EmojiBridge.ico'))
    # Python's Executor exit hook otherwise waits indefinitely for a stuck
    # native driver even though every application window has already closed.
    cleanup=threading.Thread(target=service.close,daemon=True);cleanup.start();cleanup.join(2)
    os._exit(0)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        import tkinter as tk
        from tkinter import messagebox
        root=tk.Tk();root.withdraw();messagebox.showerror('新版界面未打开',str(exc)+'\n原版入口及已有素材、草稿仍可使用。',parent=root);root.destroy()
