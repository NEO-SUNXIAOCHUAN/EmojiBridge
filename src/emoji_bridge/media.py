"""Immutable local assets and explicit, recorded conversions; never edit the input."""
from datetime import datetime
from copy import deepcopy
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
from time import perf_counter
from PIL import Image,ImageOps

from .state import sha,save_json
from .timing import measured
_inspections=ContextVar('complete_media_inspections',default=None)


@contextmanager
def inspection_session():
    """Task-local full-decode reuse for exact bytes, never metadata from disk."""
    if _inspections.get() is not None:
        yield
        return
    cache=OrderedDict();token=_inspections.set(cache)
    try:yield
    finally:cache.clear();_inspections.reset(token)


@measured("media_validation")
def inspect(path,thumbnails=False,*,statistics=None,cancel=None):
    from .frame_store import inspect_local,cancelled
    path=Path(path)
    if not path.is_absolute() or not path.is_file():raise ValueError('absolute_existing_file_required')
    cancelled(cancel)
    cache=_inspections.get();digest=sha(path) if cache is not None else None
    if not thumbnails and cache is not None and digest in cache:
        cache.move_to_end(digest);metadata,alpha=cache[digest]
        if statistics is None or alpha is not None:
            if statistics is not None:statistics['transparent_frames']=alpha
            return deepcopy(metadata),[]
    metadata,refs=inspect_local(path,cancel=cancel,statistics=statistics,thumbnails=thumbnails)
    if digest is not None and metadata['sha256']!=digest:raise ValueError('source_changed_during_inspection')
    if cache is not None:
        cache[metadata['sha256']]=(deepcopy(metadata),statistics['transparent_frames'] if statistics is not None else None)
        while len(cache)>32:cache.popitem(last=False)
    return metadata,refs


