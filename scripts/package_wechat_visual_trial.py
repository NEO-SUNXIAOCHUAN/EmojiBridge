"""Build the second isolated trial and a reversible patch for the first trial."""
from pathlib import Path
import hashlib,json,shutil,subprocess,zipfile

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'exports/wechat-visual-S0164/EmojiBridge-S0164-WeChat-visual-trial-full.zip'
BASE_SHA='96c6a71af1fef21a60e08d2ae98a7c203016468f5b795eff84d9983a9d1c329e'
OUT=ROOT/'exports/wechat-visual-S0164-R2'
FILES=['src/emoji_bridge/wechat.py','src/emoji_bridge/wechat_visual.py',
       'src/emoji_bridge/wechat_visual_bridge.py','src/emoji_bridge/compatibility.py',
       'src/emoji_bridge/transfer.py','scripts/wechat_batch.py',
       'scripts/wechat_uia.ps1','scripts/wechat_visual_ocr.ps1']
def digest(data):return hashlib.sha256(data).hexdigest()
def file_sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def json_bytes(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')

def main():
    if file_sha(BASE)!=BASE_SHA:raise ValueError('baseline_archive_changed')
    if OUT.exists():raise ValueError('fresh_output_directory_required')
    OUT.mkdir(parents=True)
    full=OUT/'EmojiBridge-S0164-R2-WeChat-visual-trial'
    patch=OUT/'EmojiBridge-S0164-R2-WeChat-visual-patch'
    patch.mkdir();full.mkdir()
    with zipfile.ZipFile(BASE) as z:
        old={name[3:]:z.read(name) for name in ['EB/BUILD.json','EB/版本信息.txt']}
        for name in FILES+['WECHAT_VISUAL_TRIAL','微信视觉测试说明.txt']:
            old[name]=z.read('EB/'+name) if 'EB/'+name in z.namelist() else None
        z.extractall(full)
    app=full/'EB';build=json.loads(old['BUILD.json'])
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    instructions='''EmojiBridge S0164 R2 微信深浅色与窗口尺寸兼容测试（非正式更新）

已有上一份 S0164 视觉测试完整包（或 S0163 已安装第一份视觉补丁）：使用小补丁包，先保存作品并正常退出 EmojiBridge，
运行“安装测试补丁.cmd”，选择原完整包的 EB 文件夹，然后打开 EmojiBridge.exe。
补丁先核对原文件并备份，只改程序文件；素材、账号、草稿、传输记录不删除。
恢复时同样先正常退出，再运行“恢复原版.cmd”并选择同一 EB 目录，将回到上一份 S0164 视觉测试版。
本补丁不会覆盖第一份补丁的备份。未安装第一份补丁的 S0163 请直接使用本次完整测试包。

没有原完整包：将完整测试 ZIP 解压到新文件夹，打开 EB/EmojiBridge.exe。
请勿把新版覆盖到正在运行的程序目录。

测试：保持微信已登录，使用100%/125%/150%系统缩放。先选一张静图和一张GIF转到微信。
正常机器继续使用原控件。控件经过有界恢复仍为空，才进入视觉兼容。
文件选择框、原件、去重和收藏结果核验复用原流程；视觉只补内部界面定位。
已有助手会话优先直接确认，不翻会话列表。找不到时，仅在空白搜索栏搜索一次文件传输助手，
确认“功能”分组内的内置助手后进入；搜索栏已有内容或结果歧义时停止，保留原内容。
请保持微信完整可见、无遮挡，不在搬运过程中切聊天或输入文字；已有草稿会保留。
若任务显示待核验，点击“继续/重试未完成”核验旧结果，不要创建相同的新任务重发。

本轮本机4.2.0.13/150%强制视觉已验证深浅色助手定位、空白搜索进入助手、静图与GIF发送添加。
窗口尺寸按实际侧栏、输入框、按钮和菜单底板定位；记录包含1100×820及1500×1000像素窗口。
前期测试发现的窄输入框背景、短发送文字和GIF遮挡菜单识别问题已修；中断项沿原消息恢复，未重发。
结果范围和耗时见同目录交付记录；100%/125%视觉布局仅合成测试。
故障同学4.2.0.53自然空树仍待本测试反馈，不能称已全面解决。QQ保留正常UIA/MSAA路径，
本次没有新增QQ全视觉转入，也没有把微信通过当作QQ通过。
不修改客户端进程内存；正式S0163包、独立素材包及网站未替换。
'''
    changes={name:(ROOT/name).read_bytes() for name in FILES}
    changes['WECHAT_VISUAL_TRIAL']=b'S0164 opt-in friend trial; UIA first; no process memory writes.\n'
    changes['微信视觉测试说明.txt']=instructions.encode('utf-8-sig')
    changes['版本信息.txt']=('EmojiBridge S0164 R2 微信视觉兼容测试\n产品提交：'+commit+
                            '\n基线：S0164 dfd9e77；正式S0163不变\n仅独立测试，故障电脑待验。\n').encode('utf-8-sig')
    for name,data in changes.items():
        destination=app/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
    build.update(build='S0164-R2-WeChat-visual-trial',source_commit=commit,source_tree_clean=True,
                 external_machine_verified=False,publication_ready=False,
                 trial={'uia_first':True,'visual_only_after_empty_provider':True,
                        'memory_writes':False,'base_archive_sha256':BASE_SHA})
    entries={entry['path']:entry for entry in build['files']}
    for name,data in changes.items():entries[name]={'path':name,'size':len(data),'sha256':digest(data)}
    build['files']=[entries[key] for key in sorted(entries)]
    changes['BUILD.json']=json_bytes(build);(app/'BUILD.json').write_bytes(changes['BUILD.json'])
    manifest={'base':'S0164 visual trial dfd9e77','product_commit':commit,'files':[]}
    for name,data in changes.items():
        destination=patch/'payload'/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
        previous=old.get(name)
        manifest['files'].append({'path':name,'sha256':digest(data),
                                 'old_sha256':digest(previous) if previous is not None else None})
    (patch/'patch-manifest.json').write_bytes(json_bytes(manifest))
    # Windows PowerShell 5.1 requires BOM for source containing Chinese text.
    installer=(ROOT/'scripts/install_wechat_visual_trial.ps1').read_text('utf-8-sig')
    installer=installer.replace('.S0164-before-visual-test','.S0164-r2-before-visual-test').replace('S0163 完整包','上一份 S0164 视觉测试完整包')
    (patch/'install.ps1').write_text(installer,encoding='utf-8-sig')
    for name,flag in [('安装测试补丁.cmd',''),('恢复原版.cmd',' -Restore')]:
        (patch/name).write_bytes(('@echo off\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" '
          '-NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0install.ps1"'+flag+'\r\n').encode('ascii'))
    (patch/'使用说明.txt').write_text(instructions,encoding='utf-8-sig')
    shutil.copyfile(app/'LICENSE',patch/'LICENSE')
    artifacts=[]
    for folder,name in [(patch,'EmojiBridge-S0164-R2-WeChat-visual-patch.zip'),
                        (full,'EmojiBridge-S0164-R2-WeChat-visual-trial-full.zip')]:
        archive=OUT/name
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for file in sorted(folder.rglob('*')):
                if file.is_file():z.write(file,file.relative_to(folder).as_posix())
        with zipfile.ZipFile(archive) as z:
            bad=z.testzip()
            if bad:raise ValueError('crc_failed: '+bad)
        artifacts.append({'name':name,'bytes':archive.stat().st_size,'sha256':file_sha(archive)})
        print(json.dumps(artifacts[-1]),flush=True)
    # Hash EVERY extracted payload against its manifest, including unmodified files.
    for entry in build['files']:
        file=app/entry['path']
        if file.stat().st_size!=entry['size'] or file_sha(file)!=entry['sha256']:
            raise ValueError('manifest_failed: '+entry['path'])
    (OUT/'SHA256SUMS.txt').write_text(''.join(a['sha256']+'  '+a['name']+'\n' for a in artifacts),encoding='ascii')
    (OUT/'交付说明.txt').write_text(instructions,encoding='utf-8-sig')
    (OUT/'verification.json').write_bytes(json_bytes({'artifacts':artifacts,'payload_files':len(build['files']),
                              'all_payload_sha256_verified':True,'all_zip_crc_verified':True,'source_commit':commit}))
    print('ALL_PAYLOAD_HASHES_OK',len(build['files']),flush=True)

if __name__=='__main__':main()
