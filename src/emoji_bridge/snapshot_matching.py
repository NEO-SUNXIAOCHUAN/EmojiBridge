"""QQ saved-cell matching, including upscaled small images and raster filtering.

This matches observed favorites, never enumerates favorites from cache files.
The default retains strict pixel/smoothing thresholds. Explicit appearance
mode uses separate thresholds/profile; it cannot validate as a strict receipt.
Neither mode generates frames or searches arbitrary positions.
"""
from collections import defaultdict
from itertools import product
from math import floor,ceil
import numpy as np
from PIL import Image,ImageFilter
from .recognition import rgb

PROFILE='qq-cell-raster-v3'
NATIVE_PROFILE='qq-cell-native-raster-v4'
LEGACY_PROFILE='qq-cell-raster-v2'
BACKGROUNDS=((34,34,34),(51,49,49),(253,253,253))
RAW_LIMIT=.055
SMOOTH_LIMIT=.025


def pixels(image,smooth=False):
    image=image.convert('RGB')
    if smooth:image=image.filter(ImageFilter.GaussianBlur(.7))
    return np.asarray(image,dtype=np.uint8)[1:-1,1:-1]


def accepted(raw,smooth):
    return np.isfinite(raw) and np.isfinite(smooth) and raw<RAW_LIMIT and smooth<SMOOTH_LIMIT


def block_sums(array):
    """Exact integer sums: their L1 distance is a LOWER bound on pixel L1.

    Includes every pixel, including uneven last blocks. This rejects impossible
    matches cheaply without changing either full-resolution acceptance limit.
    """
    h,w=array.shape[-3:-1]
    ys=np.arange(0,h,max(1,(h+3)//4));xs=np.arange(0,w,max(1,(w+3)//4))
    return np.add.reduceat(np.add.reduceat(array.astype(np.int32),ys,axis=-3),xs,axis=-2)


class CellMatcher:
    """Build each reference once, compare many cells in bounded NumPy batches."""
    def __init__(self,frames,edge=58,native=False,prefilter=False):
        self.edge=edge;self.native=native;groups=defaultdict(list)
        for key,frame in frames:
            rgba=frame.convert('RGBA');scale=edge/max(rgba.size)
            w,h=round(rgba.width*scale),round(rgba.height*scale)
            sizes={(w,h)}
            if w<h:sizes.update((w+d,h) for d in (-1,1))
            elif h<w:sizes.update((w,h+d) for d in (-1,1))
            backgrounds=BACKGROUNDS if rgba.getextrema()[3][0]<255 else BACKGROUNDS[:1]
            for background in backgrounds:
                ref=rgb(rgba,background)
                for size in sorted(sizes):
                    if min(size)<3 or max(size)>edge:continue
                    for resampler in (('LANCZOS','BOX') if native else ('LANCZOS',)):
                        rendered=ref.resize(size,getattr(Image.Resampling,resampler))
                        groups[size].append(((key,background,resampler),pixels(rendered),pixels(rendered,True)))
        self.groups={size:([r[0] for r in rows],np.asarray([r[1] for r in rows]),
                           np.asarray([r[2] for r in rows])) for size,rows in groups.items()}
        self.coarse={size:block_sums(refs) for size,(_,refs,_) in self.groups.items()} if prefilter else None

    def match(self,cell,*,appearance=False,padding=0,cancel_check=None):
        # Practical matching is explicitly labelled and never passes strict
        # receipt validation as though it were the previous exact profile.
        raw_limit=.10 if appearance else RAW_LIMIT
        smooth_limit=.075 if appearance else SMOOTH_LIMIT
        if not 0<=padding<=2 or (padding and not appearance):raise ValueError('cell_padding_invalid')
        if min(cell.size)-2*padding!=self.edge or max(cell.size)-min(cell.size)>1:raise ValueError('complete_square_cell_required')
        found={}
        for (w,h),(keys,raw_refs,smooth_refs) in self.groups.items():
            if cancel_check:cancel_check()
            # Odd short dimensions have a half-pixel centre; the native global
            # coordinate may round either way. Only these two centres, no search.
            xs={floor((cell.width-w)/2),ceil((cell.width-w)/2)}
            ys={floor((cell.height-h)/2),ceil((cell.height-h)/2)}
            if padding:
                xs={x+d for x in xs for d in range(-padding,padding+1)}
                ys={y+d for y in ys for d in range(-padding,padding+1)}
            for x,y in product(sorted(xs),sorted(ys)):
                crop=cell.crop((x,y,x+w,y+h))
                raw=pixels(crop).astype(np.int16);smooth=None
                if self.coarse is None:possible=np.arange(len(keys))
                else:
                    bounds=np.abs(self.coarse[(w,h)]-block_sums(raw)).sum(axis=(1,2,3))/(raw.size*255)
                    possible=np.flatnonzero(bounds<raw_limit)
                for start in range(0,len(possible),32):
                    if cancel_check:cancel_check()
                    indices=possible[start:start+32]
                    errors=np.abs(raw_refs[indices].astype(np.int16)-raw).mean(axis=(1,2,3))/255
                    for offset in np.flatnonzero(errors<raw_limit):
                        n=int(indices[offset])
                        if smooth is None:smooth=pixels(crop,True).astype(np.int16)
                        smoothed=float(np.abs(smooth_refs[n].astype(np.int16)-smooth).mean()/255)
                        error=float(errors[offset])
                        if not (np.isfinite(error) and np.isfinite(smoothed) and error<raw_limit and smoothed<smooth_limit):continue
                        patch_error=None
                        if appearance:
                            diff=np.abs(raw_refs[n].astype(np.int16)-raw).mean(axis=2)/255
                            patch_error=max(float(b.mean()) for row in np.array_split(diff,min(6,diff.shape[0])) for b in np.array_split(row,min(6,diff.shape[1]),axis=1))
                            if patch_error>.12:continue
                        key,background,resampler=keys[n];hit={'kind':'full_saved_cell','profile':NATIVE_PROFILE if self.native else PROFILE,
                                         'error':error,'smoothed_error':smoothed,'render_size':[w,h],
                                         'background':list(background)}
                        if self.native:hit['resampler']=resampler
                        if appearance:hit.update(profile='qq-appearance-v1',max_patch_error=patch_error)
                        if key not in found or error<found[key]['error']:found[key]=hit
        return found
