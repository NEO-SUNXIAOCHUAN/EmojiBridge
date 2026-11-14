import hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from desktop_startup import prepare_downloaded_assemblies

@unittest.skipUnless(os.name=='nt','Windows download ADS')
class DownloadMarks(unittest.TestCase):
    def fixture(self,root):
        path=root/'runtime/desktop/pythonnet/runtime/Python.Runtime.dll'
        path.parent.mkdir(parents=True);path.write_bytes(b'fixture managed assembly')
        entry=dict(path=path.relative_to(root).as_posix(),size=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        (root/'BUILD.json').write_text(json.dumps(dict(files=[entry])),'utf8')
        Path(str(path)+':Zone.Identifier').write_text('[ZoneTransfer]\nZoneId=3\n')
        return path
    def test_exact_verified_dll_only_user_file_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=self.fixture(root)
            user=root/'personal.dll';user.write_bytes(b'user data')
            mark=Path(str(user)+':Zone.Identifier');mark.write_text('[ZoneTransfer]\nZoneId=3\n')
            before=path.read_bytes();self.assertEqual(prepare_downloaded_assemblies(root),[path.relative_to(root).as_posix()])
            self.assertEqual(path.read_bytes(),before);self.assertTrue(mark.exists())
            self.assertEqual(prepare_downloaded_assemblies(root),[])
    def test_corrupt_dll_keeps_mark(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=self.fixture(root);path.write_bytes(b'changed')
            Path(str(path)+':Zone.Identifier').write_text('[ZoneTransfer]\nZoneId=3\n')
            with self.assertRaisesRegex(RuntimeError,'校验'):prepare_downloaded_assemblies(root)
            self.assertTrue(Path(str(path)+':Zone.Identifier').exists())
    def test_missing_manifest_keeps_mark(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=self.fixture(root);(root/'BUILD.json').unlink()
            with self.assertRaisesRegex(RuntimeError,'校验'):prepare_downloaded_assemblies(root)
            self.assertTrue(Path(str(path)+':Zone.Identifier').exists())

if __name__=='__main__':unittest.main()
