"""Build S0175 lite/full and pinned optional components from verified runtime."""
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess,zipfile,os,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
OUT=ROOT/'exports/release-S0175'
BASE=ROOT/'exports/release-S0174/EmojiBridge-S0174-Windows-x64-full.zip'
BASE_SHA='48f7b8c4e9ba425ba3d31c7dc9241304bde5fd64f0e39d20cc2059c3e4406795'
ABI='S0174'
URL='https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0175/'
COMPONENTS={
 'anime':('动漫抠图','IS-Net Anime，动漫主体提取',('runtime/cutout-models/isnet-anime.onnx',)),
 'fine':('精细抠图','BiRefNet Lite，精细边缘主体提取',('runtime/cutout-models/birefnet-general-lite.onnx',)),
 'speech':('字幕转写','CPU 本地字幕转写，含 tiny 模型与专用依赖',('runtime/speech/','runtime/speech-models/')),
 'templates':('模板扩展','表情工厂模板引擎、模板资源与专用依赖',('runtime/meme/',)),
}
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def jb(value):return json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8')
def row(path,base):return dict(path=path.relative_to(base).as_posix(),size=path.stat().st_size,sha256=sha(path))
def writezip(file,folder,names,prefix=''):
    with zipfile.ZipFile(file,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name in sorted(names):z.write(folder/name,prefix+name)
    with zipfile.ZipFile(file) as z:
        assert z.testzip() is None
def stage():
    assert sha(BASE)==BASE_SHA,'baseline_changed'
    app=OUT/'full/EB'
    if app.exists():raise ValueError('fresh_stage_required')
    app.mkdir(parents=True)
    with zipfile.ZipFile(BASE) as z:
        build=json.loads(z.read('EB/BUILD.json'))
        for entry in build['files']:
            target=app/entry['path'];target.parent.mkdir(parents=True,exist_ok=True)
            with z.open('EB/'+entry['path']) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst,1024*1024)
            assert sha(target)==entry['sha256'] and target.stat().st_size==entry['size'],entry['path']
    assemble()

def assemble():
    app=OUT/'full/EB'
    with zipfile.ZipFile(BASE) as z:build=json.loads(z.read('EB/BUILD.json'))
    # Runtime comes only from the verified ZIP; all product sources come from
    # the current checkout, retaining every accumulated S0169–S0173 fix.
    from export_public_source import selected
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf8').split('\0')
    for name in tracked:
        if not name or not selected(name) or name.startswith(('tests/','desktop-ui/','docs/')):continue
        src=ROOT/name
        if src.is_file():
            dst=app/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    guide='''EmojiBridge S0175\n\n请完整解压，打开 EB 文件夹，双击 EmojiBridge.exe。不要只拖出 EXE。无需安装 Python。\n\n轻量版：默认 U²-Net 抠图、基本编辑、视频/GIF、互通识字和视觉组件离线可用。\n轻量模板版：在轻量版基础上包含模板扩展，不用另装模板包。\n完整版：另外包含动漫、精细抠图、tiny 字幕及模板扩展。base/small/SAM2 不在完整离线范围。\n轻量版需要扩展时：设置 → 可选组件 → 下载组件 → 导入已下载组件包；不用解压组件 ZIP。\n保留 assets/factory；不删用户素材、模型、草稿或旧版本。四张经典 Meme 仍仅在独立演示包。\n\n控件优先，仅当前步骤控件不可用才视觉。微信只使用本人的文件传输助手，QQ 只添加个人收藏。未知发送结果先核验，不自动重发。\n读取 QQ 收藏或补原件时，请勿移动鼠标。互通不锁鼠标；自动点击和视觉核验期间，请勿点击、滚动、拖动或遮挡目标窗口，避免指针覆盖操作区域。需要操作时先取消，稍后继续。\nQQ 路径未找到可在账号设置选择 Tencent Files、本人账号或 nt_qq 文件夹；多个账号须本人确认。\nWebView2 为系统组件，缺少时按启动提示安装微软官方运行时。\n'''
    (app/'使用说明.txt').write_text(guide,'utf-8-sig')
    (app/'版本信息.txt').write_text('EmojiBridge S0175 · 轻量 / 完整离线同代码\n','utf-8-sig')
    # Components are byte-identical to S0174 and retain its pinned ABI/URLs.
    catalog=json.loads((ROOT/'RELEASE_COMPONENTS.json').read_text('utf8'))
    for spec in catalog['components'].values():
        original=ROOT/'exports/release-S0174'/spec['filename']
        assert sha(original)==spec['sha256']
        for e in spec['files']:
            assert sha(app/e['path'])==e['sha256'],e['path']
    (app/'RELEASE_COMPONENTS.json').write_bytes(jb(catalog))
    (OUT/'RELEASE_COMPONENTS.json').write_bytes(jb(catalog))
    excluded={e['path'] for spec in catalog['components'].values() for e in spec['files']}
    names=[p.relative_to(app).as_posix() for p in app.rglob('*') if p.is_file()]
    templates={e['path'] for e in catalog['components']['templates']['files']}
    for variant in ('lite','lite-templates'):
        destroot=OUT/variant/'EB';destroot.mkdir(parents=True)
        omit=excluded if variant=='lite' else excluded-templates
        for name in names:
            if name in omit:continue
            dest=destroot/name;dest.parent.mkdir(parents=True,exist_ok=True);os.link(app/name,dest)
    build.pop('optional_components',None)
    (OUT/'base-build.json').write_bytes(jb(build))
    stamp()
