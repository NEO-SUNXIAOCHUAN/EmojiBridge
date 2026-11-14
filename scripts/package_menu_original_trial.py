"""Isolated S0167 friend trial, based on the immutable S0166 full ZIP."""
from pathlib import Path
import json,subprocess,zipfile,shutil,hashlib
from package_wechat_visual_trial import digest,file_sha,json_bytes

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'exports/batch-compat-S0166/EmojiBridge-S0166-batch-compat-trial-full.zip'
BASE_SHA='f21d1f259dddc87eb22e83de00c1c518585aa0b3713d13fc7907c0de42a00246'
OUT=ROOT/'exports/menu-original-S0167'
FILES=['scripts/collection_transfer.py', 'scripts/wechat_uia.ps1', 'src/emoji_bridge/appearance_originals.py', 'src/emoji_bridge/media.py', 'src/emoji_bridge/wechat.py', 'src/emoji_bridge/wechat_visual.py', 'src/emoji_bridge/wechat_visual_bridge.py', 'RELEASE_NOTES.md']
FILES += ['src/emoji_bridge/background_remove.py','scripts/desktop_service.py','third_party/cutout/NOTICE.md']
FILES += ['src/emoji_bridge/video.py','src/emoji_bridge/capabilities.py','scripts/factory_speech_worker.py','scripts/video_speech_ui.py','scripts/scribble_tools.py','THIRD_PARTY_NOTICES.md','RELEASE_RIGHTS.md','third_party/FFmpeg-NOTICE.md','third_party/factory/NOTICE.md','third_party/factory/Whisper-LICENSE.txt']
OFFLINE=ROOT/'private/T008/feedback-S0166/offline-payload'
FILES += ['scripts/factory_template_input.py','scripts/factory_meme_worker.py','scripts/factory_preview_worker.py','assets/factory/catalog.json','TEMPLATE_CATALOG.json']

INSTRUCTIONS='EmojiBridge S0167 菜单与原件准备测试（独立测试，非公开更新）\n\n已安装未改动的 S0166 完整测试包：使用本次小补丁，选择旧 EB 目录。\n其他版本或已修改文件：使用完整包，解压到新文件夹启动 EB/EmojiBridge.exe。\n先保存作品、正常退出旧版。不要同时运行两份，不删除用户素材目录。\n补丁会校验旧文件，保留备份，支持恢复；校验不符不会强行覆盖。\n\n修复：微信视觉菜单整图 OCR 把“添加到表情”识别错误，改为定位实际文字行后精确识别。\n小字需两种留白识别一致，不按菜单第几项盲点；灰色禁用、重复候选、遮挡与失焦仍停止。\n控件优先：视觉接管后仍先读取原生菜单；只读弹窗探测不再反复枚举不可用主窗口树。\n菜单只读探测2秒上限（助手进程首次启动单列），失败才转视觉，不重复输入操作。\n原件准备：同一批量内复用按SHA核验的解码与证据解析，文件变化仍重新检查；增加每项阶段/耗时。\n正常QQ UIA/MSAA优先级、后台让位、所选优先、防重及未确定不重发全部保留。\n\n本轮本机150%深色：新六张3静3动真实纯视觉发送收藏全部确认34.156秒；只读复核5.318秒六项已有零重发。\n该测试强制视觉为明确注入，真实客户端动作和结果不是模拟；不是故障同学电脑通过。\n正常微信原生绑定1.505秒，未转视觉。此前QQ来源的六份已就绪原件1.725秒入隔离素材库，零QQ操作。\n用户三处失败菜单原画面识别回放通过。缩放/反色回放与几何测试不冒充真实系统DPI/浅色验证。\n本轮没有新QQ全库更新实测，六张中的原件长等待尚缺故障端任务记录，不能宣称所有卡顿已解决。\n真实外机、浅色及100/125仍待验，保留前轮已知限制。正式S0163/独立Meme包/网站不改，不写客户端内存。\n\n请先测试同一失败菜单，再测六张（含动图）并继续同任务，检查是否全部确认、是否重复。\n测试完成可在“查看互通结果”核对具体未完成项；已提交待确认先核验，不要新建任务反复发送。\n'

