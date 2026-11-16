"""Service-level regressions with isolated data; no QQ or WeChat input."""
from pathlib import Path
import sys,tempfile,unittest,threading,time,json,os
from types import SimpleNamespace as N
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from PIL import Image
from emoji_bridge.materials import MaterialStore
from emoji_bridge.state import save_json,sha

class Behavior(unittest.TestCase):
    def test_hidden_monitor_discovers_changes_and_resumes_after_cancel(self):
        from collection_service import Collections
        from emoji_bridge.pilot import install_choice
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache=root/'Ori';cache.mkdir();store=MaterialStore(root/'material-library')
            profile=install_choice(root,{'qq_ori':str(cache),'read_authorized':True})
            file=cache/'a.dat';Image.new('RGB',(12,13),'red').save(file,format='PNG');os.utime(file,(1,1))
            service=Collections(store);service.start_monitor()
            def wait(count):
                deadline=time.monotonic()+25
                while time.monotonic()<deadline:
                    try:items=json.loads((profile/'runtime-data/T005/library.json').read_text('utf8'))['clients']['qq']['items']
                    except (OSError,ValueError,KeyError):items=None
                    if items is not None and len(items)==count:return items
                    time.sleep(.1)
                self.fail('background directory snapshot did not settle')
            try:
                first=wait(1);self.assertEqual(store.search()[1],0)
                service.cancel('qq')
                file.unlink();other=cache/'b.dat';Image.new('RGB',(14,17),'blue').save(other,format='PNG');os.utime(other,(1,1))
                with service.guard:service.checked['qq']=0;service.retry['qq']['after']=0
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    items=wait(1)
                    if items[0]['id']!=first[0]['id']:break
                    time.sleep(.1)
                self.assertNotEqual(items[0]['id'],first[0]['id'])
                other.unlink()
                with service.guard:service.checked['qq']=0
                wait(0);self.assertEqual(store.search()[1],0)
            finally:
                service.close();service.monitor.join(3)
                if service.process and service.process.poll() is None:service.process.wait(10)
            self.assertFalse(service.monitor.is_alive())

    def test_folder_hierarchy_duplicates_restore_and_cancel(self):
        from desktop_service import DesktopService
        from emoji_bridge.collection_tree import listing
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'表情';(folder/'反应'/'开心').mkdir(parents=True)
            for n in range(6):Image.new('RGB',(20+n,15),(n*20,30,80)).save(folder/'反应'/'开心'/f'{n}.png')
            (folder/'bad.gif').write_bytes(b'invalid')
            store=MaterialStore(root/'library');service=object.__new__(DesktopService)
            service.store=store;service.cancel=threading.Event();service.task={}
            service.choose_directory=lambda:str(folder);service.start=lambda fn,text:fn()
            result=service.import_folder(True,'',True)
            self.assertEqual(store.search()[1],6);self.assertEqual(len(result['errors']),1)
            nodes=listing(store);self.assertIn('表情 / 反应 / 开心',[n['breadcrumb'] for n in nodes])
            ident=store.search()[0][0]['id'];store.organize([ident],deleted=True,add_tags=['保留'])
            result=service.import_folder(True,'',True)
            self.assertEqual(store.search()[1],6);self.assertEqual(store.get(ident)['tags'],['保留'])
            self.assertEqual(sum(r['state']=='restored' for r in result['import_results']),1)
            service.cancel.set();self.assertIn('已取消',service.import_folder(True,'',False)['text'])
            self.assertEqual(store.search()[1],6)

    def test_unavailable_index_keeps_unknown_but_allows_first_attempt(self):
        import wechat_batch as batch
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fresh=N(prior=None,report={'status':'not_submitted','submission_state':'not_started'})
            unknown=N(prior={'status':'batch_send_pending'},report={'status':'pending_confirmation','submission_state':'may_have_started'})
            with patch('wechat_acquire.current_index',side_effect=OSError('busy')):
                batch.skip_index_members([fresh,unknown],root,root/'cancel',source=root/'wx.db')
            self.assertEqual(fresh.report['status'],'not_submitted');self.assertEqual(fresh.report['membership_check'],'unavailable')
            self.assertEqual(unknown.report['status'],'pending_confirmation')
            with patch('wechat_acquire.current_index',side_effect=InterruptedError('cancel')):
                with self.assertRaises(InterruptedError):batch.skip_index_members([fresh],root,root/'cancel',source=root/'wx.db')

    def test_unknown_receipt_is_shared_across_cache_and_library(self):
        from material_transfer import prior_jobs
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);store=MaterialStore(root/'library');profile=root/'profile';digest='a'*64
            save_json(store.root/'tasks/old.json',{'profile':str(profile),'target':'wechat','jobs':[{'item_id':digest,'status':'pending_confirmation','submission_state':'may_have_started'}]})
            plan={'target':'wechat','jobs':[{'item_id':'source:'+digest,'source_sha256':digest}]}
            found=prior_jobs(store,plan,profile,store.root/'tasks/new.json')
            self.assertEqual(found['source:'+digest]['submission_state'],'may_have_started')

if __name__=='__main__':unittest.main()
