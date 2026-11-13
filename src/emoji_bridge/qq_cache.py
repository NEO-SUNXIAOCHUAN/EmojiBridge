"""Read-only QQ personal_emoji/Ori candidates, never a favorite membership index.

Directory knowledge is documented in docs/T006-qq-cache.md. No upstream code
is imported. Files in this cache can outlive favorites and stay unverified until
bound to independent personal-favorite evidence.
"""
from pathlib import Path
from datetime import datetime
import hashlib,io,re,os
import numpy as np
from PIL import Image,ImageOps
from .media import inspect
from .state import sha

FORMATS={'JPEG':'.jpg','PNG':'.png','GIF':'.gif','WEBP':'.webp'}
INVENTORY_VERSION=3
LAST_DIAGNOSTICS={}
FAILURE_CODES={'cache_digest_filename_required','immediate_cache_file_required',
    'cache_file_size_limit','unsupported_cache_media','cache_changed_while_reading',
    'preview_identity_collision','PermissionError','FileNotFoundError',
    'UnidentifiedImageError','OSError','ValueError','DecompressionBombError'}


def diagnostic_summary(report):
    """Counts only: never export candidate names, paths or exception text."""
    failures={}
    for row in report.get('failures',[]):
        reason=row.get('reason');code=reason if isinstance(reason,str) and reason in FAILURE_CODES else 'other'
        failures[code]=failures.get(code,0)+1
    return dict(readable=len(report.get('items',[])),unreadable=sum(failures.values()),failure_reasons=failures)


def safe_diagnostics(value):
    result={}
    for key in ('readable','unreadable'):
        count=value.get(key)
        if type(count) is int and 0<=count<=1_000_000:result[key]=count
    reasons={}
    for code,count in value.get('failure_reasons',{}).items():
        if type(count) is int and 0<=count<=1_000_000:
            key=code if code in FAILURE_CODES else 'other'
            reasons[key]=reasons.get(key,0)+count
    result['failure_reasons']=reasons
    return result


def personal_root(path):
    path=Path(path).resolve(strict=True)
    if (path.name!='Ori' or path.parent.name not in ('personal_emoji','personal-emoji')
            or path.parent.parent.name!='Emoji' or path.parent.parent.parent.name!='nt_data'):
        raise ValueError('personal_emoji_ori_directory_required')
    return path


def candidate_path(root,name):
    root=personal_root(root);path=root/name
    if Path(name).name!=name or path.resolve().parent!=root or not path.is_file():
        raise ValueError('immediate_cache_file_required')
    if not re.fullmatch('[a-fA-F0-9]{32}',path.stem):raise ValueError('cache_digest_filename_required')
    return path


def first_frame(path):
    path=Path(path)
    size=path.stat().st_size
    if size>160*1024*1024:raise ValueError('cache_file_size_limit')
    # Animated decoders perform many tiny reads while examining frame headers.
    # One bounded disk read keeps those seeks in memory, with identical pixels.
    # Do not reserve 160 MiB for each tiny candidate. The extra byte detects growth.
    with path.open('rb') as stream:raw=stream.read(size+1)
    if len(raw)!=size:raise ValueError('cache_changed_while_reading')
    with Image.open(io.BytesIO(raw)) as im:
        if im.format not in FORMATS or im.width*im.height>32_000_000:raise ValueError('unsupported_cache_media')
        frame=ImageOps.exif_transpose(im).convert('RGBA')
        meta={'format':im.format,'size':list(frame.size),'bytes':path.stat().st_size,
              'first_frame_alpha':frame.getextrema()[3][0]<255}
        frame.thumbnail((96,96),Image.Resampling.LANCZOS)
        return meta,frame


from emoji_bridge.timing import measured

