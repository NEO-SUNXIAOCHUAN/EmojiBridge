"""Bounded portable-host checks before loading managed desktop assemblies."""
from pathlib import Path
import hashlib,json,os

WEBVIEW2_DOWNLOAD='https://developer.microsoft.com/microsoft-edge/webview2/#download-section'

def prepare_downloaded_assemblies(app):
    """Remove download ADS only from exact, manifest-verified bundled DLLs."""
    app=Path(app).resolve();folder=app/'runtime/desktop'
    if os.name!='nt' or not folder.is_dir():return []
    marked=[]
    for path in folder.rglob('*.dll'):
        resolved=path.resolve()
        if not resolved.is_relative_to(app):
            raise RuntimeError('桌面组件路径异常，请重新完整解压软件。')
        stream=Path(str(path)+':Zone.Identifier')
        if stream.exists():marked.append((path,stream))
    if not marked:return []
    try:
        manifest=json.loads((app/'BUILD.json').read_text('utf-8'))
        entries={e['path']:e for e in manifest['files']}
        # Validate every affected assembly before changing any ADS.
        for path,_ in marked:
            entry=entries[path.relative_to(app).as_posix()]
            with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
            if path.stat().st_size!=entry['size'] or digest!=entry['sha256']:
                raise ValueError('assembly_hash_mismatch')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise RuntimeError('桌面组件校验未通过，未解除下载标记。请从正式下载入口重新下载并完整解压；不要覆盖个人素材目录。') from exc
    done=[]
    for path,stream in marked:
        try:stream.unlink()
        except OSError as exc:
            raise RuntimeError('无法处理软件组件的下载标记。请关闭软件，在下载压缩包的“属性”中勾选“解除锁定”，然后解压到可写的新文件夹重试；无需管理员运行。') from exc
        done.append(path.relative_to(app).as_posix())
    return done

def webview2_version(app):
    import ctypes as c
    loader=Path(app)/'runtime/desktop/webview/lib/runtimes/win-x64/native/WebView2Loader.dll'
    if not loader.is_file():
        raise RuntimeError('缺少 WebView2Loader.dll，请完整解压软件包后重试。')
    library=c.WinDLL(str(loader));version=c.c_void_p()
    query=library.GetAvailableCoreWebView2BrowserVersionString
    query.argtypes=[c.c_wchar_p,c.POINTER(c.c_void_p)];query.restype=c.c_long
    result=query(None,c.byref(version))
    try:return c.wstring_at(version) if result==0 and version.value else None
    finally:
        if version.value:
            free=c.windll.ole32.CoTaskMemFree;free.argtypes=[c.c_void_p];free.restype=None;free(version)

def ensure_webview2(app,probe=None):
    if os.name!='nt':return True
    probe=probe or webview2_version
    if probe(app):return True
    import tkinter as tk
    from tkinter import ttk
    import webbrowser
    root=tk.Tk();root.title('EmojiBridge · 安装界面运行组件');root.resizable(False,False)
    frame=ttk.Frame(root,padding=22);frame.pack()
    ttk.Label(frame,text='尚未检测到 Microsoft Edge WebView2 Runtime',font=('',12,'bold')).pack(anchor='w')
    ttk.Label(frame,text='这是显示软件界面所需的微软组件，与抠图、视频模型无关。\n打开微软下载页，安装 Evergreen Standalone Installer（x64），\n安装完成后点“重新检查”。已有素材和草稿不会被删除。',padding=(0,12)).pack(anchor='w')
    status=tk.StringVar();ttk.Label(frame,textvariable=status).pack(anchor='w')
    buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=(12,0));ready=[False]
    def download():
        try:opened=webbrowser.open(WEBVIEW2_DOWNLOAD)
        except Exception:opened=False
        status.set('下载页已打开；安装完成后返回这里重试。' if opened else '浏览器未打开，请复制下方地址到浏览器。')
    def retry():
        if probe(app):ready[0]=True;root.destroy()
        else:status.set('仍未检测到运行组件，请完成安装后重试。')
    ttk.Button(buttons,text='打开微软下载页',command=download).pack(side='left',padx=(0,8))
    ttk.Button(buttons,text='重新检查',command=retry).pack(side='left',padx=(0,8))
    ttk.Button(buttons,text='退出',command=root.destroy).pack(side='right')
    url=ttk.Entry(frame,width=78);url.insert(0,WEBVIEW2_DOWNLOAD);url.configure(state='readonly');url.pack(fill='x',pady=(12,0))
    root.mainloop();return ready[0]
