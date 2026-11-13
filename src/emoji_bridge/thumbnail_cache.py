"""Bounded presentation cache. Originals and export quality are untouched."""
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
import threading,hashlib
from PIL import Image

class ThumbnailCache:
    def __init__(self, entries=128, budget=16*1024*1024, root=None):
        self.entries=entries;self.budget=budget;self.bytes=0
        self.items=OrderedDict();self.lock=threading.Lock()
        self.root=Path(root) if root else None

    def read(self, file, size=384):
        size=max(96,min(1024,int(size)))
        file=Path(file);stat=file.stat();key=(str(file),stat.st_size,stat.st_mtime_ns,size)
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key);return self.items[key]
            cached=self.root/(hashlib.sha256(repr(key).encode()).hexdigest()+'.png') if self.root else None
            if cached and cached.is_file():data=cached.read_bytes()
            else:
                with Image.open(file) as source:
                    source.thumbnail((size,size),Image.Resampling.LANCZOS);stream=BytesIO();source.convert('RGBA').save(stream,'PNG')
                data=stream.getvalue()
                if cached:
                    cached.parent.mkdir(parents=True,exist_ok=True);temp=cached.with_suffix('.partial');temp.write_bytes(data);temp.replace(cached)
                    # Derived display data only; bounded disk cache, originals untouched.
                    files=list(cached.parent.glob('*.png'))
                    if len(files)>1024:
                        for old in sorted(files,key=lambda p:p.stat().st_mtime)[:len(files)-1024]:old.unlink(missing_ok=True)
            if len(data)<=self.budget:
                self.items[key]=data;self.bytes+=len(data)
                while len(self.items)>self.entries or self.bytes>self.budget:
                    self.bytes-=len(self.items.popitem(last=False)[1])
            return data
