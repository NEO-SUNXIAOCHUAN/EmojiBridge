"""Isolated S0166 friend trial, based on the immutable S0165 full ZIP."""
from pathlib import Path
import json,subprocess,zipfile,shutil
from package_wechat_visual_trial import digest,file_sha,json_bytes

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'exports/qq-visual-S0165/EmojiBridge-S0165-QQ-visual-trial-full.zip'
BASE_SHA='7e00dc0a23947ea42527dbb54d7bc1b7758748d4c7dddf4fb4ff10812dc157fa'
OUT=ROOT/'exports/batch-compat-S0166'
FILES=['scripts/client_material_import.py', 'scripts/collection_enrich.py', 'scripts/collection_service.py', 'scripts/collection_transfer.py', 'scripts/qq_accessible.cs', 'scripts/qq_appearance_prepare.py', 'scripts/qq_catalog.py', 'scripts/qq_favorites_uia.ps1', 'scripts/qq_offline_index.py', 'scripts/wechat_batch.py', 'scripts/wechat_retry.py', 'src/emoji_bridge/paging.py', 'src/emoji_bridge/snapshot_originals.py', 'src/emoji_bridge/state.py', 'src/emoji_bridge/wechat_visual.py', 'src/emoji_bridge/wechat_visual_bridge.py', 'scripts/qq_selected_prepare.py', 'RELEASE_NOTES.md']

INSTRUCTIONS='EmojiBridge S0166 批量与原件修复测试（独立测试，非正式更新）\n\n完整包：解压到新文件夹，启动 EB/EmojiBridge.exe。请先保存作品并正常退出旧版，不要同时运行两份。\n小补丁：仅适用于未自行改动的 S0165 完整测试包；选择原 EB 目录，校验不匹配会拒绝覆盖。\n补丁保留原程序备份，可用“恢复原版.cmd”回退。其他版本用完整包，不要删除用户素材目录。\n\n控件优先：QQ UIA → MSAA，确实缺少当前步骤能力才用视觉；微信正常控件优先，空树才走视觉。\n微信视觉修正最新消息下沿被裁切导致无法右键；新视觉发送每组两张，原生仍每组五张。\nQQ 补充备用渲染器格子类与实际 DPI 原件匹配；已加载页不等待，空白格子短时有界等候。\n原件按所选条目优先准备，后台补齐为互通让位并在结束后恢复；本地已就绪不会逐张打开 QQ。\n未知提交仍先核验，不盲目重发。本轮按最新反馈聚焦 QQ 更新和 QQ 转微信。\n修复并发保存临时文件竞争；保留取消、账号核对、遮挡和结果不确定时的暂停保护。\n视觉模式的过窄微信窗口会在开始前适当展开以保持助手身份标识；处理中移动窗口应暂停重试。\n\n本轮实测：微信150%深色强制视觉新六张（3静3动）连续37.621秒确认；重复4.982秒零发送添加。\nQQ150%深色强制视觉六张已提交，首次面板核验未完成；随后5.847秒六张均确认已有、零重提。\nQQ后续新增试验曾遇容量已满；用户自行清理后重新取新六张做来源测试。没有由程序删除收藏。\n新六张来源：QQ原生读取两页29项4.786秒，只准备所选六项20.208秒，六份SHA均与原始样本一致。\n使用已有缓存但重新建立所选对应关系5.685秒，六项就绪，其余23项保持未准备。\n这六份QQ原件转微信纯视觉35.471秒全部确认；重复4.933秒全部已有、零重发零添加，未再打开QQ。\n这是真实来源扫描、原件准备和目标发送链路；调度让位另由回归测试验证，非物理界面点击全流程录像。\n正常 QQ UIA 导航5.458秒、微信正常持久控件绑定2.736秒，均未切视觉。\n上述空控件是明确测试注入，客户端动作和结果真实；不是故障同学电脑已通过。\n深浅色/100/125/150几何另有合成回归；本轮真实浅色、100/125及故障外机仍需验证。\n新所选原件补齐通过隔离样本检查，外机慢加载与所有远端原件可取不作保证。\n\n保持目标窗口和收藏面板完整可见。QQ只添加个人收藏，不向联系人发送消息。\nQQ收藏容量已满不能靠软件绕过。待确认任务请“继续/重试未完成”，不要重复创建同一任务。\n正式S0163、独立Meme素材包、网站和用户数据不改；不写客户端内存、不公开更新。\n本包不是“所有电脑零问题”版本，请先测静图/GIF各一张，再测六张和重复运行。\n'

