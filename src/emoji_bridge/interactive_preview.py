"""One active calculation and one latest request per view, with a bounded LRU.

Only Pillow images cross this boundary; callers create Tk objects on their UI thread.
Saving/export never uses or cancels this preview worker.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock


class PreviewQueue:
    def __init__(self, pixels=12_000_000):
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='display-preview')
        self.lock=Lock();self.pending=OrderedDict();self.cache=OrderedDict();self.errors={}
        self.pixels=0;self.limit=pixels;self.running=False;self.closed=False;self.latest={};self.wanted={};self.serial=0;self.active_key=None

    def completed(self,view):
        with self.lock:
            key=self.latest.get(view)
            return (key,self.cache[key]) if key in self.cache else None

    def get(self,key):
        with self.lock:
            value=self.cache.get(key)
            if value is not None:self.cache.move_to_end(key)
            return value

    def request(self,view,key,render):
        with self.lock:
            if self.closed:return
            if self.wanted.get(view)!=key:self.errors.pop(view,None)
            self.wanted[view]=key
            if key in self.cache:
                self.pending.pop(view,None)
                if self.latest.get(view)!=key:self.latest[view]=key;self.serial+=1
                return
            if key==self.active_key:
                self.pending.pop(view,None)
                return
            self.pending[view]=(key,render)
            if view=='central':self.pending.move_to_end(view,last=False)
            if self.running:return
            self.running=True
        self.pool.submit(self._run)

    def _run(self):
        while True:
            with self.lock:
                if self.closed or not self.pending:self.running=False;return
                view,(key,render)=self.pending.popitem(last=False)
                self.active_key=key
            try:
                image=render()
                with self.lock:
                    if self.closed:return
                    old=self.cache.pop(key,None)
                    if old is not None:self.pixels-=old.width*old.height
                    self.cache[key]=image;self.pixels+=image.width*image.height
                    for target,wanted in self.wanted.items():
                        if wanted==key:self.latest[target]=key
                    self.serial+=1
                    while self.pixels>self.limit and len(self.cache)>1:
                        evicted,old=self.cache.popitem(last=False);self.pixels-=old.width*old.height
                        self.latest={v:k for v,k in self.latest.items() if k!=evicted}
                    self.errors.pop(view,None)
                    self.active_key=None
            except Exception as exc:
                with self.lock:
                    if self.wanted.get(view)==key:self.errors[view]=str(exc)
                    self.active_key=None

    def clear_pending(self):
        with self.lock:self.pending.clear()

    def close(self):
        with self.lock:self.closed=True;self.pending.clear();self.cache.clear();self.latest.clear();self.pixels=0
        self.pool.shutdown(wait=False,cancel_futures=True)
