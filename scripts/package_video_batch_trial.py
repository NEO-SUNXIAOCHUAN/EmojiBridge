"""Isolated S0168 friend trial, based on the immutable S0167 full ZIP."""
from pathlib import Path
import json,subprocess,zipfile,shutil,hashlib
from package_wechat_visual_trial import digest,file_sha,json_bytes

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'exports/menu-original-S0167/EmojiBridge-S0167-menu-original-trial-full.zip'
BASE_SHA='a3874c73b99175bd9c6c26be34c724bf76f508eb4230d5abff2bbc300fb7d448'
OUT=ROOT/'exports/video-batch-S0168'
FILES=['scripts/editor_drag_card.py','scripts/editor_output.py','scripts/video_tools.py','scripts/wechat_batch.py','src/emoji_bridge/background_remove.py','src/emoji_bridge/wechat_visual.py','src/emoji_bridge/wechat_visual_bridge.py','RELEASE_NOTES.md']

INSTRUCTIONS='EmojiBridge S0168 视频拖出与连续六张测试（独立候选，未公开更新）\n\n已有未改动的 S0167 完整测试包：下载补丁，正常退出旧版后运行“安装测试补丁.cmd”，选择旧 EB 目录。\n其他版本：下载完整包，解压到新文件夹，启动 EB/EmojiBridge.exe。\n二选一即可。不要同时运行新旧两份，不删除个人素材目录。\n补丁严格校验旧文件，保留备份并提供恢复；未知修改不强行覆盖。\n\n视频选段复用编辑器成品卡，图片、文字、留白均可拖。未准备时点击生成，就绪后按住拖到文件夹或聊天输入框。\n改变选段或输出设置立即使旧成品失效；取消/失败可重试。拖入聊天不代表自动发送。\n微信输入框预检查与待发送媒体检查分开；窄绿色光标边缘不再误报草稿；短暂结果提示消失后继续核验，不认作成功。\n控件优先，只有当前步骤控件不可用才用视觉。真实草稿/遮挡/身份歧义和未确定不重发保护保留。\n\n本机150%深色：全新3静3动强制视觉连续发送收藏确认32.406秒，重复8.212秒六项已有、零重发。\n强制视觉是明确测试注入，真实客户端发送/收藏不是模拟；不代表故障同学电脑已经通过。\n首轮曾因短暂提示失效停下，已发送内容仅核验/补收藏，未重发。失败记录保留。\n视频GIF真实拖到Explorer，96帧与修改后的12帧文件SHA一致；三种抠图模型空缓存禁网实际推理通过。\n本轮未新增故障外机、真实浅色及100/125实发、QQ全库/冷原件补齐测试，不宣称所有环境无故障。\n\n本包包括全部三种抠图模型、模板、识字/跟随、FFmpeg及默认tiny字幕。互通仍需QQ/微信登录及网络。\n模型与图片均在本机处理；不写客户端内存。模板与独立演示素材、四张Meme归属保持；用户已有素材不删除。\n请复测原失败六张、改窗口大小和外观后的同任务继续，核对已确认数量及是否重复。\n本地验证范围和SHA见交付目录；正式发布包及网站不自动替换。\n'
OFFLINE_GUIDE='离线功能与模型（S0168）\n\n完整解压后直接运行 EB/EmojiBridge.exe。\nU2-Net、IS-Net Anime、BiRefNet Lite 三种抠图模型均随包提供，选择后点“自动抠主体”即可，无需另外下载。\n模板、识字/跟随、FFmpeg 视频、tiny 字幕转写继续随包离线；QQ/微信互通仍需网络和登录。\n验证后直接读取随包模型，不再额外复制同一权重到用户缓存。已有个人模型缓存和素材不删除。\n模型大小没有通过量化/裁剪降低，效果和内存需求仍取决于模型和输入。\n\n可选字幕 base/small：视频“台词/字幕”选择模型，点“下载并安装所选模型”，完成后点“本地转写”。\n可取消、失败可重试；tiny无需下载。“官方下载页”可查看对应来源。\n需要更换抠图模型文件时：“主体/修正”展开“模型文件”，使用浏览器下载链接，随后“导入所选模型”选择 ONNX 或原配套 ZIP，自动校验安装。\n通常无需这一步。损坏或选错模型不会覆盖已有可用文件。\n'

