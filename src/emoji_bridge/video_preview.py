"""Bounded FFmpeg preview and on-demand frame cache; never runs matting."""
import hashlib
import json
import queue
import subprocess
import threading
from pathlib import Path
from PIL import Image
from .video import frame,ensure_tools,_flags


class FrameCache:
    def __init__(self,path,metadata,root):
        self.path=Path(path);self.metadata=metadata
        stat=self.path.stat()
        key=hashlib.sha256(str((str(self.path.resolve()),stat.st_size,stat.st_mtime_ns)).encode()).hexdigest()
        self.root=Path(root)/key;self.root.mkdir(parents=True,exist_ok=True)

    def get(self,seconds,width=160,cancel=None):
        seconds=round(max(0,min(float(seconds),self.metadata['duration']-.001)),3)
        output=self.root/f'{width}-{round(seconds*1000)}.png'
        if not output.exists():frame(self.path,seconds,output,width=width,metadata=self.metadata,cancel=cancel)
        with Image.open(output) as image:return image.convert('RGB')


class VideoStream:
    """Stream only the selected interval, retaining at most three decoded frames."""
    def __init__(self,path,metadata,start,end,width=720,fps=30):
        self.frames=queue.Queue(maxsize=3);self.stop=threading.Event();self.process=None
        self.start=float(start);self.end=float(end);self.fps=min(fps,metadata['fps'] or fps)
        self.width=min(width,metadata['width']);self.height=max(1,round(metadata['height']*self.width/metadata['width']))
        self.path=path;self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def put(self,value):
        while not self.stop.is_set():
            try:self.frames.put(value,timeout=.05);return
            except queue.Full:pass

    def run(self):
        try:
            ffmpeg,_=ensure_tools(cancel=self.stop)
            command=[str(ffmpeg),'-nostdin','-v','error','-ss',str(self.start),'-t',str(self.end-self.start),'-i',str(self.path),
                '-an','-vf',f'fps={self.fps},scale={self.width}:{self.height},setsar=1','-f','rawvideo','-pix_fmt','rgb24','pipe:1']
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,**_flags());self.process=process
            size=self.width*self.height*3;index=0
            while not self.stop.is_set():
                data=bytearray()
                while len(data)<size:
                    block=process.stdout.read(size-len(data))
                    if not block:break
                    data.extend(block)
                if len(data)!=size:break
                self.put((Image.frombytes('RGB',(self.width,self.height),bytes(data)),self.start+index/self.fps));index+=1
            if not self.stop.is_set():
                code=process.wait()
                self.put((None,'结束' if code==0 else '此片段无法继续预览'))
        except Exception as exc:
            if not self.stop.is_set():self.put((None,str(exc)))
        finally:
            process=self.process
            if process:
                if process.poll() is None:process.terminate()
                process.wait(timeout=3);process.stdout.close()

    def close(self):
        self.stop.set()
        if self.process and self.process.poll() is None:self.process.terminate()
