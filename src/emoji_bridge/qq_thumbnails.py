"""Link actual QQ personal Thumb renders to intact Ori, never export a Thumb."""
from pathlib import Path
import hashlib
import io
import json
import re
import numpy as np
from PIL import Image, ImageOps
from .qq_cache import personal_root, FORMATS
from .snapshot_matching import CellMatcher, pixels


def thumbnail_root(ori):
    root=personal_root(ori).parent/'Thumb'
    if not root.is_dir() or root.resolve().parent!=personal_root(ori).parent:
        raise ValueError('personal_thumbnail_directory_required')
    return root


def fingerprint(root):
    rows=[(p.name,p.stat().st_size,p.stat().st_mtime_ns) for p in sorted(root.iterdir()) if p.is_file()]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def thumb_bytes(root,name):
    root=Path(root).resolve();p=root/name
    if (Path(name).name!=name or p.resolve().parent!=root
            or not re.fullmatch('[a-fA-F0-9]{32}',p.stem)):
        raise ValueError('immediate_digest_thumbnail_required')
    before=p.stat()
    if before.st_size>160*1024*1024:raise ValueError('thumbnail_size_limit')
    data=p.read_bytes();after=p.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError('thumbnail_changed_while_reading')
    return data


def frames(data):
    with Image.open(io.BytesIO(data)) as im:
        count=getattr(im,'n_frames',1)
        if im.format not in FORMATS or im.width*im.height>32_000_000 or count>2000 or im.width*im.height*count>256_000_000:
            raise ValueError('thumbnail_decode_incomplete')
        for n in range(count):
            im.seek(n);yield n,ImageOps.exif_transpose(im).convert('RGBA')


def search(ori,cells,cancel=lambda:None):
    """Account for ALL immediate Thumb candidates, including missing Ori pairs."""
    root=thumbnail_root(ori);before=fingerprint(root)
    hits={ident:{} for ident in cells};failures=[];count=0
    for path in sorted(root.iterdir()):
        cancel()
        if not path.is_file():continue
        count+=1
        try:
            data=thumb_bytes(root,path.name)
            matcher=CellMatcher(frames(data),native=True,prefilter=len(cells)>=8)
            for ident,cell in cells.items():
                found=matcher.match(cell)
                if found:
                    frame=min(found,key=lambda n:found[n]['error'])
                    hits[ident][path.name]=dict(found[frame],frame=frame,thumbnail_sha256=hashlib.sha256(data).hexdigest())
        except (OSError,ValueError) as exc:
            failures.append(dict(name=path.name,reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__))
    cancel()
    if fingerprint(root)!=before:raise ValueError('thumbnail_inventory_changed')
    return dict(root=str(root),fingerprint=before,candidate_count=count,candidates=hits,failures=failures,
                scope='all_immediate_personal_emoji_Thumb_full_frames',complete_candidates=not failures,
                original_or_collection_complete_proven=False)


def static_correspondence(original,thumbnail):
    """Full high-resolution image check; intentionally no animation inference."""
    with Image.open(original) as ori,Image.open(thumbnail) as thumb:
        if getattr(ori,'n_frames',1)!=1 or getattr(thumb,'n_frames',1)!=1:
            raise ValueError('thumbnail_cannot_disambiguate_animation')
        a=ImageOps.exif_transpose(ori).convert('RGBA');b=ImageOps.exif_transpose(thumb).convert('RGBA')
        if a.getextrema()[3][0]!=255 or b.getextrema()[3][0]!=255:
            raise ValueError('thumbnail_alpha_correspondence_unproven')
        if min(b.size)<64 or b.width*b.height<16384:
            raise ValueError('thumbnail_detail_insufficient')
        if abs(a.width/a.height-b.width/b.height)>.003:
            raise ValueError('thumbnail_aspect_changed')
        a=a.convert('RGB').resize(b.size,Image.Resampling.LANCZOS);b=b.convert('RGB')
        raw=float(np.abs(pixels(a).astype(np.int16)-pixels(b)).mean()/255)
        smooth=float(np.abs(pixels(a,True).astype(np.int16)-pixels(b,True)).mean()/255)
        if raw>=.015 or smooth>=.01:raise ValueError('thumbnail_original_content_mismatch')
        return dict(profile='full-static-thumb-v1',raw=raw,smooth=smooth,size=list(b.size))
