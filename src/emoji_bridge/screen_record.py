"""Explicit Windows region capture using the existing FFmpeg gdigrab device."""
from pathlib import Path
import subprocess
import time
from .video import ensure_tools,_flags,probe


class RegionRecording:
    def __init__(self,region,path,*,fps=12,max_seconds=600):
        x,y,width,height=map(int,region)
        if width<16 or height<16 or width*height>16_000_000:raise ValueError('请选择16像素以上、不超过1600万像素的录制区域')
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.temporary=self.path.with_name(self.path.stem+'.recording.mp4')
        ffmpeg,_=ensure_tools()
        self.log=self.path.with_suffix('.log').open('wb');self.started=time.monotonic()
        args=[str(ffmpeg),'-hide_banner','-v','error','-f','gdigrab','-framerate',str(fps),'-draw_mouse','0',
              '-offset_x',str(x),'-offset_y',str(y),'-video_size',f'{width}x{height}','-i','desktop',
              '-t',str(max_seconds),'-an','-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2',
              '-c:v','libx264','-preset','ultrafast','-crf','18','-pix_fmt','yuv420p',str(self.temporary)]
        try:self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=self.log,**_flags())
        except Exception:self.log.close();raise

    def running(self):return self.process.poll() is None

    def stop(self):
        try:
            if self.running():
                self.process.stdin.write(b'q\n');self.process.stdin.flush()
            try:self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.terminate();self.process.wait(timeout=3)
                raise ValueError('录屏未能正常结束，已停止采集；原素材保持')
            if self.process.returncode or not self.temporary.exists():raise ValueError('录屏失败，请重新选择可见区域；日志已保留')
            info=probe(self.temporary)
            if info['duration']<=0:raise ValueError('未录到有效画面，请重新开始')
            self.temporary.replace(self.path);return self.path
        finally:
            self.log.close()
            if self.process.stdin:self.process.stdin.close()
