"""Assemble the three S0183 distributions from pinned, already tested payloads.

Run from the repository with its packaged Python. No runtime downloads, source
overlays, user profiles or untracked source packages are included.
"""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess, zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'exports/release-S0183'
BASE = ROOT / 'exports/live-drawing-S0183/EmojiBridge-S0183-Windows-x64-lite.zip'
BASE_SHA = 'f9b12ddfd40d3e8cf9143e559b922d90f6b56ada476e5031bfe15cd53b06dae4'
COMMIT = '9142c80a66fc63521e8eb493830fca28e82dedab'
URL = 'https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0183/'
VARIANTS = {'lite': (), 'lite-templates': ('templates',), 'full': ('anime', 'fine', 'speech', 'templates')}

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', 'utf8')

GUIDE = '''EmojiBridge S0183

完整解压 ZIP，打开 EB 文件夹，双击 EmojiBridge.exe。不要只取出 EXE 或在压缩包内运行。
无需安装 Python、无需管理员权限；缺少系统 WebView2 时按启动提示安装微软官方运行环境。

轻量版：默认 U²-Net 自动抠主体、编辑、视频/GIF、OCR/跟随与互通视觉组件离线可用。
轻量模板版：在轻量版基础上包含模板引擎与既定模板资源。
完整离线版：另外包含动漫、精细抠图与 tiny 字幕；base/small/SAM2 不内置。
三种版本代码相同，选择一种下载。设置 → 可选组件可下载并安装，或直接导入组件 ZIP。
可选组件继续使用 S0174 的固定地址和校验，不需要重复安装兼容组件。

QQ 直接读取选定的个人表情缓存目录，QQ 可以关闭；点击“更新”才重新扫描，不自动持续扫描。
微信沿用已有读取能力。读取、复制、互通不会自动加入素材库；仅“加入素材库”保存所选项。
缓存条目随源文件变化；已加入素材库的独立原件继续保留。
互通与素材库卡片始终支持勾选：点击后恰好选中一张就复制，零张或多张不复制。
全选、清空、翻页和后台列表更新不自动复制。随手素材复制后保持打开，快捷键只收回/呼出窗口。

桌面贴图每次独立创建；短按固定键固定/解除，长按后拖动旋转，右键可播放/暂停 GIF、自动抠主体。
随手素材的形状、箭头、文字、画笔直接在实时桌面上绘制，背景和 GIF 继续播放。
任一工具下点已有对象即可选择，拖动移动；上方圆点旋转，右下角缩放；双击文字继续编辑。
完成仅成为临时桌面贴图，不自动保存到素材库/随手素材；需要永久保留时主动保存。

互通控件优先，当前步骤缺能力才用视觉，不修改 QQ/微信进程内存。
微信使用本人的文件传输助手；QQ 目标只添加个人收藏。自动操作期间不要遮挡或切换目标窗口。
发送结果未知时先核验，不自动重发。不同客户端版本、窗口布局和缩放仍可能影响兼容性。

公开 S0175 没有内置更新模块，须手动安装本次新版一次，保留旧目录和用户数据。
之后启动只检查官方稳定版元数据；点击更新才下载同类型完整 ZIP，校验后保存退出并重启。
这是完整包更新，不是差分补丁；不要通过删除素材库或覆盖仍运行的程序来升级。
设置中可备份素材库。既有素材、收藏、标签、合集和草稿不需重新导入。
'''

