"""SAM2 adapter with bounded frame loading and independent corrected masks."""
from pathlib import Path
from collections import OrderedDict
import sys,json,time

def main(request):
    root=Path(request['model_root']);settings=json.loads((root/'ready.json').read_text('utf8'))
    sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'third_party/sam2'),*settings['paths']]
    import torch,numpy as np
    from PIL import Image
    from sam2.build_sam import build_sam2,build_sam2_video_predictor
    torch.set_num_threads(8);device='cpu';start=time.perf_counter();folder=Path(request['result']).parent
    config='configs/sam2.1/sam2.1_hiera_t.yaml';checkpoint=str(root/'sam2.1_hiera_tiny.pt');indices=request['indices'];anchor=indices.index(request['anchor']);output={};metrics={};stopped=[]
    def rgb(i):
        with Image.open(request['frames'][i]) as image:return np.array(image.convert('RGB'))
    def save(i,mask):
        file=folder/f'{indices[i]}-sam-mask.png';Image.fromarray(mask.astype('uint8')*255).save(file);output[str(indices[i])]=str(file)
        (folder/'progress.json').write_text(json.dumps({'done':len(output),'total':len(indices),'frame':indices[i]}),'utf8')
    with torch.inference_mode():
        if request['action']=='segment':
            from sam2.sam2_image_predictor import SAM2ImagePredictor
            predictor=SAM2ImagePredictor(build_sam2(config,checkpoint,device=device,apply_postprocessing=False));metrics['load']=time.perf_counter()-start
            tick=time.perf_counter();predictor.set_image(rgb(anchor));metrics['encode']=time.perf_counter()-tick
            points=request.get('points') or [];box=request.get('box') or []
            box=np.array([min(p[0] for p in box),min(p[1] for p in box),max(p[0] for p in box),max(p[1] for p in box)]) if len(box)>=2 else None
            tick=time.perf_counter();masks,scores,_=predictor.predict(point_coords=np.array([p['point'] for p in points]) if points else None,point_labels=np.array([int(p['keep']) for p in points]) if points else None,box=box,multimask_output=False)
            metrics['prompt']=time.perf_counter()-tick;save(anchor,masks[0]>0)
        else:
            if len(indices)>180:raise ValueError('SAM2 首版一次传播最多180帧；请缩小选区分段修正，未截短素材')
            import sam2.sam2_video_predictor as video_module
            class Frames:
                def __init__(self,edge):self.edge=edge;self.cache=OrderedDict()
                def __len__(self):return len(indices)
                def __getitem__(self,i):
                    if i not in self.cache:
                        image=Image.fromarray(rgb(i)).resize((self.edge,self.edge));x=torch.from_numpy(np.array(image).astype('float32')/255).permute(2,0,1)
                        self.cache[i]=(x-torch.tensor([.485,.456,.406])[:,None,None])/torch.tensor([.229,.224,.225])[:,None,None]
                        while len(self.cache)>2:self.cache.popitem(last=False)
                    self.cache.move_to_end(i);return self.cache[i]
            first=rgb(0)
            video_module.load_video_frames=lambda video_path,image_size,**kwargs:(Frames(image_size),first.shape[0],first.shape[1])
            predictor=build_sam2_video_predictor(config,checkpoint,device=device,apply_postprocessing=False);metrics['load']=time.perf_counter()-start
            state=predictor.init_state('owned-frame-sequence',offload_video_to_cpu=True,offload_state_to_cpu=True)
            keyframes=set(request.get('keyframes',[]))|{request['anchor']}
            for i,frame in enumerate(indices):
                if frame in keyframes:
                    with Image.open(request['masks'][i]) as mask:predictor.add_new_mask(state,i,1,np.array(mask.convert('L'))>127)
            for reverse in (False,True):
                for i,_,logits in predictor.propagate_in_video(state,start_frame_idx=anchor,reverse=reverse):
                    if indices[i] in keyframes:continue
                    mask=(logits[0,0]>0).cpu().numpy();save(i,mask)
                    if not mask.any():stopped.append({'frame':indices[i],'reason':'此帧未见主体；可在后续重现帧补提示'})
    metrics['total']=time.perf_counter()-start
    Path(request['result']).write_text(json.dumps({'masks':output,'algorithm':'SAM2.1 Hiera Tiny / CPU / mask-prompt propagation','stopped':stopped,'metrics':metrics},ensure_ascii=False),'utf8')

if __name__=='__main__':main(json.loads(Path(sys.argv[1]).read_text('utf8')))
