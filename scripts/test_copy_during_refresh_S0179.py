"""Real cross-process lock regression for local copying during cache refresh."""
import sys,json,hashlib,subprocess,tempfile,os,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'src'),str(R/'scripts')]
from PIL import Image
from emoji_bridge import paths,catalog
from emoji_bridge.state import save_json,single_instance,task_scope
from collection_worker import run

class CopyDuringRefresh(unittest.TestCase):
 def test_available_files_copy_under_scanner_lock_without_catalog_write(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);cache=root/'cache';cache.mkdir();p=cache/'image.png';Image.new('RGBA',(20,25),(15,60,90,100)).save(p);os.utime(p,(1,1))
   choice={'qq_ori':str(cache),'read_authorized':True};identity='\0'.join(str(Path(choice[k]).resolve()).casefold() if choice.get(k) else 'disabled:'+k for k in ('wechat_emoticon_db','qq_ori'));profile=root/hashlib.sha256(identity.encode()).hexdigest()[:24];save_json(profile/'runtime-data/client-sources.json',choice)
   req=dict(profile=str(profile),client='qq',action='refresh',cancel=str(root/'cancel'),status=str(root/'status.json'),request=str(root/'request.json'),ids=[])
   self.assertTrue(run(req)['read_succeeded']);paths.configure_data_root(profile);lib=catalog.read(catalog.PATH);item=lib['clients']['qq']['items'][0]
   lib['clients']['wechat']['items']=[dict(id='wechat:local',managed_original=str(p),source_sha256=item['source_sha256'])];catalog.save(lib);before=Path(catalog.PATH).read_bytes()
   with task_scope('scanner','更新 QQ 收藏'),single_instance(profile/'runtime-data/T005/collection.lock'):
    for client,ident in [('qq',item['id']),('wechat','wechat:local')]:
     request=dict(req,action='copy',client=client,ids=[ident]);save_json(root/'request.json',request)
     if client=='qq':
      old=R/'exports/copy-repeat-S0178/EmojiBridge-S0178-Windows-x64-lite/EB/scripts/collection_worker.py'
      if old.exists():
       subprocess.run([sys.executable,'-X','utf8',str(old),str(root/'request.json')],check=True,timeout=15)
       self.assertTrue(json.loads((root/'status.json').read_text('utf8'))['deferred'])
     subprocess.run([sys.executable,'-X','utf8',str(R/'scripts/collection_worker.py'),str(root/'request.json')],check=True,timeout=15)
     result=json.loads((root/'status.json').read_text('utf8'));self.assertIn('file',result,result);self.assertEqual(hashlib.sha256(Path(result['file']).read_bytes()).hexdigest(),item['source_sha256']);self.assertEqual(Path(catalog.PATH).read_bytes(),before)
    # Missing bytes still fail instead of reporting a successful stale copy.
    p.unlink();save_json(root/'request.json',dict(req,action='copy',ids=[item['id']]))
    subprocess.run([sys.executable,'-X','utf8',str(R/'scripts/collection_worker.py'),str(root/'request.json')],check=True,timeout=15)
    self.assertTrue(json.loads((root/'status.json').read_text('utf8'))['failed']);self.assertEqual(Path(catalog.PATH).read_bytes(),before)

if __name__=='__main__':unittest.main()
