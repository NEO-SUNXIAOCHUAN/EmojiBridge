"""Explicit, cancellable local-library check. Never resets data or permissions."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from .paths import APP_ROOT
from .state import sha, save_json
from .material_diagnostics import record,access_context


def _reason(exc):
    if isinstance(exc, PermissionError):return '访问被拒绝或文件正被独占，不等于原件损坏；关闭占用后重试，仍失败请保留检查结果'
    if isinstance(exc, FileNotFoundError):return '原件缺失；保留记录，需找回原文件或备份'
    if isinstance(exc, IsADirectoryError):return '原件记录指向文件夹；保留记录待检查'
    return '文件内容或访问异常；详见本地诊断'


def run(store, *, cancel=None, progress=None, examples=None, ids=None):
    examples=Path(examples) if examples else APP_ROOT/'assets/examples'
    # Exact content identity, never names, first frames, or UI positions.
    bundled={}
    for entry in json.loads((examples/'manifest.json').read_text('utf8')):
        if cancel and cancel.is_set():break
        path=examples/entry['file']
        bundled[sha(path)]=path
    if ids is None and examples==APP_ROOT/'assets/examples':
        from .promo_assets import media_sources
        bundled.update(media_sources())
    live=set(store.matching_ids())
    ids=list(live) if ids is None else [ident for ident in dict.fromkeys(ids) if ident in live]
    report={'version':2,'access':access_context(store.root),'total':len(ids),'checked':0,'healthy':0,'restored':0,'covers_rebuilt':0,'issues':[],'cancelled':False}
    backup=None
    for ident in ids:
        if cancel and cancel.is_set():report['cancelled']=True;break
        item=store.get(ident)
        try:
            try:original=store.original(ident)
            except FileNotFoundError:
                source=bundled.get(ident)
                if not source:raise
                if sha(source)!=ident:raise ValueError('recovery_content_mismatch')
                # Back up SQLite before any index update; keep old locations and
                # files intact. Recovery writes only a new owned content object.
                if backup is None:
                    directory=store.root/'diagnostics';directory.mkdir(exist_ok=True)
                    fd,name=tempfile.mkstemp(prefix='materials-before-repair-',suffix='.db',dir=directory);os.close(fd)
                    backup=Path(name)
                    with store.connect() as conn:
                        dest=sqlite3.connect(backup)
                        try:conn.backup(dest)
                        finally:dest.close()
                directory=store.root/'objects'/ident[:2]/ident
                directory.mkdir(parents=True,exist_ok=True)
                original=directory/('recovered-original'+source.suffix.lower())
                if original.exists():
                    if sha(original)!=ident:raise ValueError('recovery_content_mismatch')
                else:
                    fd,name=tempfile.mkstemp(prefix='recover-',suffix='.tmp',dir=directory)
                    temp=Path(name)
                    try:
                        with os.fdopen(fd,'wb') as out,source.open('rb') as src:
                            while chunk:=src.read(1024*1024):
                                if cancel and cancel.is_set():raise InterruptedError('cancelled')
                                out.write(chunk)
                            out.flush();os.fsync(out.fileno())
                        if sha(temp)!=ident:raise ValueError('recovery_content_mismatch')
                        os.replace(temp,original)
                    finally:temp.unlink(missing_ok=True)
                with store.connect() as conn:
                    conn.execute('UPDATE materials SET relative_file=? WHERE id=? AND relative_file=?',
                                 (str(original.relative_to(store.root)),ident,item['relative_file']))
                report['restored']+=1;item=store.get(ident)
            cover=item['thumbnail']
            from PIL import Image
            try:
                with Image.open(cover) as image:image.verify()
                valid=True
            except (OSError,ValueError,SyntaxError):valid=False
            store.thumbnail_bytes(ident)
            if not valid:report['covers_rebuilt']+=1
            report['healthy']+=1
        except InterruptedError:
            report['cancelled']=True;break
        except (OSError,ValueError,SyntaxError) as exc:
            record(store.root,'library_check',item['path'],exc,ident=ident)
            report['issues'].append({'id':ident[:16],'reason':_reason(exc),'error':type(exc).__name__,
                                    'errno':getattr(exc,'errno',None),'winerror':getattr(exc,'winerror',None)})
        report['checked']+=1
        if progress:progress(report['checked'],len(ids))
    # One refresh also retries covers that failed transiently in the browser.
    with store.connect() as conn:conn.execute('UPDATE library_revision SET value=value+1')
    save_json(store.root/'library-check.json',report)
    return report