INSTRUCTIONS += '\n抠主体修复：本完整包和补丁均包含默认 U2-Net 模型，无需首次联网下载。\n另外两种模型仍可选；需要时下载原配套 IS-Net 动漫或 BiRefNet Lite 模型包。\n旧版只需抠主体的用户也可单独安装 U2-Net 模型包，不必改动互通。\n模型在本机运行，不上传图片。首次载入耗时与电脑有关，不保证任意图片分割质量。\n'

OFFLINE_GUIDE='''默认功能离线就绪（S0167 完整测试包）

完整解压后运行 EB/EmojiBridge.exe，无需安装 Python 或寻找模型目录。
默认抠主体 U2-Net、模板生成、识字/跟随、视频处理及 tiny 字幕转写随包提供。
QQ/微信互通仍需要客户端登录及网络；“离线”指本地编辑与生成。

可选抠图模型：
1. 在编辑器“主体/修正”选择 IS-Net Anime 或 BiRefNet Lite。
2. 展开“模型文件”，点“下载所选模型（浏览器）”。
3. 下载完点“导入所选模型…”，选择下载的 ONNX 文件，或原配套模型 ZIP。
4. 程序自动校验并安装。看到“已找到本地模型”后，点“自动抠主体”即可。
不需要解压 ZIP、不需要重命名或复制到隐藏目录。选错或不完整的模型不会覆盖已有模型。
GitHub 下载失败时，可把另一台电脑下载好的同一文件复制过来，再按第 3 步导入。

可选字幕模型：
打开视频的“台词与字幕”，选择 base 或 small，点“下载并安装所选模型”。
完成后点“本地转写”；自动保存在本机，下次直接使用，不重复下载。
“官方下载页”打开对应模型来源；通常直接使用软件的下载并安装按钮即可，无需手工选文件。
下载时可以取消，失败可重试；tiny 已随包准备，不需要等待其他模型。

下载与安装不会上传图片、删除用户素材或改动客户端内存。
首次模型载入仍需时间，识字/分割/转写效果取决于输入内容和电脑性能。
'''
INSTRUCTIONS += '\n默认离线范围：U2-Net、模板、OCR/跟随、FFmpeg 视频和 tiny 字幕转写全部随包。\n可选模型下载/自动安装/导入步骤见“默认离线功能与模型下载.txt”。\n补丁含新增离线组件，体积不再是之前的小代码补丁；无需同时下载完整包和补丁。\n'

