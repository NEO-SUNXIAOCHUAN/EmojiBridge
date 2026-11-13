"""Petpet's declarative XYWH subset, translated to editable scene templates.

The Java/JS renderer is not executed. Unsupported filters/deformation/scripts
produce an explicit error rather than silently changing a template's meaning.
"""
from pathlib import Path
from io import BytesIO
from uuid import uuid4
import ast,json,operator,re
from PIL import Image
from .editing import EditDocument,save_scene,load_static
from .animated_edit import SubjectSource


def number(value,width,height):
    if isinstance(value,(int,float)):return float(value)
    value=str(value).strip().removesuffix('px').replace('vw','*width/100').replace('vh','*height/100')
    tree=ast.parse(value,mode='eval')
    def visit(node):
        if isinstance(node,ast.Constant) and isinstance(node.value,(int,float)):return node.value
        if isinstance(node,ast.Name) and node.id in ('width','height'):return {'width':width,'height':height}[node.id]
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):return visit(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
        if isinstance(node,ast.BinOp) and type(node.op) in (ast.Add,ast.Sub,ast.Mult,ast.Div):return {ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv}[type(node.op)](visit(node.left),visit(node.right))
        raise ValueError('Petpet 坐标只接受数值、px/vw/vh 和四则运算；不会执行脚本')
    return visit(tree.body)


def convert(root):
    root=Path(root);file=root/'template.json';old=not file.exists()
    if old:file=root/'data.json'
    raw=json.loads(file.read_text('utf-8'));canvas=raw.get('background' if old else 'canvas') or {}
    pngs=sorted((p for p in root.glob('*.png') if p.stem.isdigit()),key=lambda p:int(p.stem))
    backgrounds=[load_static(p) for p in pngs]
    dimensions=backgrounds[0].size if backgrounds else (300,300)
    w,h=[round(number(canvas.get(k,dimensions[n]),*dimensions)) for n,k in enumerate(('width','height'))]
    if not 1<=w<=8192 or not 1<=h<=8192:raise ValueError('Petpet 画布尺寸超出1～8192范围')
    delay=max(1,round(float(raw.get('delay',1000/float(raw.get('fps',20))))))
    count=int(canvas.get('length',len(backgrounds) or 1));slots=[];layers=[]
    if old:
        elements=[dict(a,type='image',key=a.get('type','TO').lower(),coords=a.get('pos'),behind=not a.get('avatarOnTop',True)) for a in raw.get('avatar',[])]
        elements += [dict(t,type='text',coords=t.get('pos'),key=f'文案{n+1}') for n,t in enumerate(raw.get('text',[]))]
    else:elements=raw.get('elements',[])
    for element in elements:
        if element.get('type') not in ('image','text'):raise ValueError('当前 Petpet 适配仅支持 image/text；background 元素请转为本地图片层')
        if any(element.get(k) for k in ('filter','rotate','crop','round','border_radius','script')) or element.get('posType','ZOOM')!='ZOOM':raise ValueError('此 Petpet 模板含变形、裁切、圆角、滤镜或脚本，当前适配未覆盖；资源未运行')
        if element.get('opacity',1)!=1 or element.get('style') or element.get('stroke_size') or element.get('strokeSize'):raise ValueError('此 Petpet 模板的透明/描边/样式尚未适配')
        coords=element.get('coords')
        if not isinstance(coords,list) or not coords:raise ValueError('Petpet 缺少有效 coords/pos')
        if not isinstance(coords[0],list):coords=[coords]
        expected=4 if element['type']=='image' else 2
        if any(len(c)!=expected or any(isinstance(n,list) for n in c) for c in coords):raise ValueError('当前 Petpet 适配仅支持 XYWH 图片坐标和 XY 文字坐标')
        coords=[[round(number(n,w,h)) for n in c] for c in coords];count=max(count,len(coords))
        key=element.get('key') or f'素材{len(slots)+1}'
        if isinstance(key,list):
            if len(set(key))!=1:raise ValueError('动画中切换输入槽尚未适配')
            key=key[0]
        layers.append((element,coords,str(key)))
    if not 0<count<=18000 or count*delay>1800000:raise ValueError('Petpet 时间轴超过现有帧/时长预算')
    doc=EditDocument(Image.new('RGBA',(w,h),canvas.get('color','#ffffff')),[])
    background_layer=None
    if backgrounds:
        if any(b.size!=(w,h) for b in backgrounds):raise ValueError('Petpet 背景帧尺寸与画布不一致')
        image=backgrounds[0];ident=doc.add_sticker(image,(0,0));background_layer=ident
        if count>1:
            frames=tuple(backgrounds[min(i,len(backgrounds)-1)] for i in range(count));data=BytesIO();image.save(data,'PNG')
            animation=SubjectSource(data.getvalue(),frames,(delay,)*count,0,'.png')
            doc.replace_scene(doc._state.base,[dict(l,animation=animation) for l in doc.layers],[])
    for element,coords,key in layers:
        c=coords[0];kind=element['type'];default=element.get('default',element.get('src'))
        if kind=='text':
            text=element.get('text','文字')
            if not isinstance(text,str) or '$' in text:raise ValueError('Petpet 变量文案请先替换为默认文本；动态文字数组暂不适配')
            ident=doc.add_text(text,size=round(number(element.get('size',16),w,h)),color=element.get('color','#191919' if old else '#ffffff'),position=tuple(c));default=text
        else:
            image=Image.new('RGBA',(100,100),'#64758a')
            if default:
                file=(root/str(default).removeprefix('file://')).resolve()
                if not file.is_relative_to(root.resolve()) or not file.is_file():raise ValueError('Petpet 默认资源必须在模板包中；不会自动读取外部文件或网址')
                image=load_static(file)
            ident=doc.add_sticker(image,tuple(c[:2]),size=tuple(c[2:]))
        slots.append({'key':key,'kind':kind,'layer':ident,'default':default if kind=='text' else None})
        changed=dict(doc._find(ident),rotation=-float(element.get('angle',0)))
        if count>1:
            boxes=[(coords[min(n,len(coords)-1)]+[1,1] if kind=='text' else coords[min(n,len(coords)-1)]) for n in range(count)]
            changed['tracking']={'reference':boxes[0],'keys':[{'ms':n*delay,'box':box,'ok':True} for n,box in enumerate(boxes)],'duration':count*delay,'algorithm':'Petpet declarative XYWH'}
            # Even static input slots retain the template's explicit full clock.
            if kind=='image':
                data=BytesIO();image.save(data,'PNG');changed['animation']=SubjectSource(data.getvalue(),(image,)*count,(delay,)*count,0,'.png')
        all_layers=[changed if l['id']==ident else l for l in doc.layers]
        if element.get('behind') and background_layer:all_layers.insert(0,all_layers.pop())
        doc.replace_scene(doc._state.base,all_layers,[])
    if raw.get('reverse') or canvas.get('reverse'):raise ValueError('此 Petpet 模板倒序标记尚未自动适配；可在原包取消后使用编辑器倒放')
    save_scene(doc,root/'scene','Petpet 模板');doc.render().save(root/'preview.png')
    manifest={'schema':'emoji-template-v1','id':uuid4().hex,'version':1,'name':(raw.get('alias') or raw.get('metadata',{}).get('alias') or ['Petpet 模板'])[0],'slots':slots,'origin':'petpet-old' if old else 'petpet-new','fonts':['目标 Windows 中文字体'],'adapter':'XYWH/text/local-resource-v1'}
    (root/'template.json').write_text(json.dumps(manifest,ensure_ascii=False),'utf-8');return manifest
