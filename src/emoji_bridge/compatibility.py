"""Candidate families are permission to probe, never proof of compatibility.

Only sanitized capability codes leave this module. No client actions, database
or process-memory reads are performed by startup_report.
"""
import json
import re
import struct
from pathlib import Path
from .paths import APP_ROOT

POLICY=json.loads((APP_ROOT/'assets/client-compat.json').read_text(encoding='utf-8'))
FEATURES=('read_favorites','prepare_originals','send','add_favorites','verify_result')
LAST_REPORTS={}
RUNTIME_CHECKS={}
LABELS={'read_favorites':'读取收藏','prepare_originals':'准备原图','send':'发送',
        'add_favorites':'添加收藏','verify_result':'结果核验'}
REASONS={
    'wechat_visual_open_helper_first':'请先在微信打开文件传输助手，并让左侧该会话可见，再继续未完成项；已提交内容不会重发',
    'wechat_visual_helper_not_confirmed':'尚未确认文件传输助手，请先打开该会话后继续；未向其他联系人发送',
    'wechat_visual_selected_helper_not_confirmed':'请让微信左侧选中的文件传输助手可见，再继续',
    'wechat_visual_helper_icon_unproven':'未能确认内置文件传输助手图标，请打开该会话并保持窗口无遮挡后继续',
    'wechat_visual_composer_unproven':'未能识别微信输入区域，请放大微信窗口并保持无遮挡后继续',
    'wechat_visual_file_button_unproven':'未能唯一识别微信文件按钮，本次未选取文件；请保持窗口完整可见后继续',
    'wechat_visual_send_button_unproven':'未能确认微信发送按钮，输入区内容已保留，本次未点击发送',
    'wechat_visual_empty_draft_conflict':'微信输入区状态不明确，已保留原有内容，请检查后继续',
    'wechat_visual_runtime_missing':'本测试需要完整包中的视觉组件，请使用同目录提供的完整测试包',
    'wechat_visual_chinese_ocr_unavailable':'Windows中文文字识别组件不可用，请检查简体中文语言及文字识别组件是否已安装',
    'wechat_visual_ocr_failed':'本机文字识别未完成，任务已暂停，已提交项不会重发',
    'wechat_visual_ocr_timeout':'本机文字识别超时，任务已暂停，已提交项不会重发',
    'wechat_visual_layout_unsupported':'当前微信界面布局尚未识别，请显示完整聊天主窗口后继续',
    'wechat_visual_action_unsupported':'此操作尚未接入视觉兼容，已保留现有内容',
    'wechat_visual_ocr_geometry_invalid':'文字识别位置不可靠，本次未继续操作，请保持窗口无遮挡后重试',
    'client_family_unadapted':'当前客户端版本尚未适配；更换数据目录不能解决版本适配问题，另一端仍可使用',
    'client_not_detected':'客户端未打开或主窗口不能唯一识别',
    'client_display_scale_changed':'任务期间客户端缩放发生变化，请在窗口稳定后重试；已有结果保留',
    'client_display_scale_unsupported':'当前客户端缩放尚未适配；本版支持100%、125%和150%',
    'client_main_window_missing_or_ambiguous':'未能唯一确认聊天主窗口。请显示客户端主窗口后重试；图片查看器无需关闭',
    'wechat_control_missing':'微信窗口已打开，但所需控件未就绪。未提交项已保留，请待窗口加载后继续；仍失败可运行随包“检查微信控件”',
    'wechat_favorites_check_unavailable':'微信收藏去重检查未完成，本次未继续发送。请更新微信收藏后重试，已完成项会先核验。',
    'controls_not_observed':'当前窗口未呈现所需控件，尚未验证',
    'read_structure_pending':'读取时验证数据库认证/表结构或个人收藏控件',
    'original_validation_pending':'准备时核验完整原图、格式及动画',
    'operation_structure_pending':'执行时核对原生控件、本人会话及结果',
    'favorite_controls_checked':'个人收藏原生控件已识别，未执行添加',
    'local_import_controls_checked':'本地导入入口已识别，文件选择及收藏结果仍待任务检查',
    'send_controls_checked':'本人助手及发送控件已识别，未发送',
    'qq_send_not_used':'QQ使用本地导入，不发送消息',
    'source_location_missing':'未选择此端个人表情位置，其他端可继续',
    'wechat_emoticon_path_needed':'未找到微信表情库，请在设置选择微信数据文件夹',
    'wechat_multiple_emoticon_accounts_select_one':'发现多个微信账号目录，请在设置选择本人当前账号',
    'wechat_location_search_incomplete_select_one':'部分微信位置无法检查，请在设置选择实际数据文件夹',
    'favorite_schema_unsupported':'表情库缺少适配所需的表/字段',
    'favorite_membership_table_unavailable':'未找到个人收藏成员表，不能把其他图片当作收藏',
    'favorite_member_identity_invalid':'收藏中有尚未识别的条目类型，本次读取未完成；请保留诊断记录',
    'favorite_join_not_one_to_one':'收藏条目与原件记录不能唯一对应，本次读取未完成',
    'authenticated_index_checked':'当前进程的表情库页面认证、表结构与快照一致性检查通过',
    'wechat_memory_architecture_unsupported':'微信进程不是此适配器支持的x64架构',
    'target_key_not_found':'所选表情库认证未通过；请先核对当前账号目录，路径正确时仍可能是读取适配问题',
    'key_scan_timeout':'表情库密钥验证超时，未解除数据库保护',
    'page_authentication_failed':'表情数据库页面认证未通过',
    'process_read_access_denied':'系统拒绝读取本人的微信进程',
    'client_version_changed':'任务期间客户端版本发生变化，请重新检测',
    'uia_worker_stopped_no_retry':'原生控件检查未完成，尚未验证',
    'uia_startup_timeout':'窗口控制组件启动超时，尚未执行控件操作；可重试未完成项',
    'uia_helper_exited':'窗口控制组件意外退出；进度已保留，继续时先核验已提交项',
    'uia_response_timeout':'客户端控件响应超时；进度已保留，继续时先核验已提交项',
    'uia_protocol_error':'窗口控制组件返回异常；进度已保留，请重试未完成项',
    'uia_helper_io_error':'窗口控制组件连接中断；进度已保留，继续时先核验已提交项',
    'foreground_handoff_timeout':'客户端窗口恢复超时，任务已暂停；请重试未完成项',
    'foreground_handoff_access_denied':'系统拒绝与当前窗口交接前台，任务已暂停；返回本软件后可继续，已成功项保留',
    'foreground_switch_denied':'Windows未允许激活客户端，任务已暂停；请重试未完成项',
    'target_occluded':'目标控件被其他窗口遮挡，任务已暂停；进度已保留',
    'other':'检查未完成，请反馈客户端版本和失败环节',
}


