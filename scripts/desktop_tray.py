"""The existing WinForms host owns the tray; no second GUI/event loop."""
from pathlib import Path
import threading,json

class DesktopTray:
    def __init__(self,service):
        from pocket_service import on_window
        self.service=service;self.icon=None;self.image=None;self.menu=None
        def setup():
            from System.Drawing import Icon,ColorTranslator
            from System.Windows.Forms import NotifyIcon,ContextMenuStrip,MouseButtons
            self.image=Icon(str(Path(__file__).resolve().parents[1]/'assets/branding/EmojiBridge.ico'))
            service.window.native.Icon=self.image
            self.menu=ContextMenuStrip();self.icon=NotifyIcon()
            tokens=json.loads((Path(__file__).resolve().parents[1]/'assets/ui-midnight.json').read_text('utf8'))
            self.menu.BackColor=ColorTranslator.FromHtml(tokens['raised']);self.menu.ForeColor=ColorTranslator.FromHtml(tokens['ink'])
            self.icon.Icon=self.image;self.icon.Text='EmojiBridge · 随手素材';self.icon.ContextMenuStrip=self.menu
            def launch(fn):
                def run():
                    try:fn()
                    except Exception as exc:service.task['text']='操作未完成：'+str(exc)
                threading.Thread(target=run,daemon=True,name='tray-action').start()
            def main(settings=False):
                def restore():
                    import ctypes
                    native=service.window.native
                    ctypes.windll.user32.ShowWindow(ctypes.c_void_p(int(native.Handle.ToInt64())),9)
                    native.Activate()
                on_window(service.window,restore)
                if settings:
                    service.route_serial+=1;service.route_event={'serial':service.route_serial,'page':'settings'}
            for label,fn in [('打开主窗口',main),('打开随手素材',service.open_drawer),
                    ('调整贴图',service.adjust_stickers),('全部收回贴图',service.reclaim_stickers),
                    ('找回屏幕外贴图',service.recover_stickers),('设置',lambda:main(True)),
                    ('退出',service.close_window)]:
                item=self.menu.Items.Add(label);item.Click+=lambda s,e,call=fn:launch(call)
            self.icon.MouseClick+=lambda s,e:launch(service.pocket.toggle) if e.Button==MouseButtons.Left else None
            self.icon.Visible=True
        on_window(service.window,setup)

    def close(self):
        if self.icon:self.icon.Visible=False;self.icon.Dispose();self.icon=None
        if self.menu:self.menu.Dispose();self.menu=None
        if self.image:self.image.Dispose();self.image=None
