"""Opt-in, read-only UIA comparison. Never used by the transfer workflow.

The optional upstream checkout/dependency directory stays in ignored research
storage. Only control types, pattern availability, and counts are collected;
no names, text, values, screenshots, or input operations.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
PIN = 'b74c507d9e709223a0904cf08019edf55f2a75bb'
REPO = ROOT / 'private/T006/research/Windows-MCP-S0049'
DEPS = ROOT / 'private/T006/research/windows-mcp-probe-deps'
MAX_NODES = 600
SECONDS = 8


def upstream_probe(hwnd, pid):
    from emoji_bridge.windows import pid_of
    if pid_of(hwnd) != pid:
        return {'ok': False, 'reason': 'window_identity_changed'}
    # Import just upstream UIA, not the MCP server, telemetry or desktop capture.
    sys.path[:0] = [str(REPO / 'src'), str(DEPS)]
    os.environ['ANONYMIZED_TELEMETRY'] = 'false'
    os.environ['POSTHOG_API_KEY'] = ''
    start = time.perf_counter()
    import windows_mcp.uia as uia
    root = uia.ControlFromHandle(hwnd)
    initialized = time.perf_counter()
    if root is None:
        return {'ok': False, 'reason': 'root_unavailable'}
    pending = deque([(root, 0)])
    types, patterns = Counter(), Counter()
    visited = errors = pruned = 0
    geometry = []
    truncated = False
    while pending:
        if visited >= MAX_NODES or time.perf_counter() - initialized > SECONDS:
            truncated = True
            break
        node, depth = pending.popleft()
        visited += 1
        try:
            kind = int(node.ControlType)
            types[str(kind)] += 1
            if kind in (50000, 50006, 50021, 50030):
                rect = node.BoundingRectangle
                geometry.append({'kind': kind, 'depth': depth,
                                 'rect': [rect.left, rect.top, rect.right, rect.bottom]})
            for label, property_id in (
                ('invoke', uia.PropertyId.IsInvokePatternAvailableProperty),
                ('scroll', uia.PropertyId.IsScrollPatternAvailableProperty),
                ('selection_item', uia.PropertyId.IsSelectionItemPatternAvailableProperty),
            ):
                if node.GetPropertyValue(property_id):
                    patterns[label] += 1
            # No need to traverse individual chat/contact/list items for this probe.
            if kind == 50007 or depth >= 48:
                pruned += 1
                continue
            children = node.GetChildren()
            slots = max(0, MAX_NODES - visited - len(pending))
            if len(children) > slots:
                truncated = True
            pending.extend((child, depth + 1) for child in children[:slots])
        except Exception:
            errors += 1
    return {
        'ok': pid_of(hwnd) == pid, 'backend': 'windows_mcp.uia_only',
        'nodes': visited, 'types': dict(types), 'patterns': dict(patterns),
        'control_geometry': geometry,
        'errors': errors, 'pruned_list_items_or_depth': pruned,
        'truncated': truncated, 'import_and_root_seconds': round(initialized - start, 4),
        'traversal_seconds': round(time.perf_counter() - initialized, 4),
    }


def targets(include_hidden=False):
    from emoji_bridge.windows import (CALLBACK, user, pid_of, process_path,
                                      class_name, bounds)
    result = []
    @CALLBACK
    def visit(hwnd, _):
        pid = pid_of(hwnd)
        exe = process_path(pid)
        if not exe or exe.name.lower() not in ('qq.exe', 'weixin.exe', 'wechat.exe'):
            return True
        visible = bool(user.IsWindowVisible(hwnd))
        rect = bounds(hwnd)
        if rect[2] - rect[0] < 200 or rect[3] - rect[1] < 100:
            return True
        if not visible and not include_hidden:
            return True
        result.append({'hwnd': int(hwnd), 'pid': pid, 'client': exe.name,
                       'class': class_name(hwnd), 'visible': visible,
                       'minimized': bool(user.IsIconic(hwnd)),
                       'foreground': int(user.GetForegroundWindow() or 0) == int(hwnd),
                       'dpi': int(user.GetDpiForWindow(hwnd))})
        return True
    user.EnumWindows(visit, 0)
    return result


def run_child(args):
    begin = time.perf_counter()
    try:
        result = subprocess.run(args, capture_output=True, encoding='utf-8',
                                errors='replace', timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            value = {'ok': False, 'reason': 'probe_child_failed',
                     'exit_code': result.returncode}
        else:
            value = json.loads(result.stdout.lstrip('\ufeff'))
    except subprocess.TimeoutExpired:
        value = {'ok': False, 'reason': 'probe_timeout_own_child_stopped'}
    except (ValueError, OSError):
        value = {'ok': False, 'reason': 'probe_output_unavailable'}
    value['process_seconds'] = round(time.perf_counter() - begin, 4)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--include-hidden', action='store_true')
    parser.add_argument('--worker', type=int)
    parser.add_argument('--pid', type=int)
    args = parser.parse_args()
    if args.worker:
        try:
            value = upstream_probe(args.worker, args.pid)
        except Exception as exc:
            value = {'ok': False, 'reason': 'upstream_probe_failed',
                     'error_type': type(exc).__name__}
        print(json.dumps(value))
        return
    if not args.output:
        parser.error('--output is required')
    head = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'],
                                   text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(REPO), 'status', '--porcelain',
                                     '--untracked-files=no'], text=True).strip()
    if head != PIN or dirty:
        parser.error('upstream checkout must match the reviewed, unmodified pin')
    from emoji_bridge.client_sources import powershell_executable
    results = []
    for target in targets(args.include_hidden):
        item = dict(target)
        item['upstream'] = run_child([sys.executable, '-X', 'utf8', str(Path(__file__)),
                                     '--worker', str(target['hwnd']), '--pid', str(target['pid'])])
        item['dotnet'] = run_child([str(powershell_executable()), '-NoProfile',
                                   '-ExecutionPolicy', 'Bypass', '-File',
                                   str(ROOT / 'scripts/uia_structure_probe.ps1'),
                                   '-WindowHandle', str(target['hwnd']),
                                   '-ClientProcessId', str(target['pid'])])
        results.append(item)
    value = {'time': datetime.now().astimezone().isoformat(), 'upstream_commit': head,
             'python': sys.version.split()[0], 'scope': 'types_patterns_only',
             'full_mcp_server_tested': False, 'sends_adds_deletes': 0,
             'max_nodes': MAX_NODES, 'results': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    main()
