"""Optional desktop host; keep the existing Python runtime and data service."""
from pathlib import Path
import os,sys

APP=Path(__file__).resolve().parents[1]

def activate():
    bundled=APP/'runtime'/'desktop'
    folder=bundled if (bundled/'webview').exists() else Path(os.environ.get('LOCALAPPDATA',Path.home()))/'EmojiBridge/optional/desktop-webview-6.2.1'
    if not (folder/'webview/__init__.py').is_file():
        raise RuntimeError('新版桌面组件未准备好。请完整解压体验包，或使用“启动原版编辑器”。')
    sys.path.insert(0,str(folder));return folder
