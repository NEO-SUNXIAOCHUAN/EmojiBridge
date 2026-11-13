"""Explicit local experiment: locate QQ favorites without image templates.

This does not import, send, select individual favorites, scroll or grant source
credentials. It is not enabled by the production UI. Three bounded observations
compare latency and currently loaded cell geometry, not original-file identity.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--open-favorites', action='store_true')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    from uia_structure_probe import targets
    from emoji_bridge.windows import bounds, process_path
    from emoji_bridge.uia_worker import UIAWorker
    choices = []
    for item in targets():
        box = bounds(item['hwnd'])
        if (item['client'].lower() == 'qq.exe' and item['class'] == 'Chrome_WidgetWin_1'
                and box[2] - box[0] >= 600 and box[3] - box[1] >= 500):
            choices.append(item)
    if len(choices) != 1:
        parser.error('QQ main window is not unique and visible; no action performed')
    target = choices[0]
    payload = dict(window=target['hwnd'], pid=target['pid'],
                   exe=str(process_path(target['pid'])))
    worker = UIAWorker(ROOT / 'scripts/qq_favorites_uia_probe.ps1')
    results = []
    try:
        for index in range(3):
            begin = time.perf_counter()
            action = 'open-favorites' if index == 0 and args.open_favorites else 'snapshot'
            result = worker.request(**payload, action=action)
            result['request_seconds'] = round(time.perf_counter() - begin, 4)
            results.append(result)
            if not result.get('ok'):
                break
    finally:
        worker.close()
    report = dict(time=datetime.now().astimezone().isoformat(), target=target,
                  scope='personal_favorite_controls_only',
                  production_adapter_changed=False, results=results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([{key: value for key, value in item.items() if key != 'cells'}
                      for item in results], ensure_ascii=False))


if __name__ == '__main__':
    main()