def main():
    if file_sha(BASE)!=BASE_SHA:raise ValueError('baseline_archive_changed')
    if OUT.exists():raise ValueError('fresh_output_directory_required')
    # Explicit product files only. Never collect user archives or private logs.
    files=FILES
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=subprocess.check_output(['git','diff','HEAD','--',*files],cwd=ROOT)
    if dirty:raise ValueError('uncommitted_product_files')
    OUT.mkdir();full=OUT/'EmojiBridge-S0168-video-batch-trial';patch=OUT/'EmojiBridge-S0168-video-batch-patch'
    full.mkdir();patch.mkdir()
    with zipfile.ZipFile(BASE) as z:
        z.extractall(full)
    app=full/'EB';build=json.loads((app/'BUILD.json').read_text('utf8'))
    changes={name:(ROOT/name).read_bytes() for name in files}
    # Keep the existing U2-Net and offline defaults; add the other exact weights.
    model_specs={'isnet-anime':'6f184e756bb3bd901c8849220a83e38e','birefnet-general-lite':'4fab47adc4ff364be1713e97b7e66334'}
    for name,md5 in model_specs.items():
        model_name='runtime/cutout-models/'+name+'.onnx'
        with zipfile.ZipFile(ROOT/('exports/EmojiBridge-S0155-models-'+name+'.zip')) as z:model=z.read('EB/'+model_name)
        if hashlib.md5(model).hexdigest()!=md5:raise ValueError('model_checksum_failed:'+name)
        changes[model_name]=model
    changes['QQ视觉兼容测试说明.txt']=INSTRUCTIONS.encode('utf-8-sig')
    changes['默认离线功能与模型下载.txt']=OFFLINE_GUIDE.encode('utf-8-sig')
    changes['版本信息.txt']=('EmojiBridge S0168 视频拖出与连续批量测试\n产品提交：'+commit+'\n基线：S0167 b20f907\n故障外机仍待验；正式包不变。\n').encode('utf-8-sig')
    old={name:(app/name).read_bytes() if (app/name).is_file() else None for name in changes}
    old['BUILD.json']=(app/'BUILD.json').read_bytes()
    entries={e['path']:e for e in build['files']}
    for name,data in changes.items():
        p=app/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        entries[name]=dict(path=name,size=len(data),sha256=digest(data))
    build.update(build='S0168-video-batch-trial',source_commit=commit,source_tree_clean=True,
                 external_machine_verified=False,publication_ready=False,
                 trial=dict(uia_first=True,msaa_second=True,visual_only_for_missing_capability=True,
                            memory_writes=False,base_archive_sha256=BASE_SHA))
    build['files']=[entries[k] for k in sorted(entries)]
    changes['BUILD.json']=json_bytes(build);(app/'BUILD.json').write_bytes(changes['BUILD.json'])
    manifest=dict(base='S0167 b20f907',product_commit=commit,files=[])
    for name,data in changes.items():
        dest=patch/'payload'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        manifest['files'].append(dict(path=name,sha256=digest(data),old_sha256=digest(old[name]) if old[name] is not None else None))
    (patch/'patch-manifest.json').write_bytes(json_bytes(manifest))
    installer=(ROOT/'scripts/install_wechat_visual_trial.ps1').read_text('utf-8-sig').replace('.S0164-before-visual-test','.S0168-before-video-batch-test').replace('S0163 完整包','S0167 完整测试包').replace('EmojiBridge S0164 测试补丁','EmojiBridge S0168 测试补丁')
    (patch/'install.ps1').write_text(installer,encoding='utf-8-sig')
    for name,flag in [('安装测试补丁.cmd',''),('恢复原版.cmd',' -Restore')]:
        (patch/name).write_bytes(('@echo off\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0install.ps1"'+flag+'\r\n').encode('ascii'))
    (patch/'使用说明.txt').write_text(INSTRUCTIONS,encoding='utf-8-sig');(patch/'默认离线功能与模型下载.txt').write_text(OFFLINE_GUIDE,encoding='utf-8-sig');shutil.copyfile(app/'LICENSE',patch/'LICENSE')
    for e in build['files']:
        p=app/e['path']
        if p.stat().st_size!=e['size'] or file_sha(p)!=e['sha256']:raise ValueError('payload_hash_failed:'+e['path'])
    artifacts=[]
    for folder,name in [(patch,'EmojiBridge-S0168-video-batch-patch.zip'),(full,'EmojiBridge-S0168-video-batch-trial-full.zip')]:
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
