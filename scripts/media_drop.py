"""Receive browser File bytes when a native drop has no filesystem path.

The browser is the source, not its HTML thumbnail or a fetched page. Chunks are
bounded and staged on disk; the ordinary material importer owns validation,
deduplication, persistent storage, video routing and cancellation.
"""
import base64
import json
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from concurrent.futures import CancelledError
from emoji_bridge.frame_store import MAX_INPUT_BYTES

CHUNK_BYTES = 512 * 1024


class BrowserFiles:
    def __init__(self, owner):
        self.owner = owner
        self.lock = threading.Lock()
        self.batch = None

    def begin(self, files):
        if not files:raise ValueError('没有收到实际文件数据；网页链接和 HTML 尚不能作为原件导入。')
        rows=[]
        for data in files:
            name=str(data['name']).replace('\\','/').rsplit('/',1)[-1]
            size=int(data['size'])
            if not name or size<=0:raise ValueError('拖入的文件为空，未导入。')
            if size>MAX_INPUT_BYTES:raise ValueError('本地媒体单文件上限为 1 GiB；原件未改变。')
            rows.append(dict(name=name,size=size,received=0,ready=threading.Event(),error='',updated=time.monotonic()))
        with self.lock:
            if self.batch or self.owner.task.get('active') or self.owner.closing:
                return {'accepted':False,'message':'已有任务正在处理，请稍后重试。'}
            folder=self.owner.store.root/'cache/browser-drops';folder.mkdir(parents=True,exist_ok=True)
            root=Path(tempfile.mkdtemp(prefix='drop-',dir=folder));token=uuid.uuid4().hex
            for i,row in enumerate(rows):
                # Keep only the suffix as a hint. The importer inspects bytes.
                suffix=Path(row['name']).suffix
                row['path']=root/(str(i)+(suffix if len(suffix)<16 and suffix[1:].isalnum() else '.media'))
            batch=dict(token=token,rows=rows,root=root)
            self.batch=batch
            def records():
                for row in rows:
                    # Later files must get their own inactivity window. A large
                    # preceding file may legitimately take longer than 30 s.
                    row['updated']=time.monotonic()
                    while not row['ready'].wait(.1):
                        if self.owner.cancel.is_set():raise CancelledError()
                        if time.monotonic()-row['updated']>30:
                            row['error']='拖放文件数据接收超时，可重新拖入。';break
                    if self.owner.cancel.is_set():raise CancelledError()
                    yield row['path'],row['name'],row['error'],'浏览器拖入文件：'+row['name']
            def work():
                try:return self.owner.import_records(records(),len(rows),'drop')
                finally:
                    with self.lock:
                        if self.batch is batch:self.batch=None
                        shutil.rmtree(root,ignore_errors=True)
            result=self.owner.start(work,'正在接收拖入的原文件…')
            if not result.get('accepted'):
                self.batch=None;shutil.rmtree(root,ignore_errors=True);return result
            return dict(result,token=token,chunk_size=CHUNK_BYTES)

    def write(self, token, index, offset, encoded):
        # A bridge message never holds an entire large GIF in memory.
        if len(encoded)>((CHUNK_BYTES+2)//3)*4:raise ValueError('拖放数据块过大')
        body=base64.b64decode(encoded,validate=True)
        with self.lock:
            row=self.row(token,index)
            if row['ready'].is_set() or int(offset)!=row['received']:raise ValueError('拖放数据顺序不一致，请重新拖入。')
            if not body or row['received']+len(body)>row['size']:raise ValueError('拖放文件长度不一致。')
            with row['path'].open('ab') as stream:stream.write(body)
            row['received']+=len(body);row['updated']=time.monotonic()
        return True

    def finish(self, token, index, error=''):
        with self.lock:
            row=self.row(token,index)
            row['error']=str(error)[:500]
            if not error and row['received']!=row['size']:row['error']='没有收到完整文件，未导入。'
            row['ready'].set()
        return True

    def row(self,token,index):
        if not self.batch or self.batch['token']!=token or self.owner.cancel.is_set():raise CancelledError('导入已取消或结束。')
        return self.batch['rows'][int(index)]


def receive(owner, window, event, notice):
    """The native path is fastest; pathless browser Files use the same importer."""
    data=event.get('dataTransfer',{});files=data.get('files',[])
    paths=[f.get('pywebviewFullPath') for f in files]
    ticket=event.get('emojiDropId')
    # Metadata only: no webpage HTML, signed URLs, chat content or media bytes.
    from emoji_bridge.state import save_json
    try:
        save_json(owner.store.root/'diagnostics/last-drop.json',{
            'types':data.get('types',[]),'files':[{'name':f.get('name'),'size':f.get('size'),'type':f.get('type'),'has_path':bool(p)} for f,p in zip(files,paths)],
            'route':'native_paths' if paths and all(paths) else 'browser_files' if files else 'unsupported_payload'})
    except OSError:
        pass  # A diagnostic write must not consume an otherwise valid drop.
    if paths and all(paths):
        if ticket:window.evaluate_js('window.emojiDropRelease?.('+json.dumps(ticket)+')')
        result=owner.import_paths(paths,'drop')
        if not result.get('accepted'):notice(result.get('message','导入未开始。'))
    elif files and ticket:
        window.evaluate_js('void window.emojiDropImport?.('+json.dumps(ticket)+')')
    else:
        if ticket:window.evaluate_js('window.emojiDropRelease?.('+json.dumps(ticket)+')')
        notice('没有收到实际文件数据；网页链接或 HTML 不能当作 GIF 原件导入。')
