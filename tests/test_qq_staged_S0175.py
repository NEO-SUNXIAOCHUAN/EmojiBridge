"""QQ recovery must retain the same send boundaries as material transfers."""
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.state import save_json
import wechat_batch_workflow as flow
import wechat_retry as retry

class Recovery(unittest.TestCase):
    def scenario(self,root,missing=False,proof=True):
        asset=str(root/'old.json');path=root/'queue.json';lib=root/'library.json'
        old={'item_id':'old','status':'pending_confirmation','submission_state':'may_have_started',
             'target_asset':asset,'reason':'previous-failure','result':'original-report'}
        if missing:old['staged_recovery_requires_confirmation']=True
        save_json(path,{'jobs':[old,{'item_id':'new','status':'queued','submission_state':'not_started'}]})
        save_json(lib,{'clients':{'qq':{'items':[{'id':'new'}]}}})
        prepare=Mock(return_value={'proofs':{},'report':'source','blocked':False})
        target=Mock(return_value={'report_path':'recovered','results':{asset:{'status':'already_exists','collection_verified':True}}})
        with patch.object(flow,'sent_unadded',return_value=False),patch.object(retry,'staged_evidence',return_value=[{}] if proof else None),patch.object(retry,'valid',return_value=False):
            result=flow.run(path,lib,root,resume=True,execute_batch=target,prepare=prepare,preflight=lambda _:{'ok':True})
        return result,target,prepare,asset,path,old

    def test_complete_presend_group_routes_to_live_draft_check(self):
        with tempfile.TemporaryDirectory() as td:
            result,target,prepare,asset,path,old=self.scenario(Path(td))
            target.assert_called_once_with([asset],path.with_suffix('.cancel'),resume_staged=True)
            self.assertEqual(result['jobs'][0]['status'],'already_exists')
            self.assertEqual(result['jobs'][0]['recovery_history'][0]['result'],'original-report')
            prepare.assert_called_once()

    def test_missing_old_draft_is_preserved_while_new_source_can_prepare(self):
        with tempfile.TemporaryDirectory() as td:
            result,target,prepare,asset,path,old=self.scenario(Path(td),missing=True)
            target.assert_not_called();prepare.assert_called_once()
            self.assertEqual(result['jobs'][0],old)
            self.assertEqual(prepare.call_args.args[0],[{'id':'new'}])

    def test_unproven_history_blocks_fresh_tail_without_any_send(self):
        with tempfile.TemporaryDirectory() as td:
            result,target,prepare,*_=self.scenario(Path(td),proof=False)
            target.assert_not_called();prepare.assert_not_called()
            self.assertEqual(result['jobs'][1]['status'],'queued')

if __name__=='__main__':unittest.main()
