"""Pinned upstream gifski C API: streaming RGBA and non-uniform timestamps."""
from pathlib import Path
import ctypes as c,hashlib,tarfile
from PIL import Image
from .capabilities import root,download
from .animated_edit import check_cancel,selected_document,output_dimensions

VERSION='1.34.0'
def ensure(cancel=None,progress=None):
 folder=root()/'gifski';dll=folder/'gifski.dll'
 if dll.is_file():return dll
 folder.mkdir(parents=True,exist_ok=True);archive=folder/('gifski-'+VERSION+'.tar.xz')
 if not archive.exists():download('https://github.com/ImageOptim/gifski/releases/download/'+VERSION+'/'+archive.name,archive,cancel,progress)
 with archive.open('rb') as stream:
  if hashlib.file_digest(stream,'sha256').hexdigest()!='b9b6591aa163123d737353d9c8581efdf3234d28eeaa45329b31da905cd5a996':raise ValueError('gifski 组件摘要不符；请重新准备组件')
 with tarfile.open(archive) as pack:
  for name in ('win/developer/gifski.dll','win/developer/gifski.h','LICENSE'):
   check_cancel(cancel);(folder/Path(name).name).write_bytes(pack.extractfile(name).read())
 return dll

def export(document,path,*,cancel=None,progress=None,output_size=None,quality=90):
 document=selected_document(document);animation=document.animation
 if not animation:raise ValueError('高质量 GIF 需要动态作品')
 dll=ensure(cancel,lambda stage,n,t:progress(n,t,stage) if progress else None);lib=c.CDLL(str(dll))
 class Settings(c.Structure):_fields_=[('width',c.c_uint32),('height',c.c_uint32),('quality',c.c_uint8),('fast',c.c_bool),('repeat',c.c_int16)]
 lib.gifski_new.argtypes=[c.POINTER(Settings)];lib.gifski_new.restype=c.c_void_p
 lib.gifski_set_file_output.argtypes=[c.c_void_p,c.c_char_p];lib.gifski_set_file_output.restype=c.c_int
 lib.gifski_add_frame_rgba.argtypes=[c.c_void_p,c.c_uint32,c.c_uint32,c.c_uint32,c.c_void_p,c.c_double];lib.gifski_add_frame_rgba.restype=c.c_int
 lib.gifski_finish.argtypes=[c.c_void_p];lib.gifski_finish.restype=c.c_int
 callback_type=c.CFUNCTYPE(c.c_int,c.c_void_p);lib.gifski_set_progress_callback.argtypes=[c.c_void_p,callback_type,c.c_void_p]
 repeat=-1 if animation.loop is None else animation.loop
 if not -1<=repeat<=32767:raise ValueError('gifski 循环次数超出范围；请选择标准编码或 APNG')
 settings=Settings(0,0,int(quality),False,repeat);handle=lib.gifski_new(c.byref(settings))
 if not handle:raise RuntimeError('gifski 编码器无法初始化')
 callback=callback_type(lambda _:int(cancel is None or not cancel.is_set()))
 lib.gifski_set_progress_callback(handle,callback,None)
 path=Path(path);partial=path.with_suffix('.gifski.partial');size=output_dimensions(document,output_size)
 def ok(code):
  if code:check_cancel(cancel);raise RuntimeError('gifski 编码失败：'+str(code))
 try:
  ok(lib.gifski_set_file_output(handle,str(partial).encode('utf-8')))
  # The upstream API uses positive first PTS as the exact last-frame delay.
  position=animation.durations[-1]/1000
  for index,duration in enumerate(animation.durations):
   check_cancel(cancel);frame=document.render(animation_frame=index).convert('RGBA')
   if frame.size!=size:frame=frame.resize(size,Image.Resampling.LANCZOS)
   # GIF is binary-alpha; make the threshold explicit and identical to standard.
   frame.putalpha(frame.getchannel('A').point(lambda a:255 if a>=128 else 0))
   pixels=frame.tobytes();ok(lib.gifski_add_frame_rgba(handle,index,*size,c.c_char_p(pixels),position));position+=duration/1000
   if progress:progress(index+1,len(animation.durations),'高质量 GIF 编码')
  code=lib.gifski_finish(handle);handle=None;ok(code);check_cancel(cancel)
  with Image.open(partial) as image:
   elapsed=0
   for index in range(image.n_frames):image.seek(index);image.load();elapsed+=image.info.get('duration',0)
   if image.size!=size or abs(elapsed-sum(animation.durations))>10:raise ValueError('高质量 GIF 尺寸或时序核验失败')
  partial.replace(path);return path
 finally:
  if handle:lib.gifski_finish(handle)
  partial.unlink(missing_ok=True)
