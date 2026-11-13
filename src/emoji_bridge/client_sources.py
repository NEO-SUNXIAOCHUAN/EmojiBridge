"""Minimal executable and exact emoticon-path discovery; no chat data reads."""
from pathlib import Path
import ctypes as c
import json
import os
import uuid
from . import paths
from . import windows as win
from .compatibility import POLICY, require_version

VERIFIED = {client:policy['tested'] for client,policy in POLICY.items()}
LOCATION_DIAGNOSTICS = {}


def known_folder(name):
    ids = {'documents':'FDD39AD0-238F-46AF-ADB4-6C85480369C7',
           'public_documents':'ED4824AF-DCE4-45A8-81E2-FC7965083634',
           'local_app_data':'F1B32785-6FBA-4FCF-9D55-7B8E7F157091',
           'roaming_app_data':'3EB685DB-65F9-4CF6-A03A-E3EF65729F3D'}
    guid=(c.c_ubyte*16).from_buffer_copy(uuid.UUID(ids[name]).bytes_le)
    pointer=c.c_void_p()
    shell=c.WinDLL('shell32');ole=c.WinDLL('ole32')
    fn=win.api(shell,'SHGetKnownFolderPath',[c.c_void_p,c.c_uint32,c.c_void_p,c.POINTER(c.c_void_p)],c.c_long)
    free=win.api(ole,'CoTaskMemFree',[c.c_void_p],None)
    try:
        if fn(c.byref(guid),0,None,c.byref(pointer)) or not pointer.value:
            raise ValueError('system_folder_unavailable')
        return Path(c.wstring_at(pointer.value))
    finally:
        if pointer.value:free(pointer)


def powershell_executable():
    buf=c.create_unicode_buffer(32768)
    fn=win.api(win.kernel,'GetSystemDirectoryW',[c.c_wchar_p,c.c_uint],c.c_uint)
    n=fn(buf,len(buf))
    if not 0<n<len(buf):raise ValueError('system_folder_unavailable')
    path=Path(buf.value)/'WindowsPowerShell/v1.0/powershell.exe'
    if not path.is_file():raise ValueError('windows_powershell_missing')
    return path


def settings():
    file=paths.DATA_ROOT/'runtime-data/client-sources.json'
    return json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}


def running_client(client):
    if client=='wechat':return running_wechat()
    found={}
    @win.CALLBACK
    def visit(hwnd,unused):
        if win.class_name(hwnd)!='Chrome_WidgetWin_1':return True
        pid=win.pid_of(hwnd);exe=win.process_path(pid)
        if exe and exe.name.lower()=='qq.exe':found[pid]=exe
        return True
    win.user.EnumWindows(visit,0)
    if len(found)!=1:raise ValueError('qq_process_not_unique_or_not_running')
    return next(iter(found.items()))


def executable(client):
    _,exe=running_client(client)
    configured=settings().get(client+'_exe')
    if configured and Path(configured).resolve()!=exe.resolve():
        raise ValueError('client_installation_changed_open_setup')
    require_version(client,win.file_version(exe))
    return exe


def qq_profile():
    file=paths.APP_ROOT/'assets/qq/9.9.20-dark-96/profile.json'
    config=json.loads(file.read_text(encoding='utf-8'))
    exe=executable('qq');version=require_version('qq',win.file_version(exe))
    config.update(exe=str(exe),profile_dir=str(file.parent),template_version=config['version'],version=version)
    return config


def qq_configuration():
    explicit=settings().get('qq_config')
    return Path(explicit) if explicit else known_folder('public_documents')/'Tencent/QQ/UserDataInfo.ini'


def qq_personal_root():
    from .qq_cache import personal_root
    config=settings()
    if config.get('disabled_sources',{}).get('qq'):raise ValueError(config['disabled_sources']['qq'])
    explicit=config.get('qq_ori')
    if explicit:return personal_root(explicit)
    from qq_cache_probe import discover
    found=discover(qq_configuration())
    if found['limit_reached'] or len(found['candidates'])!=1:
        raise ValueError('personal_cache_root_ambiguous_or_missing')
    return personal_root(found['candidates'][0]['ori'])


def _wechat_registry_locations():
    """Only storage-location values, never enumerate account settings."""
    import winreg
    values=[]
    # Wexin is also used by the Scoop Windows manifest; accept a location only
    # if the exact personal-emoticon layout exists. Never write these keys.
    for name in ('WeChat','Weixin','Wexin'):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Software\\Tencent\\'+name) as key:
                value,kind=winreg.QueryValueEx(key,'FileSavePath')
                if kind in (winreg.REG_SZ,winreg.REG_EXPAND_SZ):values.append(value)
        except OSError:continue
    return values


def _wechat_path_value(value,documents=None):
    if not isinstance(value,str):return None
    value=value.strip('\ufeff\x00 \t\r\n')
    if value.casefold() in ('mydocument','mydocument:'):return documents
    if len(value)>2 and value[0]==value[-1]=='"':value=value[1:-1]
    if not value or any(ch in value for ch in ('\x00','\r','\n')):return None
    value=os.path.expandvars(value)
    path=Path(value)
    # Do not interpret corrupt/binary settings, relative paths or network shares.
    if not path.is_absolute() or path.drive.startswith('\\\\'):return None
    return path


