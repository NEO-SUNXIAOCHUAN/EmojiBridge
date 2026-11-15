"""One reversible auto-detected patch for S0168 original/R2, with/without S0169."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_transfer_recovery_S0169 import BASES, FILES as PREVIOUS_FILES, digest, file_sha, jb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'exports/visual-followup-S0173'
from package_draft_speed_S0172 import baselines as previous_baselines, FILES as OLD_FILES
EXTRA = ['src/emoji_bridge/wechat_visual.py', 'src/emoji_bridge/message_media.py']
FILES = OLD_FILES+EXTRA


def baselines():
    archive=ROOT/'exports/draft-speed-S0172/EmojiBridge-S0172-draft-speed.zip'
    if file_sha(archive)!='6b0002b2cd7ff6cb4dea6beb0c5c5b14f8e76514ce0a5f672f61610de45450d5':
        raise ValueError('S0172_patch_changed')
    extras={}
    for base,(path,*_) in BASES.items():
        with zipfile.ZipFile(ROOT/path) as z:
            extras[base]={p:z.read('EB/'+p) for p in EXTRA}
    with zipfile.ZipFile(archive) as prior:
        for name,old in previous_baselines():
            base=next(b for b in BASES if name.endswith(b))
            old=dict(old,**extras[base])
            entries={e['path']:e['sha256'] for e in json.loads(old['BUILD.json'])['files']}
            for p in EXTRA:
                if digest(old[p])!=entries[p]:raise ValueError('baseline_extra_changed')
            yield name,old
            patched=dict(old)
            prefix='variants/'+name+'/'
            manifest=json.loads(prior.read(prefix+'patch-manifest.json'))
            for e in manifest['files']:
                data=prior.read(prefix+'payload/'+e['path'])
                if digest(data)!=e['sha256']:raise ValueError('S0172_payload_changed')
                patched[e['path']]=data
            yield 'S0172-from-'+name,patched


def main():
    if OUT.exists() and any(p.is_file() for p in OUT.rglob('*')):
        raise ValueError('fresh_output_directory_required')
    if subprocess.check_output(['git', 'diff', 'HEAD', '--', *FILES], cwd=ROOT):
        raise ValueError('uncommitted_product_files')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    folder = OUT/'EmojiBridge-S0173-visual-followup'
    folder.mkdir(parents=True, exist_ok=True)
    versions = []
    for name, old in baselines():
        variant = folder/'variants'/name
        changes = {p: (ROOT/p).read_bytes() for p in FILES}
        changes['版本信息.txt'] = ('EmojiBridge S0173 微信输入框与完整图片定位测试\n产品提交：'+commit+
            '\n原版本：'+name+'\n输入框边线与透明/宽图完整定位修复；外机仍待验证。\n').encode('utf-8-sig')
        build = json.loads(old['BUILD.json'])
        entries = {e['path']: e for e in build['files']}
        for p, data in changes.items():
            entries[p] = dict(path=p, size=len(data), sha256=digest(data))
        build.update(build='S0173-visual-followup-'+name, source_commit=commit,
                     external_machine_verified=False, publication_ready=False)
        build['files'] = [entries[k] for k in sorted(entries)]
        changes['BUILD.json'] = jb(build)
        manifest = dict(base=name, product_commit=commit, files=[])
        for p, data in changes.items():
            target = variant/'payload'/p
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest['files'].append(dict(path=p, old_sha256=digest(old[p]) if old[p] is not None else None,
                                         sha256=digest(data)))
        (variant/'patch-manifest.json').write_bytes(jb(manifest))
        versions.append(name)
    installer = (ROOT/'scripts/install_wechat_visual_trial.ps1').read_text('utf-8-sig')
    installer = installer.replace(" $manifest=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'patch-manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json\n", '')
    anchor = " $AppDir=[IO.Path]::GetFullPath($AppDir)"
    selection = '''
 $currentBuild=Digest (ChildPath $AppDir 'BUILD.json')
 $matches=@(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'variants') -Directory | ForEach-Object {
  $m=Get-Content -LiteralPath (Join-Path $_.FullName 'patch-manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json
  $e=@($m.files | Where-Object {$_.path -eq 'BUILD.json'})
  if($e.Count -eq 1 -and $currentBuild -and ($currentBuild -eq $e[0].old_sha256 -or $currentBuild -eq $e[0].sha256)){
   [PSCustomObject]@{Root=$_.FullName;Manifest=$m}
  }
 })
 if($matches.Count -ne 1){throw '未识别为支持的 S0168/S0169/S0170/S0171/S0172 版本，未覆盖文件。请选择实际运行的 EB 文件夹。'}
 $PackageRoot=$matches[0].Root
 $manifest=$matches[0].Manifest
'''
    installer = installer.replace(anchor, anchor+selection)
    installer = installer.replace("Join-Path $PSScriptRoot 'payload'", "Join-Path $PackageRoot 'payload'")
    installer = installer.replace('.S0164-before-visual-test', '.S0173-before-visual-followup')
    installer = installer.replace('S0163 完整包', 'S0168、S0169 或 S0170 目录')
    installer = installer.replace('EmojiBridge S0164 测试补丁', 'EmojiBridge S0173 视觉定位补丁')
    installer = installer.replace('视觉兼容测试补丁已安装。', 'S0173 视觉定位测试补丁已安装并校验。')
    (folder/'install.ps1').write_text(installer, encoding='utf-8-sig')
    for name, flag in [('安装测试补丁.cmd', ''), ('恢复安装前版本.cmd', ' -Restore')]:
        (folder/name).write_bytes(('@echo off\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0install.ps1"'+flag+'\r\n').encode('ascii'))
    (folder/'LICENSE').write_bytes((ROOT/'LICENSE').read_bytes())
    (folder/'使用说明.txt').write_text('S0173 微信输入框与完整图片定位测试补丁（不是完整软件）\n适用 S0168 原包/R2 及其 S0169～S0172 受支持组合，自动识别。\n保存作品并退出 EmojiBridge，解压本补丁，双击“安装测试补丁.cmd”。\n选择实际运行的、包含 EmojiBridge.exe 的 EB 文件夹；提示 S0173 已安装并校验后从该目录启动。\n未知修改会拒绝覆盖。回退时退出软件，运行“恢复安装前版本.cmd”。不要删除旧目录。\n\n本轮修复：图片贴近输入框上沿导致边框识别失败；发送后边框重绘的短暂空档；\n透明留白/分离图案在纯视觉聊天区的完整定位；宽图缩放取整被误排除。\nUIA/MSAA 等控件优先保持，当前步骤控件不可用才用视觉。\n已发送图片只补收藏和核验；不自动重发未知结果，不删除草稿、账号或素材。\n保留 S0172 旧记录隔离、S0171 混合图片、S0170 启动恢复、S0169 恢复与 R2 DLL 修复。\n模型无需重装。本包不改 GitHub、网站或默认素材。\n本机混合六张已测试，详见交付说明；不能据此保证所有机器无故障或与控件同速。\n同学截图提示输入区域未识别，尚缺该机直接截图/任务报告；外机本包仍需复测。\n', encoding='utf-8-sig')

    archive = OUT/(folder.name+'.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(folder.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(folder).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip():
            raise ValueError('archive_crc_failed')
        for name in versions:
            m = json.loads(z.read('variants/'+name+'/patch-manifest.json'))
            for e in m['files']:
                if digest(z.read('variants/'+name+'/payload/'+e['path'])) != e['sha256']:
                    raise ValueError('payload_changed')
    result = dict(name=archive.name, bytes=archive.stat().st_size, sha256=file_sha(archive),
                  source_commit=commit, variants=versions, crc_and_payload_sha_verified=True)
    (OUT/'SHA256SUMS.txt').write_text(result['sha256']+'  '+archive.name+'\n', encoding='ascii')
    (OUT/'verification.json').write_bytes(jb(result))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
