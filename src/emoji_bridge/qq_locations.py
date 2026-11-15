"""Bounded QQ personal-emoji location discovery; never scans chat data."""
from pathlib import Path
import itertools
import os
import re

LAST_DIAGNOSTICS = {}
SAFE_ISSUES = {'config_missing', 'config_unreadable', 'config_path_invalid',
               'data_root_missing', 'location_access_denied', 'emoji_directory_missing',
               'multiple_accounts', 'location_search_limit', 'documents_unavailable'}


def configured_paths(file):
    with Path(file).open('rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('location_search_limit')
    encodings = ('utf-16', 'utf-8-sig', 'utf-16-le', 'gb18030') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else ('utf-8-sig', 'utf-16-le', 'gb18030')
    for encoding in encodings:
        try:
            value = raw.decode(encoding)
        except UnicodeError:
            continue
        matches = re.findall(r'^\s*UserDataSavePath\s*=\s*(.*?)\s*$', value, re.M | re.I)
        if not matches:
            continue
        paths = []
        for item in matches:
            # INI values may be quoted, environment-expanded or slash separated.
            item = os.path.expandvars(item.strip().strip('\x00').strip('"').strip("'"))
            path = Path(item)
            if '\x00' in item or not path.is_absolute() or item.startswith(('\\\\', '//')):
                raise ValueError('config_path_invalid')
            paths.append(path)
        return paths
    raise ValueError('config_path_invalid')


def discover(ini=None, roots=None):
    from . import client_sources as sources
    from .qq_cache import personal_root
    issues = []; hints = []; configured = ''
    def issue(code):
        if code not in issues: issues.append(code)
    if roots is None:
        try:
            hints.extend(configured_paths(ini if ini is not None else sources.qq_configuration()))
            configured = str(hints[0]) if hints else ''
        except FileNotFoundError: issue('config_missing')
        except PermissionError: issue('location_access_denied')
        except OSError: issue('config_unreadable')
        except ValueError as exc: issue(str(exc) if str(exc) in SAFE_ISSUES else 'config_path_invalid')
        if ini is None:
            try: hints.append(sources.known_folder('documents') / 'Tencent Files')
            except (ValueError, OSError): issue('documents_unavailable')
            hints.append(Path.home() / 'Documents/Tencent Files')
            saved = sources.settings()
            for key in ('qq_data_root', 'qq_ori'):
                if saved.get(key): hints.append(Path(saved[key]))
    else:
        hints = [Path(p) for p in roots]
    candidates = {}; checked = set(); accounts = 0; existing = 0
    def inspect(base):
        nonlocal accounts, existing
        key = str(base).casefold()
        if key in checked: return
        checked.add(key)
        try:
            if not base.is_absolute() or not base.is_dir():
                issue('data_root_missing'); return
            existing += 1
            name = base.name.casefold()
            if name == 'ori': probes = [base]
            elif name in ('personal_emoji', 'personal-emoji'): probes = [base / 'Ori']
            else:
                if name == 'nt_qq': emoji = base / 'nt_data/Emoji'
                elif name == 'nt_data': emoji = base / 'Emoji'
                elif name == 'emoji': emoji = base
                elif base.name.isdecimal(): emoji = base / 'nt_qq/nt_data/Emoji'
                else:
                    if (base/'Tencent Files').is_dir():inspect(base/'Tencent Files')
                    # Only immediate numeric account folders, no recursive drive scan.
                    with os.scandir(base) as entries:
                        for number,entry in enumerate(itertools.islice(entries, 513)):
                            if number==512:issue('location_search_limit');break
                            if len(checked) >= 64: issue('location_search_limit'); break
                            if entry.name.isdecimal() and entry.is_dir():
                                accounts += 1
                                if accounts > 20: issue('location_search_limit'); break
                                inspect(Path(entry.path))
                        else: return
                    return
                probes = [emoji / spelling / 'Ori' for spelling in ('personal_emoji', 'personal-emoji')]
            for path in probes:
                if not path.is_dir(): continue
                valid = personal_root(path)
                candidates[str(valid).casefold()] = {'ori': str(valid), 'current_account_binding': 'unproven'}
        except PermissionError: issue('location_access_denied')
        except OSError: issue('location_access_denied')
        except ValueError: issue('emoji_directory_missing')
    for hint in hints[:16]: inspect(hint)
    if len(hints) > 16: issue('location_search_limit')
    if existing and not candidates: issue('emoji_directory_missing')
    if len(candidates) > 1: issue('multiple_accounts')
    diagnostics = {'candidate_count': len(candidates), 'roots_checked': len(checked),
                   'existing_roots': existing, 'issues': issues}
    LAST_DIAGNOSTICS.clear(); LAST_DIAGNOSTICS.update(diagnostics)
    return {'configured_root': configured, 'numeric_roots_inspected': min(accounts, 20),
            'limit_reached': 'location_search_limit' in issues,
            'candidates': list(candidates.values()), 'diagnostics': diagnostics,
            'chat_data_read': False, 'messages_sent': 0}


def describe(info):
    count = info.get('candidate_count', 0)
    if count > 1: return f'QQ 位置：发现 {count} 个账号，请选择本人当前账号；不会自动沿用旧账号。'
    if count == 1: return 'QQ 位置：已找到个人表情目录，请确认本人账号。'
    messages = {'config_missing': '未找到 QQ 路径配置', 'config_unreadable': 'QQ 路径配置无法读取',
                'config_path_invalid': 'QQ 配置中的路径无效', 'data_root_missing': '数据目录不存在',
                'location_access_denied': '部分目录没有读取权限', 'emoji_directory_missing': '个人表情目录尚未找到或尚未生成',
                'location_search_limit': '已达到有限查找范围'}
    reasons = '；'.join(messages[v] for v in info.get('issues', []) if v in messages)
    return 'QQ 位置：' + (reasons or '尚未找到') + '。可选择 QQ 设置里的数据文件夹（Tencent Files、账号或 nt_qq）。'
