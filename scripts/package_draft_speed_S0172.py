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
OUT = ROOT/'exports/draft-speed-S0172'
from package_wechat_speed_S0171 import baselines as previous_baselines, FILES


def baselines():
    archive=ROOT/'exports/wechat-speed-S0171/EmojiBridge-S0171-wechat-speed.zip'
    if file_sha(archive)!='d65e33eb89e6e9017fd6d1dc3c68da5e5afba5949ddb36f09e917ceb2aa46cf1':
        raise ValueError('S0171_patch_changed')
    with zipfile.ZipFile(archive) as prior:
        for name,old in previous_baselines():
            yield name,old
            patched=dict(old)
            prefix='variants/'+name+'/'
            manifest=json.loads(prior.read(prefix+'patch-manifest.json'))
            for e in manifest['files']:
                data=prior.read(prefix+'payload/'+e['path'])
                if digest(data)!=e['sha256']:raise ValueError('S0171_payload_changed')
                patched[e['path']]=data
            yield 'S0171-from-'+name,patched


def main():
    if OUT.exists() and any(p.is_file() for p in OUT.rglob('*')):
        raise ValueError('fresh_output_directory_required')
    if subprocess.check_output(['git', 'diff', 'HEAD', '--', *FILES], cwd=ROOT):
        raise ValueError('uncommitted_product_files')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    folder = OUT/'EmojiBridge-S0172-draft-speed'
    folder.mkdir(parents=True, exist_ok=True)
    versions = []
    for name, old in baselines():
        variant = folder/'variants'/name
        changes = {p: (ROOT/p).read_bytes() for p in FILES}
        changes['版本信息.txt'] = ('EmojiBridge S0172 微信旧记录隔离与识别缓存测试\n产品提交：'+commit+
            '\n原版本：'+name+'\n旧草稿记录不再阻塞尚未提交项，复用相同像素识别；外机仍待验证。\n').encode('utf-8-sig')
        build = json.loads(old['BUILD.json'])
        entries = {e['path']: e for e in build['files']}
        for p, data in changes.items():
            entries[p] = dict(path=p, size=len(data), sha256=digest(data))
        build.update(build='S0172-draft-speed-'+name, source_commit=commit,
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
 if($matches.Count -ne 1){throw '未识别为支持的 S0168/S0169/S0170/S0171 版本，未覆盖文件。请选择实际运行的 EB 文件夹。'}
 $PackageRoot=$matches[0].Root
 $manifest=$matches[0].Manifest
'''
    installer = installer.replace(anchor, anchor+selection)
    installer = installer.replace("Join-Path $PSScriptRoot 'payload'", "Join-Path $PackageRoot 'payload'")
    installer = installer.replace('.S0164-before-visual-test', '.S0172-before-draft-speed')
    installer = installer.replace('S0163 完整包', 'S0168、S0169 或 S0170 目录')
    installer = installer.replace('EmojiBridge S0164 测试补丁', 'EmojiBridge S0172 旧记录隔离补丁')
    installer = installer.replace('视觉兼容测试补丁已安装。', 'S0172 旧记录隔离测试补丁已安装并校验。')
    (folder/'install.ps1').write_text(installer, encoding='utf-8-sig')
    for name, flag in [('安装测试补丁.cmd', ''), ('恢复安装前版本.cmd', ' -Restore')]:
        (folder/name).write_bytes(('@echo off\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0install.ps1"'+flag+'\r\n').encode('ascii'))
    (folder/'LICENSE').write_bytes((ROOT/'LICENSE').read_bytes())
    (folder/'使用说明.txt').write_text('S0172 微信旧记录隔离与识别缓存测试补丁（不是完整软件）\n适用S0168原包/R2，以及其安装S0169、S0170、S0171后的受支持组合，自动识别。\n保存作品并退出EmojiBridge，解压补丁，双击“安装测试补丁.cmd”。\n选择实际运行的、包含EmojiBridge.exe的EB文件夹；提示S0172已安装并校验后从同一目录启动。\n未知修改将拒绝覆盖。回退时退出软件，运行“恢复安装前版本.cmd”。不要删除原软件目录。\n\n已确认不在输入框中的旧草稿记录保留待处理，不再挡住尚未提交的新项。\n新项仍检查本人助手输入框为空；旧项不自动重发、不冒称成功。\n相同像素的菜单标签和小提示在批内复用识别结果，变化后重新识别，控件仍优先。\n保留S0171混合图片、S0170启动恢复、S0169旧草稿恢复和R2 DLL修复。\n模型、账号、草稿和素材不重装或删除。\n本机150%深色新六张强制视觉连续通过；最终约31.85秒，不能承诺与控件一样快。\n此前助手侧栏条目裁切和文件图标悬停背景各触发一次未发送暂停，手动式测试布置后通过；不宣称这两个布局边界已修。\n故障外机及实际浅色/100%/125%仍待验证。\n', encoding='utf-8-sig')

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
