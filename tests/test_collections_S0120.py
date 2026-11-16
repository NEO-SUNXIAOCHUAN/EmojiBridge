"""Local files + controlled source snapshots; never sends or operates a client."""
import copy,hashlib,json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from PIL import Image
from emoji_bridge import qq_cache,catalog,paths
from emoji_bridge.state import save_json,sha
from emoji_bridge.collection_view import grouped
from emoji_bridge.collection_discovery import Discovery
from emoji_bridge.materials import MaterialStore
from emoji_bridge.pilot import install_choice
from collection_service import Collections
from material_transfer import recovery_text
import client_material_import as imports


def record(ident,token=None,**kw):
    value=dict(id=ident,label=ident,original_state='discovered',original_available=False,**kw)
    if token:value.update(source_sha256=hashlib.sha256(token.encode()).hexdigest(),original_state='ready',original_available=True)
    return value


class Collections120(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        if os.name=='nt':
            assert self.root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
            self.tmp.name='\\\\?\\'+str(self.root.resolve())

    def test_long_managed_preview_path_and_original_bytes(self):
        ori=self.root/'nt_data/Emoji/personal_emoji/Ori';ori.mkdir(parents=True)
        for fmt in ('PNG','JPEG','GIF'):
            file=self.root/('input.'+fmt);a=Image.new('RGB',(36,29),'red');b=Image.new('RGB',(36,29),'blue')
            a.save(file,format=fmt,**({'save_all':True,'append_images':[b],'duration':[80,170],'loop':0} if fmt=='GIF' else {}))
            source=ori/(hashlib.md5(file.read_bytes()).hexdigest()+'.jpg');source.write_bytes(file.read_bytes())
        output=self.root/('中文有空格 '*10)/('long '*15)/('result '*8)
        result=qq_cache.inventory(ori,output)
        self.assertFalse(result['failures']);self.assertEqual(len(result['items']),3)
        for item in result['items']:
            self.assertGreater(len(item['preview']),260)
            with Image.open(item['preview']) as image:self.assertLessEqual(max(image.size),96)
            copied=qq_cache.copied_original(ori,item,self.root/'copies')
            self.assertEqual(sha(copied['file']),sha(ori/item['name']))
        self.assertGreaterEqual(qq_cache.INVENTORY_VERSION,3)

    def test_real_source_records_not_repeated_reads_and_stable_content_card(self):
        q=record('q1','same');w=record('w1','same')
        library={'clients':{'qq':{'items':[q]},'wechat':{'items':[]}}}
        ident=grouped(library)[0]['id']
        library['clients']['wechat']['items']=[w,w,copy.deepcopy(w)]
        library['clients']['qq']['items']+=[record('q2','same'),q]
        row=grouped(library)[0]
        self.assertEqual(row['id'],ident);self.assertEqual(row['source_count'],1)
        self.assertEqual(len(grouped(library)),3);self.assertTrue(row['duplicate'])
        self.assertEqual(len(row['duplicate_with']),2)
        for _ in range(3):self.assertEqual(len(grouped(library)),3)
        w['matching_basis']='appearance'
        rows=grouped(library);self.assertEqual(len(rows),3)
        self.assertEqual(next(r for r in rows if r['clients']==['wechat'])['comparison'],'suspected')

    def test_complete_gif_identity_timing_and_static_are_distinct(self):
        from emoji_bridge.media import inspect
        files=[];a=Image.new('RGB',(32,24),'red')
        for n,(last,duration) in enumerate((('blue',80),('green',80),('blue',120))):
            file=self.root/f'{n}.gif';a.save(file,save_all=True,append_images=[Image.new('RGB',a.size,last)],duration=duration,loop=0);files.append(file)
        png=self.root/'first.png';a.save(png);files.append(png)
        items=[]
        for n,file in enumerate(files):
            meta=inspect(file)[0]
            item=record(str(n),str(n))
            item['content_key']=hashlib.sha256(json.dumps([meta['frame_pixel_hashes'],meta['durations_ms'],meta['loop']]).encode()).hexdigest()
            items.append(item)
        items+=[record('thumbnail'),record('similar letters')]
        rows=grouped({'clients':{'qq':{'items':items}}})
        self.assertEqual(len(rows),6);self.assertFalse(any(r['duplicate'] for r in rows))
        self.assertEqual(sum(r['comparison']=='pending' for r in rows),2)

    def test_discovery_baseline_new_source_original_ready_and_restart(self):
        ledger=Discovery(self.root/'discovery.json')
        library={'clients':{'qq':{'items':[record('q','A')],'snapshot_at':'1','source_report':'1'},'wechat':{'items':[],'snapshot_at':'1','source_report':'1'}}}
        report=ledger.reconcile(grouped(library),library['clients']);self.assertTrue(report['baseline']);self.assertEqual(report['new_content'],0)
        library['clients']['wechat'].update(items=[record('w','A'),record('new')],source_report='2')
        rows=grouped(library);report=ledger.reconcile(rows,library['clients'])
        self.assertEqual((report['new_sources'],report['new_content']),(1,1))
        self.assertEqual(sum(bool(r['recent_kind']) for r in rows),2)
        before=next(m['first_discovered_at'] for r in rows for m in r['members'] if m['id']=='new')
        item=library['clients']['wechat']['items'][1];item.update(original_state='ready',original_available=True,asset=str(self.root/'asset'),source_sha256='c'*64)
        (self.root/'asset').write_text('fixture')
        rows=grouped(library);report=ledger.reconcile(rows,library['clients'])
        self.assertEqual(report['original_updates'],1);self.assertEqual(report['new_content'],0)
        self.assertEqual(next(m['first_discovered_at'] for r in rows for m in r['members'] if m['id']=='new'),before)
        ledger=Discovery(self.root/'discovery.json')
        self.assertEqual(len(ledger.data['sources']),3)
        ledger.reconcile(grouped(library),library['clients']);self.assertEqual(len(ledger.data['sources']),3)

    def test_reuse_managed_original_needs_exact_binding_and_account(self):
        store=MaterialStore(self.root/'material-library');profile=self.root/'profile'
        source=self.root/'image.png';Image.new('RGB',(30,20),'red').save(source)
        item=record('wechat:member',scan='saved',member={'md5':'member'})
        provenance=dict(client='wechat',item_id=item['id'],source_binding=imports.binding(item),profile_scope=str(profile.resolve()),sha256=sha(source))
        store.import_file(source,kind='wechat',source=json.dumps(provenance))
        source.unlink()
        result=imports.reusable_original('wechat',item,store,profile)
        self.assertIsNotNone(result);self.assertEqual(sha(result[0]),provenance['sha256'])
        self.assertIsNone(imports.reusable_original('wechat',item,store,self.root/'other'))
        self.assertIsNone(imports.reusable_original('wechat',dict(item,scan='changed'),store,profile))

    def test_startup_baseline_precedes_refresh_outside_collection_page(self):
        store=MaterialStore(self.root/'material-library')
        profile=install_choice(self.root,{'wechat_emoticon_db':None,'qq_ori':None,'read_authorized':False})
        file=profile/'runtime-data/T005/library.json'
        library={'clients':{'wechat':{'items':[record('old')],'snapshot_at':'1','source_report':'1'}}}
        save_json(file,library);service=Collections(store);service.context()
        library['clients']['wechat'].update(items=[record('old'),record('new')],snapshot_at='2',source_report='2');save_json(file,library)
        value=service.listing()
        self.assertFalse(value['discovery']['baseline']);self.assertEqual(value['discovery']['new_content'],1)
        service.close()

    def test_pause_is_not_done_or_proof_of_submission(self):
        plan={'target':'qq','run_state':'paused','jobs':[{'status':'pending_confirmation','submission_state':'not_started','reason':'foreground_changed'}]}
        self.assertIn('尚未提交',recovery_text(plan));self.assertIn('QQ 主聊天窗口',recovery_text(plan))
        plan['jobs'][0].update(status='waiting_original',reason='未取得原件')
        self.assertIn('任务尚未完成',recovery_text(plan))
        plan['jobs'][0].update(status='pending_confirmation',submission_state='may_have_started')
        self.assertIn('先核验',recovery_text(plan))

    def test_opening_paused_task_displays_actual_recovery_without_starting(self):
        import tkinter as tk
        from material_transfer_ui import create_task
        root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        profile=self.root/'profile';profile.mkdir()
        path=self.root/'paused.json'
        save_json(path,dict(target='qq',run_state='paused',profile=str(profile),jobs=[dict(id='one',item_id='owned',name='本地测试',
                  status='pending_confirmation',submission_state='not_started',reason='foreground_changed')]))
        with patch('material_transfer.run') as run,patch('material_transfer.account_label',return_value='离线样例'):
            task=create_task(root,path,profile)
            self.assertIn('尚未提交',task['status'].get());self.assertIn('QQ 主聊天窗口',task['status'].get())
            self.assertEqual(task['state']['plan']['run_state'],'paused');self.assertFalse(task['state']['busy'])
            run.assert_not_called()

    def test_refresh_coalescing_account_switch_and_cancel(self):
        base=self.root;store=MaterialStore(base/'material-library');service=Collections(store)
        choice={'wechat_emoticon_db':str(base/'wx.db'),'qq_ori':str(base/'Ori'),'read_authorized':True}
        (base/'wx.db').touch();(base/'Ori').mkdir();install_choice(base,choice);service.context()
        process=Mock();process.poll.return_value=None
        with patch('collection_service.subprocess.Popen',return_value=process):
            service.check_changes(choice)
            self.assertEqual(len(service.pending),1)
            self.assertFalse(service.request('wechat','refresh'))
            service.check_changes(choice);self.assertEqual(len(service.pending),1)
            cancel=Path(service.active['cancel']);service.cancel('wechat');self.assertTrue(cancel.exists())
            old_generation=service.generation
            install_choice(base,dict(choice,wechat_emoticon_db=str(base/'other.db')));service.context()
            self.assertGreater(service.generation,old_generation);self.assertFalse(service.pending)
            process.poll.return_value=0;service.settle();self.assertNotIn('wechat',service.states)
        service.close()

    def test_stale_authenticated_snapshot_cannot_replace_newer_or_erase_unseen(self):
        lib={'clients':{'wechat':{'items':[record('wechat:a')],'snapshot_at':'2026-10-02'}}}
        report=self.root/'index.json'
        save_json(report,dict(status='index_decrypted_and_integrity_verified',snapshot_current_consistent=True,index_count=1,index_members=[dict(md5='b')],at='2026-10-01'))
        catalog.merge_wechat(lib,report);self.assertEqual(lib['clients']['wechat']['items'][0]['id'],'wechat:a')
        value=json.loads(report.read_text());value['at']='2026-10-03';save_json(report,value)
        catalog.merge_wechat(lib,report)
        self.assertEqual(lib['clients']['wechat']['unseen_observations'][0]['item']['id'],'wechat:a')

    def test_failed_source_stops_after_three_attempts_and_reopens_on_change(self):
        store=MaterialStore(self.root/'material-library');source=self.root/'wx.db';source.touch()
        choice={'wechat_emoticon_db':str(source),'qq_ori':None,'read_authorized':True}
        install_choice(self.root,choice);service=Collections(store);service.context()
        process=Mock();process.poll.return_value=None
        with patch('collection_service.subprocess.Popen',return_value=process) as launch:
            for attempt in range(1,4):
                process.poll.return_value=None;service.check_changes(choice)
                job=service.active;self.assertIsNotNone(job)
                save_json(job['status'],{'failed':True,'active':False,'text':'source busy'})
                process.poll.return_value=0;service.settle()
                self.assertEqual(service.retry['wechat']['count'],attempt)
                service.retry['wechat']['after']=0
            service.check_changes(choice);self.assertEqual(launch.call_count,3)
            self.assertIn('已停止自动重试',service.states['wechat']['text'])
            source.write_text('new contents');process.poll.return_value=None;service.check_changes(choice)
            self.assertEqual(launch.call_count,4)
            # Another write during reading must cause a new check after settling.
            first=service.active;source.write_text('a different update');service.check_changes(choice)
            save_json(first['status'],{'active':False,'text':'read'})
            process.poll.return_value=0;service.settle()
            process.poll.return_value=None;service.check_changes(choice)
            self.assertEqual(launch.call_count,5)
        service.close()

    def test_bounded_activation_fallback_and_intervening_window(self):
        from emoji_bridge import windows as win
        target=win.Window(30,7,'Chrome_WidgetWin_1',(0,0,1000,700),96)
        for mode in ('fallback','denied','intervened'):
            user=Mock();current=[10];user.GetForegroundWindow.side_effect=lambda:current[0];user.GetAsyncKeyState.return_value=0
            if mode=='intervened':user.SetForegroundWindow.side_effect=lambda _:current.__setitem__(0,99)
            accessible=Mock(side_effect=(lambda *a:current.__setitem__(0,30)) if mode=='fallback' else None)
            with patch.object(win,'user',user),patch.object(win,'guard'),patch.object(win.time,'sleep'),patch.object(win,'activate_caption'),patch.object(win,'activate_accessible',accessible),patch('emoji_bridge.window_handoff.handoff',side_effect=win.StopAutomation('foreground_switch_denied')):
                if mode=='fallback':win.activate(target,Path('QQ.exe'),accessible_fallback=True);accessible.assert_called_once()
                else:
                    with self.assertRaisesRegex(win.StopAutomation,'foreground_changed' if mode=='intervened' else 'foreground_switch_denied'):
                        win.activate(target,Path('QQ.exe'),accessible_fallback=True)
                    if mode=='intervened':accessible.assert_not_called()

    def test_passive_qq_reads_visible_members_without_input_or_activation(self):
        import qq_catalog
        from emoji_bridge.windows import Window
        q=Mock();q.exe=Path('QQ.exe');q.frame.return_value=Image.new('RGB',(1018,728),'blue');q.panel_box.return_value=(0,0,450,337)
        config={'version':'fixture','exe':'QQ.exe','dpi':96}
        window=Window(30,7,'Chrome_WidgetWin_1',(0,0,1018,728),96)
        controls=Mock();controls.read.return_value=dict(favorites_open=True,at_top=True,loaded_cells=2,
              panel_rect=[0,0,450,337],cells=[dict(runtime_id=[1],fully_visible=True,rect=[91,25,149,83])])
        with patch.object(qq_catalog,'ROOT',self.root),patch.object(qq_catalog,'visible_window',return_value=(config,window)),patch.object(qq_catalog,'QQ',return_value=q),patch('emoji_bridge.qq_controls.FavoriteControls',return_value=controls),patch('emoji_bridge.windows.file_version',return_value='fixture'),patch.object(qq_catalog,'guard'):
            path,result=qq_catalog.scan_visible()
            self.assertEqual(len(result['items']),1);self.assertEqual(result['items'][0]['position'],1)
            self.assertFalse(result['complete']);q.bind.assert_not_called();q.close_panel.assert_not_called()
            controls.open.assert_not_called();controls.reveal.assert_not_called();controls.read.assert_called_once_with()
            path2,result2=qq_catalog.scan_visible(previous_signature=result['visible_signature'])
            self.assertIsNone(path2);self.assertTrue(result2['unchanged'])
            self.assertEqual(q.frame.call_count,1)

    def test_manual_update_reads_changed_source_not_old_catalog(self):
        """Real service/worker/catalog, authenticated-reader boundary is synthetic."""
        import collection_worker,threading
        store=MaterialStore(self.root/'material-library');source=self.root/'中文 新增.json'
        save_json(source,{'members':['a']})
        profile=install_choice(self.root,{'qq_ori':None,'wechat_emoticon_db':str(source),'read_authorized':True})
        original_root=paths.DATA_ROOT;paths.configure_data_root(profile)
        self.addCleanup(lambda:paths.configure_data_root(original_root))
        import wechat_prepare
        service=Collections(store);threads=[]
        def prepare(library_path,cancel,*args,**kwargs):
            members=json.loads(source.read_text('utf-8'))['members']
            report=profile/'reports/current.json'
            save_json(report,dict(status='index_decrypted_and_integrity_verified',snapshot_current_consistent=True,
                      index_count=len(members),index_members=[{'md5':s} for s in members],at=str(time.time())))
            library=catalog.read(library_path);catalog.merge_wechat(library,report);catalog.save(library,library_path)
            return {'status':'index_ready'}
        class Process:
            def __init__(self,args,**kwargs):
                request=json.loads(Path(args[-1]).read_text('utf-8'));self.exit=None
                def work():
                    try:result=collection_worker.run(request)
                    except Exception as exc:result={'failed':True,'text':str(exc)}
                    save_json(request['status'],dict(result,active=False));self.exit=0
                thread=threading.Thread(target=work);threads.append(thread);thread.start()
            def poll(self):return self.exit
        with patch('collection_service.subprocess.Popen',Process),patch.object(wechat_prepare,'prepare',prepare):
            for expected in (1,2):
                if expected==2:save_json(source,{'members':['a','b']})
                service.request('wechat','refresh',manual=True)
                started=time.perf_counter();value=None
                while time.perf_counter()-started<5:
                    service.tick();value=service.listing()
                    if len(value['items'])==expected and not value.get('task'):break
                    time.sleep(.02)
                self.assertEqual(len(value['items']),expected,value)
                if expected==2:
                    self.discovery_latency=time.perf_counter()-started
                    self.assertEqual(value['discovery']['new_content'],1)
                    self.assertTrue(next(r for r in value['items'] if r['members'][0]['id']=='wechat:b')['recent_kind'])
                    self.assertLess(time.perf_counter()-started,3)
        service.close()
        for thread in threads:thread.join(2)

if __name__=='__main__':unittest.main()