def main():
    if file_sha(BASE)!=BASE_SHA:raise ValueError('baseline_archive_changed')
    if OUT.exists():raise ValueError('fresh_output_directory_required')
    # Explicit product files only. Never collect user archives or private logs.
    files=FILES
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=subprocess.check_output(['git','diff','HEAD','--',*files],cwd=ROOT)
    if dirty:raise ValueError('uncommitted_product_files')
    OUT.mkdir();full=OUT/'EmojiBridge-S0167-menu-original-trial';patch=OUT/'EmojiBridge-S0167-menu-original-patch'
    full.mkdir();patch.mkdir()
    with zipfile.ZipFile(BASE) as z:
        z.extractall(full)
    app=full/'EB';build=json.loads((app/'BUILD.json').read_text('utf8'))
    changes={name:(ROOT/name).read_bytes() for name in files}
    # Include the default model in both deliverables, independent of host caches.
    # Alternative models remain optional and never replace the user's originals.
    model_name='runtime/cutout-models/u2net.onnx'
    with zipfile.ZipFile(ROOT/'exports/EmojiBridge-S0155-models-u2net.zip') as z:
        model=z.read('EB/'+model_name)
    if hashlib.md5(model).hexdigest()!='60024c5c889badc19c04ad937298a77b':
        raise ValueError('default_model_checksum_failed')
    changes[model_name]=model
    lock=json.loads((OFFLINE/'offline-lock.json').read_text('utf8'))
    for entry in lock['files']:
        name=entry['path'];p=OFFLINE/name
        if not p.resolve().is_relative_to((OFFLINE/'runtime').resolve()) or file_sha(p)!=entry['sha256']:raise ValueError('offline_payload_changed:'+name)
        changes[name]=p.read_bytes()
    changes['runtime/offline-defaults.json']=json_bytes(lock)
    changes['QQ视觉兼容测试说明.txt']=INSTRUCTIONS.encode('utf-8-sig')
    changes['默认离线功能与模型下载.txt']=OFFLINE_GUIDE.encode('utf-8-sig')
    changes['版本信息.txt']=('EmojiBridge S0167 菜单与原件准备测试\n产品提交：'+commit+'\n基线：S0166 ef6ba8c\n故障外机仍待验；正式包不变。\n').encode('utf-8-sig')
    old={name:(app/name).read_bytes() if (app/name).is_file() else None for name in changes}
    old['BUILD.json']=(app/'BUILD.json').read_bytes()
    entries={e['path']:e for e in build['files']}
    for name,data in changes.items():
        p=app/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        entries[name]=dict(path=name,size=len(data),sha256=digest(data))
    build.update(build='S0167-menu-original-trial',source_commit=commit,source_tree_clean=True,
                 external_machine_verified=False,publication_ready=False,
                 trial=dict(uia_first=True,msaa_second=True,visual_only_for_missing_capability=True,
                            memory_writes=False,base_archive_sha256=BASE_SHA))
    build['files']=[entries[k] for k in sorted(entries)]
    changes['BUILD.json']=json_bytes(build);(app/'BUILD.json').write_bytes(changes['BUILD.json'])
    manifest=dict(base='S0166 ef6ba8c',product_commit=commit,files=[])
    for name,data in changes.items():
        dest=patch/'payload'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        manifest['files'].append(dict(path=name,sha256=digest(data),old_sha256=digest(old[name]) if old[name] is not None else None))
    (patch/'patch-manifest.json').write_bytes(json_bytes(manifest))
    installer=(ROOT/'scripts/install_wechat_visual_trial.ps1').read_text('utf-8-sig').replace('.S0164-before-visual-test','.S0167-before-menu-test').replace('S0163 完整包','S0166 完整测试包').replace('EmojiBridge S0164 测试补丁','EmojiBridge S0167 测试补丁')
    (patch/'install.ps1').write_text(installer,encoding='utf-8-sig')
    for name,flag in [('安装测试补丁.cmd',''),('恢复原版.cmd',' -Restore')]:
        (patch/name).write_bytes(('@echo off\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0install.ps1"'+flag+'\r\n').encode('ascii'))
    (patch/'使用说明.txt').write_text(INSTRUCTIONS,encoding='utf-8-sig');(patch/'默认离线功能与模型下载.txt').write_text(OFFLINE_GUIDE,encoding='utf-8-sig');shutil.copyfile(app/'LICENSE',patch/'LICENSE')
    for e in build['files']:
        p=app/e['path']
        if p.stat().st_size!=e['size'] or file_sha(p)!=e['sha256']:raise ValueError('payload_hash_failed:'+e['path'])
    artifacts=[]
    for folder,name in [(patch,'EmojiBridge-S0167-menu-original-patch.zip'),(full,'EmojiBridge-S0167-menu-original-trial-full.zip')]:
        archive=OUT/name
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for p in sorted(folder.rglob('*')):
                if p.is_file():z.write(p,p.relative_to(folder).as_posix())
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:raise ValueError('zip_crc_failed')
        artifacts.append(dict(name=name,bytes=archive.stat().st_size,sha256=file_sha(archive)))
        print(json.dumps(artifacts[-1]),flush=True)
    (OUT/'SHA256SUMS.txt').write_text(''.join(a['sha256']+'  '+a['name']+'\n' for a in artifacts),encoding='ascii')
    (OUT/'交付说明.txt').write_text(INSTRUCTIONS,encoding='utf-8-sig')
    (OUT/'verification.json').write_bytes(json_bytes(dict(artifacts=artifacts,payload_files=len(entries),all_payload_sha256_verified=True,all_zip_crc_verified=True,source_commit=commit)))
    print('ALL_PAYLOAD_HASHES_OK',len(entries),flush=True)

if __name__=='__main__':main()
