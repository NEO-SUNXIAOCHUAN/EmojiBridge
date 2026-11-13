"""Build-time only: licensed Twemoji vectors, rendered by our browser build probe.

The packaged application uses only the finished offline PNG/GIF files.
"""
from pathlib import Path
import json,time,urllib.request

ROOT=Path(__file__).resolve().parents[1]/'assets/examples'
ENTRIES=[('得意猫','1f63c'),('感动','1f979'),('困困','1f634'),('酷脸','1f60e'),('惊讶','1f632'),
         ('融化','1fae0'),('庆祝','1f973'),('幽灵','1f47b'),('青蛙','1f438'),('小猫','1f431'),
         ('敬礼','1fae1'),('倒脸','1f643'),('爆米花','1f37f'),('鼓气','1f624'),('嘘','1f92b'),('小鸭','1f986')]

def fetch(url,path):
    if path.exists():return
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url,timeout=30) as response:path.write_bytes(response.read())
            return
        except OSError:
            if attempt==2:raise
            time.sleep(attempt+1)

if __name__=='__main__':
    ROOT.mkdir(parents=True,exist_ok=True)
    base='https://raw.githubusercontent.com/jdecked/twemoji/v16.0.1/'
    fetch(base+'LICENSE-GRAPHICS',ROOT/'LICENSE-GRAPHICS.txt')
    for name,code in ENTRIES:fetch(base+f'assets/svg/{code}.svg',ROOT/(code+'.svg'))
    (ROOT/'source.json').write_text(json.dumps(ENTRIES,ensure_ascii=False),encoding='utf-8')
    (ROOT/'ATTRIBUTION.txt').write_text('Twemoji v16.0.1 — Copyright Twitter, Inc. and other contributors.\nhttps://github.com/jdecked/twemoji/tree/v16.0.1\nGraphics: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/\nEmojiBridge renders these vectors to transparent PNG and creates motion variants and editable compositions.\n内置示例不是客户端收藏。SVG 原图、署名与许可随包保留。\n',encoding='utf-8')