def failure_text(client,reason):
    if reason=='client_family_unadapted' and client in POLICY:
        policy=POLICY[client]
        family=' / '.join('.'.join(map(str,f)) for f in [policy['family'],*policy.get('candidate_families',[])])
        name='微信' if client=='wechat' else 'QQ'
        return f'当前{name}版本尚未适配，本版适配 {family} 系列；选择数据目录不能解除版本限制，另一端仍可使用。'
    return REASONS.get(reason,reason)


def classify(client,version):
    policy=POLICY[client]
    if not re.fullmatch(r'\d+\.\d+\.\d+\.\d+',version or ''):return 'unsupported'
    if version==policy['tested']:return 'tested'
    families=[policy['family'],*policy.get('candidate_families',[])]
    return 'candidate' if [int(v) for v in version.split('.')[:2]] in families else 'unsupported'


def require_version(client,version):
    from .windows import StopAutomation
    if classify(client,version)=='unsupported':raise StopAutomation('client_family_unadapted')
    return version


def require_memory_architecture(exe):
    # Fixed Config.Cipher pointer layout is x64-only. Even on this architecture
    # every candidate key still needs the exact target salt AND page HMAC.
    with Path(exe).open('rb') as stream:
        header=stream.read(64)
        if len(header)!=64 or header[:2]!=b'MZ':raise ValueError('wechat_memory_architecture_unsupported')
        offset=struct.unpack_from('<I',header,60)[0]
        if not 64<=offset<=1024*1024:raise ValueError('wechat_memory_architecture_unsupported')
        stream.seek(offset);pe=stream.read(6)
    if pe!=b'PE\0\0\x64\x86':raise ValueError('wechat_memory_architecture_unsupported')


