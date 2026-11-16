"""Isolated fixtures for source separation, organization and durable recovery."""
from pathlib import Path
import sys,json,tempfile,threading,unittest,zipfile,sqlite3,hashlib,shutil,subprocess,time,os
from unittest.mock import patch
APP=Path(__file__).resolve().parents[1];sys.path[:0]=[str(APP/'src'),str(APP/'scripts')]
from PIL import Image,ImageDraw
from emoji_bridge.materials import MaterialStore
from emoji_bridge.state import save_json,sha

class Workflow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.store=MaterialStore(self.root/'library')
        self.file=self.root/'中文原图.png';Image.new('RGBA',(48,32),(240,60,90,120)).save(self.file)
        self.item,_=self.store.import_file(self.file)
    def tearDown(self):self.temp.cleanup()

    def test_sources_are_separate_and_stable(self):
        from emoji_bridge.collection_view import grouped,mark_duplicates
        item={'id':'entry','source_sha256':self.item['id'],'original_state':'ready','original_available':True,'asset':str(self.file),'preview':str(self.file)}
        lib={'clients':{'qq':{'items':[item,item]},'wechat':{'items':[item]}}}
        rows=grouped(lib);self.assertEqual(len(rows),2);self.assertTrue(all(r['duplicate'] for r in rows))
        ids=[r['id'] for r in rows];lib['clients']['qq']['items'][0]['label']='改名'
        self.assertEqual([r['id'] for r in grouped(lib)],ids)
        local={'id':'local:'+self.item['id'],'clients':['local'],'members':[{'client':'local','source_sha256':self.item['id']} ]}
        self.assertEqual(len(mark_duplicates(rows+[local])),3);self.assertEqual(len(local['duplicate_with']),2)
        self.assertEqual(self.store.search()[1],1)

    def test_tree_migration_relations_and_cycles(self):
        from emoji_bridge.collection_tree import ensure,listing,change
        self.store.organize([self.item['id']],add_collections=['旧合集'],add_tags=['标签'],favorite=True)
        # Simulate a pre-hierarchy schema without touching real libraries.
        with self.store.connect() as c:
            c.execute('DROP TABLE collection_nodes');c.execute('PRAGMA user_version=2')
        self.store=MaterialStore(self.store.root)
        root=listing(self.store)[0];child=ensure(self.store,'同名',root['id']);other=ensure(self.store,'同名')
        self.store.organize([self.item['id']],add_collections=[child['legacy_key']])
        change(self.store,child['id'],name='新名字')
        with self.assertRaises(ValueError):change(self.store,root['id'],parent_id=child['id'])
        change(self.store,child['id'],parent_id=other['id'])
        change(self.store,root['id'],delete=True)
        item=self.store.get(self.item['id']);self.assertTrue(item['favorite']);self.assertEqual(item['tags'],['标签'])
        self.assertIn(child['legacy_key'],item['collections']);self.assertEqual(sha(self.store.original(item['id'])),item['id'])
        self.assertTrue((self.store.root/'materials-before-S0176.db').is_file())

    def test_backup_restore_video_draft_and_corruption(self):
        from emoji_bridge.library_backup import create,restore
        from emoji_bridge.editing import load_static,save_scene,load_scene,EditDocument
        draft=self.store.root/'drafts'/'abc';doc=EditDocument(load_static(self.file));save_scene(doc,draft,'草稿')
        video=self.store.root/'video-sources'/'sample'/'original.mp4';video.parent.mkdir(parents=True);video.write_bytes(b'owned-video-fixture')
        output=self.store.root/'video-output'/'kept.mp4';output.parent.mkdir();output.write_bytes(b'referenced-output')
        (output.parent/'temporary.mp4').write_bytes(b'unreferenced')
        save_json(video.parent/'source.json',{'path':str(video),'sha256':sha(video),'name':'测试视频'})
        with self.store.connect() as c:c.execute('INSERT INTO sources VALUES (?,?,?,?)',(self.item['id'],'edited',json.dumps({'schema':'video-work-v1','source_path':str(video),'output':str(output)}),'now'))
        self.store.organize([self.item['id']],add_collections=['保留合集'],deleted=True)
        save_json(self.store.root/'desktop-ui.json',{'glass':True,'draft_dir':str(draft)})
        archive=self.root/'backup.zip';create(self.store,archive)
        with zipfile.ZipFile(archive) as z:self.assertNotIn('video-output/temporary.mp4',z.namelist())
        restored=self.root/'new'/'material-library'
        rename=os.rename;tries=[]
        def briefly_locked(a,b):
            tries.append(1)
            if len(tries)<3:raise PermissionError('temporary indexer handle')
            return rename(a,b)
        with patch('emoji_bridge.library_backup.os.rename',side_effect=briefly_locked):restore(archive,restored)
        self.assertEqual(len(tries),3)
        new=MaterialStore(restored);self.assertEqual(new.search(view='trash')[1],1)
        self.assertEqual(json.loads((restored/'desktop-ui.json').read_text())['draft_dir'],str(restored/'drafts/abc'))
        self.assertEqual(sha(new.original(self.item['id'])),self.item['id']);load_scene(restored/'drafts/abc')
        self.assertEqual(json.loads((restored/'video-sources/sample/source.json').read_text())['path'],str(restored/'video-sources/sample/original.mp4'))
        values=new.sources(self.item['id']);self.assertTrue(any(str(restored).replace('\\','\\\\') in v['value'] for v in values))
        damaged=self.root/'damaged.zip'
        with zipfile.ZipFile(archive) as z,zipfile.ZipFile(damaged,'w') as out:
            for name in z.namelist():out.writestr(name,b'broken' if name.endswith('original.mp4') else z.read(name))
        before=sha(self.store.db)
        with self.assertRaises(ValueError):restore(damaged,self.root/'bad')
        self.assertFalse((self.root/'bad').exists());self.assertEqual(sha(self.store.db),before)
        missing=self.root/'missing.zip'
        with zipfile.ZipFile(archive) as z,zipfile.ZipFile(missing,'w') as out:
            for name in z.namelist():
                if name!='materials.db':out.writestr(name,z.read(name))
        with self.assertRaises(ValueError):restore(missing,self.root/'missing')

    def test_similar_is_manual_and_excludes_gif(self):
        from emoji_bridge.similar_materials import candidates
        a=Image.new('RGB',(120,120),'white');d=ImageDraw.Draw(a);d.ellipse((20,15,100,100),fill='orange');d.rectangle((40,40,70,70),fill='black')
        a.save(self.root/'a.png');a.resize((90,90)).save(self.root/'b.jpg')
        x,_=self.store.import_file(self.root/'a.png');y,_=self.store.import_file(self.root/'b.jpg')
        a.save(self.root/'c.gif',save_all=True,append_images=[Image.new('RGB',a.size,'red')],duration=100)
        animated,_=self.store.import_file(self.root/'c.gif')
        report=candidates(self.store,[x['id'],y['id'],animated['id']]);self.assertEqual(report['checked'],2)
        self.assertEqual(len(report['pairs']),1);self.assertEqual(self.store.search()[1],4)

    def test_pocket_copy_keeps_visible(self):
        from pocket_service import PocketAPI
        from types import SimpleNamespace as N
        service=N(copy_guard=threading.Lock(),owner=N(drag_files=lambda ids:[str(self.file)],store=self.store),hide=lambda:self.fail('copy must not hide'))
        api=object.__new__(PocketAPI);api._service=service;api._window=N(native=N(Handle=N(ToInt64=lambda:123)))
        with patch('emoji_bridge.file_clipboard.copy_media_to_clipboard',return_value={'copied':True}):
            self.assertTrue(api.copyItem({'id':self.item['id']})['copied'])

    def test_metadata_check_has_no_package_download(self):
        from emoji_bridge.app_update import latest,version
        app=self.root/'app';app.mkdir();save_json(app/'BUILD.json',{'build':'S0175','distribution':'lite'})
        self.assertLess(version('S0168'),version('S0168R2'));self.assertLess(version('S0168R2'),version('S0175'))
        asset={'name':'EmojiBridge-S0176-Windows-x64-lite.zip','bytes':2,'sha256':'a'*64,'url':'https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0176/EmojiBridge-S0176-Windows-x64-lite.zip'}
        urls=[]
        def get(url):
            urls.append(url);return [asset] if url.endswith('release-assets.json') else {'tag_name':'S0176'}
        with patch('emoji_bridge.app_update.read_json',side_effect=get):result=latest(app)
        self.assertTrue(result['available']);self.assertEqual(len(urls),2);self.assertFalse(any(u.endswith('.zip') for u in urls))

    def test_update_archive_validation(self):
        from emoji_bridge.app_update import unpack
        payload=b'new-code';build={'build':'S0176','distribution':'lite','database_schema':3,'files':[{'path':'app.py','size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}]}
        archive=self.root/'app.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('EB/BUILD.json',json.dumps(build));z.writestr('EB/app.py',payload)
        unpack(archive,self.root/'good','S0176','lite')
        with zipfile.ZipFile(self.root/'bad-app.zip','w') as z:z.writestr('EB/BUILD.json',json.dumps(build));z.writestr('EB/app.py',b'BAD-code')
        with self.assertRaises(ValueError):unpack(self.root/'bad-app.zip',self.root/'bad-app','S0176','lite')

    def test_atomic_record_when_unique_temp_exceeds_max_path(self):
        import os
        if os.name!='nt':self.skipTest('Windows MAX_PATH boundary')
        parent=self.root/('a'*60)/('b'*60)
        parent=parent/('c'*(240-len(str(parent))-len('/record.json/') ))
        file=parent/'record.json'
        self.assertGreater(len(str(file))+37,260)
        save_json(file,{'ready':True});save_json(file,{'ready':False})
        self.assertEqual(json.loads(file.read_text()),{'ready':False})

    def test_online_component_download_and_reuse(self):
        import io,os
        from emoji_bridge import release_components as components
        app=self.root/'component-app';app.mkdir();payload=b'model-fixture'
        entries=[{'path':'runtime/model.onnx','size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}]
        archive=self.root/'component.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('component.json',json.dumps({'schema':'emojibridge-component-v1','id':'anime','abi':'fixture','files':entries}))
            z.writestr(entries[0]['path'],payload)
        spec=dict(title='fixture',purpose='test',filename='component.zip',bytes=archive.stat().st_size,unpacked_bytes=len(payload),sha256=sha(archive),files=entries,
                  url='https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/component.zip')
        save_json(app/'RELEASE_COMPONENTS.json',{'schema':'emojibridge-components-v1','abi':'fixture','components':{'anime':spec}})
        with patch.dict(os.environ,{'EMOJI_BRIDGE_COMPONENTS':str(self.root/'components')}):
            with patch('urllib.request.urlopen',return_value=io.BytesIO(b'bad')):
                with self.assertRaises(ValueError):components.download_install('anime',app)
            self.assertIsNone(components.bundle('anime',app))
            with patch('urllib.request.urlopen',return_value=io.BytesIO(archive.read_bytes())) as fetch:
                components.download_install('anime',app);self.assertEqual(fetch.call_count,1)
            self.assertEqual(components.resolve('anime',entries[0]['path'],app).read_bytes(),payload)
            with patch('urllib.request.urlopen',side_effect=AssertionError('already installed')):
                components.download_install('anime',app)

if __name__=='__main__':unittest.main()
