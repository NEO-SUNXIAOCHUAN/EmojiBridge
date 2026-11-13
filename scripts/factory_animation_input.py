"""Bridge reviewed upstream per-frame makers to our lossless streaming output.

MemeCrafters' maker supplies the visual algorithm. Its merge_gif averages frame
durations; use EmojiBridge's existing timeline/encoder to retain input timing.
"""
from pathlib import Path
from io import BytesIO
import sys

SUPPORTED={'meme:seal','meme:stare_at_you'}


def install(engine,request):
    if request['key'] not in SUPPORTED:return
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
    from PIL import Image
    from pil_utils import BuildImage
    from emoji_bridge.animated_edit import GifSource,CompositeTimeline,layer_frame
    from emoji_bridge.animation_formats import export_animation
    sources=[]
    for file in request['images']:
        with Image.open(file) as im:
            sources.append({'animation':GifSource.read(file)} if getattr(im,'is_animated',False) else {'image':im.convert('RGBA')})
    if not any(s.get('animation') for s in sources):return
    import importlib
    module=importlib.import_module('meme_generator.memes.'+request['key'].split(':')[1])
    timeline=CompositeTimeline([s for s in sources if s.get('animation')])
    def make(images,maker):
        class Scene:
            animation=timeline
            def render(self,animation_frame=0):
                frames=[BuildImage(layer_frame(s,timeline,animation_frame).copy() if s.get('animation') else s['image'].copy()) for s in sources]
                return maker(frames).image.convert('RGBA')
        scene=Scene();scene.size=scene.render().size
        file=Path(request['result']).with_suffix('.input-animation.png')
        export_animation(scene,file)
        return BytesIO(file.read_bytes())
    module.make_png_or_gif=make
