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
OUT = ROOT/'exports/startup-recovery-S0170'
FILES = PREVIOUS_FILES+['src/emoji_bridge/wechat.py']
OLD_PATCHES = {
    'S0168-original': 'dd3d22ef185d78b464ad1471371cf08b29c06c6e36e7919cb6985fb7020a4bc2',
    'S0168-R2': '686a0af4adacb482d91ec7b384a977cd36f15e69e67674e3b31999305913ae53',
}


def baselines():
    for base, (relative, expected) in BASES.items():
        archive = ROOT/relative
        if file_sha(archive) != expected:
            raise ValueError('baseline_changed:'+base)
        with zipfile.ZipFile(archive) as z:
            old = {p: z.read('EB/'+p) if 'EB/'+p in z.namelist() else None
                   for p in FILES+['BUILD.json', '版本信息.txt']}
            yield base, old
            previous = ROOT/'exports/transfer-recovery-S0169'/('EmojiBridge-S0169-from-'+base+'.zip')
            if file_sha(previous) != OLD_PATCHES[base]:
                raise ValueError('previous_patch_changed')
            with zipfile.ZipFile(previous) as p:
                patched = dict(old)
                manifest = json.loads(p.read('patch-manifest.json'))
                for entry in manifest['files']:
                    data = p.read('payload/'+entry['path'])
                    if digest(data) != entry['sha256']:
                        raise ValueError('previous_payload_changed')
                    patched[entry['path']] = data
            yield 'S0169-from-'+base, patched


def main():
    if OUT.exists() and any(p.is_file() for p in OUT.rglob('*')):
        raise ValueError('fresh_output_directory_required')
    if subprocess.check_output(['git', 'diff', 'HEAD', '--', *FILES], cwd=ROOT):
        raise ValueError('uncommitted_product_files')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    folder = OUT/'EmojiBridge-S0170-startup-recovery'
    folder.mkdir(parents=True, exist_ok=True)
    versions = []
    for name, old in baselines():
        variant = folder/'variants'/name
        changes = {p: (ROOT/p).read_bytes() for p in FILES}
        changes['版本信息.txt'] = ('EmojiBridge S0170 微信启动恢复测试\n产品提交：'+commit+
            '\n原版本：'+name+'\n修复冷启动跳过空控件恢复；外机原因与通过仍待确认。\n').encode('utf-8-sig')
        build = json.loads(old['BUILD.json'])
        entries = {e['path']: e for e in build['files']}
        for p, data in changes.items():
            entries[p] = dict(path=p, size=len(data), sha256=digest(data))
        build.update(build='S0170-startup-recovery-'+name, source_commit=commit,
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
 if($matches.Count -ne 1){throw '未识别为支持的 S0168/S0169 版本，未覆盖文件。请选择实际运行的 EB 文件夹。'}
 $PackageRoot=$matches[0].Root
 $manifest=$matches[0].Manifest
'''
    installer = installer.replace(anchor, anchor+selection)
    installer = installer.replace("Join-Path $PSScriptRoot 'payload'", "Join-Path $PackageRoot 'payload'")
    installer = installer.replace('.S0164-before-visual-test', '.S0170-before-startup-recovery')
    installer = installer.replace('S0163 完整包', 'S0168 或 S0169 完整包')
    installer = installer.replace('EmojiBridge S0164 测试补丁', 'EmojiBridge S0170 启动恢复补丁')
    installer = installer.replace('视觉兼容测试补丁已安装。', 'S0170 启动恢复测试补丁已安装并校验。')
    (folder/'install.ps1').write_text(installer, encoding='utf-8-sig')
    for name, flag in [('安装测试补丁.cmd', ''), ('恢复安装前版本.cmd', ' -Restore')]:
        (folder/name).write_bytes(('@echo off\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0install.ps1"'+flag+'\r\n').encode('ascii'))
    (folder/'LICENSE').write_bytes((ROOT/'LICENSE').read_bytes())
    (folder/'使用说明.txt').write_text('''S0170 微信启动恢复测试补丁（不是独立完整包）
适用：S0168 原完整包、R2，及这两版已正确安装 S0169 的目录；自动识别，不必猜测。
保存作品并退出 EmojiBridge，解压补丁，双击“安装测试补丁.cmd”。
选择实际运行的、包含 EmojiBridge.exe 的 EB 目录。只有提示 S0170 已安装并校验才算完成。
之后从该 EB 目录打开 EmojiBridge.exe，可查看“版本信息.txt”确认 S0170。
需要回退时退出软件，再运行“恢复安装前版本.cmd”，选择同一 EB 目录。

修复首次控件检查过慢跳过标准恢复、无法进入空控件视觉后备的问题。
正常控件仍优先；身份不明、前台变化、多窗口歧义和未知发送不绕过。
包含既有 S0169 草稿恢复和 R2 DLL 启动修复；不重装模型，不删除素材/账号/草稿。
本轮修复经模拟慢启动回归验证；不代表录像电脑根因全部确定，也不是外机通过证明。
进程未找到/多进程、非空但缺少关键角色、实际视觉识别失败仍可能阻断。
登录完成并显示文件传输助手后继续原任务。已提交项先核验，不要手动重复发送。
若仍失败，保留原任务的“查看互通结果”，需要具体失败原因定位下一步。
''', encoding='utf-8-sig')
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
