"""Isolated product-flow regression; never opens or sends to QQ/WeChat."""
import hashlib,json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from PIL import Image
from emoji_bridge import cache_listing,paths,catalog
from emoji_bridge.materials import MaterialStore
from emoji_bridge.state import save_json


class CacheWorkflow(unittest.TestCase):
    def test_full_scope_incremental_cancel_and_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache=root/'cache';cache.mkdir()
            samples=[]
            for n in range(12):
                p=root/f'{n}.png';Image.new('RGBA',(8+n,9),(n*19,60,90,255)).save(p);samples.append(p.read_bytes())
            for n in range(1000):
                p=cache/f'旧缓存{n}.dat';p.write_bytes(samples[n%12]);os.utime(p,(1,1))
            (cache/'损坏.gif').write_bytes(b'not media');os.utime(cache/'损坏.gif',(1,1))
            store=MaterialStore(root/'material-library');before=store.search(limit=100)[1]
            index_path=root/'indexes/qq.json';events=[]
            index=cache_listing.scan(cache,index_path,progress=lambda n,t,c:events.append(n),cancel=lambda:len(events)>=81)
            self.assertEqual(index['state'],'cancelled');self.assertEqual(len(events),81)
            ready_before=index['counts']['ready']
            index=cache_listing.scan(cache,index_path)
            self.assertEqual(index['counts']['ready'],1000);self.assertEqual(index['counts']['failed'],1)
            self.assertEqual(index['counts']['unchanged'],ready_before)
            index=cache_listing.scan(cache,index_path)
            self.assertEqual(index['counts']['unchanged'],1000)
            self.assertEqual(store.search(limit=100)[1],before)
            side=cache_listing.catalog_side(index)
            self.assertEqual(len(side['items']),1000)
            selected=side['items'][0];copy=cache_listing.snapshot(selected,root/'copy')
            self.assertEqual(hashlib.sha256(copy.read_bytes()).hexdigest(),selected['source_sha256'])
            self.assertEqual(store.search(limit=100)[1],before)
            # The first selected source may disappear after preparation. The
            # temporary task copy still works and is not a material record.
            Path(selected['cache_file']).unlink()
            with self.assertRaises(OSError):cache_listing.snapshot(selected,root/'copy')
            self.assertTrue(copy.is_file())
            item,duplicate=store.import_file(copy,kind='qq',expected_sha=selected['source_sha256'])
            self.assertFalse(duplicate);self.assertEqual(store.search(limit=100)[1],before+1)
            store.organize([item['id']],add_tags=['保留标签'],add_collections=['我的合集'],favorite=True)
            again,duplicate=store.import_file(copy,kind='qq');self.assertTrue(duplicate)
            self.assertEqual(again['tags'],['保留标签']);self.assertEqual(store.search(limit=100)[1],before+1)
            other=root/'other';other.mkdir();(other/'一张').write_bytes(samples[3]);os.utime(other/'一张',(1,1))
            changed=cache_listing.scan(other,index_path)
            self.assertEqual(changed['counts']['ready'],1);self.assertEqual(len(changed['files']),1)

    def test_worker_read_direct_transfer_then_explicit_import(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache=root/'Ori';cache.mkdir()
            for n in range(6):
                file=cache/f'{n}.unknown';Image.new('RGB',(16+n,12),(20*n,50,80)).save(file,format='PNG');os.utime(file,(1,1))
            choice={'qq_ori':str(cache),'read_authorized':True}
            identity='\0'.join(str(Path(choice[k]).resolve()).casefold() if choice.get(k) else 'disabled:'+k for k in ('wechat_emoticon_db','qq_ori'))
            profile=root/'profiles'/hashlib.sha256(identity.encode()).hexdigest()[:24]
            save_json(profile/'runtime-data/client-sources.json',choice);save_json(root/'last-profile.json',{'profile':profile.name})
            store=MaterialStore(root/'material-library');paths.configure_data_root(profile)
            request=dict(profile=str(profile),store=str(store.root),client='qq',action='refresh',manual=True,
                cancel=str(root/'cancel'),status=str(root/'status.json'),request=str(root/'request.json'),ids=[],plan=str(profile/'runtime-data/T005/import.json'))
            from collection_worker import run
            result=run(request);self.assertTrue(result['read_succeeded']);self.assertEqual(result['count'],6)
            self.assertEqual(store.search(limit=100)[1],0)
            library=catalog.read(catalog.PATH)
            from emoji_bridge.collection_view import grouped
            rows=grouped(library);self.assertEqual(len(rows),6);self.assertTrue(all(r['ready'] for r in rows))
            from collection_transfer import create
            plan_path=store.root/'tasks/test.json'
            create(store,rows,[r['id'] for r in rows],'wechat',profile,plan_path,source_client='qq')
            from material_transfer import run as transfer
            calls=[]
            def target(assets,cancel,**kwargs):
                calls.extend(assets)
                return {'results':{str(Path(a).resolve()):dict(status='desktop_confirmed',collection_verified=True,collection_persisted=True) for a in assets}}
            result=transfer(plan_path,profile,wx_execute=target,preflight=lambda clients:{'ok':True})
            self.assertEqual(len(calls),6,result);self.assertEqual(result['run_state'],'finished',result)
            self.assertEqual(store.search(limit=100)[1],0)
            self.assertTrue(all(j.get('source_file') for j in result['jobs']))
            # Reopening the same task must not call the target again.
            transfer(plan_path,profile,wx_execute=target,preflight=lambda clients:{'ok':True});self.assertEqual(len(calls),6)
            ids=[i['id'] for i in library['clients']['qq']['items'][:2]]
            result=run(dict(request,action='copy',ids=ids[:1]));self.assertTrue(Path(result['file']).is_file())
            self.assertEqual(store.search(limit=100)[1],0)
            run(dict(request,action='import',ids=ids));self.assertEqual(store.search(limit=100)[1],2)
            run(dict(request,action='import',ids=ids));self.assertEqual(store.search(limit=100)[1],2)


if __name__=='__main__':unittest.main()