def _wechat_config_location(file,documents=None):
    try:
        with Path(file).open('rb') as stream:data=stream.read(65537)
    except FileNotFoundError:return None
    if not data or len(data)>65536:return None
    encodings=(('utf-16',) if data.startswith((b'\xff\xfe',b'\xfe\xff')) else
               ('utf-16-le',) if b'\x00' in data[:32] else ('utf-8-sig','mbcs'))
    for encoding in encodings:
        try:value=data.decode(encoding)
        except (UnicodeError,LookupError):continue
        path=_wechat_path_value(value,documents)
        if path is not None:return path
    return None


def discover_emoticon_locations(roots=None):
    """Bounded metadata checks under defaults or explicit storage hints.

    Only two known path-only config files are read. No DB contents, drive-wide
    recursion, chat directories or unrelated config files are opened.
    """
    automatic=roots is None;issues=set();hints=[];config_hints=0
    if automatic:
        roots=[Path.home()/'xwechat_files'];documents=None
        try:
            documents=known_folder('documents');roots.append(documents/'xwechat_files')
        except (ValueError,OSError):issues.add('documents_unavailable')
        for value in _wechat_registry_locations():
            path=_wechat_path_value(value,documents)
            if path is not None:hints.append(path)
        try:
            base=known_folder('roaming_app_data')/'Tencent'
            for relative in ('xwechat/config/51a1fffea11325a1e4104c6b3de47af7.ini',
                             'WeChat/All Users/config/3ebffe94.ini'):
                try:path=_wechat_config_location(base/relative,documents)
                except OSError:issues.add('location_config_unreadable');continue
                if path is not None:hints.append(path)
        except (ValueError,OSError):issues.add('location_config_unreadable')
        config_hints=len(set(hints))
        roots+=hints+[p/'xwechat_files' for p in hints if p.name.casefold()!='xwechat_files']
    else:
        roots=[Path(p) for p in roots]
        roots+= [p/'xwechat_files' for p in roots if p.name.casefold()!='xwechat_files']
    found=set();seen=set();existing=0
    for root in roots:
        root=Path(root)
        try:
            canonical=root.resolve()
            if canonical in seen:continue
            seen.add(canonical)
            if not root.is_dir():continue
            existing+=1
            # The folder picker may select storage root, account or db_storage.
            direct=[root/'db_storage/emoticon/emoticon.db',root/'emoticon/emoticon.db']
            if root.name.casefold()=='emoticon':direct.append(root/'emoticon.db')
            local=[p.resolve() for p in direct if p.is_file()]
            found.update(local)
            if local:continue
            with os.scandir(root) as entries:
                for number,entry in enumerate(entries):
                    if number>=512:issues.add('location_search_limit');break
                    try:
                        if not entry.is_dir():continue
                        path=Path(entry.path)/'db_storage/emoticon/emoticon.db'
                        if path.is_file():found.add(path.resolve())
                    except OSError:issues.add('location_access_denied')
        except OSError:issues.add('location_access_denied')
    diagnostics={'candidate_count':len(found),'roots_checked':len(seen),'existing_roots':existing,
                 'configured_hints':config_hints,'issues':sorted(issues),'database_contents_read':False}
    if automatic:LOCATION_DIAGNOSTICS.clear();LOCATION_DIAGNOSTICS.update(diagnostics)
    return {'candidates':sorted(found),'diagnostics':diagnostics}


def emoticon_candidates(roots=None):
    return discover_emoticon_locations(roots)['candidates']


def running_wechat():
    found={};paths={}
    @win.CALLBACK
    def visit(hwnd,unused):
        # Discovery identifies version independently of the exact Qt UI adapter.
        # Operation binding still requires its supported window/control structure.
        kind=win.class_name(hwnd)
        if not (kind.startswith('Qt') or kind=='WeChatMainWndForPC'):return True
        pid=win.pid_of(hwnd)
        if pid not in paths:paths[pid]=win.process_path(pid)
        exe=paths[pid]
        if exe and exe.name.lower() in ('weixin.exe','wechat.exe'):found[pid]=exe
        return True
    win.user.EnumWindows(visit,0)
    if len(found)!=1:raise ValueError('wechat_process_not_unique_or_not_running')
    pid,exe=next(iter(found.items()))
    return pid,exe


def emoticon_database(roots=None,explicit=None):
    disabled=settings().get('disabled_sources',{}).get('wechat')
    if disabled and not explicit:raise ValueError(disabled)
    if explicit:
        path=Path(explicit).resolve()
        if path.name!='emoticon.db' or path.parent.name!='emoticon' or not path.is_file():
            raise ValueError('only_existing_emoticon_database_allowed')
        return path
    # Shallow, fixed application paths only. No recursive drive or chat search.
    locations=discover_emoticon_locations(roots);found=locations['candidates']
    if locations['diagnostics']['issues']:
        raise ValueError('wechat_location_search_incomplete_select_one')
    if not found:raise ValueError('wechat_emoticon_path_needed')
    if len(found)!=1:raise ValueError('wechat_multiple_emoticon_accounts_select_one')
    return next(iter(found))
