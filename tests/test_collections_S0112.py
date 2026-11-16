import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from emoji_bridge.collection_view import grouped,retain_unseen
from emoji_bridge.pilot import install_choice
from emoji_bridge.materials import MaterialStore
from emoji_bridge.state import save_json
from collection_service import Collections

def item(id,sha='a',key='b',**kw):
    return dict(id=id,source_sha256=sha*64,content_key=key*64,original_state='ready',original_available=True,**kw)

class CollectionsTest(unittest.TestCase):
    def test_full_content_variants_kept_and_history_not_membership(self):
        q=item('q');w=item('w',sha='c');different=item('different',sha='d',key='e')
        lib={'clients':{'qq':{'items':[q,different],'snapshot_at':'old'},'wechat':{'items':[w],'snapshot_at':'new'}}}
        rows=grouped(lib,history={('qq','different'):{'state':'confirmed'}})
        self.assertEqual(len(rows),3)
        shared=[r for r in rows if r['duplicate']]
        self.assertEqual(len(shared),2)
        self.assertTrue(all(len(r['members'])==1 for r in rows))
        other=next(r for r in rows if r['members'][0]['id']=='different')
        self.assertIn('曾添加',other['states']);self.assertNotIn('两端都有',other['states'])
        w['matching_basis']='appearance'
        self.assertEqual(len(grouped(lib)),3)

    def test_partial_unseen_kept_but_not_current_membership(self):
        old={'items':[item('qq:1')],'snapshot_at':'yesterday'}
        now={'items':[item('qq:1',sha='d',key='e')],'snapshot_at':'today'}
        retain_unseen(old,now)
        rows=grouped({'clients':{'qq':now,'wechat':{'items':[item('w')]}}})
        historical=next(r for r in rows if r['historical_only'])
        self.assertNotIn('两端都有',historical['states']);self.assertTrue(historical['members'][0]['unseen'])
        self.assertEqual(historical['members'][0]['read_at'],'yesterday')

    def test_account_switch_discards_active_response_and_qq_hint_is_not_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);store=MaterialStore(base/'material-library');service=Collections(store)
            choice={'wechat_emoticon_db':None,'qq_ori':str(base/'qq')};(base/'qq').mkdir()
            first=install_choice(base,choice);service.context()
            cancel=base/'cancel';status=base/'status.json';save_json(status,{'text':'old result'})
            service.active={'generation':service.generation,'cancel':str(cancel),'status':str(status),'client':'qq','action':'refresh'}
            class Process:
                def poll(self):return 0
            service.process=Process()
            second=install_choice(base,dict(choice,qq_ori=str(base/'other')));service.context();service.settle()
            self.assertTrue(cancel.exists());self.assertNotEqual(first,second);self.assertNotIn('qq',service.states)
            with patch.object(service,'request') as request:
                service.check_changes(choice);request.assert_called_once_with('qq','refresh',manual=False)
            service.close()

if __name__=='__main__':unittest.main()
