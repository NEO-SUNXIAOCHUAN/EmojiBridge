"""Cheap Ori directory hints; no decoding, UI, chat data or membership claims."""
from datetime import datetime
from pathlib import Path
import time
from emoji_bridge import catalog
from emoji_bridge.qq_cache import personal_root
from emoji_bridge.state import save_json, single_instance

from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
STATE = ROOT / 'private/T006/cache-changes/state.json'


def compare(previous, current):
    if previous is None or previous.get('root') != current['root']:
        return {'state': 'baseline' if previous is None else 'root_changed',
                'added': [], 'changed': [], 'missing': []}
    old, new = previous['files'], current['files']
    return {'state': 'compared', 'added': sorted(new.keys() - old.keys()),
            'changed': sorted(k for k in new.keys() & old.keys() if new[k] != old[k]),
            'missing': sorted(old.keys() - new.keys())}


def check(root=None, state_path=STATE, acknowledge=False,cancel_check=None):
    """Keep unacknowledged hints across restarts; no images or window access.

    Acknowledging directory changes never establishes collection completeness.
    Missing files are cache changes, not evidence of removed favorites.
    """
    started = time.perf_counter()
    if root is None:
        from emoji_bridge.client_sources import qq_personal_root
        root = qq_personal_root()
    root = personal_root(root)
    files = {}
    for p in root.iterdir():
        if cancel_check:cancel_check()
        if p.is_file():
            st = p.stat()
            files[p.name] = [st.st_size, st.st_mtime_ns]
    current = {'root': str(root), 'files': files}
    path = Path(state_path)
    with single_instance(path.with_suffix('.lock')):
        if cancel_check:cancel_check()
        previous = catalog.read(path) if path.exists() else None
        baseline = previous.get('baseline') if previous else None
        diff = compare(baseline, current)
        result = dict(diff, schema='qq-cache-change-hints-v1',
                      checked_at=datetime.now().astimezone().isoformat(), files_seen=len(files),
                      seconds=round(time.perf_counter() - started, 4),
                      membership_proven=False, current_account_binding='unproven',
                      images_decoded=0, native_ui_calls=0, messages_sent=0)
        if baseline is None or acknowledge:
            baseline = current
            result['baseline_acknowledged'] = acknowledge
        save_json(path, {'baseline': baseline, 'last_check': result})
    return result


def label(result):
    state = result.get('state')
    if state == 'baseline':return '缓存变化检测已就绪；缓存不能证明收藏是否增删。'
    if state == 'root_changed':return 'QQ 缓存位置变化；仍显示旧收藏快照，请刷新收藏。'
    changed = sum(len(result.get(k, [])) for k in ('added', 'changed', 'missing'))
    if changed:
        return (f'缓存线索：新增 {len(result["added"])}、变化 {len(result["changed"])}、缺失 {len(result["missing"])}；'
                '请刷新收藏确认，不自动加入列表。')
    return '缓存文件信息未变；取消收藏等变化仍需刷新确认。'
