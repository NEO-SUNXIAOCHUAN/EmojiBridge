"""Bounded background preview: one open asset, never decode every GIF in the grid."""
import queue
import threading
import time
from PIL import Image, ImageOps


class FrameStream:
    def __init__(self, path, size=(760, 560), *, start_frame=0, loop=True, end_frame=None,respect_loop=False):
        self.frames = queue.Queue(maxsize=2)
        self.stop = threading.Event()
        self.done = threading.Event()
        self.first_frame_ms=None;self.started=time.perf_counter()
        self.thread = threading.Thread(target=self._decode, args=(path, size, start_frame, loop, end_frame,respect_loop), daemon=True,
                                       name='material-preview')
        self.thread.start()

    def _put(self, value):
        while not self.stop.is_set():
            try:
                self.frames.put(value, timeout=.1)
                return True
            except queue.Full:
                pass
        return False

    def _decode(self, path, size, start_frame, loop, end_frame,respect_loop):
        try:
            with Image.open(path) as image:
                from .frame_store import animation_offset,frame_duration
                offset=animation_offset(image)
                count = getattr(image, 'n_frames', 1)-offset
                repeats=image.info.get('loop');cycles=0
                total=None if repeats==0 else (1 if repeats is None else repeats+1 if image.format=='GIF' else repeats)
                while not self.stop.is_set():
                    for n in range(start_frame, min(count,end_frame) if end_frame is not None else count):
                        if self.stop.is_set():
                            return
                        image.seek(n+offset)
                        frame = ImageOps.exif_transpose(image).convert('RGBA')
                        frame.thumbnail(size, Image.Resampling.LANCZOS)
                        duration = frame_duration(image)
                        if self.first_frame_ms is None:self.first_frame_ms=(time.perf_counter()-self.started)*1000
                        if not self._put((frame, duration, n, count)):
                            return
                    cycles+=1
                    if count == 1 or not loop or respect_loop and total is not None and cycles>=total:
                        return
                    start_frame=0
        except Exception as exc:
            self._put((None, str(exc), 0, 0))
        finally:self.done.set()

    def close(self):
        self.stop.set()


def thumbnail(path):
    with Image.open(path) as image:
        return image.convert('RGBA')
