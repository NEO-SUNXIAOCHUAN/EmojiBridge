"""User-requested static candidates; never deletes or merges material records.

pHash functions adapted from OhMyMeme/src/webui.py, GPL-3.0,
f6ed27da57f8480b3d38a4e116ac59b741588387.
EB adds EXIF/alpha normalization, immutable-content caching, cancellation and
manual library-only scope. Animations are excluded, not compared by first frame.
"""
import math
from pathlib import Path
from PIL import Image, ImageOps
from .materials import is_dynamic
from .state import save_json
from .cache_listing import read_json

_PHASH_DCT_COS = [
    [math.cos((2 * x + 1) * k * math.pi / (2 * 32)) for x in range(32)]
    for k in range(8)
]
_PHASH_DCT_NORM = [1.0 if k == 0 else math.sqrt(0.5) for k in range(8)]

def _gray_pixels(img):
    """取 32x32 灰度像素列表（兼容新旧 Pillow：get_flattened_data/getdata）"""
    from PIL import Image

    small = img.convert("L").resize((32, 32), Image.LANCZOS)
    getter = getattr(small, "get_flattened_data", None)
    if getter is not None:
        return list(getter())
    return list(small.getdata())


def _perceptual_hash(img) -> int:
    """计算 PIL 图像的 64 位感知哈希（pHash，8x8 可分离 DCT）；比均值哈希判别力更强"""
    try:
        px = _gray_pixels(img)
        rows = [[0.0] * 32 for _ in range(8)]
        for k in range(8):
            ck = _PHASH_DCT_COS[k]
            for x in range(32):
                ckx = ck[x]
                row = rows[k]
                base = x * 32
                for y in range(32):
                    row[y] += px[base + y] * ckx
        dct = [[0.0] * 8 for _ in range(8)]
        for k in range(8):
            ck = _PHASH_DCT_NORM[k]
            for j in range(8):
                s = 0.0
                cl = _PHASH_DCT_COS[j]
                for y in range(32):
                    s += rows[k][y] * cl[y]
                dct[k][j] = ck * _PHASH_DCT_NORM[j] * s / 4.0
        coeffs = [dct[k][j] for k in range(8) for j in range(8)]
        median = sorted(coeffs)[len(coeffs) // 2]
        h = 0
        for i, c in enumerate(coeffs):
            if c > median:
                h |= 1 << i
        return h
    except Exception:
        return 0




def candidates(store, ids=(), collection='', cancel=None, progress=None):
    selected=list(dict.fromkeys(ids)) or store.matching_ids(category=collection)
    cache_path=store.root/'cache/similar-static-v1.json'
    cache=read_json(cache_path,{})
    images=[];errors=[]
    for n,ident in enumerate(selected):
        if cancel and cancel.is_set():break
        try:
            item=store.get(ident)
            if is_dynamic(item['metadata']):continue
            file=store.original(ident);stat=file.stat();signature=[stat.st_size,stat.st_mtime_ns]
            previous=cache.get(ident,{})
            if previous.get('signature')==signature:value=previous['hash']
            else:
                with Image.open(file) as im:
                    rgba=ImageOps.exif_transpose(im).convert('RGBA')
                    background=Image.new('RGBA',rgba.size,'white')
                    background.alpha_composite(rgba)
                    value=_perceptual_hash(background)
                cache[ident]={'hash':value,'signature':signature}
            if value:
                images.append((ident,value))
        except (OSError,ValueError) as exc:errors.append({'id':ident,'reason':str(exc)})
        finally:
            if progress:progress(n+1,len(selected))
    save_json(cache_path,cache)
    pairs=[]
    for n,(ident,value) in enumerate(images):
        if cancel and cancel.is_set():break
        for other,h in images[n+1:]:
            distance=(value^h).bit_count()
            if distance<=8:pairs.append({'left':ident,'right':other,'distance':distance})
    return {'pairs':sorted(pairs,key=lambda p:(p['distance'],p['left'],p['right'])),
            'errors':errors,'checked':len(images),'cancelled':bool(cancel and cancel.is_set())}