def refresh():
    from export_public_source import selected
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf8').split('\0')
    for variant in ('full','lite','lite-templates'):
        app=OUT/variant/'EB'
        for name in tracked:
            if not name or not selected(name) or name.startswith(('tests/','desktop-ui/','docs/')):continue
            src=ROOT/name
            if src.is_file():
                dst=app/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    stamp()

def stamp():
    build=json.loads((OUT/'base-build.json').read_text('utf8'))
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    for variant in ('full','lite','lite-templates'):
        app=OUT/variant/'EB'
        entries=[row(p,app) for p in sorted(app.rglob('*')) if p.is_file() and p.name!='BUILD.json' and '__pycache__' not in p.parts and p.suffix!='.pyc']
        current=dict(build,build='S0175',source_commit=commit,distribution=variant,files=entries,
                     component_catalog='RELEASE_COMPONENTS.json',publication_ready=False,external_machine_verified=False)
        current['trial']=dict(build.get('trial',{}),base_archive_sha256=BASE_SHA)
        current['max_archive_path_chars']=max(len('EB/'+e['path']) for e in entries)
        if variant=='lite':current['template_packages']={}
        (app/'BUILD.json').write_bytes(jb(current))
def archives():
    stamp()
    for variant in ('lite','lite-templates','full'):
        app=OUT/variant/'EB';build=json.loads((app/'BUILD.json').read_text('utf8'))
        names=[e['path'] for e in build['files']]+['BUILD.json']
        file=OUT/f'EmojiBridge-S0175-Windows-x64-{variant}.zip';writezip(file,app,names,'EB/')
        with zipfile.ZipFile(file) as z:
            for e in build['files']:
                h=hashlib.sha256();size=0
                with z.open('EB/'+e['path']) as f:
                    while block:=f.read(1024*1024):h.update(block);size+=len(block)
                assert size==e['size'] and h.hexdigest()==e['sha256'],e['path']
        print(variant,file.stat().st_size,sha(file),flush=True)
    sums()
def sums():
    files=sorted(OUT.glob('*.zip'))
    results=[dict(name=p.name,bytes=p.stat().st_size,sha256=sha(p),url=URL+p.name) for p in files]
    (OUT/'SHA256SUMS.txt').write_text(''.join(r['sha256']+'  '+r['name']+'\n' for r in results),'ascii')
    (OUT/'release-assets.json').write_bytes(jb(results))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('stage','assemble','refresh','stamp','archives','sums'));args=parser.parse_args();globals()[args.action]()
