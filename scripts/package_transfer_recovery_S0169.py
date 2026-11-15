"""Small reversible patches for the two immutable S0168 full releases."""
from pathlib import Path
import hashlib,json,subprocess,zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'exports/transfer-recovery-S0169'
FILES=['scripts/bridge_ui.py','scripts/material_transfer.py','scripts/wechat_batch.py',
       'scripts/wechat_retry.py','scripts/desktop_runtime.py','scripts/desktop_startup.py']
BASES={
    'S0168-original':('exports/video-batch-S0168/EmojiBridge-S0168-video-batch-trial-full.zip',
                     '07ce39d5dfc086fd3d4958d9f16cc07ba511f0f483cb7fd7a13b39a41236f7b5'),
    'S0168-R2':('exports/download-ready-S0168/EmojiBridge-S0168-download-ready-trial-full.zip',
               'db36b970e6b1834d0995d5b4c8a8e113185addcf8bc75f48c36d410d1a815472')}

def digest(data):return hashlib.sha256(data).hexdigest()
def file_sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def jb(obj):return json.dumps(obj,ensure_ascii=False,indent=2).encode('utf8')

def main():
    if OUT.exists():raise ValueError('fresh_output_directory_required')
    if subprocess.check_output(['git','diff','HEAD','--',*FILES],cwd=ROOT):raise ValueError('uncommitted_product_files')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    OUT.mkdir();artifacts=[]
    for variant,(relative,expected) in BASES.items():
        base=ROOT/relative
        if file_sha(base)!=expected:raise ValueError('baseline_changed:'+variant)
        folder=OUT/('EmojiBridge-S0169-from-'+variant);folder.mkdir()
        with zipfile.ZipFile(base) as z:
            old_build=z.read('EB/BUILD.json');build=json.loads(old_build)
            changes={p:(ROOT/p).read_bytes() for p in FILES}
            changes['版本信息.txt']=('EmojiBridge S0169 微信旧草稿恢复测试\n产品提交：'+commit+
                '\n基于 '+variant+'。故障外机首次中断原因尚未确定，不代表全部问题已解决。\n').encode('utf-8-sig')
            entries={e['path']:e for e in build['files']}
            for p,data in changes.items():entries[p]=dict(path=p,size=len(data),sha256=digest(data))
            build.update(build='S0169-transfer-recovery-'+variant,source_commit=commit,
                         source_tree_clean=True,external_machine_verified=False,publication_ready=False)
            build['files']=[entries[k] for k in sorted(entries)]
            changes['BUILD.json']=jb(build)
            manifest=dict(base=variant,product_commit=commit,files=[])
            for p,data in changes.items():
                old=z.read('EB/'+p) if 'EB/'+p in z.namelist() else None
                dest=folder/'payload'/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
                manifest['files'].append(dict(path=p,sha256=digest(data),old_sha256=digest(old) if old is not None else None))
            (folder/'LICENSE').write_bytes(z.read('EB/LICENSE'))
        (folder/'patch-manifest.json').write_bytes(jb(manifest))
        installer=(ROOT/'scripts/install_wechat_visual_trial.ps1').read_text('utf-8-sig')
        installer=installer.replace('.S0164-before-visual-test','.S0169-before-recovery')
        installer=installer.replace('S0163 完整包',variant+' 完整包').replace('EmojiBridge S0164 测试补丁','EmojiBridge S0169 恢复测试补丁')
        installer=installer.replace('视觉兼容测试补丁已安装。','旧草稿恢复测试补丁已安装。')
        (folder/'install.ps1').write_text(installer,encoding='utf-8-sig')
        for name,flag in [('安装测试补丁.cmd',''),('恢复原版.cmd',' -Restore')]:
            (folder/name).write_bytes(('@echo off\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0install.ps1"'+flag+'\r\n').encode('ascii'))
        guide=f'''仅适用于 {variant} 完整包；不是独立软件，不适用 S0167 或其他自行修改版本。
1. 保存作品，正常退出目标 EmojiBridge，保留原目录和用户数据。
2. 解压本补丁，双击“安装测试补丁.cmd”，选择原包内有 EmojiBridge.exe 的 EB 文件夹。
3. 正常打开软件，继续原任务。旧草稿已不存在时会询问是否手动发送过。
   只有确实没有手动发送、且已移除旧草稿时才确认；已经发过请选否，避免重复发送。
4. 需要回退时正常退出软件，运行“恢复原版.cmd”，选择同一个 EB 文件夹。

修复：旧记录停在选文件之后、点击发送之前，输入框已空时反复检查同一草稿的问题。
复核未命中不再覆盖最初的具体失败原因。保留控件优先、视觉后备及未知提交不重发。
原 S0168 同时补入已验证的 R2 下载后 DLL 校验启动修复；不改模型、默认素材或用户库。
本机新六张强制视觉38.929秒收藏确认、5.040秒复核零重发；真实空输入框/注入旧记录恢复6.297秒，零发送添加。
故障同学首次中断原因缺少现场详情，仍待该电脑验证；不能称全部兼容问题已解决。
本机原生首次绑定65.656秒，慢启动未解决。本轮未新增浅色/100%/125%实发验证。
'''
        (folder/'使用说明.txt').write_text(guide,encoding='utf-8-sig')
        archive=OUT/(folder.name+'.zip')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for p in sorted(folder.rglob('*')):
                if p.is_file():z.write(p,p.relative_to(folder).as_posix())
        with zipfile.ZipFile(archive) as z:
            if z.testzip():raise ValueError('archive_crc_failed')
            for e in manifest['files']:
                if digest(z.read('payload/'+e['path']))!=e['sha256']:raise ValueError('payload_changed')
        artifacts.append(dict(name=archive.name,bytes=archive.stat().st_size,sha256=file_sha(archive)))
        print(json.dumps(artifacts[-1]),flush=True)
    (OUT/'SHA256SUMS.txt').write_text(''.join(a['sha256']+'  '+a['name']+'\n' for a in artifacts),encoding='ascii')
    (OUT/'verification.json').write_bytes(jb(dict(artifacts=artifacts,source_commit=commit,archive_crc_verified=True,payload_sha_verified=True)))

if __name__=='__main__':main()
