import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
from emoji_bridge import qq_locations as qq, release_components as rc
from emoji_bridge.windows import visual_window_rect


class Locations(unittest.TestCase):
    def test_config_formats_and_nested_picker(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'中文 空格/Tencent Files'
            ori=base/'123456789/nt_qq/nt_data/Emoji/personal_emoji/Ori';ori.mkdir(parents=True)
            config=Path(temp)/'QQ.ini'
            for encoding in ('utf-8-sig','utf-16','utf-16-le','gb18030'):
                config.write_bytes(('[General]\nUserDataSavePath = "'+str(base)+'"\n').encode(encoding))
                self.assertEqual(qq.discover(config)['candidates'][0]['ori'],str(ori))
            for folder in (base,base/'123456789',base/'123456789/nt_qq',ori):
                self.assertEqual(len(qq.discover(roots=[folder])['candidates']),1)

    def test_fail_then_create_then_change_no_failure_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            config=Path(temp)/'QQ.ini';base=Path(temp)/'Tencent Files'
            self.assertFalse(qq.discover(config)['candidates'])
            config.write_text('UserDataSavePath='+str(base),'utf-8')
            self.assertIn('data_root_missing',qq.discover(config)['diagnostics']['issues'])
            ori=base/'123/nt_qq/nt_data/Emoji/personal-emoji/Ori';ori.mkdir(parents=True)
            self.assertEqual(len(qq.discover(config)['candidates']),1)
            other=base/'456/nt_qq/nt_data/Emoji/personal_emoji/Ori';other.mkdir(parents=True)
            self.assertIn('multiple_accounts',qq.discover(config)['diagnostics']['issues'])
            config.write_text('UserDataSavePath='+str(base/'123/nt_qq'),'utf-8')
            self.assertEqual(len(qq.discover(config)['candidates']),1)

    def test_qq_disappears_wechat_remains_usable(self):
        from emoji_bridge import pilot
        with patch.object(pilot.compat,'classify',return_value='candidate'),patch.object(pilot.sources,'running_client',side_effect=[(1,Path('C:/Weixin.exe')),ValueError('qq absent')]),patch.object(pilot.sources.win,'file_version',return_value='4.2.0.53'),patch.object(pilot.sources,'emoticon_database',return_value=Path('C:/wx/emoticon.db')):
            result=pilot.validate_choice({'clients':{'wechat':{'exe':str(Path('C:/Weixin.exe')),'version':'4.2.0.53'},'qq':{'exe':'QQ.exe','version':'9.9'}}},'wx','qq')
            self.assertIn('wechat_emoticon_db',result);self.assertEqual(result['disabled_sources']['qq'],'client_not_detected')

    def test_position_all_edges_and_negative_monitor(self):
        for dpi in (96,120,144):
            for area in ((0,0,2560,1400),(-2560,0,0,1400)):
                for x,y in ((area[0],0),(area[2]-1200,0),(area[0],500),(area[2]-1200,500)):
                    r=visual_window_rect((x,y,x+1200,y+900),area,dpi)
                    self.assertGreater(r[0],area[0]);self.assertGreater(r[1],area[1]);self.assertLess(r[2],area[2]);self.assertLess(r[3],area[3])

    def test_denied_config_still_allows_manual_root(self):
        with tempfile.TemporaryDirectory() as temp:
            ori=Path(temp)/'123/nt_qq/nt_data/Emoji/personal_emoji/Ori';ori.mkdir(parents=True)
            with patch.object(qq,'configured_paths',side_effect=PermissionError):
                self.assertIn('location_access_denied',qq.discover(Path(temp)/'config')['diagnostics']['issues'])
            self.assertEqual(len(qq.discover(roots=[temp])['candidates']),1)

    def test_account_limit_is_reported_not_silently_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            for i in range(21):(Path(temp)/str(i)/'nt_qq/nt_data/Emoji/personal_emoji/Ori').mkdir(parents=True)
            report=qq.discover(roots=[temp]);self.assertTrue(report['limit_reached']);self.assertEqual(len(report['candidates']),20)


class Components(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=Path(self.temp.name)/'app';self.app.mkdir();self.home=Path(self.temp.name)/'installed'
        self.env=patch.dict('os.environ',{'EMOJI_BRIDGE_COMPONENTS':str(self.home)});self.env.start();self.addCleanup(self.env.stop)
        self.file=Path(self.temp.name)/'component.zip';self.make()
    def make(self,extra=None,abi='S0174',data=b'model',name='runtime/cutout-models/isnet-anime.onnx'):
        import hashlib
        entry={'path':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        manifest={'schema':'emojibridge-component-v1','id':'anime','abi':abi,'files':[entry]}
        with zipfile.ZipFile(self.file,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr(name,data);z.writestr('component.json',json.dumps(manifest))
            if extra:z.writestr(*extra)
        spec={'files':[entry],'sha256':rc.digest(self.file),'bytes':self.file.stat().st_size,'unpacked_bytes':len(data),'title':'动漫模型','purpose':'抠图','url':'https://example.invalid','filename':'component.zip'}
        (self.app/'RELEASE_COMPONENTS.json').write_text(json.dumps({'schema':'emojibridge-components-v1','abi':'S0174','components':{'anime':spec}}),'utf-8')
    def test_install_repeat_reuse_and_status(self):
        rc.install(self.file,'anime',self.app);path=rc.resolve('anime','runtime/cutout-models/isnet-anime.onnx',self.app)
        self.assertEqual(path.read_bytes(),b'model');self.assertEqual(rc.status(self.app,True)[0]['state'],'installed')
        before=path.stat().st_mtime_ns;rc.install(self.file,'anime',self.app);self.assertEqual(path.stat().st_mtime_ns,before)
        path.write_bytes(b'xxxxx');self.assertEqual(rc.status(self.app,True)[0]['state'],'corrupt')
    def test_cancel_and_disk_full_preserve_old_pointer(self):
        rc.install(self.file,'anime',self.app);pointer=self.home/'anime/current.json';before=pointer.read_bytes()
        cancel=threading.Event();cancel.set()
        with self.assertRaises(InterruptedError):rc.install(self.file,'anime',self.app,cancel)
        with patch.object(rc.shutil,'disk_usage',return_value=type('Space',(),{'free':0})()):
            with self.assertRaises(OSError):rc.install(self.file,'anime',self.app)
        self.assertEqual(pointer.read_bytes(),before)
    def test_corrupt_wrong_version_unexpected_traversal(self):
        self.file.write_bytes(self.file.read_bytes()+b'bad')
        with self.assertRaises(ValueError):rc.install(self.file,'anime',self.app)
        self.make(abi='S0173')
        with self.assertRaises(ValueError):rc.install(self.file,'anime',self.app)
        self.make(extra=('../outside',b'bad'))
        with self.assertRaises(ValueError):rc.install(self.file,'anime',self.app)
        self.make(name='../escape')
        with self.assertRaises(ValueError):rc.install(self.file,'anime',self.app)
        self.assertFalse((Path(self.temp.name)/'escape').exists())
    def test_cancel_during_stream_and_reentry(self):
        self.make(data=b'x'*(3*1024*1024));cancel=threading.Event()
        with self.assertRaises(InterruptedError):rc.install(self.file,'anime',self.app,cancel,lambda *args:cancel.set())
        self.assertFalse((self.home/'anime/current.json').exists())
        with rc.LOCK:
            with self.assertRaises(RuntimeError):rc.install(self.file,'anime',self.app)

    def test_symlink_and_upgrade_keep_existing_component(self):
        import stat
        rc.install(self.file,'anime',self.app);old=rc.resolve('anime','runtime/cutout-models/isnet-anime.onnx',self.app)
        pointer=self.home/'anime/current.json';before=pointer.read_bytes()
        self.make(data=b'new model')
        with patch.object(rc.os,'replace',side_effect=OSError('simulated publication failure')):
            with self.assertRaises(OSError):rc.install(self.file,'anime',self.app)
        self.assertEqual(pointer.read_bytes(),before);self.assertEqual(old.read_bytes(),b'model')
        rc.install(self.file,'anime',self.app);self.assertEqual(old.read_bytes(),b'model')
        self.assertEqual(rc.resolve('anime','runtime/cutout-models/isnet-anime.onnx',self.app).read_bytes(),b'new model')
        self.make();data=json.loads((self.app/'RELEASE_COMPONENTS.json').read_text());spec=data['components']['anime']
        with zipfile.ZipFile(self.file) as z:contents={i.filename:z.read(i) for i in z.infolist()}
        with zipfile.ZipFile(self.file,'w') as z:
            for name,content in contents.items():
                info=zipfile.ZipInfo(name);info.external_attr=((stat.S_IFLNK|0o777)<<16) if name!='component.json' else 0
                z.writestr(info,content)
        spec.update(bytes=self.file.stat().st_size,sha256=rc.digest(self.file));(self.app/'RELEASE_COMPONENTS.json').write_text(json.dumps(data),'utf8')
        with self.assertRaises(ValueError):rc.install(self.file,'anime',self.app)

if __name__=='__main__':unittest.main()
