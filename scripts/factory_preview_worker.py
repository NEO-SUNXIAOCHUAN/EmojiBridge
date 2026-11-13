"""Reusable MemeCrafters preview process. Formal generation uses its own worker.

Intercept the engine's common GIF writer to encode display-sized lossless WebP
directly from frames. The engine's frame evaluation and timing remain unchanged.
"""
import argparse,json,sys,time,os
from pathlib import Path
from io import BytesIO

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dependencies');args=parser.parse_args();sys.path.insert(0,args.dependencies)
    dlls=os.add_dll_directory(str(Path(args.dependencies).resolve())) if os.name=='nt' else None
    import meme_generator as engine
    from PIL import Image
    import meme_generator.utils as utils
    edge=384
    original=utils.save_gif
    def display_animation(frames,duration):
        images=[]
        for frame in frames:
            image=frame.convert('RGBA');image.thumbnail((edge,edge),Image.Resampling.LANCZOS);images.append(image)
        output=BytesIO();images[0].save(output,'WEBP',save_all=True,append_images=images[1:],duration=round(duration*1000),loop=0,lossless=True,method=0)
        return output
    for module in list(sys.modules.values()):
        if getattr(module,'__name__','').startswith('meme_generator') and getattr(module,'save_gif',None) is original:setattr(module,'save_gif',display_animation)
    extension=Path(__file__).resolve().parents[1]/'third_party/meme_contrib/memes'
    if extension.is_dir():
        register=engine.add_meme;engine.add_meme=lambda key,*a,**kw:register('contrib_'+key,*a,**kw)
        try:engine.load_memes(extension)
        finally:engine.add_meme=register
    for line in sys.stdin:
        try:request=json.loads(line)
        except ValueError:continue
        if request.get('action')=='close':break
        tick=time.perf_counter();result=Path(request['result']);meta=result.with_suffix('.json')
        try:
            edge=request.get('edge',384)
            output=engine.get_meme(request['key'].removeprefix('meme:'))(images=[Path(p) for p in request['images']],texts=request['texts'],args=request['parameters'])
            # Templates which use a separate writer still work; decode just the
            # produced display file once, never on the UI thread.
            with Image.open(output) as source:
                images=[];durations=[];loop=source.info.get('loop')
                for i in range(getattr(source,'n_frames',1)):
                    source.seek(i);image=source.convert('RGBA');image.thumbnail((edge,edge),Image.Resampling.LANCZOS);images.append(image);durations.append(source.info.get('duration',100))
            images[0].save(result.with_suffix('.png'),'PNG')
            options={'save_all':True,'append_images':images[1:],'duration':durations,'lossless':True,'method':0}
            if loop is not None:options['loop']=loop
            images[0].save(result,'WEBP',**options)
            value={'ok':True,'frames':len(images),'durations':durations,'loop':loop,'size':images[0].size,'seconds':time.perf_counter()-tick}
        except Exception as exc:value={'ok':False,'error':str(exc),'seconds':time.perf_counter()-tick}
        meta.write_text(json.dumps(value,ensure_ascii=False),'utf8')

if __name__=='__main__':main()
