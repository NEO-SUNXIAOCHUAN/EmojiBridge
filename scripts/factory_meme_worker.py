"""Isolated MemeCrafters adapter. Called by the same desktop job service."""
import argparse,json,sys,inspect,time,traceback,os
from pathlib import Path

# Portable CPython's ._pth intentionally omits the script directory. Resolve
# our own adapters explicitly, as the desktop/native entrypoints already do;
# keep isolation from the current directory and global Python environment.
APP=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(APP/'scripts'),str(APP/'src')]
from factory_template_input import catalog_defaults,prepare_texts


def main():
    parser=argparse.ArgumentParser();parser.add_argument('request',type=Path);parser.add_argument('--dependencies',type=Path,required=True)
    args=parser.parse_args();sys.path.insert(0,str(args.dependencies.resolve()))
    dlls=os.add_dll_directory(str(args.dependencies.resolve())) if os.name=='nt' else None
    request=json.loads(args.request.read_text('utf-8'));result=Path(request['result'])
    excluded=set(json.loads((APP/'third_party/factory/excluded-templates.json').read_text('utf-8')))
    if request.get('key','').removeprefix('meme:') in excluded:raise ValueError('该模板已移除，请选择其他模板；已有作品保留')
    import meme_generator as engine
    engine.config.gif.gif_max_frames=18000;engine.config.gif.gif_max_size=1024
    # Only the reviewed fixed upstream modules shipped with this application.
    # User template packages remain declarative; they never enter this loader.
    extension=Path(__file__).resolve().parents[1]/'third_party/meme_contrib/memes'
    if extension.is_dir():
        register=engine.add_meme
        engine.add_meme=lambda key,*a,**kw:register('contrib_'+key,*a,**kw)
        try:engine.load_memes(extension)
        finally:engine.add_meme=register
    if request['action']=='catalog':
        catalog=[]
        for meme in engine.get_memes():
            if meme.key in excluded:continue
            if request.get('keys') and meme.key not in request['keys']:continue
            params=meme.params_type
            code=inspect.getsource(meme.function)
            # Upstream's make_jpg_or_gif explicitly iterates source frames;
            # unknown templates require a user-selected static frame instead.
            animation='preserve' if 'make_jpg_or_gif(' in code or 'make_gif_or_combined_gif(' in code else 'explicit-frame'
            schema=params.args_type.args_model.model_json_schema() if params.args_type else {}
            catalog.append(dict(key='meme:'+meme.key,name=next(iter(meme.keywords),meme.key),keywords=meme.keywords,tags=sorted(meme.tags),
                min_images=params.min_images,max_images=params.max_images,min_texts=params.min_texts,max_texts=params.max_texts,
                default_texts=params.default_texts,parameters=schema,animation_policy=animation,
                version=engine.__version__,source='https://github.com/MemeCrafters/meme-generator',license='MIT (code); resources individually sourced',
                verified=False))
        result.write_text(json.dumps([catalog_defaults(row) for row in catalog],ensure_ascii=False),'utf-8');return
    if request['action']=='verify':
        from PIL import Image
        folder=Path(request['folder']);folder.mkdir(parents=True,exist_ok=True);results=[]
        for meme in engine.get_memes():
            if meme.key in excluded:continue
            if request.get('keys') and meme.key not in request['keys']:continue
            tick=time.perf_counter();params=meme.params_type
            try:
                defaults=catalog_defaults(dict(key=meme.key,min_texts=params.min_texts,default_texts=params.default_texts))
                texts=defaults['default_texts'] or ['今天也要开心']*defaults['min_texts']
                texts=texts[:params.max_texts]
                while len(texts)<params.min_texts:texts.append('一起出发')
                output=meme(images=[Path(request['sample'])]*params.min_images,texts=prepare_texts(meme.key,texts,params.min_images),args={})
                path=folder/(meme.key+'.media');path.write_bytes(output.getvalue())
                with Image.open(path) as image:
                    fmt=image.format;size=image.size;frames=image.n_frames if hasattr(image,'n_frames') else 1
                    for i in range(frames):image.seek(i);image.load()
                final=path.with_suffix({'PNG':'.png','JPEG':'.jpg','GIF':'.gif','WEBP':'.webp'}[fmt]);path.replace(final)
                row=dict(key='meme:'+meme.key,ok=True,file=str(final),format=fmt,size=size,frames=frames,bytes=final.stat().st_size)
            except Exception as exc:row=dict(key='meme:'+meme.key,ok=False,error=type(exc).__name__+': '+str(exc))
            row['seconds']=time.perf_counter()-tick;results.append(row)
            result.write_text(json.dumps(results,ensure_ascii=False),'utf-8')
        return
    from factory_animation_input import install
    install(engine,request)
    meme=engine.get_meme(request['key'].removeprefix('meme:'))
    output=meme(images=[Path(p) for p in request.get('images',[])],texts=prepare_texts(request['key'],request.get('texts',[]),len(request.get('images',[]))),args=request.get('parameters',{}))
    if request.get('preview'):
        from PIL import Image
        with Image.open(output) as image:
            image=image.convert('RGBA');image.thumbnail((360,280));image.save(result,'PNG')
        return
    result.write_bytes(output.getvalue())


if __name__=='__main__':main()
