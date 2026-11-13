"""Read a specific WeChat emoticon index, without persisting keys or memory dumps.

Windows reader/page AES reused from Ant39140/wechat_meme_export (MIT).
WCDB 4.1 layout verified against liusheng22/export-wechat-emoji; see notices.
No chat DB discovery, cached image search, thumbnail or non-favorite fallback.
"""
from __future__ import annotations
import ctypes
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import struct
import time
from urllib.parse import urlsplit
from urllib.parse import urlunsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError, URLError
import io
from contextvars import ContextVar
from contextlib import contextmanager
from PIL import Image

from .paths import DATA_ROOT as ROOT, APP_ROOT
PAGE = 4096
LIMIT = 128 * 1024 * 1024
NAME = b'com.Tencent.WCDB.Config.Cipher'
MASK = bytes.fromhex('d2c7442458020000004889442450488b450048844c2448488944254048584c24')
KEY_PATTERN = re.compile(rb"[xX]'([0-9a-fA-F]{64,192})'")
_locators = ContextVar('wechat_index_locators', default=None)


@contextmanager
def key_scan_session():
    """Task-local address hints only, never keys or decrypted membership.

    Every use re-reads the process and authenticates the exact current DB page.
    Missing/moved hints fall back to the ordinary bounded search. Nothing is
    written to disk, and nested batch calls share the outer task's lifetime.
    """
    if _locators.get() is not None:
        yield
        return
    hints = {}; token = _locators.set(hints)
    try:yield
    finally:hints.clear(); _locators.reset(token)


class IndexErrorSafe(RuntimeError):
    """Messages must not contain key material, memory, URLs or database values."""


