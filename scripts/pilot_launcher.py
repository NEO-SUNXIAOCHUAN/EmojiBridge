"""Pilot entrypoint; a clean package never imports the developer's runtime data."""
from pathlib import Path
import argparse,json,sys
APP_ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(APP_ROOT/'src'),str(APP_ROOT/'scripts')]
from emoji_bridge import paths
from emoji_bridge.client_sources import known_folder
from emoji_bridge.pilot import setup,BUILD


def main():
    from emoji_bridge.process_storage import configure
    configure()
    parser=argparse.ArgumentParser();parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--data-dir',type=Path);parser.add_argument('--self-check',action='store_true')
    parser.add_argument('--bridge',action='store_true',help='open the existing client bridge and account selector')
    args=parser.parse_args()
    if not (args.bridge or args.smoke or args.self_check):
        from material_library_ui import create_root
        from desktop_shell import DesktopShell
        from emoji_bridge.materials import MaterialStore,default_root
        from emoji_bridge.state import single_instance
        store=MaterialStore(args.data_dir/'material-library' if args.data_dir else default_root())
        root=create_root()
        try:
            with single_instance(store.root/'library-ui.lock'):
                app=DesktopShell(root,store,base=args.data_dir);root.mainloop()
        except RuntimeError as exc:
            from tkinter import messagebox
            messagebox.showinfo('素材库','素材库已打开，请切回已有窗口。\n'+str(exc),parent=root)
            root.destroy()
        return 0
    if args.self_check:
        import PIL,numpy,cryptography,tkinter,sqlite3,hashlib,importlib
        from emoji_bridge.wechat_index import vendor
        from emoji_bridge.client_sources import powershell_executable
        vendor('memory');vendor('decrypt');powershell_executable()
        modules=('startup_prepare','qq_startup_pipeline','wechat_prepare','selected_transfer',
                 'qq_batch_workflow','wechat_batch_workflow','local_bridge','bridge_ui')
        for name in modules:importlib.import_module(name)
        resources=APP_ROOT/'assets/qq/9.9.20-dark-96'
        profile=json.loads((resources/'profile.json').read_text(encoding='utf-8'))
        for name,digest in profile['templates'].items():
            if hashlib.sha256((resources/(name+'.png')).read_bytes()).hexdigest()!=digest:
                raise ValueError('packaged_icon_checksum_mismatch')
        for name in ('qq_favorites_uia.ps1','qq_accessible.cs','wechat_uia.ps1','window_focus.ps1','client_compat.ps1'):
            if not (APP_ROOT/'scripts'/name).is_file():raise ValueError('packaged_uia_script_missing')
        root=tkinter.Tk();root.withdraw();root.update();root.destroy()
        print(json.dumps({'build':BUILD,'runtime':sys.version.split()[0],'standalone_prefix':str(Path(sys.prefix).resolve()),
                          'tk_ok':True,'workflow_modules_loaded':len(modules),'resources_verified':True,
                          'pillow':PIL.__version__,'numpy':numpy.__version__,'cryptography':cryptography.__version__}))
        return 0
    import tkinter as tk
    from tkinter import messagebox
    base=args.data_dir or known_folder('local_app_data')/'EmojiBridgePilot'
    root=tk.Tk()
    try:
        profile=base/'smoke-profile' if args.smoke else setup(root,base)
        if profile is None:root.destroy();return 0
        paths.configure_data_root(profile)
        # Import only after choosing this account pair's isolated workspace.
        from bridge_ui import App
        from emoji_bridge.state import single_instance,save_json
        with single_instance(base/'pilot.lock'):
            app=App(root,auto_previews=not args.smoke)
            if args.smoke:
                root.update()
                from emoji_bridge import catalog
                report={'build':BUILD,'clean_library':all(not s['items'] for s in app.library['clients'].values()),
                        'selected':sum(map(len,app.selected.values())),'data_root':str(paths.DATA_ROOT),
                        'resource_root':str(APP_ROOT),'client_actions':0}
                save_json(base/'smoke-result.json',report);root.after(300,root.destroy)
            root.mainloop()
        return 0
    except Exception as exc:
        # User-facing failure; do not expose secrets or dump runtime objects.
        messagebox.showerror('启动未完成','错误类型：'+type(exc).__name__+'。请确认已解压完整程序且目录可写；保留现有数据后重新启动。',parent=root)
        root.destroy();return 2


if __name__=='__main__':raise SystemExit(main())
