"""Bounded, offline-browser miniPaint trial; not a replacement editor or client test.

Usage: python scripts/minipaint_trial.py --source <pinned checkout> --output <new folder>
The upstream source is obtained separately from the commit in the report. Browser
dependencies stay in the developer runtime; no project runtime dependency is added.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

APP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(APP / 'src'), str(APP / 'scripts')]
from emoji_bridge.materials import MaterialStore
from emoji_bridge.media import sha
from emoji_bridge.state import save_json
from material_transfer import create
from PIL import Image, ImageDraw

UPSTREAM_COMMIT = 'a79733eb803fc97084ef0ee4faa96b031e69e1c0'
UPSTREAM_BUNDLE_SHA256 = 'd084e2659fa7dc1c125663d08e354ccfab3c0cfb78281716ff83b0a6b9283356'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if output.exists():
        raise ValueError('Use a new evidence folder; previous trial results are retained.')
    package = json.loads((source / 'package.json').read_text(encoding='utf-8'))
    if package['version'] != '4.14.3' or not (source / 'MIT-LICENSE.txt').exists():
        raise ValueError('This trial was reviewed for miniPaint 4.14.3 with its MIT notice.')
    bundle_sha = hashlib.sha256((source / 'dist/bundle.js').read_bytes()).hexdigest()
    if bundle_sha != UPSTREAM_BUNDLE_SHA256:
        raise ValueError('Bundle differs from the recorded upstream commit; use the pinned source.')
    output.mkdir(parents=True)
    fixture = output / 'input.png'
    image = Image.new('RGBA', (800, 500), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((60, 150, 330, 420), fill='#36b089')
    draw.rectangle((400, 180, 740, 440), fill=(225, 80, 110, 140))
    image.save(fixture)
    alternate = Image.new('RGBA', image.size, (0, 0, 0, 0))
    ImageDraw.Draw(alternate).ellipse((420, 130, 700, 410), fill='#3468d2')
    gif = output / 'two-frames.gif'
    image.save(gif, save_all=True, append_images=[alternate], duration=[80, 210], loop=2, disposal=2)
    store = MaterialStore(output / 'library')
    original, _ = store.import_file(fixture, name='miniPaint透明样本')
    before_hash = sha(store.original(original['id']))
    env = dict(os.environ)
    runtime_modules = Path(sys.executable).parent.parent / 'node/node_modules'
    env.setdefault('PLAYWRIGHT_MODULE_PATH', str(runtime_modules / 'playwright'))
    node = shutil.which('node') or str(runtime_modules.parent / 'bin/node.exe')
    start = time.perf_counter()
    completed = subprocess.run([node, str(APP / 'tests/probe_minipaint_S0100.cjs'),
        str(source), str(store.original(original['id'])), str(gif), str(output / 'browser')],
        env=env, text=True, encoding='utf-8', capture_output=True, timeout=120)
    (output / 'browser.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
    if completed.returncode:
        raise RuntimeError('miniPaint trial failed; see browser.log')
    draft = output / 'browser/draft.json'
    browser = json.loads((output / 'browser/browser-evidence.json').read_text(encoding='utf-8'))
    with Image.open(output / 'browser/result.png') as result:
        rgba = result.convert('RGBA')
        alpha = rgba.getchannel('A')
        assert rgba.size == image.size and alpha.getextrema() == (0, 255)
        assert alpha.getpixel((500, 300)) == 140
        material, _ = store.save_work(rgba, name='miniPaint静态试接结果', source_ids=[original['id']],
            recipe={'external_editor':'miniPaint', 'version':package['version'],
                    'upstream_commit':UPSTREAM_COMMIT, 'external_draft':str(draft)})
    # Existing library exports are the exact same durable files prepared for DND_Files.
    dragged = store.export([material['id']], store.root / 'drag-out')[0]
    assert sha(dragged) == material['id'] and sha(store.original(original['id'])) == before_hash
    # Build the existing task intents only. Client execution is deliberately absent.
    for target in ('wechat', 'qq'):
        create(store, [material['id']], target, output / f'{target}-intent.json')
    fresh = MaterialStore(store.root)
    assert fresh.get(material['id'])['source_kinds'] == ['edited']
    assert json.loads(draft.read_text(encoding='utf-8'))['layers'][1]['type'] == 'text'
    report = {'upstream_commit':UPSTREAM_COMMIT, 'minipaint_version':package['version'],
        'license':'MIT', 'bundle_sha256':bundle_sha,
        'seconds':round(time.perf_counter()-start,3), 'browser':browser,
        'source_unchanged':True, 'transparent_result':True, 'partial_alpha_preserved':True,
        'saved_to_shared_MaterialStore':True, 'reopened_store':True, 'drag_file_sha_matches':True,
        'existing_target_intents':['qq','wechat'], 'client_execution_count':0,
        'editor_adoption':'Keep current Tk/Pillow engine; static bridge trial only',
        'draft_scope':'miniPaint JSON remains editable in miniPaint; not an EmojiBridge scene.json'}
    save_json(output / 'result.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
