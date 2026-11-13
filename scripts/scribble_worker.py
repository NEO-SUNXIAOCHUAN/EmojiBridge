"""Select a model's alpha using scribbles; optional constrained GrabCut only
when foreground/exclusion seeds share a component. Reuse the existing DIS
correspondence worker for motion, keeping the model's per-frame soft alpha.
"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))


def select(alpha, marks, rgb):
    import cv2
    import numpy as np
    support=(alpha>8).astype('uint8')
    _,labels=cv2.connectedComponents(support,8)
    wanted=set(int(n) for n in np.unique(labels[marks==1]))-{0}
    if not wanted or float(np.median(alpha[marks==1]))<64:raise ValueError('当前模型没有可靠识别出标记处的主体；原图和标记保留，可换模型或调整标记')
    excluded=set(int(n) for n in np.unique(labels[marks==2]))-{0}
    selector=np.isin(labels,list(wanted))
    refined=False
    if wanted & excluded:
        # Unmarked pixels retain a model prior, not a hard background label.
        gc=np.where(alpha>127,cv2.GC_PR_FGD,cv2.GC_PR_BGD).astype('uint8')
        gc[alpha<=8]=cv2.GC_BGD;gc[marks==1]=cv2.GC_FGD;gc[marks==2]=cv2.GC_BGD
        if not np.any(gc==cv2.GC_BGD):raise ValueError('缺少可区分的背景，请补涂排除区域')
        cv2.grabCut(rgb,gc,None,np.zeros((1,65)),np.zeros((1,65)),3,cv2.GC_INIT_WITH_MASK)
        _,parts=cv2.connectedComponents(((gc==1)|(gc==3)).astype('uint8'),8)
        wanted=set(int(n) for n in np.unique(parts[marks==1]))-{0}
        selector=np.isin(parts,list(wanted));refined=True
        # A hole exactly the size of a negative brush is not subject selection.
        # Inspect the ring outside the prompt: if it remains the selected
        # component, the automatic prior/GrabCut could not separate identities.
        ring=cv2.dilate((marks==2).astype('uint8'),np.ones((9,9),np.uint8)) & (marks!=2).astype('uint8')
        ring=(ring>0)&(alpha>64)
        if ring.any() and np.mean(selector[ring])>.6:
            raise ValueError('当前模型未能分开相连或遮挡的主体；请扩大排除提示或换模型，未应用笔刷形状的残缺结果')
    # Grow the selected core into its soft boundary, without hardening alpha.
    # Background inference is retained verbatim where the selector is opaque.
    fringe=cv2.dilate(selector.astype('uint8'),np.ones((3,3),np.uint8))
    output=alpha*fringe
    output[marks==2]=0
    return output,refined


def run(request):
    import numpy as np
    from PIL import Image
    from subject_vision_worker import run as propagate
    folder=Path(request['result']).parent;indices=request['indices'];anchor=request['anchor']
    with Image.open(request['marks']) as im:marks=np.array(im.convert('L'))
    n=indices.index(anchor)
    with Image.open(request['masks'][n]) as im:alpha=np.array(im.convert('L'))
    with Image.open(request['frames'][n]) as im:rgb=np.array(im.convert('RGB'))
    chosen,refined=select(alpha,marks,rgb);seed=folder/'anchor.png';Image.fromarray(chosen).save(seed)
    output={str(anchor):str(seed)};metrics=[]
    if len(indices)>1:
        masks=list(request['masks']);masks[n]=str(seed)
        tracked=propagate({**request,'action':'propagate','masks':masks,'result':str(folder/'flow.json')})
        if tracked['stopped']:
            first=tracked['stopped'][0]
            raise ValueError(f"第 {first['frame']+1} 帧主体对应不稳定，未应用部分结果；请缩短选段或在附近参考帧重新标记")
        metrics=tracked['metrics']
        # Select the matching current model component, never stamp an unmoving
        # source-coordinate mask on later frames. Soft edges come from each model.
        for i,path in tracked['masks'].items():
            index=indices.index(int(i))
            with Image.open(path) as im:prior=np.array(im.convert('L'))
            with Image.open(request['masks'][index]) as im:current=np.array(im.convert('L'))
            import cv2
            _,components=cv2.connectedComponents((current>8).astype('uint8'),8)
            labels=set(int(v) for v in np.unique(components[prior>127]))-{0}
            if not labels:raise ValueError(f'第 {int(i)+1} 帧模型未取得所选主体；未应用部分结果')
            # Restrict to the moving support if multiple subjects touch.
            # A separated object retains its current edges as it grows or
            # uncovers itself; flow chooses its component, not an old silhouette.
            # Shared components still need the propagated constrained boundary.
            support=cv2.dilate((prior>8).astype('uint8'),np.ones((7,7),np.uint8)) if refined else 1
            value=current*np.isin(components,list(labels)).astype('uint8')*support
            dest=folder/f'{i}-selected.png';Image.fromarray(value).save(dest);output[i]=str(dest)
    Path(request['result']).write_text(json.dumps({'masks':output,'refined':refined,'metrics':metrics}),'utf8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('request');parser.add_argument('--dependencies');args=parser.parse_args()
    if args.dependencies:sys.path.insert(0,args.dependencies)
    run(json.loads(Path(args.request).read_text('utf8')))
