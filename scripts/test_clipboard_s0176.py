"""Real Windows clipboard formats on an isolated, hidden owner window."""
from pathlib import Path
import sys,tempfile,ctypes as c,unittest
from ctypes import wintypes as w
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from PIL import Image
from emoji_bridge.file_clipboard import copy_media_to_clipboard

class Clipboard(unittest.TestCase):
    def test_static_transparency_and_animation_original(self):
        u=c.WinDLL('user32');shell=c.WinDLL('shell32')
        u.CreateWindowExW.argtypes=[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,c.c_int,c.c_int,c.c_int,c.c_int,w.HWND,w.HMENU,w.HINSTANCE,c.c_void_p];u.CreateWindowExW.restype=w.HWND
        u.DestroyWindow.argtypes=[w.HWND];u.OpenClipboard.argtypes=[w.HWND]
        u.GetClipboardData.argtypes=[w.UINT];u.GetClipboardData.restype=w.HANDLE
        u.RegisterClipboardFormatW.argtypes=[w.LPCWSTR];u.RegisterClipboardFormatW.restype=w.UINT
        shell.DragQueryFileW.argtypes=[w.HANDLE,w.UINT,w.LPWSTR,w.UINT];shell.DragQueryFileW.restype=w.UINT
        hwnd=u.CreateWindowExW(0,'STATIC','EmojiBridge clipboard test',0,0,0,1,1,w.HWND(-3),None,None,None)
        self.assertTrue(hwnd)
        try:
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);png=root/'透明.png';gif=root/'动画.gif'
                a=Image.new('RGBA',(12,18),(210,40,70,100));a.save(png)
                a.convert('RGB').save(gif,save_all=True,append_images=[Image.new('RGB',a.size,'blue')],duration=80)
                for file,animated in ((png,False),(gif,True)):
                    result=copy_media_to_clipboard(file,hwnd)
                    self.assertEqual(result['kind'],'animation_file' if animated else 'image_and_file')
                    self.assertTrue(u.OpenClipboard(hwnd))
                    try:
                        self.assertTrue(u.IsClipboardFormatAvailable(15))
                        self.assertEqual(bool(u.IsClipboardFormatAvailable(17)),not animated)
                        self.assertEqual(bool(u.IsClipboardFormatAvailable(u.RegisterClipboardFormatW('PNG'))),not animated)
                        drop=u.GetClipboardData(15);text=c.create_unicode_buffer(32768);shell.DragQueryFileW(drop,0,text,len(text))
                        self.assertEqual(Path(text.value),file)
                        u.EmptyClipboard()
                    finally:u.CloseClipboard()
        finally:u.DestroyWindow(hwnd)

if __name__=='__main__':unittest.main()