def vendor(name):
    spec = importlib.util.spec_from_file_location('wx_vendor_' + name, APP_ROOT / 'third_party/wechat_meme_export' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mac_key(key, salt):
    return hashlib.pbkdf2_hmac('sha512', key, bytes(x ^ 0x3a for x in salt), 2, 32)


def check_page(page, number, key_mac):
    if len(page) != PAGE or number < 1:
        raise IndexErrorSafe('invalid_page')
    start = 16 if number == 1 else 0
    digest = hmac.new(key_mac, page[start:4032] + struct.pack('<I', number), 'sha512').digest()
    if not hmac.compare_digest(digest, page[4032:]):
        raise IndexErrorSafe('page_authentication_failed')


def matching_key(data, page):
    for match in KEY_PATTERN.finditer(data):
        value = match[1]
        if len(value) % 2:
            continue
        raw = bytes.fromhex(value.decode('ascii'))
        # Only key + exact target database salt, never return unrelated keys.
        if len(raw) != 48 or raw[32:] != page[:16]:
            continue
        try:
            check_page(page, 1, mac_key(raw[:32], page[:16]))
            return raw[:32]
        except IndexErrorSafe:
            pass
    return None


def scan_key(pid, expected_exe, page, timeout=90, progress=lambda event: None, cancel_check=lambda: None):
    from .windows import process_path, file_version
    from .compatibility import require_version, require_memory_architecture
    if process_path(pid) != Path(expected_exe).resolve() or Path(expected_exe).name.lower() != 'weixin.exe':
        raise IndexErrorSafe('wechat_process_identity_mismatch')
    require_version('wechat',file_version(expected_exe))
    require_memory_architecture(expected_exe)
    memory = vendor('memory')
    reader = memory.ProcessMemoryReader()
    handle = reader.open_process(0x410, False, pid)
    if not handle:
        raise IndexErrorSafe('process_read_access_denied')
    deadline = time.monotonic() + timeout
    stats = {'pid': pid, 'bytes_read': 0, 'regions_skipped': 0, 'config_names': 0, 'config_blobs': 0}
    hints = _locators.get()
    identity = (pid, str(Path(expected_exe).resolve()), page[:16])

    def read(address, size):
        cancel_check()
        if time.monotonic() >= deadline:
            raise IndexErrorSafe('key_scan_timeout')
        data = reader.read(handle, address, size)
        stats['bytes_read'] += len(data)
        return data

    def chunks():
        address = 0
        mbi = memory.MemoryBasicInformation()
        while reader.virtual_query_ex(handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            cancel_check()
            if time.monotonic() >= deadline:
                raise IndexErrorSafe('key_scan_timeout')
            base, size = int(mbi.BaseAddress or 0), int(mbi.RegionSize)
            if size <= 0 or base + size <= address:
                break
            address = base + size
            if mbi.State != 0x1000 or mbi.Protect & 0x100 or mbi.Protect & 255 not in (2,4,8,32,64,128):
                continue
            if size > 1024**3:
                stats['regions_skipped'] += 1
                continue
            tail = b''
            for offset in range(0, size, 1024**2):
                data = read(base + offset, min(1024**2, size - offset))
                if not data:
                    break
                block = tail + data
                yield base + offset - len(tail), block
                tail = block[-256:]

    try:
        hint = hints.get(identity) if hints is not None else None
        if hint:
            address, length, masked = hint
            blob = read(address, length)
            decoded = bytes(v ^ MASK[i % 32] for i,v in enumerate(blob)) if masked else blob
            key = matching_key(decoded, page)
            if key:
                return key, dict(stats, method='task_locator_fresh_read_target_hmac')
            hints.pop(identity, None)
        names = set()
        progress({'phase': 'scan_target_process', 'pid': pid})
        for base, data in chunks():
            key = matching_key(data, page)
            if key:
                if hints is not None:
                    match = next(m for m in KEY_PATTERN.finditer(data) if matching_key(m[0], page) == key)
                    hints[identity] = (base + match.start(), len(match[0]), False)
                return key, dict(stats, method='target_salt_literal_hmac')
            offset = data.find(NAME)
            while offset >= 0:
                names.add(base + offset)
                offset = data.find(NAME, offset + 1)
        stats['config_names'] = len(names)
        if not names:
            raise IndexErrorSafe('target_key_not_found')
        progress({'phase': 'scan_config_references', 'config_names': len(names)})
        patterns = [struct.pack('<QQ', address, len(NAME)) for address in names]
        for base, data in chunks():
            for pattern in patterns:
                offset = data.find(pattern)
                while offset >= 0:
                    node = read(base + offset - 0x10, 0x50)
                    if len(node) == 0x50:
                        pointer = struct.unpack_from('<Q', node, 0x28)[0]
                        if 0x10000 < pointer < 0x7fffffffffff:
                            obj = read(pointer + 0x88, 0x28)
                            if len(obj) == 0x28:
                                address, length = struct.unpack_from('<QQ', obj, 8)
                                if 0x10000 < address < 0x7fffffffffff and 0 < length <= 1024:
                                    blob = read(address, length)
                                    stats['config_blobs'] += 1
                                    decoded = bytes(v ^ MASK[i % 32] for i,v in enumerate(blob))
                                    key = matching_key(decoded, page)
                                    if key:
                                        if hints is not None:hints[identity] = (address, length, True)
                                        return key, dict(stats, method='config_cipher_target_salt_hmac')
                    offset = data.find(pattern, offset + 1)
        raise IndexErrorSafe('target_key_not_found')
    finally:
        reader.close_handle(handle)


def snapshot(db_path):
    db_path = Path(db_path).resolve()
    if db_path.name != 'emoticon.db' or db_path.parent.name != 'emoticon':
        raise IndexErrorSafe('only_explicit_emoticon_database_allowed')
    wal_path = Path(str(db_path) + '-wal')
    shm_path = Path(str(db_path) + '-shm')
    def read(path, optional=False):
        if optional and not path.exists():
            return b''
        if path.stat().st_size > LIMIT:
            raise IndexErrorSafe('snapshot_size_limit')
        return path.read_bytes()
    # Bounded two-pass consistency check, no silent retry while client writes.
    def shm_header():
        if not shm_path.exists():return b''
        with shm_path.open('rb') as stream:return stream.read(136)
    db, wal, shm = read(db_path), read(wal_path, True), shm_header()
    if db != read(db_path) or wal != read(wal_path, True) or shm != shm_header():
        raise IndexErrorSafe('source_changed_during_snapshot')
    checkpoint = {'checked':False}
    if shm:
        if len(shm) < 136 or shm[:48] != shm[48:96] or checksum(shm[:40]) != struct.unpack_from('<II',shm,40):
            raise IndexErrorSafe('wal_index_header_unstable_or_invalid')
        checkpoint = {'checked':True, 'mx_frame':struct.unpack_from('<I',shm,16)[0],
                      'backfilled':struct.unpack_from('<I',shm,96)[0]}
    return db, wal, {'db_sha256': hashlib.sha256(db).hexdigest(), 'wal_sha256': hashlib.sha256(wal).hexdigest(),
                    'stable_two_pass': True, 'database_bytes': len(db), 'wal_bytes': len(wal),
                    'checkpoint':checkpoint,'scope': 'explicit emoticon.db, WAL and 136-byte WAL-index header only'}


def checksum(data, chain=(0,0), big=False):
    if len(data) % 8:
        raise IndexErrorSafe('invalid_checksum_length')
    a,b = chain
    for x,y in struct.iter_unpack('>II' if big else '<II', data):
        a = (a + x + b) & 0xffffffff
        b = (b + y + a) & 0xffffffff
    return a,b


def wal_transactions(wal):
    report = {'present': bool(wal), 'transactions': 0, 'valid_frames': 0, 'uncommitted_frames': 0, 'tail': 'none'}
    if not wal:
        return [], report
    if len(wal) < 32:
        raise IndexErrorSafe('wal_header_incomplete')
    magic,version,size = struct.unpack_from('>III', wal)
    if magic not in (0x377f0682,0x377f0683) or version != 3007000 or size != PAGE:
        raise IndexErrorSafe('wal_header_unsupported')
    big = magic == 0x377f0683
    chain = struct.unpack_from('>II', wal, 24)
    if checksum(wal[:24], big=big) != chain:
        raise IndexErrorSafe('wal_header_checksum_failed')
    salt = wal[16:24]
    transactions,pending = [],[]
    offset = 32
    while offset + 24 + PAGE <= len(wal):
        header, page = wal[offset:offset+24], wal[offset+24:offset+24+PAGE]
        number, db_size = struct.unpack_from('>II', header)
        if header[8:16] != salt:
            report['tail'] = 'stale_salt_after_valid_prefix'
            break
        if number < 1 or number > LIMIT // PAGE or db_size > LIMIT // PAGE:
            raise IndexErrorSafe('wal_page_number_invalid')
        actual = checksum(page, checksum(header[:8], chain, big), big)
        if actual != struct.unpack_from('>II', header, 16):
            # A stable snapshot with an unexplained corrupt chain is not called complete.
            raise IndexErrorSafe('wal_frame_checksum_failed')
        chain = actual
        pending.append((number, page))
        report['valid_frames'] += 1
        if db_size:
            transactions.append((db_size, pending))
            pending = []
        offset += PAGE + 24
    if offset != len(wal) and report['tail'] == 'none':
        report['tail'] = 'partial_frame'
    report['transactions'] = len(transactions)
    report['uncommitted_frames'] = len(pending)
    return transactions, report


def decrypt_snapshot(db, wal, key):
    if len(db) < PAGE or len(db) % PAGE:
        raise IndexErrorSafe('encrypted_database_size_invalid')
    aes = vendor('decrypt')
    km = mac_key(key, db[:16])
    def decode(page, number):
        check_page(page, number, km)
        return aes.decrypt_page(page, number - 1, key)
    pages = [decode(db[i:i+PAGE], i // PAGE + 1) for i in range(0, len(db), PAGE)]
    transactions, report = wal_transactions(wal)
    for size, frames in transactions:
        decoded = [(number, decode(page, number)) for number,page in frames]
        if any(number > size for number,_ in decoded):
            raise IndexErrorSafe('wal_transaction_page_outside_commit')
        pages = (pages + [b''] * max(0,size - len(pages)))[:size]
        for number, page in decoded:
            pages[number-1] = page
        if any(len(p) != PAGE for p in pages):
            raise IndexErrorSafe('missing_committed_page')
    plain = bytearray(b''.join(pages))
    # Merged read-only in-memory image: no SQLite WAL file access or writes.
    plain[18:20] = b'\x01\x01'
    return plain, report


def open_index(plain):
    conn = sqlite3.connect(':memory:')
    conn.deserialize(plain)
    conn.execute('PRAGMA query_only=ON')
    conn.execute('PRAGMA trusted_schema=OFF')
    if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        conn.close()
        raise IndexErrorSafe('sqlite_integrity_failed')
    return conn


def schema_summary(conn):
    result = {}
    # Fixed known emoticon tables only, never arbitrary DB/table discovery.
    for table in ('kFavEmoticonOrderTable','kCustomEmoticonOrderTable','kNonStoreEmoticonTable'):
        columns = [r[1] for r in conn.execute(f'PRAGMA table_info({table})')]
        result[table] = {'columns':columns, 'count': conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] if columns else None}
    return result


# Native interactive entries observed in an authenticated 4.2.0.13 index.
# These are game actions, not media digests. Keep unknown/malformed identities
# fail-closed; never invent a file or use their thumbnails as transferable data.
BUILTIN_FAVORITES={'dice_emoticon_md5':'dice','jsb_emoticon_md5':'rock_paper_scissors'}


def favorites(conn,summary=None):
    schema=schema_summary(conn)
    if not schema['kFavEmoticonOrderTable']['columns']:
        raise IndexErrorSafe('favorite_membership_table_unavailable')
    for table,required in {'kFavEmoticonOrderTable':{'md5'},
                           'kNonStoreEmoticonTable':{'md5','type','cdn_url','tp_url','extern_url'}}.items():
        if not required.issubset(schema[table]['columns']):
            raise IndexErrorSafe('favorite_schema_unsupported')
    try:
        rows=conn.execute('''SELECT o.rowid, o.md5, n.type, n.cdn_url, n.tp_url, n.extern_url
                            FROM kFavEmoticonOrderTable o LEFT JOIN kNonStoreEmoticonTable n ON o.md5=n.md5
                            ORDER BY o.rowid''').fetchall()
    except sqlite3.OperationalError:
        raise IndexErrorSafe('favorite_schema_unsupported') from None
    if len(rows)!=schema['kFavEmoticonOrderTable']['count']:
        raise IndexErrorSafe('favorite_join_not_one_to_one')
    items=[]; seen=set(); builtins=[]
    for rowid,digest,kind,cdn,tp,external in rows:
        if not isinstance(digest,str) or digest.lower() in seen:
            raise IndexErrorSafe('favorite_member_identity_invalid')
        seen.add(digest.lower())
        if digest in BUILTIN_FAVORITES and kind==3 and not any((cdn,tp,external)):
            builtins.append(BUILTIN_FAVORITES[digest]);continue
        if not re.fullmatch('[a-fA-F0-9]{32}',digest):
            raise IndexErrorSafe('favorite_member_identity_invalid')
        # Thumbnail and encrypted-resource fallback deliberately absent.
        urls=[(field,value) for field,value in [('cdn_url',cdn),('tp_url',tp),('extern_url',external)]
              if isinstance(value,str) and value.startswith(('https://','http://'))]
        items.append({'ordinal':len(items)+1,'rowid':rowid,'md5':digest.lower(),'type':kind,
                      'membership_table':'kFavEmoticonOrderTable','urls':urls})
    if summary is not None:
        summary.update(source_rows=len(rows),media_members=len(items),
                       builtin_actions=builtins,builtin_actions_count=len(builtins))
    return items


def public_item(item):
    return {**{k:v for k,v in item.items() if k!='urls'},
            'original_candidates':[{'field':f,'host':urlsplit(url).hostname} for f,url in item['urls']]}


def cdn_url(url):
    parsed=urlsplit(url)
    if parsed.hostname not in ('wxapp.tc.qq.com','vweixinf.tc.qq.com') or parsed.username or parsed.password or parsed.port not in (None,80,443):
        raise IndexErrorSafe('resource_host_not_allowlisted')
    if not parsed.path.startswith('/'):raise IndexErrorSafe('resource_path_invalid')
    # The upstream tool uses the certificate-valid wxapp host for this CDN.
    return urlunsplit(('https','wxapp.tc.qq.com',parsed.path,parsed.query,''))


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return super().redirect_request(req,fp,code,msg,headers,cdn_url(newurl))


def download_preview(item,folder,cancel_check=lambda: None):
    """Decode only the first complete frame; never certify original bytes.

    The URL comes from the authenticated favorite member. GIF downloads can
    stop as soon as frame zero is complete. A preview is not an MD5-verified
    original and must never be fed to the acquisition receipt machinery.
    """
    folder=Path(folder).resolve()
    if not folder.is_relative_to(ROOT/'private'):raise IndexErrorSafe('preview_output_must_be_private')
    folder.mkdir(parents=True,exist_ok=True)
    attempts=[]
    for field,url in item['urls']:
        if field!='cdn_url':continue
        try:
            cancel_check();raw=bytearray()
            opener=build_opener(ProxyHandler({}),SafeRedirect())
            request=Request(cdn_url(url),headers={'User-Agent':'Mozilla/5.0','Accept':'*/*'})
            with opener.open(request,timeout=10) as response:
                if response.status!=200:raise IndexErrorSafe('resource_http_not_200')
                while len(raw)<8*1024*1024:
                    cancel_check();chunk=response.read(32*1024)
                    if not chunk:break
                    raw.extend(chunk)
                    try:
                        with Image.open(io.BytesIO(raw)) as im:
                            if im.width*im.height>16_000_000:raise IndexErrorSafe('preview_pixel_limit')
                            # Static formats wait for EOF; GIF frame zero can
                            # decode independently of the remaining animation.
                            if im.format!='GIF':continue
                            frame=im.convert('RGBA')
                    except (OSError,ValueError):continue
                    break
                else:raise IndexErrorSafe('preview_download_size_limit')
            cancel_check()
            # Also handles a complete JPEG/PNG; never enable truncated loading.
            with Image.open(io.BytesIO(raw)) as im:
                if im.width*im.height>16_000_000:raise IndexErrorSafe('preview_pixel_limit')
                from PIL import ImageOps
                frame=ImageOps.exif_transpose(im).convert('RGBA')
            frame.thumbnail((96,96),Image.Resampling.LANCZOS)
            path=folder/'display.png';temporary=folder/'display.part.png'
            frame.save(temporary);temporary.replace(path)
            return {'status':'preview_available','display_preview':str(path),
                    'bytes_read':len(raw),'original_verified':False,'member':public_item(item)}
        except Exception as exc:
            if isinstance(exc,IndexErrorSafe) and str(exc)=='cancel_requested':raise
            attempts.append({'field':field,'error':str(exc) if isinstance(exc,IndexErrorSafe) else type(exc).__name__})
    return {'status':'preview_unavailable','reason':'预览暂未取得；搬运时仍需完整原件。','attempts':attempts}


from emoji_bridge.timing import measured

@measured("download")
def download_original(item,folder,cancel_check=lambda: None,max_attempts=2,io_timeout=8,attempt_timeout=180):
    from .media import inspect
    folder=Path(folder).resolve()
    if not folder.is_relative_to(ROOT/'private'):
        raise IndexErrorSafe('original_output_must_be_private')
    folder.mkdir(parents=True,exist_ok=True)
    attempts=[]
    if not any(field=='cdn_url' for field,_ in item['urls']):
        return {'status':'original_unavailable','member':public_item(item),'attempts':[]}
    if not re.fullmatch('[a-f0-9]{32}',item.get('md5','')):raise IndexErrorSafe('favorite_digest_invalid')
    # A completed, digest-bound file may survive cancellation before its
    # acquisition receipt was written. Reuse bytes; never reuse partial files.
    for extension in ('.gif','.png','.jpg','.webp'):
        saved=folder/(item['md5']+extension)
        if not saved.is_file():continue
        cancel_check()
        if hashlib.md5(saved.read_bytes()).hexdigest()!=item['md5']:
            return {'status':'original_unavailable','member':public_item(item),
                    'attempts':[{'field':'cdn_url','error':'existing_original_changed'}]}
        meta,_=inspect(saved)
        return {'status':'original_verified','path':str(saved),'member':public_item(item),
                'metadata':meta,'md5_matches_favorite':True,'url_field':'cdn_url','host':'wxapp.tc.qq.com',
                'reused_download':True,'attempts':[{'field':'cdn_url','status':'reused_complete_file'}]}
    # Strict exact member MD5 avoids accepting CDN thumbnails or format rewrites.
    retries=max(1,min(3,max_attempts))
    for field,url in item['urls']:
        if field!='cdn_url':continue
        for number in range(1,retries+1):
          started=time.monotonic();phase='connect';length=0
          try:
            cancel_check()
            request=Request(cdn_url(url),headers={'User-Agent':'Mozilla/5.0','Accept':'*/*'})
            opener=build_opener(ProxyHandler({}),SafeRedirect())
            with opener.open(request,timeout=io_timeout) as response:
                if response.status!=200:raise IndexErrorSafe('resource_http_not_200')
                chunks=[];phase='read'
                while length<=32*1024*1024:
                    cancel_check()
                    if time.monotonic()-started>attempt_timeout:raise TimeoutError('download_deadline')
                    # read1 returns available bytes without filling a whole
                    # chunk, providing cancellation and deadline checkpoints.
                    chunk=getattr(response,'read1',response.read)(64*1024)
                    if not chunk:break
                    chunks.append(chunk);length+=len(chunk)
                raw=b''.join(chunks)
            cancel_check()
            if len(raw)>32*1024*1024:raise IndexErrorSafe('original_download_size_limit')
            if hashlib.md5(raw).hexdigest()!=item['md5']:
                raise IndexErrorSafe('favorite_md5_mismatch')
            phase='decode'
            with Image.open(io.BytesIO(raw)) as im:
                extension={'GIF':'.gif','PNG':'.png','JPEG':'.jpg','WEBP':'.webp'}.get(im.format)
            if not extension:raise IndexErrorSafe('original_format_unsupported')
            path=folder/(item['md5']+extension)
            if path.exists():
                if path.read_bytes()!=raw:raise IndexErrorSafe('existing_original_changed')
            else:
                with path.open('xb') as stream:stream.write(raw)
            meta,_=inspect(path)
            return {'status':'original_verified','path':str(path),'member':public_item(item),
                    'metadata':meta,'md5_matches_favorite':True,'url_field':field,'host':'wxapp.tc.qq.com',
                    'attempts':attempts+[{'field':field,'status':'passed','attempt':number,
                        'seconds':round(time.monotonic()-started,3),'bytes':length}]}
          except Exception as exc:
            if isinstance(exc,IndexErrorSafe) and str(exc)=='cancel_requested':raise
            error=str(exc) if isinstance(exc,IndexErrorSafe) else type(exc).__name__
            from urllib.error import URLError
            retryable=(isinstance(exc,(TimeoutError,ConnectionError)) or
                       isinstance(exc,URLError) and isinstance(exc.reason,(TimeoutError,ConnectionError)))
            attempt={'field':field,'error':error,'phase':phase,'attempt':number,
                     'seconds':round(time.monotonic()-started,3),'bytes':length}
            if isinstance(exc,HTTPError):attempt['http_status']=exc.code
            if isinstance(exc,HTTPError):retryable=exc.code in (408,429,500,502,503,504)
            if isinstance(exc,URLError) and isinstance(exc.reason,TimeoutError):attempt['error']='TimeoutError'
            attempt['will_retry']=retryable and number<retries
            attempts.append(attempt)
            if not attempt['will_retry']:break
            deadline=time.monotonic()+.3*number
            while time.monotonic()<deadline:
                cancel_check();time.sleep(min(.1,max(0,deadline-time.monotonic())))
    return {'status':'original_unavailable','member':public_item(item),'attempts':attempts}