def feature(state,reason):return {'state':state,'reason':reason if reason in REASONS else 'other'}


def record_index_check(pid,version,reason=None):
    # Diagnostic only, never consulted to authorize an operation or reuse keys.
    RUNTIME_CHECKS['wechat']={'pid':pid,'version':version,
        'result':feature('unsupported' if reason else 'checked',reason or 'authenticated_index_checked')}


def startup_report(client,version,probe=True):
    family=classify(client,version)
    result={'version':version if re.fullmatch(r'[0-9.]{3,24}',version or '') else 'unknown',
            'version_evidence':family,'adapter':POLICY[client]['adapter'],
            'historically_tested_version':POLICY[client]['tested'],'read_only':True,
            'features':{name:feature('unverified',reason) for name,reason in zip(FEATURES,
                ('read_structure_pending','original_validation_pending','operation_structure_pending',
                 'operation_structure_pending','operation_structure_pending'))}}
    if family=='unsupported':
        result['features']={name:feature('unsupported','client_family_unadapted') for name in FEATURES}
        return result
    if client=='qq':result['features']['send']=feature('not_used','qq_send_not_used')
    runtime=RUNTIME_CHECKS.get(client)
    if runtime and runtime['version']==version:
        from .client_sources import running_client
        try:current_pid,_=running_client(client)
        except (OSError,ValueError):current_pid=None
        if current_pid==runtime['pid']:
            for name in ('read_favorites','verify_result'):result['features'][name]=runtime['result'].copy()
    if not probe:return result
    from .uia_worker import UIAWorker
    from client_preflight import inspect_client
    worker=None
    try:
        check=inspect_client(client);w=check['window']
        if check['client_version']!=version:raise ValueError('client_version_changed')
        from .client_sources import executable
        worker=UIAWorker(APP_ROOT/('scripts/qq_favorites_uia.ps1' if client=='qq' else 'scripts/wechat_uia.ps1'))
        value=worker.request(window=w['hwnd'],pid=w['pid'],exe=str(executable(client)),
                             rect=w['rect'],action='describe' if client=='qq' else 'capabilities',
                             foreground=False,timeout_seconds=8)
        if not value.get('ok'):raise ValueError(value.get('reason','controls_not_observed'))
        if client=='qq':result['controls_backend']=value.get('backend','uia')
        if client=='qq' and value.get('favorites_open'):
            result['features']['read_favorites']=feature('checked','favorite_controls_checked')
            if value.get('import_ready'):result['features']['add_favorites']=feature('checked','local_import_controls_checked')
        if client=='wechat' and value.get('send_ready'):
            result['features']['send']=feature('checked','send_controls_checked')
        result['window_controls_observed']=bool(value.get('toolbar_ready') if client=='qq' else value.get('send_ready'))
    except Exception as exc:
        reason=str(exc) if str(exc) in REASONS else 'controls_not_observed'
        # A UI limitation does not disable WX's independently authenticated DB reader.
        for name in (('read_favorites','add_favorites','verify_result') if client=='qq' else ('send','add_favorites')):
            result['features'][name]=feature('unverified',reason)
    finally:
        if worker:worker.close()
    return result


def describe(report):
    status={'tested':'该版本在开发机曾实测通过','candidate':'同架构候选，搬运待实测','unsupported':'架构未适配'}
    names={'checked':'仅能力检查通过','unverified':'未验证','unsupported':'不支持','not_used':'不使用'}
    lines=[report['version']+' · '+status[report['version_evidence']]]
    for name,value in report['features'].items():
        lines.append(LABELS[name]+'：'+names[value['state']]+'；'+REASONS[value['reason']])
    return '\n'.join(lines)