@measured('candidate_index')
def inventory(root,preview_folder,cancel=lambda:None,workers=3,on_preview=None):
    root=personal_root(root);preview_folder=Path(preview_folder).resolve()
    if preview_folder.is_relative_to(root.parent.parent.parent):raise ValueError('output_must_not_modify_cache')
    # Pillow's filename writer uses the Win32 path limit even where Python
    # directory enumeration succeeds. Keep the source path untouched; extend
    # only our managed output path. v3 invalidates v2's cached write failures.
    if os.name=='nt' and not str(preview_folder).startswith('\\\\?\\'):
        value=str(preview_folder)
        preview_folder=Path('\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value)
    preview_folder.mkdir(parents=True,exist_ok=True);items=[];failures=[]
    # Only immediate media candidates. Never recurse into chats or account data.
    def decode(file):
        try:
            cancel()
            if not file.is_file():return None
            path=candidate_path(root,file.name);before=path.stat();meta,frame=first_frame(path)
            after=path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('cache_changed_while_reading')
            return path,before,meta,frame
        except Exception as exc:
            if str(exc)=='cancel_requested':raise
            return {'name':file.name,'reason':str(exc) if isinstance(exc,ValueError) else type(exc).__name__}
    # Only three bounded file reads, never client input. Publish previews on
    # this coordinator so two extensions sharing a stem cannot race a write.
    from concurrent.futures import ThreadPoolExecutor
    from collections import deque
    files=iter(sorted(root.iterdir()));limit=max(1,min(3,workers))
    with ThreadPoolExecutor(max_workers=limit) as pool:
      pending=deque()
      def fill():
        while len(pending)<limit:
            cancel();file=next(files,None)
            if file is None:break
            pending.append(pool.submit(decode,file))
      fill()
      while pending:
        cancel();value=pending.popleft().result()
        if value is None:fill();continue
        if isinstance(value,dict):failures.append(value);fill();continue
        path,before,meta,frame=value
        try:
            # Keep different filenames separate even if they claim the same
            # digest. Only copied_original validates the actual full-byte MD5.
            preview=preview_folder/(hashlib.sha256(path.name.lower().encode('utf8')).hexdigest()+'.png')
            if preview.exists():
                with Image.open(preview) as saved:
                    if saved.convert('RGBA').size!=frame.size or saved.convert('RGBA').tobytes()!=frame.tobytes():
                        raise ValueError('preview_identity_collision')
            else:frame.save(preview)
            items.append({'name':path.name,'claimed_md5':path.stem.lower(),'metadata':meta,'preview':str(preview),
                'size':before.st_size,'mtime_ns':before.st_mtime_ns,'current_favorite':'unproven',
                'original_verified':False,'extension_matches_format':path.suffix.lower()==FORMATS[meta['format']]})
            if on_preview:on_preview(path.name,frame)
        except Exception as exc:failures.append({'name':path.name,'stage':'preview_write','reason':str(exc) if isinstance(exc,ValueError) else type(exc).__name__})
        fill()
    return {'schema':'qq-personal-cache-candidates-v1','at':datetime.now().astimezone().isoformat(),'root':str(root),
            'scope':'immediate personal_emoji/Ori cache; stale/deleted favorites may remain',
            'current_account_binding':'unproven','complete_collection_proven':False,
            'items':items,'failures':failures,'inventory_version':INVENTORY_VERSION,
            'messages_sent':0,'source_files_modified':False}


def copied_original(root,item,destination):
    """Copy one selected cache candidate intact and decode every frame.

    Success here proves bytes, not current collection membership.
    """
    root=personal_root(root);file=candidate_path(root,item['name']);dest=Path(destination).resolve()
    if dest.is_relative_to(root.parent.parent.parent):raise ValueError('output_must_not_modify_cache')
    if item['claimed_md5']!=file.stem.lower():raise ValueError('candidate_identity_mismatch')
    before=file.stat()
    if (before.st_size,before.st_mtime_ns)!=(item['size'],item['mtime_ns']):raise ValueError('cache_candidate_changed')
    if before.st_size>160*1024*1024:raise ValueError('cache_file_size_limit')
    raw=file.read_bytes();after=file.stat();digest=hashlib.md5(raw).hexdigest()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('cache_changed_while_copying')
    if digest!=item['claimed_md5']:raise ValueError('cache_filename_md5_mismatch')
    with Image.open(io.BytesIO(raw)) as im:extension=FORMATS.get(im.format)
    if not extension:raise ValueError('unsupported_cache_media')
    checksum=hashlib.sha256(raw).hexdigest();dest.mkdir(parents=True,exist_ok=True);copy=dest/(checksum+extension)
    if copy.exists():
        if sha(copy)!=checksum:raise ValueError('existing_copy_changed')
    else:
        with copy.open('xb') as stream:stream.write(raw)
    statistics={};metadata,_=inspect(copy,statistics=statistics)
    if metadata['sha256']!=checksum:raise ValueError('cache_or_copy_changed')
    transparent_frames=statistics['transparent_frames']
    return {'schema':'qq-personal-cache-original-v1','file':str(copy),'sha256':checksum,'md5':digest,
        'metadata':metadata,'transparent_frames':transparent_frames,'original_bytes_preserved':True,
        'current_favorite':'unproven','complete_collection_proven':False,'messages_sent':0,
        'cache_source':str(file),'cache_stat_unchanged':True,'extension_corrected_on_copy':file.suffix.lower()!=extension}


def visual_candidates(reference,report,limit=5):
    """Rank first-frame leads only; similarity does not grant original receipts."""
    _,ref=first_frame(reference);ratio=ref.width/ref.height;ranked=[]
    for item in report['items']:
        width,height=item['metadata']['size']
        if abs(width/height-ratio)>.025:continue
        with Image.open(item['preview']) as image:
            current=image.convert('RGBA').resize(ref.size,Image.Resampling.LANCZOS)
            error=float(np.abs(np.asarray(ref,dtype=float)-np.asarray(current,dtype=float)).mean()/255)
        ranked.append({'name':item['name'],'error':round(error,7),'metadata':item['metadata']})
    return sorted(ranked,key=lambda x:x['error'])[:limit]


def validate_copy(record):
    """Check intact copy and exact Ori bytes before claiming a source mapping."""
    if (record.get('schema')!='qq-personal-cache-original-v1' or not record.get('original_bytes_preserved')
            or record.get('current_favorite')!='unproven' or record.get('complete_collection_proven') is not False):
        raise ValueError('cache_copy_evidence_required')
    source=Path(record['cache_source']);original=candidate_path(source.parent,source.name);copy=Path(record['file'])
    if original.stem.lower()!=record['md5'] or record['metadata']['sha256']!=record['sha256']:
        raise ValueError('cache_copy_identity_mismatch')
    for path in (original,copy):
        if path.stat().st_size>160*1024*1024:raise ValueError('cache_file_size_limit')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=record['sha256'] or hashlib.md5(raw).hexdigest()!=record['md5']:
            raise ValueError('cache_or_copy_changed')
    return record
