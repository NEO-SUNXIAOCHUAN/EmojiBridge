"""Optional OpenCV GrabCut and bidirectional optical-flow mask correspondence.

No static-mask broadcasting. A keyframe is kept and becomes the next anchor.
Scene discontinuity/large correspondence errors stop that direction explicitly.
"""
import argparse,json,sys
from pathlib import Path

def run(request):
    import cv2
    import numpy as np
    from PIL import Image
    folder=Path(request['result']).parent
    indices=request['indices'];anchor=request['anchor'];paths=dict(zip(indices,request['frames']));masks=dict(zip(indices,request['masks']))
    output={};stopped=[];metrics=[]
    def load(i):
        with Image.open(paths[i]) as im:rgb=np.array(im.convert('RGB'))
        with Image.open(masks[i]) as im:mask=np.array(im.convert('L'))
        return rgb,mask
    def save(i,mask):
        path=folder/f'{i}-repaired.png';Image.fromarray(mask).save(path);output[str(i)]=str(path)
    if request['action']=='segment':
        rgb,prior=load(anchor);h,w=prior.shape;labels=np.where(prior>127,cv2.GC_PR_FGD,cv2.GC_PR_BGD).astype('uint8')
        labels[[0,-1],:]=cv2.GC_BGD;labels[:,[0,-1]]=cv2.GC_BGD
        box=request.get('box') or []
        if len(box)>=2:
            x0,x1=sorted([round(box[0][0]),round(box[-1][0])]);y0,y1=sorted([round(box[0][1]),round(box[-1][1])])
            x0,x1=max(0,x0),min(w,x1);y0,y1=max(0,y0),min(h,y1)
            if x1-x0<3 or y1-y0<3:raise ValueError('选框太小或在素材之外')
            labels[:]=cv2.GC_BGD;labels[y0:y1,x0:x1]=cv2.GC_PR_FGD
        for p in request.get('points',[]):
            x,y=map(round,p['point'])
            if 0<=x<w and 0<=y<h:cv2.circle(labels,(x,y),max(2,round(min(w,h)/100)),cv2.GC_FGD if p['keep'] else cv2.GC_BGD,-1)
        cv2.grabCut(rgb,labels,None,np.zeros((1,65),np.float64),np.zeros((1,65),np.float64),5,cv2.GC_INIT_WITH_MASK)
        result=np.where((labels==cv2.GC_FGD)|(labels==cv2.GC_PR_FGD),255,0).astype('uint8')
        if not result.any():raise ValueError('未找到主体；扩大选框或在主体内部添加保留点')
        save(anchor,result);algorithm='OpenCV GrabCut 5 iterations'
    else:
        keyframes=set(request.get('keyframes',[]));algorithm='OpenCV DIS optical flow, reverse warp and forward/backward residual'
        for direction in (-1,1):
            prev,mask=load(anchor);i=anchor+direction
            while i in paths:
                current,existing=load(i)
                if i in keyframes:prev,mask=current,existing;i+=direction;continue
                if current.shape!=prev.shape:
                    stopped.append({'frame':i,'reason':'画面尺寸变化'});break
                h,w=mask.shape;ratio=min(1,640/max(w,h));small=(max(8,round(w*ratio)),max(8,round(h*ratio)))
                a=cv2.cvtColor(cv2.resize(prev,small),cv2.COLOR_RGB2GRAY);b=cv2.cvtColor(cv2.resize(current,small),cv2.COLOR_RGB2GRAY)
                flow=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
                backward=flow.calc(b,a,None);forward=flow.calc(a,b,None)
                yy,xx=np.mgrid[:small[1],:small[0]].astype('float32');mx=xx+backward[:,:,0];my=yy+backward[:,:,1]
                reverse=cv2.remap(forward,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
                residual=np.linalg.norm(backward+reverse,axis=2)
                warped=cv2.remap(a,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
                delta=np.abs(warped.astype('float32')-b)
                active=cv2.resize(mask,small)>64
                region=cv2.remap(active.astype('uint8'),mx,my,cv2.INTER_NEAREST)>0
                motion_error=float(np.median(residual[region])) if region.any() else float('inf')
                photo_error=float(np.mean(delta[region])) if region.any() else float('inf')
                metrics.append({'frame':i,'median_roundtrip_pixels':motion_error if region.any() else None,'mean_gray_error':photo_error if region.any() else None})
                if not region.any() or motion_error>3 or photo_error>45:
                    stopped.append({'frame':i,'reason':'主体出画或画面对应不稳定，请在此帧补修正','median_roundtrip_pixels':None if not region.any() else motion_error,'mean_gray_error':None if not region.any() else photo_error});break
                full=cv2.resize(backward,(w,h));full[:,:,0]*=w/small[0];full[:,:,1]*=h/small[1]
                yy,xx=np.mgrid[:h,:w].astype('float32')
                mask=cv2.remap(mask,xx+full[:,:,0],yy+full[:,:,1],cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
                save(i,mask);prev=current;i+=direction
                (folder/'progress.json').write_text(json.dumps({'done':len(output),'total':len(indices)-1,'frame':i-direction}),'utf8')
    result={'masks':output,'algorithm':algorithm,'stopped':stopped,'metrics':metrics}
    Path(request['result']).write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),'utf8')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('request');parser.add_argument('--dependencies');args=parser.parse_args()
    if args.dependencies:sys.path.insert(0,args.dependencies)
    run(json.loads(Path(args.request).read_text('utf8')))
