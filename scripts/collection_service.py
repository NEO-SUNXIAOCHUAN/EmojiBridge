"""Account-scoped presentation and serialized existing catalog jobs for the desktop."""
from pathlib import Path
import copy,hashlib,json,os,subprocess,sys,threading,time,uuid
from emoji_bridge.state import save_json
from emoji_bridge.collection_view import grouped

APP=Path(__file__).resolve().parents[1]


class Collections:
    def __init__(self,store):
        self.store=store;self.base=store.root.parent;self.profile=None;self.generation=0
        self.active=None;self.pending={};self.states={};self.stamps={};self.files={};self.closed=False
        self.guard=threading.RLock();self.cache=None;self.cache_stamp=None;self.last_check=0
        self.history_cache={};self.history_stamp=None;self.owned_cache=(set(),set());self.owned_revision=None
        self.transfer_paused=False
        self.retry={};self.checked={};self.visible_signature=None;self.discovery=None
        self.reads={}
        self.rows_stamp=None;self.rows_cache=[];self.ready_counts={}
        self.enrichment_paused=set()

    def context(self):
        pointer=self.base/'last-profile.json'
        if not pointer.exists():
            if self.active:Path(self.active['cancel']).touch()
            if self.profile is not None:self.generation+=1
            self.profile=None;self.pending.clear();self.cache=None;self.cache_stamp=None;self.states={};return None
        tag=json.loads(pointer.read_text('utf-8')).get('profile','')
        if len(tag)!=24 or any(c not in '0123456789abcdef' for c in tag):raise ValueError('账号引用无效，请重新选择')
        profile=self.base/'profiles'/tag
        choice=json.loads((profile/'runtime-data/client-sources.json').read_text('utf-8'))
        identity='\0'.join(str(Path(choice[k]).resolve()).casefold() if choice.get(k) else 'disabled:'+k for k in ('wechat_emoticon_db','qq_ori'))
        if hashlib.sha256(identity.encode()).hexdigest()[:24]!=tag:raise ValueError('账号目录与配置不一致，请重新选择账号')
        if profile!=self.profile:
            if self.active:Path(self.active['cancel']).touch()
            self.profile=profile;self.generation+=1;self.files={};self.pending.clear();self.cache=None;self.cache_stamp=None;self.stamps={};self.states={};self.history_stamp=None
            self.retry={};self.checked={};self.visible_signature=None
            self.enrichment_paused.clear()
            try:self.reads=json.loads((profile/'runtime-data/T005/refresh-status.json').read_text('utf-8'))
            except FileNotFoundError:self.reads={}
            from emoji_bridge.collection_discovery import Discovery
            self.discovery=Discovery(profile/'runtime-data/T005/discovery.json')
            # Establish the saved baseline before startup refresh, even when
            # the user first opens the library/editor instead of this page.
            library=self.load_library(profile)
            self.discovery.reconcile(grouped(library),library.get('clients',{}))
        return profile,choice

    def load_library(self,profile):
        file=profile/'runtime-data/T005/library.json'
        if not file.exists():return {'clients':{}}
        stamp=file.stat().st_mtime_ns
        if stamp!=self.cache_stamp:
            library=json.loads(file.read_text('utf-8'))
            from emoji_bridge.state import sha
            for item in library.get('clients',{}).get('qq',{}).get('items',[]):
                if not item.get('observation_key') and item.get('preview') and 'position' in item:
                    try:item['observation_key']=str(item['position'])+':'+sha(item['preview'])
                    except OSError:pass
            from emoji_bridge.collection_view import retain_unseen
            for side in library.get('clients',{}).values():retain_unseen(side,side)
            self.cache=library;self.cache_stamp=stamp
        return self.cache

    def listing(self):
        with self.guard:
            context=self.context()
            if not context:return {'connected':False,'items':[],'sides':{},'total':0}
            profile,choice=context;self.settle();library=self.load_library(profile)
            revision=self.store.revision()
            if revision!=self.owned_revision:
                with self.store.connect() as conn:
                    owned={r[0] for r in conn.execute('SELECT id FROM materials WHERE id NOT IN (SELECT material_id FROM material_flags WHERE deleted=1)')}
                    content=set()
                    for row in conn.execute("SELECT material_id,value FROM sources WHERE kind IN ('qq','wechat')"):
                        if row[0] not in owned:continue
                        try:value=json.loads(row[1]).get('content_key')
                        except (ValueError,AttributeError):continue
                        if value:content.add(value)
                self.owned_cache=(owned,content);self.owned_revision=revision
            owned,content=self.owned_cache
            from emoji_bridge.transfer_history import collect
            history_stamp=(self.cache_stamp,tuple((p.name,p.stat().st_mtime_ns) for p in (profile/'runtime-data/T005/queues').glob('*.json')))
            if history_stamp!=self.history_stamp:
                self.history_cache=collect(profile,library) if library.get('clients') else {};self.history_stamp=history_stamp
            rows_stamp=(str(profile),history_stamp,revision)
            if self.rows_stamp!=rows_stamp:
                rows=grouped(library,owned,self.history_cache,content)
                stats={}
                def file_stat(file):
                    if not file:return None
                    if file not in stats:
                        try:stats[file]=Path(file).stat()
                        except OSError:stats[file]=None
                    return stats[file]
                for r in rows:
                    file=r.pop('preview',None)
                    if not file_stat(file):
                        file=next((str(self.store.get(m['source_sha256'])['thumbnail']) for m in r['members'] if m.get('source_sha256') in owned),None)
                    if file_stat(file):self.files[r['id']]=file
                    stat=file_stat(self.files.get(r['id']))
                    r['has_preview']=bool(stat);r['preview_version']=str(stat.st_mtime_ns) if stat else 'missing'
                self.rows_cache=rows;self.rows_stamp=rows_stamp
                self.ready_counts={c:sum(m['original_ready'] for r in rows for m in r['members'] if m['client']==c and not m['unseen']) for c in ('qq','wechat')}
            # Consumers add local associations and receipts; never mutate the
            # cached source snapshot. Execution still revalidates actual files.
            rows=copy.deepcopy(self.rows_cache)

            discovery=self.discovery.reconcile(rows,library.get('clients',{}))
            # Same-account durable confirmation only. Platform source tags and
            # collection overlap are not delivery receipts.
            from material_transfer import job_stage
            plans=list((self.store.root/'tasks').glob('*.json'))
            transfer_stamp=tuple((p.name,p.stat().st_mtime_ns) for p in plans)
            if getattr(self,'confirmed_stamp',None)!=(str(profile),transfer_stamp):
                confirmed={}
                for p in plans:
                    try:
                        value=json.loads(p.read_text('utf-8'))
                        if value.get('profile')!=str(profile.resolve()):continue
                        for j in value.get('jobs',[]):
                            if job_stage(j) in ('已确认收藏','用户已确认完成'):
                                confirmed.setdefault(j['item_id'],set()).add(value['target'])
                    except (OSError,ValueError,KeyError):continue
                self.confirmed_cache=confirmed;self.confirmed_stamp=(str(profile),transfer_stamp)
            for row in rows:
                row['confirmed_targets']=sorted({t for m in row['members'] for t in self.confirmed_cache.get(m.get('source_sha256'),())})
            sides={}
            for c in ('qq','wechat'):
                side=library.get('clients',{}).get(c,{})
                values=list({i['id']:i for i in side.get('items',[]) if not i.get('receipt_only') and not i.get('source_receipt_only')}.values())
                account=Path(choice.get('qq_ori' if c=='qq' else 'wechat_emoticon_db') or '').parts
                label=account[-6] if c=='qq' and len(account)>=6 else account[-4] if len(account)>=4 else '未绑定'
                sides[c]={'count':len(values),'ready':self.ready_counts.get(c,0),
                          'preview_paused':c in self.enrichment_paused,
                          'account':label,'read_at':side.get('snapshot_at'),'scope':side.get('scope','尚未读取'),
                          'check':self.reads.get(c,{}),
                          'visible_update':side.get('visible_update'),
                          'state':self.states.get(c,{'text':'点击更新读取收藏'}),
                          'historical':len(side.get('unseen_observations',[])),
                          'partial':not side.get('complete',False)}
                # Also explain a disabled source before another doomed refresh;
                # old saved raw failure codes remain readable without scanning.
                from emoji_bridge.compatibility import failure_text
                state=dict(sides[c]['state'])
                reason=state.get('reason') or choice.get('disabled_sources',{}).get(c) or state.get('text')
                if reason=='client_family_unadapted':
                    state.update(failed=True,reason=reason,text=failure_text(c,reason))
                sides[c]['state']=state
            for row in rows:
                for member in row['members']:member['account']=sides[member['client']]['account']
            imported=[]
            for c in ('qq','wechat'):
                pointer=profile/f'runtime-data/T005/last-material-{c}.json'
                try:
                    plan=Path(json.loads(pointer.read_text('utf-8'))['path']).resolve()
                    if plan.is_relative_to(profile/'runtime-data/T005'):
                        imported.extend(j['material_id'] for j in json.loads(plan.read_text('utf-8'))['jobs'] if j.get('material_id'))
                except (OSError,ValueError,KeyError):pass
            current=[r for r in rows if not r['historical_only']]
            historical=[r for r in rows if r['historical_only']]
            return {'connected':True,'account_scope':profile.name,'items':current,'history_items':historical,'sides':sides,'total':len(current),
                    'history_total':len(historical),
                    'source_count':sum(r['source_count'] for r in current),'duplicate_groups':sum(r['duplicate'] for r in current),
                    'comparison':{'exact':sum(r['source_count'] for r in current if r['identity_verified']),
                                  'pending':sum(r['source_count'] for r in current if not r['identity_verified']),
                                  'suspected_groups':sum(r['comparison']=='suspected' for r in current)},
                    'discovery':discovery,
                    'task':dict(self.active or {}),'states':dict(self.states),'imported_items':list(dict.fromkeys(imported))}

    def check_changes(self,choice):
        if self.closed or self.transfer_paused:return
        for client,key in (('wechat','wechat_emoticon_db'),('qq','qq_ori')):
            value=choice.get(key)
            if not value:continue
            file=Path(value);files=[file,Path(value+'-wal')] if client=='wechat' else [file]
            stamp=tuple((f.stat().st_size,f.stat().st_mtime_ns) if f.exists() else None for f in files)
            previous=self.stamps.get(client);self.stamps[client]=stamp
            if previous!=stamp:
                self.retry.pop(client,None)
                if client=='qq':self.visible_signature=None
            if client=='qq':
                visible_context=self.qq_visible_context()
                if visible_context!=getattr(self,'last_qq_context',None):
                    self.last_qq_context=visible_context
                    if visible_context and not self.retry.get(client,{}).get('cancelled'):
                        self.retry.pop(client,None);self.checked.pop(client,None);self.visible_signature=None
            now=time.monotonic();retry=self.retry.get(client,{})
            if retry.get('count',0)>=3 and previous==stamp:continue
            if now<retry.get('after',0):continue
            if client=='wechat':
                if previous!=stamp or retry:self.request(client,'refresh',manual=False)
            elif now-self.checked.get(client,0)>=8:
                if self.can_observe_qq():self.request(client,'refresh',manual=False)
                elif not self.states.get(client,{}).get('active') and (previous!=stamp or not self.states.get(client)):
                    self.states[client]={'text':'打开 QQ → 表情 → 我的收藏首屏，可自动检查；点“更新”可完整读取。缓存文件不算收藏。','needs_update':True}

    @staticmethod
    def qq_visible_context():
        # Tiny focus/identity gate; never activates a client. Semantic panel
        # checks run in the existing cancellable worker.
        from emoji_bridge.windows import user,pid_of,process_path
        foreground=user.GetForegroundWindow()
        try:
            pid=pid_of(foreground) if foreground else None
            return (foreground,pid) if pid and process_path(pid).name.casefold()=='qq.exe' else None
        except (OSError,ValueError):return None

    @classmethod
    def can_observe_qq(cls):return bool(cls.qq_visible_context())

    def tick(self):
        with self.guard:
            if self.closed:return
            context=self.context();self.settle()
            # S0122: collection reads are explicit. Polling only settles tasks.

    def request(self,client,action='refresh',ids=(),manual=True,retry=False,priority=False):
        if client not in ('qq','wechat') or action not in ('refresh','import','previews','enrich'):raise ValueError('未知收藏操作')
        if action=='enrich' and (not ids or len(ids)>18):raise ValueError('清晰预览每批最多18项')
        self.rows_stamp=None
        with self.guard:
            if self.transfer_paused:return False
            if not self.context():raise ValueError('请先选择本人账号')
            if action=='enrich':
                if retry:self.enrichment_paused.discard(client)
                elif client in self.enrichment_paused:return False
            key=(client,action)
            if action=='enrich' and priority:
                if self.active and self.active['action']=='enrich' and self.active['client']!=client:
                    # Yield between items, never interrupt a write/acquisition.
                    save_json(Path(self.active['request']).with_name('priority.json'),{'yield':True})
                # Promote within the existing account writer, not a second
                # downloader or a foreground-client lease. The worker consumes
                # this mailbox between items and publishes each ready item.
                owner=self.active if self.active and (self.active['client'],self.active['action'])==key else self.pending.get(key)
                if owner and owner['generation']==self.generation:
                    owner['priority']=True
                    save_json(Path(owner['request']).with_name('priority.json'),{'ids':list(dict.fromkeys(ids))[:18]})
                    return True
            if self.active and (self.active['client'],self.active['action'])==key:
                if not (client=='qq' and action=='refresh' and manual and not self.active.get('manual')):return False
            if key in self.pending:return False
            jobid=uuid.uuid4().hex;folder=self.profile/'runtime-data/T005/desktop-jobs'/jobid
            folder.mkdir(parents=True)
            plan=self.profile/f'runtime-data/T005/last-material-{client}.json'
            previous=json.loads(plan.read_text('utf-8')).get('path') if retry and plan.exists() else None
            job={'profile':str(self.profile),'store':str(self.store.root),'client':client,'action':action,'manual':manual,
                 'attempt_at':time.time(),'priority':bool(priority),
                 'source_stamp':self.stamps.get(client),
                 'visible_signature':self.visible_signature if client=='qq' and not manual else None,
                 'ids':list(dict.fromkeys(ids)),'retry':retry,'cancel':str(folder/'cancel'),'status':str(folder/'status.json'),
                 'plan':previous or str(folder/'import.json'),'request':str(folder/'request.json'),'generation':self.generation}
            if action=='import':save_json(plan,{'path':job['plan']})
            save_json(job['request'],job);self.pending[key]=job
            self.states[client]={'active':True,'action':action,'text':'已排队：'+({'import':'原件入库','previews':'加载当前页预览','enrich':'补齐清晰预览'}.get(action,'更新收藏'))}
            self.checked[client]=time.monotonic()
            self.states[client]['attempt_at']=job['attempt_at']
            if manual:self.retry.pop(client,None)
            self.settle();return True

    def finish_refresh(self,job,state):
        if job['action']!='refresh':return
        client=job['client'];cancelled=Path(job['cancel']).exists()
        yielded=bool(job.get('yielded_to_transfer') and not job.get('user_cancelled'))
        if yielded and state.get('read_succeeded'):cancelled=False
        check=dict(self.reads.get(client,{}))
        check.update(attempt_at=job['attempt_at'],finished_at=time.time(),
                     result=('yielded' if yielded else 'cancelled') if cancelled else 'deferred' if state.get('deferred') else 'success' if state.get('read_succeeded') else 'incomplete',
                     text=state.get('text','读取未完成'),reason=state.get('reason'))
        if state.get('read_succeeded') and not cancelled:
            check.update(success_at=check['finished_at'],coverage=state.get('coverage',''))
            for key in ('count','report'):
                if state.get(key) is not None:check[key]=state[key]
        self.reads[client]=check
        save_json(self.profile/'runtime-data/T005/refresh-status.json',self.reads)
        if cancelled and yielded:
            self.retry.pop(client,None);self.checked[client]=time.monotonic()
        elif cancelled:self.retry[client]={'count':3,'after':0,'cancelled':True}
        elif state.get('deferred'):
            # A real client owner is not a failed read. Yield without spending
            # the three-error retry budget or updating the successful snapshot.
            self.retry[client]={'count':0,'after':time.monotonic()+2}
        elif state.get('failed'):
            count=self.retry.get(client,{}).get('count',0)+1
            self.retry[client]={'count':count,'after':time.monotonic()+2**count}
            if count>=3:state['text']+=' 已停止自动重试；请检查来源后点“更新”。'
        else:self.retry.pop(client,None)

    def yield_to_transfer(self):
        """Ask the current reader to stop; its process still owns all leases."""
        job=self.active
        if not job or job.get('user_cancelled'):return
        if job.get('manual') and job['action']!='refresh':return
        job['yielded_to_transfer']=True
        job['resume_after_transfer']=bool(job['action']=='enrich' or job.get('manual') and job['action']=='refresh')
        Path(job['cancel']).touch()

    def resume_read(self,job,state):
        if (not job.get('resume_after_transfer') or job.get('user_cancelled') or self.closed
                or state.get('read_succeeded') or (job['client'],job['action']) in self.pending):return
        # A new worker must read the current client view, never continue from
        # stale scroll coordinates. Previously committed catalog/originals stay.
        folder=Path(job['request']).parent.parent/uuid.uuid4().hex;folder.mkdir()
        resumed=dict(job,cancel=str(folder/'cancel'),status=str(folder/'status.json'),request=str(folder/'request.json'))
        for key in ('yielded_to_transfer','resume_after_transfer'):resumed.pop(key,None)
        save_json(resumed['request'],resumed)
        self.pending[(job['client'],job['action'])]=resumed
        self.states[job['client']]={'active':True,'action':job['action'],'text':'已让位给互通；未完成的更新将在互通结束后继续，已读结果保留。'}

    def settle(self):
        if self.active:
            job=self.active;file=Path(job['status']);running=self.process.poll() is None
            if job['generation']==self.generation and file.exists():
                try:self.states[job['client']]={**json.loads(file.read_text('utf-8')),'action':job['action']}
                except (OSError,ValueError):pass
                if Path(job['cancel']).exists() and (self.states[job['client']].get('active') or running and job.get('yielded_to_transfer') and not job.get('user_cancelled')):
                    self.states[job['client']]['text']=('正在结束当前读取，让互通优先；已读结果保留。' if job.get('yielded_to_transfer') and not job.get('user_cancelled') else '已取消后续更新，正在结束当前读取；原列表保留。')
                    if running and job.get('yielded_to_transfer') and not job.get('user_cancelled'):
                        self.states[job['client']].update(active=True,failed=False,reason=None)
            if running:return
            if job['generation']==self.generation and (not file.exists() or self.states.get(job['client'],{}).get('active')):
                self.states[job['client']]={'failed':True,'text':'读取进程未完成，请重试；旧数据保留。'}
            if job['generation']==self.generation and job['action']=='refresh':
                state=self.states.get(job['client'],{})
                if job.get('source_stamp')!=self.stamps.get(job['client']):self.stamps.pop(job['client'],None)
                if state.get('visible_signature'):self.visible_signature=state['visible_signature']
                self.finish_refresh(job,state)
                self.resume_read(job,state)
            elif job['generation']==self.generation and job['action']=='enrich':
                self.resume_read(job,self.states.get(job['client'],{}))
            if job['generation']==self.generation and job['action']=='enrich' and not Path(job['cancel']).exists():
                remaining=self.states.get(job['client'],{}).get('remaining_ids',[])
                if remaining:
                    job=dict(job,ids=remaining,priority=False)
                    Path(job['request']).with_name('priority.json').unlink(missing_ok=True)
                    Path(job['status']).unlink(missing_ok=True)
                    save_json(job['request'],job);self.pending[(job['client'],'enrich')]=job
            self.rows_stamp=None  # Original/preview completion changes readiness.
            self.active=None
        if self.pending and not self.closed and not self.transfer_paused:
            key=next((k for k,j in self.pending.items() if j.get('priority')),next((k for k,j in self.pending.items() if j.get('manual')),next(iter(self.pending))));job=self.pending.pop(key);self.active=job
            try:
                self.process=subprocess.Popen([sys.executable,'-X','utf8',str(APP/'scripts/collection_worker.py'),job['request']],
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except OSError as exc:
                self.active=None;self.states[job['client']]={'failed':True,'text':'读取未启动：'+str(exc)+'。原列表保留，可重试。'}
                self.finish_refresh(job,self.states[job['client']])
                save_json(job['status'],self.states[job['client']])

    def cancel(self,client):
        with self.guard:
            self.enrichment_paused.add(client)
            self.pending={k:v for k,v in self.pending.items() if k[0]!=client}
            if self.active and self.active['client']==client:
                self.active['user_cancelled']=True
                Path(self.active['cancel']).touch()
            self.states[client]={'text':'已请求取消；完成项保留。'}
            self.retry[client]={'count':3,'after':0,'cancelled':True}

    def close(self):
        self.closed=True;self.pending.clear()
        if self.active:Path(self.active['cancel']).touch()
