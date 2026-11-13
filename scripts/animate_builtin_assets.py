"""Build-time licensed motion variants using the existing effect/export code."""
import json,math
from pathlib import Path
from PIL import Image
from emoji_bridge.animated_edit import SubjectSource,export_gif
from emoji_bridge.dropped_item import ItemOptions,render_frame,document

root=Path(__file__).resolve().parents[1]/'assets/examples';entries=json.loads((root/'source.json').read_text('utf-8'));manifest=[]
for name,code in entries:
    manifest.append({'file':code+'.png','name':name,'collections':['日常反应']+(['创作素材'] if code in ('1f438','1f47b','1f431','1f986') else [])})
for name,code in [('飘飘幽灵','1f47b'),('快乐小鸭','1f986'),('庆祝摇摆','1f973')]:
    source=Image.open(root/(code+'.png')).convert('RGBA');frames=[]
    for i in range(16):
        frame=Image.new('RGBA',(288,288));value=source.rotate(math.sin(i/16*math.tau)*9,Image.Resampling.BICUBIC,expand=False)
        frame.alpha_composite(value,(16,round(16+math.sin(i/16*math.tau)*10)));frames.append(frame)
    animation=SubjectSource((root/(code+'.png')).read_bytes(),tuple(frames),(70,)*16,0,'.png')
    file=code+'-motion.gif';export_gif(document({'animation':animation,'options':{}},code),root/file)
    manifest.append({'file':file,'name':name,'collections':['日常反应','创作素材'],'modification':'EmojiBridge 旋转 / 浮动动画，16帧'})
code='1f438';source=Image.open(root/(code+'.png')).convert('RGBA');options=ItemOptions(size=256,seconds=2)
frames=tuple(render_frame(source,i*50,options) for i in range(40));animation=SubjectSource((root/(code+'.png')).read_bytes(),frames,(50,)*40,0,'.png')
export_gif(document({'animation':animation,'options':{}},code),root/'frog-item.gif')
manifest.append({'file':'frog-item.gif','name':'青蛙 · 掉落物','collections':['创作素材'],'modification':'EmojiBridge 40帧薄片旋转动画'})
(root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
