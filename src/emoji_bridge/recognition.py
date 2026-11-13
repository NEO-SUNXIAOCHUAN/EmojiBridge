"""Aspect-aware matching of selected ordinary media, limited to supplied UI crops."""
from dataclasses import asdict
from collections import OrderedDict
import numpy as np
from PIL import Image
from .vision import matches,Match


def rgb(frame,background=(34,34,34)):
    layer=Image.new('RGBA',frame.size,(*background,255))
    layer.alpha_composite(frame.convert('RGBA'))
    return layer.convert('RGB')


def resized(frame,edge):
    ref=rgb(frame);ref.thumbnail((edge,edge),Image.Resampling.LANCZOS);return ref


def find_media(image,refs,edges,limit_frames=8):
    selected=np.linspace(0,len(refs)-1,min(limit_frames,len(refs)),dtype=int)
    candidates=[]
    for index in selected:
        for edge in edges:
            ref=resized(refs[index],edge)
            for hit in matches(image,ref,max_error=.045,count=4):
                candidates.append(hit)
    candidates.sort(key=lambda h:h.error)
    found=[]
    for hit in candidates:
        if not any(abs(hit.center[0]-p.center[0])<12 and abs(hit.center[1]-p.center[1])<12 for p in found):found.append(hit)
    if not found and len(refs)==1:
        # A high-contrast native thumbnail can miss the sparse proposal points
        # while agreeing over the full image. Keep the same full-pixel threshold.
        for edge in edges:
            for hit in matches(image,resized(refs[0],edge),max_error=.12,count=4):
                if hit.error<=.045 and not any(abs(hit.center[0]-p.center[0])<12 and abs(hit.center[1]-p.center[1])<12 for p in found):
                    found.append(hit)
    if not found and len(refs)>limit_frames:
        # Coarse animation poses propose locations only. Acceptance still needs
        # full-pixel agreement with an actual decoded source frame.
        proposed=[]
        for index in selected:
            for edge in edges:
                proposed.extend(matches(image,resized(refs[index],edge),max_error=.12,count=2))
        proposed.sort(key=lambda h:h.error)
        checked=[]
        for hit in proposed:
            if any(abs(hit.center[0]-p.center[0])<8 and abs(hit.center[1]-p.center[1])<8 and hit.width==p.width for p in checked):continue
            checked.append(hit)
            _,error=frame_evidence(image.crop((hit.x,hit.y,hit.x+hit.width,hit.y+hit.height)),refs)
            if error<.04 and not any(abs(hit.center[0]-p.center[0])<12 and abs(hit.center[1]-p.center[1])<12 for p in found):
                hit.error=error;found.append(hit)
    return found


class FrameMatcher:
    """One asset's bounded, reusable decoded references; acceptance is unchanged."""
    def __init__(self,refs):
        self.refs=refs;self.cache=OrderedDict();self.cache_bytes=0

    def expected(self,size,background):
        key=(size,background)
        expected=self.cache.get(key)
        if expected is None:
            expected=np.asarray([np.asarray(rgb(ref,background).resize(size,Image.Resampling.LANCZOS),dtype=np.uint8)[1:-1,1:-1] for ref in self.refs])
            while self.cache and self.cache_bytes+expected.nbytes>32*1024*1024:
                _,old=self.cache.popitem(last=False);self.cache_bytes-=old.nbytes
            if expected.nbytes<=32*1024*1024:
                self.cache[key]=expected;self.cache_bytes+=expected.nbytes
        else:self.cache.move_to_end(key)
        return expected

    def __call__(self,crop,background=(34,34,34)):
        expected=self.expected(crop.size,background)
        actual=np.asarray(crop.convert('RGB'),dtype=np.int16)[1:-1,1:-1]
        errors=[]
        for start in range(0,len(expected),32):
            errors.extend(np.abs(expected[start:start+32].astype(np.int16)-actual).mean(axis=(1,2,3))/255)
        index=int(np.argmin(errors));return (index if errors[index]<.055 else None),float(errors[index])


