"""Draft asset preservation, real Tk pan exit, independent Win32 stickers."""
from pathlib import Path
import sys,tempfile,unittest,hashlib,ctypes as c
from ctypes import wintypes as w
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from PIL import Image

class Drafts(unittest.TestCase):
    def test_batch_validates_before_removing_and_preserves_scene_assets(self):
        from draft_catalog import remove_many,listing,resolve
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for ident in ('aa','bb','cc'):
                p=root/'drafts'/ident;p.mkdir(parents=True)
                (p/'scene.json').write_text('{"name":"draft"}')
                (p/'original.png').write_bytes(b'immutable referenced asset')
            with self.assertRaises(ValueError):remove_many(root,['aa','../bad'])
            self.assertEqual(len(listing(root)),3)
            self.assertEqual(remove_many(root,['aa','bb','aa']),['aa','bb'])
            self.assertEqual([x['id'] for x in listing(root)],['cc'])
            for ident in ('aa','bb'):
                self.assertEqual((root/'drafts'/ident/'original.png').read_bytes(),b'immutable referenced asset')
                self.assertTrue((root/'drafts'/ident/'scene.json').is_file())
                with self.assertRaises(ValueError):resolve(root,ident)

class Pan(unittest.TestCase):
    def test_pan_button_escape_and_tool_switch_restore_editing(self):
        from emoji_bridge.materials import MaterialStore
        from material_library_ui import create_root
        from desktop_shell import DesktopShell
        import time,gc
        with tempfile.TemporaryDirectory() as folder:
            root=create_root();store=MaterialStore(Path(folder)/'library');shell=DesktopShell(root,store,base=Path(folder)/'client')
            try:
                path=Path(folder)/'picture.png';Image.new('RGBA',(180,120),'red').save(path)
                item=store.import_file(path)[0];shell.edit([item['id']])
                end=time.monotonic()+10
                while shell.editor.busy and time.monotonic()<end:root.update();time.sleep(.01)
                e=shell.editor;root.update();revision=e.doc.revision
                e.hand_button.invoke();self.assertTrue(e.hand_mode)
                e.canvas.event_generate('<ButtonPress-1>',x=100,y=100)
                e.canvas.event_generate('<B1-Motion>',x=130,y=140)
                e.canvas.event_generate('<ButtonRelease-1>',x=130,y=140)
                pan=e.pan;e.hand_button.invoke();self.assertFalse(e.hand_mode)
                self.assertEqual(e.pan,pan);self.assertEqual(e.doc.revision,revision)
                e.hand_button.invoke();e.canvas.focus_force();root.update()
                e.canvas.event_generate('<Escape>');root.update();self.assertFalse(e.hand_mode)
                e.hand_button.invoke();e.set_tool('text');self.assertFalse(e.hand_mode)
                e.select_tool();layer=e.doc.layers[0];ident=layer['id'];a,b,_,_=e.doc.layer_bounds(ident)
                x=round(e.origin[0]+(a+40)*e.scale);y=round(e.origin[1]+(b+40)*e.scale)
                before=e.doc._find(ident)['position']
                e.canvas.event_generate('<ButtonPress-1>',x=x,y=y)
                e.canvas.event_generate('<B1-Motion>',x=x+30,y=y+20)
                e.canvas.event_generate('<ButtonRelease-1>',x=x+30,y=y+20);root.update()
                self.assertNotEqual(e.doc._find(ident)['position'],before)
            finally:
                if shell.editor and not shell.editor.closed:shell.editor.close(force=True)
                shell.close();shell=None;root=None;gc.collect()

class Stickers(unittest.TestCase):
    def test_repeated_instances_pin_toggle_rotation_and_original_preserved(self):
        from emoji_bridge.desktop_stickers import StickerManager
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'picture.png';Image.new('RGBA',(100,60),'red').save(path)
            original=hashlib.sha256(path.read_bytes()).hexdigest();manager=StickerManager()
            try:
                handles=[int(manager.show(path,'same-material')['id']) for _ in range(3)]
                self.assertEqual(len(set(handles)),3)
                h=handles[0]
                def clicks():
                    state=manager._windows[h];point=w.POINT()
                    manager.user32.GetCursorPos(c.byref(point))
                    manager.user32.SetCursorPos.argtypes=[c.c_int,c.c_int]
                    try:
                        manager.user32.SetCursorPos(state['x']+5,state['y']+5)
                        manager._procedure(h,0x0201,0,0)
                        manager._procedure(h,0x0202,0,0)
                        self.assertTrue(state['fixed'])
                        self.assertFalse(manager.user32.GetWindowLongPtrW(h,-20)&0x20)
                        manager._procedure(h,0x0201,0,0);manager._procedure(h,0x0202,0,0);self.assertFalse(state['fixed'])
                        size=manager._display_frame(state).size
                        manager._rotate(h,90);self.assertEqual(manager._display_frame(state).size,size[::-1])
                        self.assertEqual(manager._windows[handles[1]].get('angle',0),0)
                        manager._rotate(h,0);self.assertEqual(manager._display_frame(state).size,size)
                    finally:manager.user32.SetCursorPos(point.x,point.y)
                manager._submit(clicks)
                self.assertEqual(manager.close_all()['closed'],3)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),original)
                self.assertIsNone(manager._error)
            finally:manager.shutdown()

if __name__=='__main__':unittest.main()
