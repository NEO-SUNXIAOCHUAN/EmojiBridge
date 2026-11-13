"""Starter scope regression; synthetic optional items, no external media files."""
import json,tempfile,unittest,hashlib
from pathlib import Path
from PIL import Image
from emoji_bridge.materials import MaterialStore
from emoji_bridge import builtin_examples as b
from emoji_bridge.state import save_json

class Upgrade(unittest.TestCase):
    def test_new_and_old_library_do_not_add_optional_items(self):
        with tempfile.TemporaryDirectory(prefix='基础 素材 ') as tmp:
            store=MaterialStore(Path(tmp)/'库')
            self.assertEqual(b.install(store),21)
            before=(store.root/'builtin-examples.json').read_bytes()
            self.assertFalse(b.needs_preparation(store))
            self.assertEqual(b.install(store),0)
            self.assertEqual(store.search()[1],21)
            self.assertEqual(before,(store.root/'builtin-examples.json').read_bytes())
            manifest=json.loads((b.APP_ROOT/'assets/examples/manifest.json').read_text('utf8'))
            self.assertEqual(len(manifest),20)
            self.assertFalse(any(e.get('id','').startswith('starter-meme-20261113-') for e in manifest))

    def test_existing_optional_items_and_retired_receipts_are_preserved(self):
        with tempfile.TemporaryDirectory(prefix='升级 保留 ') as tmp:
            store=MaterialStore(Path(tmp)/'库');b.install(store)
            receipt=json.loads((store.root/'builtin-examples.json').read_text('utf8'))
            items=[]
            for n in range(4):
                p=Path(tmp)/f'用户图{n}.png';Image.new('RGBA',(20+n,23),(n*50,90,80,180)).save(p)
                item,_=store.import_file(p);items.append(item)
                if n<3:receipt['starter-meme-20261113-'+str(n+1)]=item['id']
            save_json(store.root/'builtin-examples.json',receipt)
            store.organize([items[0]['id']],deleted=True)
            items[1]['thumbnail'].unlink()
            self.assertFalse(b.needs_preparation(store))
            self.assertEqual(b.install(store),0)
            self.assertEqual(store.search()[1],24)
            for item in items:self.assertEqual(hashlib.sha256(item['path'].read_bytes()).hexdigest(),item['id'])
            self.assertNotIn(items[0]['id'],store.matching_ids())
            self.assertFalse(items[1]['thumbnail'].exists())
            self.assertEqual(receipt,json.loads((store.root/'builtin-examples.json').read_text('utf8')))

if __name__=='__main__':unittest.main()