class QQFrameMatcher(FrameMatcher):
    """QQ's observed light panel composites transparent pixels onto #fdfdfd.

    Compare real frames at the unchanged full-pixel threshold; do not invert
    artwork or lighten opaque images to make a different source match.
    """
    def __init__(self,refs,*,prefilter=True):
        super().__init__(refs)
        self.transparent=any(ref.convert('RGBA').getextrema()[3][0]<255 for ref in refs)
        self.prefilter=prefilter;self.bounds_cache=OrderedDict()

    def possible_cell(self,crop):
        """Integer lower bound: reject only when every full-frame error > .04.

        All survivors still use the unchanged pixel/frame matcher. Both observed
        alpha backgrounds are included, with bounded per-asset summary storage.
        """
        if not self.prefilter:return True
        from .snapshot_matching import block_sums
        actual=np.asarray(crop.convert('RGB'),dtype=np.uint8)[1:-1,1:-1]
        sums=block_sums(actual);limit=.04*actual.size*255
        for background in ([(34,34,34),(253,253,253)] if self.transparent else [(34,34,34)]):
            key=(crop.size,background);bounds=self.bounds_cache.get(key)
            if bounds is None:
                bounds=block_sums(self.expected(crop.size,background))
                self.bounds_cache[key]=bounds
                if len(self.bounds_cache)>32:self.bounds_cache.popitem(last=False)
            else:self.bounds_cache.move_to_end(key)
            if np.any(np.abs(bounds-sums).sum(axis=(1,2,3))<=limit):return True
        return False

    def __call__(self,crop,background=(34,34,34)):
        result=super().__call__(crop,background)
        if self.transparent and result[1]>=.04 and background!=(253,253,253):
            light=super().__call__(crop,(253,253,253))
            if light[1]<result[1]:return light
        return result


def frame_evidence(crop,refs,background=(34,34,34)):
    actual=np.asarray(crop.convert('RGB'),dtype=np.float32)
    # Ignore a one-pixel thumbnail edge, retain actual content rather than motion alone.
    actual=actual[1:-1,1:-1]
    errors=[]
    for ref in refs:
        expected=np.asarray(rgb(ref,background).resize(crop.size,Image.Resampling.LANCZOS),dtype=np.float32)[1:-1,1:-1]
        errors.append(float(np.abs(actual-expected).mean()/255))
    index=int(np.argmin(errors));return (index if errors[index]<.055 else None),errors[index]


def find_in_cells(image,refs,cells,matcher=None,*,pixel_tolerance=0):
    """Full-frame fallback at supplied, freshly identified favorite cells only."""
    hits=[];matcher=matcher or FrameMatcher(refs)
    for left,top,right,bottom in cells:
        if not (0<=left<right<=image.width and 0<=top<bottom<=image.height):continue
        edge=min(right-left,bottom-top)
        template=resized(refs[0],edge);nominal_width,nominal_height=template.size
        candidates=[]
        # References were thumbnailed to 180 px; account for one-pixel integer
        # rounding of the shorter dimension in the native full-source thumbnail.
        sizes=[(nominal_width,nominal_height)]
        if nominal_width>nominal_height:sizes.extend((nominal_width,nominal_height+d) for d in (-1,1))
        elif nominal_height>nominal_width:sizes.extend((nominal_width+d,nominal_height) for d in (-1,1))
        # Chromium rounds CSS media size and accessible bounds separately at
        # fractional DPI. This opt-in is limited to proven favorite cells;
        # retain every pixel/frame and the same acceptance threshold.
        if not 0<=pixel_tolerance<=2:raise ValueError('cell_pixel_tolerance_invalid')
        if pixel_tolerance:
            for delta in range(1,pixel_tolerance+1):
                sizes.append(resized(refs[0],edge-delta).size)
        for width,height in sizes:
            if width<3 or height<3 or width>right-left or height>bottom-top:continue
            x=round((left+right-width)/2);y=round((top+bottom-height)/2)
            for dx in range(-pixel_tolerance,pixel_tolerance+1):
                for dy in range(-pixel_tolerance,pixel_tolerance+1):
                    xx,yy=x+dx,y+dy
                    if not (0<=xx<xx+width<=image.width and 0<=yy<yy+height<=image.height):continue
                    crop=image.crop((xx,yy,xx+width,yy+height))
                    if isinstance(matcher,QQFrameMatcher) and not matcher.possible_cell(crop):continue
                    frame,error=matcher(crop)
                    if frame is not None and error<.04:candidates.append(Match(xx,yy,width,height,error))
        if candidates:hits.append(min(candidates,key=lambda hit:hit.error))
    return hits


