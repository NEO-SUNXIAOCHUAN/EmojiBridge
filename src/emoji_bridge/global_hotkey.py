"""Windows RegisterHotKey with NOREPEAT; one owner, clean unregister."""
import ctypes,threading,queue
from ctypes import wintypes

class Hotkey:
 def __init__(self,combination,callback):
  parts=combination.upper().split('+');mods=0x4000;keys={'CTRL':2,'ALT':1,'SHIFT':4,'WIN':8}
  for part in parts[:-1]:
   if part not in keys:raise ValueError('快捷键使用 Ctrl / Alt / Shift / Win ＋ 一个字母')
   mods|=keys[part]
  key=parts[-1]
  if len(key)!=1 or not key.isascii() or not key.isalnum() or mods==0x4000:raise ValueError('请使用至少一个修饰键和字母/数字')
  self.id=None;ready=queue.Queue()
  def run():
   user=ctypes.windll.user32;self.id=ctypes.windll.kernel32.GetCurrentThreadId();message=wintypes.MSG()
   if not user.RegisterHotKey(None,0xEB13,mods,ord(key)):ready.put(False);return
   ready.put(True)
   try:
    while user.GetMessageW(ctypes.byref(message),None,0,0)>0:
     if message.message==0x312:
      try:callback()
      except Exception:pass
   finally:user.UnregisterHotKey(None,0xEB13)
  self.thread=threading.Thread(target=run,daemon=True,name='material-hotkey');self.thread.start()
  if not ready.get(timeout=3):raise ValueError('这个快捷键已被其他软件占用，请换一个组合')
 def close(self):
  if self.id:ctypes.windll.user32.PostThreadMessageW(self.id,0x12,0,0)
