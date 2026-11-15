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
OUT = ROOT/'exports/wechat-speed-S0171'
from package_startup_recovery_S0170 import baselines as previous_baselines
FILES = PREVIOUS_FILES+['src/emoji_bridge/wechat.py', 'src/emoji_bridge/wechat_visual_bridge.py']


def baselines():
    archive=ROOT/'exports/startup-recovery-S0170/EmojiBridge-S0170-startup-recovery.zip'
    if file_sha(archive)!='ce0fa94652268b2be54a5fbe15ad612da7a39054523dda3ae2f2bab53d3b3918':
        raise ValueError('S0170_patch_changed')
    with zipfile.ZipFile(archive) as prior:
        for name,old in previous_baselines():
            base=name.removeprefix('S0169-from-')
            p='src/emoji_bridge/wechat_visual_bridge.py'
            with zipfile.ZipFile(ROOT/BASES[base][0]) as z:old[p]=z.read('EB/'+p)
            yield name,old
            patched=dict(old)
            prefix='variants/'+name+'/'
            manifest=json.loads(prior.read(prefix+'patch-manifest.json'))
            for e in manifest['files']:
                data=prior.read(prefix+'payload/'+e['path'])
                if digest(data)!=e['sha256']:raise ValueError('S0170_payload_changed')
                patched[e['path']]=data
            yield 'S0170-from-'+name,patched


def main():
    if OUT.exists() and any(p.is_file() for p in OUT.rglob('*')):
        raise ValueError('fresh_output_directory_required')
    if subprocess.check_output(['git', 'diff', 'HEAD', '--', *FILES], cwd=ROOT):
        raise ValueError('uncommitted_product_files')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    folder = OUT/'EmojiBridge-S0171-wechat-speed'
    folder.mkdir(parents=True, exist_ok=True)
    versions = []
    for name, old in baselines():
        variant = folder/'variants'/name
        changes = {p: (ROOT/p).read_bytes() for p in FILES}
        changes['版本信息.txt'] = ('EmojiBridge S0171 微信混合图片与速度测试\n产品提交：'+commit+
            '\n原版本：'+name+'\n修复高低图片并排光标误判，缩短空树后备等待；外机仍待验证。\n').encode('utf-8-sig')
        build = json.loads(old['BUILD.json'])
        entries = {e['path']: e for e in build['files']}
        for p, data in changes.items():
            entries[p] = dict(path=p, size=len(data), sha256=digest(data))
        build.update(build='S0171-wechat-speed-'+name, source_commit=commit,
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
 if($matches.Count -ne 1){throw '未识别为支持的 S0168/S0169/S0170 版本，未覆盖文件。请选择实际运行的 EB 文件夹。'}
 $PackageRoot=$matches[0].Root
 $manifest=$matches[0].Manifest
'''
    installer = installer.replace(anchor, anchor+selection)
    installer = installer.replace("Join-Path $PSScriptRoot 'payload'", "Join-Path $PackageRoot 'payload'")
    installer = installer.replace('.S0164-before-visual-test', '.S0171-before-wechat-speed')
    installer = installer.replace('S0163 完整包', 'S0168、S0169 或 S0170 目录')
    installer = installer.replace('EmojiBridge S0164 测试补丁', 'EmojiBridge S0171 混合图片补丁')
    installer = installer.replace('视觉兼容测试补丁已安装。', 'S0171 混合图片测试补丁已安装并校验。')
    (folder/'install.ps1').write_text(installer, encoding='utf-8-sig')
    for name, flag in [('安装测试补丁.cmd', ''), ('恢复安装前版本.cmd', ' -Restore')]:
        (folder/name).write_bytes(('@echo off\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0install.ps1"'+flag+'\r\n').encode('ascii'))
    (folder/'LICENSE').write_bytes((ROOT/'LICENSE').read_bytes())
    (folder/'使用说明.txt').write_text('S0171 微信混合图片与速度测试补丁（不是完整软件）\n适用 S0168 原完整包、R2，及其安装 S0169 或 S0170 后的目录，自动识别。\n保存作品并退出 EmojiBridge；解压补丁，双击“安装测试补丁.cmd”。\n选择实际运行的、包含 EmojiBridge.exe 的 EB 文件夹。提示 S0171 已安装并校验后，从该目录启动。\n可查看 EB/版本信息.txt 确认 S0171。未知版本/自行修改的文件将拒绝覆盖。\n回退：退出软件，运行“恢复安装前版本.cmd”，选择同一目录。不要删除原软件目录。\n\n修复高低图片并排时，正常插入光标被误判为额外草稿的问题。\n控件优先，标准恢复后仍为空树才转视觉，减少重复空树轮询。\n保留完整媒体/额外草稿检查、已提交先核验和未知不重发。\n包含 S0170 启动恢复、S0169 草稿恢复、R2 DLL 启动修复；模型和用户素材不重装或删除。\n本机150%深色两组新六张分别约33.45秒和30.67秒，全部确认收藏。\n后一组强制主窗口/菜单视觉；两组均为注入路径选择后的真实客户端操作，不是故障外机通过。\n外机、实际浅色及100%/125%仍待验证；不保证全部机器无问题或速度等同控件。\n旧任务请继续原任务；未知发送先核验，不要手动重复发送。\n准备互通时所选原件会保存到素材库，方便重试和编辑，此行为未更改。\n', encoding='utf-8-sig')

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