def distinguish_candidates(image, refs, hits, backgrounds=((34,34,34),)):
    """Reject locally different artwork hidden by a low whole-image mean.

    Only refines ambiguous, geometrically proven cells. All pixels and all
    reference frames remain evidence; no best-score winner is selected. Two
    matching covers (including distinct GIFs with the same first frame) remain
    ambiguous. This is a visual membership check, never a content digest.
    """
    if len(hits)<2:return hits,[]
    accepted=[];evidence=[]
    for hit in hits:
        actual=np.asarray(image.crop((hit.x,hit.y,hit.x+hit.width,hit.y+hit.height)).convert('RGB'),dtype=float)[1:-1,1:-1]
        residual=float('inf')
        for ref in refs:
            for background in backgrounds:
                expected=np.asarray(rgb(ref,background).resize((hit.width,hit.height),Image.Resampling.LANCZOS),dtype=float)[1:-1,1:-1]
                difference=np.abs(actual-expected).mean(axis=2)/255
                # A small wrong face/colour should not be diluted by the shared
                # background. Subdivision is proportional to the actual image.
                patches=[float(block.mean()) for row in np.array_split(difference,min(6,difference.shape[0]))
                         for block in np.array_split(row,min(6,difference.shape[1]),axis=1)]
                residual=min(residual,max(patches))
        passed=residual<=.12
        evidence.append(dict(x=hit.x,y=hit.y,width=hit.width,height=hit.height,whole_error=hit.error,
                             max_patch_error=round(residual,6),accepted=passed))
        if passed:accepted.append(hit)
    return accepted,evidence


def _visual_witness(arrays,extra=None):
    """Find up to three pairwise-distinct states, without greedy clustering.

    Each new vertex is tested against *all* earlier vertices. A bridging first
    frame cannot hide a later pair or triple. Stop at three: this is a playback
    witness, not an assertion of the animation's total unique-frame count.
    """
    if not len(arrays):return []
    graph=np.zeros((len(arrays),len(arrays)),dtype=bool);best=[0]
    for i in range(1,len(arrays)):
        distinct=np.abs(arrays[:i]-arrays[i]).mean(axis=(1,2,3))/255>.018
        if extra is not None:
            distinct &= np.abs(extra[:i]-extra[i]).mean(axis=(1,2,3))/255>.018
        neighbors=np.flatnonzero(distinct)
        graph[i,:i]=distinct;graph[:i,i]=distinct
        if len(neighbors):best=[int(neighbors[0]),i]
        pairs=np.argwhere(np.triu(graph[np.ix_(neighbors,neighbors)],1))
        if len(pairs):
            a,b=pairs[0];return [int(neighbors[a]),int(neighbors[b]),i]
    return best


def animation_verdict(observations,refs,samples=None):
    if samples is not None and len(samples)!=len(observations):raise ValueError('animation_samples_mismatch')
    arrays=np.asarray([np.asarray(rgb(ref).resize((48,48)),dtype=np.float32) for ref in refs])
    # Identical encoded frames are not distinct visual states. Bound the source
    # requirement by its actual pairwise-distinct content, not n_frames.
    unique=[];seen=set()
    for i,arr in enumerate(arrays):
        key=arr.tobytes()
        if key not in seen:seen.add(key);unique.append(i)
    source=_visual_witness(arrays[unique])
    required=len(source)
    matched=[i for i,o in enumerate(observations) if o['frame'] is not None and 0<=o['frame']<len(refs)]
    # Sort by source id for a stable witness even if sampling order changes.
    matched.sort(key=lambda i:observations[i]['frame'])
    ids=[observations[i]['frame'] for i in matched]
    actual=None if samples is None else np.asarray([
        np.asarray(samples[i].convert('RGB').resize((48,48)),dtype=np.float32) for i in matched])
    witness=_visual_witness(arrays[ids],actual)
    return {'playback_confirmed':required>=2 and len(witness)>=required,'matched_observations':len(ids),
            'distinct_visual_frames':[ids[i] for i in witness],
            'witness_observations':[matched[i] for i in witness],
            'required_visual_states':required,'visual_count_cap':3,
            'actual_pixels_checked':samples is not None,'all_frames_verified':False,'timing_verified':False}
