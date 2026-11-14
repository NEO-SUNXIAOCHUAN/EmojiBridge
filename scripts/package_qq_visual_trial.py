"""Isolated S0165 friend trial, based on the immutable S0164 R2 full ZIP."""
from pathlib import Path
import json,subprocess,zipfile,shutil
from package_wechat_visual_trial import digest,file_sha,json_bytes

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'exports/wechat-visual-S0164-R2/EmojiBridge-S0164-R2-WeChat-visual-trial-full.zip'
BASE_SHA='36e61f3184213606d7cb0a9fbb8c0f3edb5a431bd20ec6a900a3642305e22884'
OUT=ROOT/'exports/qq-visual-S0165'
FILES=['scripts/client_preflight.py','scripts/qq_accessible.cs','scripts/qq_favorites_uia.ps1',
       'scripts/qq_import.py','scripts/qq_source_ui.py','src/emoji_bridge/qq_controls.py',
       'src/emoji_bridge/qq_visual.py','src/emoji_bridge/client_geometry.py','src/emoji_bridge/paging.py',
       'RELEASE_NOTES.md']

INSTRUCTIONS='''EmojiBridge S0165 QQ 控件与视觉兼容测试（独立测试，非正式更新）

已有 S0164 R2 微信视觉完整测试包：下载小补丁，保存作品并正常退出 EmojiBridge，
运行“安装测试补丁.cmd”，选择原 EB 文件夹。安装核对原文件并保留独立备份。
需要回退时正常退出测试版，运行“恢复原版.cmd”，选择同一文件夹。
不要把补丁用于裸 S0163、S0160 或自行改过程序文件的目录；校验不匹配会拒绝覆盖。
其他版本请下载完整测试包，解压到新文件夹运行 EB/EmojiBridge.exe。
不必卸载旧包；不要同时运行两份程序。原素材、草稿、账号及任务记录保留。

QQ：正常 UIA 优先，其次 MSAA；两套控件都缺少当前步骤能力时才补视觉。
补充“切换我的收藏按钮”分组节点及其分类条祖先，不按第二个图标盲点。
同账号多个已确认聊天窗口可选用一个；最小化窗口恢复后重新核对，旧坐标不用来点击。
识别合并会话与独立会话两种收藏页脚，不依赖任务栏显示与否。
工具栏可用而收藏入口缺失时只补该步骤，不重复打开已出现的面板。
QQ 只添加个人收藏，不向当前联系人发消息。微信沿用 R2 的本人文件传输助手流程。

请先选一张静图、一张 GIF 测试更新和转入，完成后再试同一组，观察有无重复。
保持目标窗口和收藏面板完整可见；遮挡、切换前台、取消或不确定结果会停止。
暂不关闭或清空旧任务；出现待核验请使用“继续/重试未完成”，不要盲目重新发送。

本机真实150%深色已完成纯视觉收藏打开/重开、新 GIF 添加及已有静图核验；
重复两项3.673秒零提交，两种实际窗口尺寸已有结果核验通过。
这里的“控件不可用”由测试注入，截图和 QQ 操作为真实；不等于故障外机已通过。
独立/合并页脚、深浅色、100/125/150布局为合成回归；新增原生分组标签为真实 C# 假节点回归。
100/125实际尝试因前台改变停止，不能算通过；外机实际版本、浅色及完整转入仍需这次反馈。
正式 S0163、四张 Meme 独立素材包与网站未改，不写客户端进程内存。
详细证据与未验证项见交付记录；本包不是“所有电脑、所有版本零问题”的承诺。
'''

def main():
    if file_sha(BASE)!=BASE_SHA:raise ValueError('baseline_archive_changed')
    if OUT.exists():raise ValueError('fresh_output_directory_required')
    # Explicit product files only. Never collect user archives or private logs.
    files=FILES+[p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'assets/qq/visual-anchors').iterdir()) if p.is_file()]
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=subprocess.check_output(['git','diff','HEAD','--',*files],cwd=ROOT)
    if dirty:raise ValueError('uncommitted_product_files')
    OUT.mkdir();full=OUT/'EmojiBridge-S0165-QQ-visual-trial';patch=OUT/'EmojiBridge-S0165-QQ-visual-patch'
    full.mkdir();patch.mkdir()
    with zipfile.ZipFile(BASE) as z:
        z.extractall(full)
    app=full/'EB';build=json.loads((app/'BUILD.json').read_text('utf8'))
    changes={name:(ROOT/name).read_bytes() for name in files}
    changes['QQ视觉兼容测试说明.txt']=INSTRUCTIONS.encode('utf-8-sig')
    changes['版本信息.txt']=('EmojiBridge S0165 QQ 控件与视觉兼容测试\n产品提交：'+commit+'\n基线：S0164 R2 440d5c8\n故障外机仍待验；正式包不变。\n').encode('utf-8-sig')
    old={name:(app/name).read_bytes() if (app/name).is_file() else None for name in changes}
    old['BUILD.json']=(app/'BUILD.json').read_bytes()
    entries={e['path']:e for e in build['files']}
    for name,data in changes.items():
        p=app/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        entries[name]=dict(path=name,size=len(data),sha256=digest(data))
    build.update(build='S0165-QQ-visual-trial',source_commit=commit,source_tree_clean=True,
                 external_machine_verified=False,publication_ready=False,
                 trial=dict(uia_first=True,msaa_second=True,visual_only_for_missing_capability=True,
                            memory_writes=False,base_archive_sha256=BASE_SHA))
    build['files']=[entries[k] for k in sorted(entries)]
    changes['BUILD.json']=json_bytes(build);(app/'BUILD.json').write_bytes(changes['BUILD.json'])
    manifest=dict(base='S0164 R2 440d5c8',product_commit=commit,files=[])
    for name,data in changes.items():
        dest=patch/'payload'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        manifest['files'].append(dict(path=name,sha256=digest(data),old_sha256=digest(old[name]) if old[name] is not None else None))
    (patch/'patch-manifest.json').write_bytes(json_bytes(manifest))
    installer=(ROOT/'scripts/install_wechat_visual_trial.ps1').read_text('utf-8-sig').replace('.S0164-before-visual-test','.S0165-before-qq-visual-test').replace('S0163 完整包','S0164 R2 微信视觉完整测试包')
    (patch/'install.ps1').write_text(installer,encoding='utf-8-sig')
    for name,flag in [('安装测试补丁.cmd',''),('恢复原版.cmd',' -Restore')]:
        (patch/name).write_bytes(('@echo off\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0install.ps1"'+flag+'\r\n').encode('ascii'))
    (patch/'使用说明.txt').write_text(INSTRUCTIONS,encoding='utf-8-sig');shutil.copyfile(app/'LICENSE',patch/'LICENSE')
    for e in build['files']:
        p=app/e['path']
        if p.stat().st_size!=e['size'] or file_sha(p)!=e['sha256']:raise ValueError('payload_hash_failed:'+e['path'])
    artifacts=[]
    for folder,name in [(patch,'EmojiBridge-S0165-QQ-visual-patch.zip'),(full,'EmojiBridge-S0165-QQ-visual-trial-full.zip')]:
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