def stage():
    assert sha(BASE) == BASE_SHA, 'tested_lite_changed'
    OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BASE) as z:
        base = json.loads(z.read('EB/BUILD.json'))
        assert base['source_commit'] == COMMIT and base['build'] == 'S0183'
        entries = {e['path']:e for e in base['files']}
        assert set(z.namelist()) == {'EB/'+p for p in entries} | {'EB/BUILD.json'}
        for name, entry in entries.items():
            data = z.read('EB/'+name)
            assert len(data) == entry['size'] and hashlib.sha256(data).hexdigest() == entry['sha256'], name
        catalog = json.loads(z.read('EB/RELEASE_COMPONENTS.json'))
        assert catalog == json.loads((ROOT/'RELEASE_COMPONENTS.json').read_text('utf8'))
        for variant, components in VARIANTS.items():
            app = OUT/variant/'EB'
            if app.exists(): raise ValueError('fresh_stage_required: '+str(app))
            app.mkdir(parents=True)
            for name in entries:
                p = app/name; p.parent.mkdir(parents=True, exist_ok=True)
                with z.open('EB/'+name) as src, p.open('wb') as dst: shutil.copyfileobj(src,dst,1024*1024)
            for ident in components:
                spec = catalog['components'][ident]
                archive = ROOT/'exports/release-S0174'/spec['filename']
                assert archive.stat().st_size == spec['bytes'] and sha(archive) == spec['sha256']
                with zipfile.ZipFile(archive) as component:
                    expected = {'schema':'emojibridge-component-v1','id':ident,'abi':catalog['abi'],'files':spec['files']}
                    assert json.loads(component.read('component.json')) == expected
                    assert set(component.namelist()) == {e['path'] for e in spec['files']} | {'component.json'}
                    for e in spec['files']:
                        p=app/e['path']; assert not p.exists(), e['path']
                        p.parent.mkdir(parents=True, exist_ok=True)
                        with component.open(e['path']) as src, p.open('wb') as dst: shutil.copyfileobj(src,dst,1024*1024)
                        assert p.stat().st_size==e['size'] and sha(p)==e['sha256'], e['path']
            (app/'使用说明.txt').write_text(GUIDE,'utf8')
            (app/'版本信息.txt').write_text(f'EmojiBridge S0183 · {variant}\n产品提交 {COMMIT}\n数据库格式 3\n','utf8')
            (app/'交互更新说明.txt').write_text('QQ 直接读取'+GUIDE.split('QQ 直接读取',1)[1], 'utf8')
            current=dict(base,distribution=variant,assembly_source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                         release_payload_base_sha256=BASE_SHA,publication_ready=False,external_machine_verified=False)
            current['files']=[dict(path=p.relative_to(app).as_posix(),size=p.stat().st_size,sha256=sha(p))
                              for p in sorted(app.rglob('*')) if p.is_file()]
            current['max_archive_path_chars']=max(len('EB/'+e['path']) for e in current['files'])
            if 'templates' in components:
                with zipfile.ZipFile(ROOT/'exports/release-S0175/EmojiBridge-S0175-Windows-x64-full.zip') as old:
                    current['template_packages']=json.loads(old.read('EB/BUILD.json')).get('template_packages',{})
            # The model/runtime bytes and all executable product files match the
            # tested lite package; only the three human-readable guides change.
            actual={e['path']:e for e in current['files']}
            changed=[n for n,e in entries.items() if actual[n]['sha256']!=e['sha256']]
            assert set(changed)=={'使用说明.txt','版本信息.txt','交互更新说明.txt'}, changed
            write_json(app/'BUILD.json',current)
            print('staged',variant,len(current['files']),flush=True)
    shutil.copyfile(ROOT/'RELEASE_COMPONENTS.json',OUT/'RELEASE_COMPONENTS.json')

def archives():
    for variant in VARIANTS:
        app=OUT/variant/'EB'; build=json.loads((app/'BUILD.json').read_text('utf8'))
        archive=OUT/f'EmojiBridge-S0183-Windows-x64-{variant}.zip'
        with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for e in build['files']:z.write(app/e['path'],'EB/'+e['path'])
            z.write(app/'BUILD.json','EB/BUILD.json')
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            for e in build['files']:
                data=z.read('EB/'+e['path'])
                assert len(data)==e['size'] and hashlib.sha256(data).hexdigest()==e['sha256'], e['path']
        print('verified',variant,archive.stat().st_size,sha(archive),flush=True)
    sums()

def sums():
    rows=[dict(name=p.name,bytes=p.stat().st_size,sha256=sha(p),url=URL+p.name) for p in sorted(OUT.glob('*.zip'))]
    write_json(OUT/'release-assets.json',rows)
    (OUT/'SHA256SUMS.txt').write_text(''.join(e['sha256']+'  '+e['name']+'\n' for e in rows),'ascii')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('stage','archives','sums'))
    globals()[parser.parse_args().action]()