def main():
    if file_sha(BASE)!=BASE_SHA:raise ValueError('baseline_archive_changed')
    if OUT.exists():raise ValueError('fresh_output_directory_required')
    # Explicit product files only. Never collect user archives or private logs.
    files=FILES
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=subprocess.check_output(['git','diff','HEAD','--',*files],cwd=ROOT)
    if dirty:raise ValueError('uncommitted_product_files')
    OUT.mkdir();full=OUT/'EmojiBridge-S0166-batch-compat-trial';patch=OUT/'EmojiBridge-S0166-batch-compat-patch'
    full.mkdir();patch.mkdir()
    with zipfile.ZipFile(BASE) as z:
        z.extractall(full)
    app=full/'EB';build=json.loads((app/'BUILD.json').read_text('utf8'))
    changes={name:(ROOT/name).read_bytes() for name in files}
    changes['QQ视觉兼容测试说明.txt']=INSTRUCTIONS.encode('utf-8-sig')
    changes['版本信息.txt']=('EmojiBridge S0166 批量与原件修复测试\n产品提交：'+commit+'\n基线：S0165 4a8631a\n故障外机仍待验；正式包不变。\n').encode('utf-8-sig')
    old={name:(app/name).read_bytes() if (app/name).is_file() else None for name in changes}
    old['BUILD.json']=(app/'BUILD.json').read_bytes()
    entries={e['path']:e for e in build['files']}
    for name,data in changes.items():
        p=app/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        entries[name]=dict(path=name,size=len(data),sha256=digest(data))
    build.update(build='S0166-batch-compat-trial',source_commit=commit,source_tree_clean=True,
                 external_machine_verified=False,publication_ready=False,
                 trial=dict(uia_first=True,msaa_second=True,visual_only_for_missing_capability=True,
                            memory_writes=False,base_archive_sha256=BASE_SHA))
    build['files']=[entries[k] for k in sorted(entries)]
    changes['BUILD.json']=json_bytes(build);(app/'BUILD.json').write_bytes(changes['BUILD.json'])
    manifest=dict(base='S0165 4a8631a',product_commit=commit,files=[])
    for name,data in changes.items():
        dest=patch/'payload'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        manifest['files'].append(dict(path=name,sha256=digest(data),old_sha256=digest(old[name]) if old[name] is not None else None))
    (patch/'patch-manifest.json').write_bytes(json_bytes(manifest))
    installer=(ROOT/'scripts/install_wechat_visual_trial.ps1').read_text('utf-8-sig').replace('.S0164-before-visual-test','.S0166-before-batch-compat-test').replace('S0163 完整包','S0165 完整测试包')
    (patch/'install.ps1').write_text(installer,encoding='utf-8-sig')
    for name,flag in [('安装测试补丁.cmd',''),('恢复原版.cmd',' -Restore')]:
        (patch/name).write_bytes(('@echo off\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0install.ps1"'+flag+'\r\n').encode('ascii'))
    (patch/'使用说明.txt').write_text(INSTRUCTIONS,encoding='utf-8-sig');shutil.copyfile(app/'LICENSE',patch/'LICENSE')
    for e in build['files']:
        p=app/e['path']
        if p.stat().st_size!=e['size'] or file_sha(p)!=e['sha256']:raise ValueError('payload_hash_failed:'+e['path'])
    artifacts=[]
    for folder,name in [(patch,'EmojiBridge-S0166-batch-compat-patch.zip'),(full,'EmojiBridge-S0166-batch-compat-trial-full.zip')]:
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
