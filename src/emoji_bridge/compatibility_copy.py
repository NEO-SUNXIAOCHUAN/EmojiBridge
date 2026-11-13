"""Explicit local output choices, not undocumented client acceptance limits."""
from bisect import bisect_right
from itertools import accumulate
from pathlib import Path
import json


def settings(root,target):
    default={'max_edge':320 if target=='wechat' else None,'max_fps':None,'colors':255}
    path=Path(root)/'compatibility.json'
    if path.exists():default.update(json.loads(path.read_text('utf-8')).get(target,{}))
    return default


def set_settings(root,target,value):
    from .state import save_json
    path=Path(root)/'compatibility.json'
    data=json.loads(path.read_text('utf-8')) if path.exists() else {}
    data[target]=value;save_json(path,data)


def sample_timing(durations,max_fps):
    """Sample the full clock on GIF's 10ms grid, without shortening its end."""
    if max_fps is None:return tuple(range(len(durations))),tuple(durations)
    if not 1<=max_fps<=60:raise ValueError('兼容帧率应为1～60，或保留原时序')
    total=sum(durations)
    if not total:return tuple(range(len(durations))),tuple(durations)
    ends=tuple(accumulate(durations));points={0,total}
    for n in range(1,int(total*max_fps/1000)+1):
        stamp=round(n*100/max_fps)*10
        if 0<stamp<total:points.add(stamp)
    points=sorted(points);indices=[];times=[]
    for a,b in zip(points,points[1:]):
        index=min(len(durations)-1,bisect_right(ends,a))
        if indices and indices[-1]==index:times[-1]+=b-a
        else:indices.append(index);times.append(b-a)
    return tuple(indices),tuple(times)


def describe(info):
    seconds=info['duration_ms']/1000;fps=info['frames']/seconds if seconds else 0
    w,h=info['oriented_size']
    return f'{w}×{h} · {seconds:.2f}秒 · {info["frames"]}帧 / 平均{fps:.2f}fps · {info["bytes"]/1024**2:.2f}MiB'