@measured("conversion")
def prepare_asset(source,target,storage,max_edge=None,native=False,*,cancel=None,metrics=None,max_fps=None,colors=255,progress=None):
    started=perf_counter();timing={}
    if not Path(source).is_absolute():raise ValueError('absolute_existing_file_required')
    if max_edge is not None and not 32<=max_edge<=4096:raise ValueError('invalid_max_edge')
    source=Path(source).resolve();storage=Path(storage).resolve()
    if target not in ('qq','wechat'):raise ValueError('unknown_target')
    if not 2<=colors<=255:raise ValueError('兼容颜色数应为2～255，另保留透明色')
    if max_fps is not None and not 1<=max_fps<=60:raise ValueError('兼容帧率应为1～60')
    # Tested conservative conversion profile, not a claimed WeChat size limit.
    if target=='wechat' and max_edge is None and not native:max_edge=320
    from .animated_edit import check_cancel
    check_cancel(cancel);key=sha(source)
    if native and (max_edge is not None or max_fps is not None or colors!=255):raise ValueError('source_native_cannot_resize')
    variant=f'{target}-native' if native else f'{target}-edge{max_edge or 0}'
    if max_fps is not None or colors!=255:variant+=f'-fps{max_fps or 0}-c{colors}'
    folder=storage/key/variant
    manifest_path=folder/'asset.json'
    if manifest_path.exists():
        # Content-addressed preparation is idempotent. In particular, never
        # erase collection receipts or silently repair changed evidence.
        existing=load_asset(manifest_path)
        if existing['source_sha256']!=key or existing['target']!=target:
            raise ValueError('asset_variant_mismatch')
        if sha(source)!=key:raise ValueError('source_changed_during_prepare')
        if metrics is not None:metrics.update(timing,reused=True,total_seconds=perf_counter()-started)
        return manifest_path,existing
    info,_=inspect(source,cancel=cancel)
    timing['source_inspection_seconds']=perf_counter()-started
    if info['sha256']!=key:raise ValueError('source_changed_during_prepare')
    folder.mkdir(parents=True,exist_ok=True)
    original=folder/('original'+{'JPEG':'.jpg','PNG':'.png','GIF':'.gif','WEBP':'.webp'}[info['format']])
    if not original.exists():
        from .file_io import copy_file
        copy_file(source,original,cancel=cancel)
    if sha(original)!=key:raise ValueError('original_copy_mismatch')
    output=original;conversion={'operation':'none','lossy':False}
    needs_gif=target=='wechat' and info['format']!='GIF' and not native
    resize=max_edge is not None and max(info['oriented_size'])>max_edge
    if needs_gif or resize or max_fps is not None or colors!=255:
        from types import SimpleNamespace
        from .animated_edit import export_gif,check_cancel
        from .compatibility_copy import sample_timing
        indices,durations=sample_timing(info['durations_ms'],max_fps)
        output=folder/'prepared.gif'
        has_alpha=False
        with Image.open(original) as im:
            def render(*,animation_frame=0):
                nonlocal has_alpha
                check_cancel(cancel);im.seek(indices[animation_frame])
                frame=ImageOps.exif_transpose(im).convert('RGBA')
                alpha=frame.getchannel('A');has_alpha |= alpha.getextrema()[0]<255
                if 0<alpha.getextrema()[1]<128:raise ValueError('alpha_conversion_would_remove_visible_content')
                return frame
            dimensions=tuple(info['oriented_size'])
            ratio=min(1,max_edge/max(dimensions)) if max_edge else 1
            output_size=tuple(max(1,round(v*ratio)) for v in dimensions)
            document=SimpleNamespace(size=dimensions,render=render,
                animation=SimpleNamespace(frames=range(len(indices)),durations=durations,loop=info['loop']))
            timing['gif']={}
            export_gif(document,output,output_size=output_size,cancel=cancel,metrics=timing['gif'],colors=colors,progress=progress)
        conversion={'operation':'resize_and_gif' if resize else 'gif_compat' if info['format']=='GIF' else 'static_to_gif','lossy':True,
                    'max_edge':max_edge,'max_fps':max_fps,'colors':colors,
                    'note':'explicit palette/size/frame-rate copy; full duration and original retained'}
        if has_alpha:conversion.update(alpha='binary_threshold_128',transparent_background_preserved=True,
                                       alpha_note='GIF cannot retain partial alpha; original RGBA retained')
    if output==original:
        # These are the exact bytes already fully decoded above. Verify the
        # copy, then reuse the frame/timing metadata instead of decoding again.
        if sha(output)!=key:raise ValueError('original_copy_mismatch')
        prepared=deepcopy(info)
    else:
        prepared,unused=inspect(output,cancel=cancel)
    if max_fps is None and (prepared['frames']!=info['frames'] or prepared['durations_ms']!=info['durations_ms']):
        raise ValueError('animation_structure_changed_conversion_rejected')
    if prepared['duration_ms']!=info['duration_ms']:raise ValueError('animation_duration_changed')
    if info['frames']>1 and prepared['loop']!=info['loop']:raise ValueError('animation_loop_changed')
    if sha(source)!=key:raise ValueError('source_changed_during_prepare')
    check_cancel(cancel)
    manifest={'schema':'local-asset-v1','target':target,'source':str(source),'source_sha256':key,
              'source_only':native,
              'original_copy':str(original),'prepared':str(output),'prepared_sha256':prepared['sha256'],
              'original_metadata':info,'prepared_metadata':prepared,'conversion':conversion,
              'created':datetime.now().astimezone().isoformat()}
    save_json(folder/'asset.json',manifest)
    if metrics is not None:metrics.update(timing,reused=False,total_seconds=perf_counter()-started)
    return folder/'asset.json',manifest


def load_asset(path):
    data=json.loads(Path(path).read_text(encoding='utf8'))
    if data.get('schema')!='local-asset-v1':raise ValueError('invalid_asset_manifest')
    for name,digest in (('original_copy','source_sha256'),('prepared','prepared_sha256')):
        p=Path(data[name])
        if not p.is_absolute() or sha(p)!=data[digest]:raise ValueError('asset_changed')
    if data.get('source_provenance') or data.get('source_provenances'):
        from .originals import origin_for_asset
        origin_for_asset(data)
    return data


def references(asset):
    return inspect(Path(asset['prepared']),thumbnails=True)[1]
