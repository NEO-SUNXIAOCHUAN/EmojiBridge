"""Real Windows process/Job/rename checks using isolated packaged-runtime fixtures."""
from pathlib import Path
import sys,os,tempfile,json,shutil,subprocess,time,unittest
APP=Path(__file__).resolve().parents[1];sys.path[:0]=[str(APP/'src'),str(APP/'scripts')]
from emoji_bridge.state import save_json,sha
from emoji_bridge.app_update import copy_bootstrap

@unittest.skipUnless(os.name=='nt','Windows Job lifecycle')
class WindowsUpdate(unittest.TestCase):
    def case(self,fail=False,saved=True):
        with tempfile.TemporaryDirectory(prefix='eb-update-test-') as temp:
            root=Path(temp);app=root/'EB';stage=root/'session'/'staged';library=root/'data/material-library';library.mkdir(parents=True)
            (library/'sentinel').write_bytes(b'userdata-keep');before=sha(library/'sentinel')
            runtime=Path(sys.executable).parent
            for folder,build in ((app,'S0175'),(stage,'S0176')):
                (folder/'runtime').mkdir(parents=True);(folder/'scripts').mkdir()
                copy_bootstrap(runtime,folder/'runtime')
                save_json(folder/'BUILD.json',{'build':build,'source_commit':build,'database_schema':3,'distribution':'lite'})
            (app/'scripts/desktop_modern.py').write_text("from pathlib import Path\nPath(__file__).parents[1].joinpath('rollback-started').write_text('yes')\n",'utf8')
            newcode="import json,sys,os,time\nfrom pathlib import Path\np=Path(sys.argv[sys.argv.index('--update-session')+1]);v=json.loads(p.read_text('utf8'))\nv['services_ready']=True;v['pid']=os.getpid()\np.with_name('started.json').write_text(json.dumps(v),'utf8')\ntime.sleep(12)\n"
            (stage/'scripts/desktop_modern.py').write_text('raise SystemExit(2)' if fail else newcode,'utf8')
            parent=root/'parent.py'
            parent.write_text("import sys,os,time,json\nfrom pathlib import Path\nsys.path.insert(0,"+repr(str(APP/'src'))+")\nfrom emoji_bridge.instance_job import install\nfrom emoji_bridge.app_update import launch_helper\nfrom emoji_bridge.state import save_json\ninstall()\np,child=launch_helper(Path("+repr(str(app))+"),Path("+repr(str(root/'session'))+"),Path("+repr(str(library))+"),{'build':'S0176','source_commit':'S0176'})\nwhile not Path(p['session']).joinpath('listening.json').exists():time.sleep(.05)\n"+("save_json(Path(p['session'])/'saved-ready.json',{'token':p['token']})\n" if saved else '')+"os._exit(0)\n",'utf8')
            parent_process=subprocess.Popen([sys.executable,'-X','utf8',str(parent)],creationflags=subprocess.CREATE_NO_WINDOW)
            try:parent_process.wait(40)
            except subprocess.TimeoutExpired:
                parent_process.kill();parent_process.wait()
                self.fail((root/'session/helper.log').read_text('utf8',errors='replace'))
            self.assertEqual(parent_process.returncode,0)
            state=root/'session/state.json';deadline=time.monotonic()+30;value={}
            while time.monotonic()<deadline:
                try:value=json.loads(state.read_text('utf8'))
                except (OSError,ValueError):pass
                if value.get('state') in ('complete','rolled_back','cancelled','failed'):break
                time.sleep(.1)
            self.assertEqual(value.get('state'),'cancelled' if not saved else 'rolled_back' if fail else 'complete',value)
            self.assertEqual(sha(library/'sentinel'),before)
            self.assertEqual(json.loads((app/'BUILD.json').read_text())['build'],'S0176' if saved and not fail else 'S0175')
            if saved and not fail:
                info=json.loads((root/'session/started.json').read_text());os.kill(info['pid'],15)
            time.sleep(.5)
    def test_switch_after_saved_exit_survives_job(self):self.case()
    def test_start_failure_rolls_back(self):self.case(fail=True)
    def test_crash_without_ready_does_not_switch(self):self.case(saved=False)

if __name__=='__main__':unittest.main()
