"""Owned animation sources and non-destructive recipes in existing scene folders."""
from pathlib import Path
from PIL import Image
from .animated_edit import GifSource,SubjectSource
from .animation_recipe import RecipeSource,apply_recipe
from .frame_paint import PaintedSource,PatchedFrames
from .cutout_masks import MaskedFrames
from .frame_store import original_digest,copy_original,PngFrames,MAX_FRAME_COUNT,MAX_TIME_MS,cancelled


def write_source(source,directory,asset,cancel=None):
    cancelled(cancel)
    if isinstance(source,RecipeSource):
        return {'recipe_source':write_source(source.master,directory,asset,cancel),'recipe':source.recipe}
    if isinstance(source,PaintedSource):
        return {'paint_source':write_source(source.master,directory,asset,cancel),'patches':{str(i):asset(f) for i,f in source.patches.items()}}
    suffix=source.original_suffix if isinstance(source,SubjectSource) else source.container_suffix
    file=directory/(original_digest(source.original)+suffix)
    if not file.exists():
        temp=file.with_suffix('.tmp');copy_original(source.original,temp);temp.replace(file)
    if not isinstance(source,SubjectSource):return file.name
    value={'frames':[],'durations':list(source.durations),'loop':source.loop,'original':file.name}
    if isinstance(source.frames,MaskedFrames):
        value.update(original_frames=[asset(f) for f in source.frames.originals],masks=[asset(source.frames.mask(i)) for i in range(len(source.frames))])
    else:value['frames']=[asset(f) for f in source.frames]
    return value


def read_source(value,directory,cancel=None,depth=0):
    cancelled(cancel)
    if depth>64:raise ValueError('草稿效果嵌套过深')
    def local(name,suffixes=None):
        if not isinstance(name,str) or Path(name).name!=name or (suffixes and Path(name).suffix not in suffixes):raise ValueError('草稿动态资源路径无效')
        path=directory/name
        if path.resolve().parent!=directory.resolve():raise ValueError('草稿动态资源位于外部')
        return path
    if isinstance(value,str):return GifSource.read(local(value,('.gif','.png','.webp')),cancel=cancel)
    if 'recipe_source' in value:return apply_recipe(read_source(value['recipe_source'],directory,cancel,depth+1),value['recipe'])
    if 'paint_source' in value:
        master=read_source(value['paint_source'],directory,cancel,depth+1);patches={}
        for index,name in value['patches'].items():
            index=int(index)
            if not 0<=index<len(master.frames):raise ValueError('草稿画笔帧号无效')
            with Image.open(local(name,('.png',))) as image:patches[index]=image.convert('RGBA')
        return PaintedSource(master.original,PatchedFrames(master.frames,patches),master.durations,master.loop,master,patches)
    durations=tuple(map(int,value['durations']));names=value.get('original_frames',value['frames'])
    if not 0<len(durations)<=MAX_FRAME_COUNT or min(durations)<1 or sum(durations)>MAX_TIME_MS or len(durations)!=len(names):raise ValueError('草稿动态时序无效')
    paths=[local(n,('.png',)) for n in names]
    with Image.open(paths[0]) as first:dimensions=first.size
    frames=PngFrames(paths,dimensions)
    if 'original_frames' in value:
        masks=value['masks']
        if len(masks)!=len(paths):raise ValueError('动态蒙版数量无效')
        frames=MaskedFrames(frames,PngFrames([local(n,('.png',)) for n in masks],dimensions))
    original=local(value['original'])
    return SubjectSource(original.read_bytes() if original.stat().st_size<=8*1024**2 else original,frames,durations,value['loop'],original.suffix)
