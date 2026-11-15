"""Local pilot setup. No client input, database reads, or uploads in discovery."""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import platform
import re
from . import client_sources as sources, paths
from .state import save_json
from . import compatibility as compat

BUILD='S0174'


def discovery():
    result={'clients':{},'wechat_databases':[],'qq_roots':[],'issues':[]}
    for client in ('wechat','qq'):
        try:
            _,exe=sources.running_client(client);version=sources.win.file_version(exe)
            result['clients'][client]={'exe':str(exe),'version':version,
                'compatibility':compat.classify(client,version)}
        except (ValueError,OSError) as exc:result['issues'].append(client+': '+type(exc).__name__)
    try:locations=sources.discover_emoticon_locations()
    except (ValueError,OSError):
        locations={'candidates':[],'diagnostics':{'candidate_count':0,'issues':['location_access_denied']}}
        result['issues'].append('wechat_location_check_incomplete')
    result['wechat_databases']=[str(p) for p in locations['candidates']]
    result['wechat_location']=locations['diagnostics']
    if result['wechat_databases'] and result['clients'].get('wechat',{}).get('compatibility') in ('tested','candidate'):
        from .active_emoticon import detect
        try:result['wechat_active']=detect(result['wechat_databases'])
        except (ValueError,OSError):result['wechat_active']={'state':'unverified','reason':'active_file_query_failed'}
        result['wechat_location']['active_account']={k:v for k,v in result['wechat_active'].items() if k!='index'}
        sources.LOCATION_DIAGNOSTICS.update(result['wechat_location'])
    try:
        from qq_cache_probe import discover
        found=discover()
        result['qq_location']=found.get('diagnostics',{})
        result['qq_roots']=[i['ori'] for i in found['candidates']]
        if found['limit_reached']:result['issues'].append('qq_account_search_limit')
    except (ValueError,OSError):result['issues'].append('qq_data_location_needed')
    return result


def discovery_with_capabilities():
    result=discovery()
    for client,info in result['clients'].items():
        try:info['capabilities']=compat.startup_report(client,info['version'])
        except Exception:
            # A hung/failed provider on one side must not discard the other
            # client's successful discovery or the account directory choices.
            result['issues'].append(client+'_controls_check_incomplete')
    return result


def validate_choice(found,wechat_db,qq_ori):
    from .qq_cache import personal_root
    candidates={k:v for k,v in found['clients'].items() if compat.classify(k,v.get('version'))!='unsupported'}
    if not candidates:
        reasons=[compat.failure_text(k,'client_family_unadapted') for k in found['clients']]
        raise ValueError('当前客户端尚未验证或未打开。'+(' '.join(reasons) if reasons else '请打开本人的客户端后重新检测。'))
    result={'schema':'pilot-sources-v1','disabled_sources':{},'read_authorized':True,
            'wechat_send_target':'文件传输助手','qq_send_allowed':False,'auto_resize_qq':True,
            'at':datetime.now().astimezone().isoformat()}
    for client in ('wechat','qq'):
        info=found['clients'].get(client)
        if client not in candidates:
            result['disabled_sources'][client]='client_family_unadapted' if info else 'client_not_detected'
            continue
        try:
            _,exe=sources.running_client(client)
            if str(exe)!=info['exe'] or sources.win.file_version(exe)!=info['version']:
                result['disabled_sources'][client]='client_changed';continue
        except (ValueError,OSError):
            result['disabled_sources'][client]='client_not_detected';continue
        result[client+'_exe']=str(exe)
        location=wechat_db if client=='wechat' else qq_ori
        if not location:
            result['disabled_sources'][client]='source_location_missing'
            continue
        try:
            value=sources.emoticon_database(explicit=location) if client=='wechat' else personal_root(location)
        except (ValueError,OSError):
            result['disabled_sources'][client]='source_location_missing';continue
        result['wechat_emoticon_db' if client=='wechat' else 'qq_ori']=str(value)
    if len(result['disabled_sources'])==2:raise ValueError('至少需要一个可读取客户端和本人的有效表情位置。')
    if result.get('wechat_emoticon_db') and found.get('wechat_active',{}).get('state')=='identified':
        # Re-query at the acceptance boundary: an account can switch after the
        # setup screen appeared. Never carry a previous account's recommendation.
        from .active_emoticon import detect
        values=found['wechat_databases'];fresh=detect(values)
        if (fresh.get('state')!='identified' or
                Path(values[fresh['index']]).resolve()!=Path(result['wechat_emoticon_db']).resolve()):
            raise ValueError('当前微信使用的目录与选择不一致或核验未完成，请重新检测后确认本人账号。')
    return result


def install_choice(base,choice):
    # Isolate each pair of account paths. Never load another account's journal.
    identity='\0'.join(str(Path(choice[k]).resolve()).casefold() if choice.get(k) else 'disabled:'+k
                       for k in ('wechat_emoticon_db','qq_ori'))
    tag=hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]
    profile=Path(base)/'profiles'/tag
    save_json(profile/'runtime-data/client-sources.json',choice)
    save_json(Path(base)/'last-profile.json',{'profile':tag})
    return profile


def previous_choice(base):
    file=Path(base)/'last-profile.json'
    if not file.exists():return None
    value=json.loads(file.read_text(encoding='utf-8')).get('profile','')
    if not re.fullmatch('[a-f0-9]{24}',value):raise ValueError('invalid_profile_reference')
    file=Path(base)/'profiles'/value/'runtime-data/client-sources.json'
    return json.loads(file.read_text(encoding='utf-8')) if file.exists() else None


def location_text(info):
    count=info.get('candidate_count',0)
    active=info.get('active_account',{})
    if active.get('state')=='identified' and not info.get('issues'):text=f'微信位置：发现 {count} 个目录，已预选当前微信正在使用的表情库，请确认本人账号。'
    elif count>1:text=f'微信位置：发现 {count} 个账号目录，暂未唯一识别当前账号，请在上方选择。'
    elif count==1:text='微信位置：已找到表情库；这里只确认文件位置，尚未验证读取能力。'
    else:text='微信位置：未找到表情库。可按微信设置中的存储位置，点“选择数据文件夹”。'
    if info.get('issues'):text+=' 部分位置未查完，可手动选择；无需降低客户端版本。'
    if count and active.get('state')!='identified':
        reason=active.get('reason')
        text+= {'active_no_file_owner':' 微信尚未持有可识别的表情库，请打开微信表情收藏后重新检测，或选择本人目录。',
                'active_query_timeout':' 当前账号核验超时，可重试；已发现目录保留。',
                'active_multiple_candidates':' 多个表情库同时被微信使用，需要选择本人当前目录。'}.get(reason,'')
    return text


def preferred_wechat(found,values,previous=None):
    info=found.get('wechat_location',{})
    if info.get('issues'):return ''
    active=found.get('wechat_active',{});index=active.get('index')
    original=found.get('wechat_databases',[])
    if active.get('state')=='identified' and type(index) is int and 0<=index<len(original):
        return original[index] if original[index] in values else ''
    # One discovered location may be offered for confirmation; multiple folders
    # never inherit an old choice as though it were the currently logged-in one.
    return values[0] if len(values)==1 else ''


def location_feedback():
    info=sources.LOCATION_DIAGNOSTICS
    if not info:return {'state':'not_checked'}
    result={key:info[key] for key in ('candidate_count','roots_checked','existing_roots','configured_hints')
            if type(info.get(key)) is int and info[key]>=0}
    allowed={'documents_unavailable','location_config_unreadable','location_search_limit','location_access_denied'}
    result.update(issues=[v for v in info.get('issues',[]) if v in allowed],database_contents_read=False)
    active=info.get('active_account',{})
    if active:
        from .active_emoticon import SAFE_REASONS
        result['active_account']={'state':'identified' if active.get('state')=='identified' else 'unverified',
                                 'reason':active.get('reason') if active.get('reason') in SAFE_REASONS else 'other'}
    return result


def setup(root,base,on_ready=None):
    import tkinter as tk
    import queue,threading
    from tkinter import ttk,filedialog
    from ui_dialogs import messagebox
    from ui_style import apply,ScrollBody
    apply(root)
    root.title('表情互通 · 首次使用与账号选择');root.geometry('800x700');root.minsize(700,560)
    scroll=ScrollBody(root);scroll.pack(fill='both',expand=True)
    frame=ttk.Frame(scroll.body,padding=20);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='先登录微信和 QQ，再确认本人的表情数据',font=('Microsoft YaHei UI',15)).pack(anchor='w',fill='x')
    ttk.Label(frame,text='微信4.1 / 4.2系列、QQ9.9系列按能力检测；具体版本仍逐项核验。客户端支持100%、125%和150%缩放。\n一端不可读取时，另一端仍可准备。检测不发送、不收藏、不删除。',wraplength=700).pack(anchor='w',fill='x',pady=8)
    summary=tk.StringVar();ttk.Label(frame,textvariable=summary,wraplength=700).pack(anchor='w',fill='x',pady=6)
    fields={};combos={};found={};answer=[];detected=queue.Queue();detecting=[False];validating=[False];manual={}
    location_hint=tk.StringVar()
    qq_hint=tk.StringVar()
    for key,label in [('wechat_emoticon_db','微信个人表情数据库'),('qq_ori','QQ 个人表情 Ori 目录')]:
        ttk.Label(frame,text=label).pack(anchor='w',fill='x',pady=(12,3))
        row=ttk.Frame(frame);row.pack(fill='x');fields[key]=tk.StringVar()
        combos[key]=ttk.Combobox(row,textvariable=fields[key],state='readonly');combos[key].pack(side='left',fill='x',expand=True)
        combos[key].bind('<<ComboboxSelected>>',lambda event,k=key:manual.update({k:fields[k].get()}))
        def browse(k=key):
            value=(filedialog.askopenfilename(parent=root,title='选择本人的 emoticon.db',filetypes=[('表情数据库','emoticon.db')])
                   if k=='wechat_emoticon_db' else filedialog.askdirectory(parent=root,title='选择本人的 personal_emoji 下的 Ori 文件夹'))
            if value:
                manual[k]=value
                combos[k]['values']=list(combos[k]['values'])+[value];fields[k].set(value)
                if k=='wechat_emoticon_db':
                    location_hint.set('微信位置：已手动选择文件；开始准备时检查路径和读取能力。')
                    found.pop('wechat_active',None)
        ttk.Button(row,text='选择其他位置',command=browse).pack(side='right',padx=(8,0))
        if key=='wechat_emoticon_db':
            def browse_wechat_folder():
                value=filedialog.askdirectory(parent=root,title='选择微信设置中的存储位置或本人账号文件夹')
                if not value:return
                locations=sources.discover_emoticon_locations([value])
                values=[str(p) for p in locations['candidates']]
                combos['wechat_emoticon_db']['values']=values
                fields['wechat_emoticon_db'].set(values[0] if len(values)==1 and not locations['diagnostics']['issues'] else '')
                manual['wechat_emoticon_db']=fields['wechat_emoticon_db'].get()
                found['wechat_location']=locations['diagnostics']
                found['wechat_databases']=values;found.pop('wechat_active',None)
                sources.LOCATION_DIAGNOSTICS.clear();sources.LOCATION_DIAGNOSTICS.update(locations['diagnostics'])
                location_hint.set(location_text(locations['diagnostics']))
            ttk.Button(row,text='选择数据文件夹',command=browse_wechat_folder).pack(side='right',padx=(8,0))
            ttk.Label(frame,textvariable=location_hint,wraplength=700).pack(anchor='w',fill='x',pady=3)
        else:
            def browse_qq_folder():
                value=filedialog.askdirectory(parent=root,title='选择 QQ 数据位置：Tencent Files、本人账号或 nt_qq 文件夹')
                if not value:return
                from .qq_locations import discover,describe
                report=discover(roots=[value]);values=[item['ori'] for item in report['candidates']]
                found['qq_roots']=values;found['qq_location']=report['diagnostics']
                combos['qq_ori']['values']=values
                choice=values[0] if len(values)==1 and not report['limit_reached'] else ''
                fields['qq_ori'].set(choice);manual['qq_ori']=choice
                qq_hint.set(describe(report['diagnostics']))
            ttk.Button(row,text='选择数据文件夹',command=browse_qq_folder).pack(side='right',padx=(8,0))
            ttk.Label(frame,textvariable=qq_hint,wraplength=700).pack(anchor='w',fill='x',pady=3)
    consent=tk.BooleanVar(value=False)
    from ui_style import consent_checkbutton
    consent_checkbutton(frame,variable=consent,text='这是我本人的账号，我同意在本机读取个人表情并准备原件。').pack(anchor='w',fill='x',pady=(20,5))
    ttk.Label(frame,text='微信读取会在本机验证表情数据库所需密钥，不保存密钥、不读聊天数据库、不上传个人数据。\n读取 QQ 收藏时会自动恢复并调整窗口大小，完成准备后由你勾选搬运。\nQQ 不发消息；搬到微信只使用本人的文件传输助手。不会自动删除聊天记录。',wraplength=700).pack(anchor='w',fill='x',pady=6)
    def refresh():
        if detecting[0] or validating[0]:return
        detecting[0]=True;summary.set('正在只读检测版本和可见控件；不切换窗口，不读取聊天内容。')
        def work():
            try:
                detected.put(discovery_with_capabilities())
            except Exception as exc:detected.put(type(exc).__name__)
        threading.Thread(target=work,daemon=True,name='compatibility-readonly').start()
        root.after(80,finish_refresh)
    def finish_refresh():
        if not frame.winfo_exists():return
        try:result=detected.get_nowait()
        except queue.Empty:root.after(80,finish_refresh);return
        detecting[0]=False
        try:
            if not isinstance(result,dict):
                found.clear()
                for key in combos:
                    values=[manual[key]] if manual.get(key) and Path(manual[key]).exists() else []
                    combos[key]['values']=values;fields[key].set(values[0] if values else '')
                raise ValueError('detection_incomplete')
            found.clear();found.update(result)
            from .qq_locations import describe
            qq_hint.set(describe(found.get('qq_location',{})))
            location_hint.set(location_text(found.get('wechat_location',{'candidate_count':len(found['wechat_databases'])})))
            for client,info in found['clients'].items():
                if 'capabilities' in info:compat.LAST_REPORTS[client]=info['capabilities']
            summary.set('  |  '.join(('微信' if k=='wechat' else 'QQ')+'：'+v['version']+{'tested':' · 本机实测过','candidate':' · 同架构待实测','unsupported':' · 架构未适配'}[v['compatibility']] for k,v in found['clients'].items()) or '未发现已登录客户端，请打开后重新检测。')
            if found.get('issues'):summary.set(summary.get()+'；部分检查未完成，已找到的账号仍可选择；兼容能力中查看详情。')
            try:old=previous_choice(base) or {}
            except (ValueError,OSError):old={}
            for key,source in [('wechat_emoticon_db','wechat_databases'),('qq_ori','qq_roots')]:
                values=found[source]
                # A previous source is displayed, but still requires local confirmation.
                explicit=manual.get(key)
                if explicit and Path(explicit).exists() and explicit not in values:values=[explicit]+values
                combos[key]['values']=values
                if explicit in values:fields[key].set(explicit)
                elif key=='wechat_emoticon_db':fields[key].set(preferred_wechat(found,values,old.get(key)))
                else:fields[key].set(values[0] if len(values)==1 and 'location_search_limit' not in found.get('qq_location',{}).get('issues',[]) else '')
        except Exception as exc:
            found.clear()
            for key in combos:
                values=[manual[key]] if manual.get(key) and Path(manual[key]).exists() else []
                combos[key]['values']=values;fields[key].set(values[0] if values else '')
            qq_hint.set('QQ 位置：检测未完成，请重新检测或选择实际数据文件夹。')
            location_hint.set('微信位置：检测未完成，已明确选择且仍存在的位置保留。')
            summary.set('检测未完成：'+type(exc).__name__+'；可以选择实际表情位置后重试。')
    def start():
        if validating[0]:return
        if detecting[0]:messagebox.showinfo('正在检测','只读能力检查尚未结束，请稍候。',parent=root);return
        if not consent.get():messagebox.showinfo('确认本机读取','请确认本人的账号和读取范围。',parent=root);return
        import copy
        snapshot=copy.deepcopy(found);wx=fields['wechat_emoticon_db'].get();qq=fields['qq_ori'].get()
        validated=queue.Queue();validating[0]=True
        summary.set('正在核对所选账号与当前客户端；尚未开始发送。窗口可正常关闭。')
        def validate():
            try:validated.put((True,validate_choice(snapshot,wx,qq)))
            except Exception as exc:validated.put((False,str(exc) if isinstance(exc,ValueError) else '账号核验未完成，请重新检测后再试。'))
        def finish():
            if not frame.winfo_exists():return
            try:ok,value=validated.get_nowait()
            except queue.Empty:root.after(80,finish);return
            validating[0]=False
            if fields['wechat_emoticon_db'].get()!=wx or fields['qq_ori'].get()!=qq:
                summary.set('选择已变化，请按当前选择重新开始准备。');return
            if not ok:
                summary.set('账号核验未完成；可重新检测或重新选择。')
                messagebox.showerror('尚未开始读取',value,parent=root);return
            try:profile=install_choice(base,value)
            except OSError:
                summary.set('账号配置未能保存，请检查本应用数据目录的访问权限。');return
            answer.append(profile);scroll.destroy();row.destroy()
            if on_ready:on_ready(profile)
            else:root.quit()
        threading.Thread(target=validate,daemon=True,name='account-choice-check').start()
        root.after(80,finish)
    row=ttk.Frame(root,padding=12);row.pack(side='bottom',fill='x',before=scroll)
    ttk.Button(row,text='重新检测',command=refresh).pack(side='left')
    def details():
        messagebox.showinfo('兼容能力（只读检测）',compatibility_text(found.get('clients',{}),probe=False),parent=root)
    ttk.Button(row,text='兼容能力',command=details).pack(side='left',padx=5)
    def export():
        file=filedialog.asksaveasfilename(parent=root,title='保存环境反馈',defaultextension='.json',initialfile='表情互通-环境反馈.json')
        if file:save_json(file,feedback({}))
    ttk.Button(row,text='导出环境反馈',command=export).pack(side='left',padx=8)
    ttk.Button(row,text='开始准备表情',command=start).pack(side='right')
    scroll.attach()
    root.after(100,refresh)
    if on_ready:return frame
    root.protocol('WM_DELETE_WINDOW',root.quit);root.mainloop()
    return answer[0] if answer else None


SAFE_CODES={'foreground_changed','client_display_scale_changed','client_version_changed','cancel_requested',
            'original_unavailable','resource_unavailable','download_failed','animation_variant_not_unique',
            'selected_favorite_original_not_matched_in_cache','selected_favorite_has_multiple_cache_candidates',
            'saved_original_match_not_strong_enough','cache_candidates_incomplete',
            'wechat_process_not_unique_or_not_running'}


def task_feedback(data_root):
    """Summarize the saved queue, without following child reports or executing it."""
    from collections import Counter
    from .transfer import INTERRUPTIONS
    base=Path(data_root).resolve()/'runtime-data/T005'
    pointer=base/'last-queue.json'
    if not pointer.exists():return {'availability':'not_recorded'}
    try:
        path=Path(json.loads(pointer.read_text(encoding='utf-8'))['plan']).resolve()
        path.relative_to((base/'queues').resolve())
        plan=json.loads(path.read_text(encoding='utf-8'))
        if plan.get('schema')!='selected-workflow-v1':raise ValueError('invalid_queue_schema')
        jobs=plan['jobs']
        if not isinstance(jobs,list) or not all(isinstance(j,dict) for j in jobs):raise ValueError('invalid_jobs')
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        return {'availability':'unreadable'}
    reasons=SAFE_CODES | set(compat.REASONS) | INTERRUPTIONS | {
        'source_preparation_failed','saved_source_invalid','source_original_pending',
        'source_favorite_not_reconfirmed','originals_not_all_prepared_no_new_submission',
        'file_dialog_not_found','multiple_file_dialogs','calibration_template_changed',
        'file_dialog_not_ready','file_dialog_not_unique','file_path_readback_mismatch',
        'native_message_timeout','prepared_file_changed','staged_file_copy_mismatch',
        'file_dialog_selection_not_accepted','composer_media_loading_timeout',
        'native_dialog_control_not_unique_or_disabled','file_path_set_failed',
        'calibrated_window_resize_failed','control_moved','qq_uia_top_not_observed','panel_did_not_close',
        'favorite_or_animation_not_confirmed_no_retry','prior_attempt_no_blind_resubmit',
        'bounded_favorites_not_found_no_resubmit','reopened_favorite_view_changed_no_resubmit',
        'favorite_scroll_stalled_no_resubmit','earlier_batch_members_need_verification',
        'batch_members_not_visually_distinguishable_no_add','batch_members_not_visually_distinguishable_no_retry',
        'prior_batch_attempt_no_automatic_resend','prior_unsent_draft_requires_confirmation',
        'prior_sent_batch_add_only','prior_add_result_unknown','staged_batch_item_not_unique',
        'wechat_media_not_ready_no_resend','wechat_submitted_messages_not_found_no_resend',
        'wechat_group_incomplete_no_next_send','sent_media_not_unique_no_resend','cancelled_escape',
    }
    def safe(value,allowed,missing='not_recorded'):
        return value if isinstance(value,str) and value in allowed else missing if value is None else 'other'
    statuses={'queued','running','failed','cancelled','paused_before_submit','pending_confirmation','desktop_confirmed','already_exists','add_executed'}
    stages={'acquisition','prepared','transfer','done','opening_qq','opening_favorites','checking_duplicates','checking_result','recovering_favorites'}
    counts=Counter(safe(j.get('status'),statuses) for j in jobs)
    failures=Counter((safe(j.get('status'),statuses),safe(j.get('stage'),stages),
                      safe(j.get('reason'),reasons),safe(j.get('submission_state'),{'not_started','may_have_started'}),
                      safe(j.get('file_selection_step'),{'opening','filling','waiting_composer','sending'},None))
                     for j in jobs if j.get('status') in ('failed','pending_confirmation','cancelled','paused_before_submit'))
    result={'availability':'recorded','scope':'last_saved_queue_not_current_client_state',
            'source_client':safe(plan.get('source_client'),{'wechat','qq'}),
            'run_state':safe(plan.get('run_state'),{'running','paused','partial','finished','cancelled'}),
            'total':len(jobs),'counts':dict(counts),
            'issues':[{'status':s,'stage':t,'reason':r,'submission_state':u,'count':n,
                       **({'file_selection_step':f} if f else {})}
                      for (s,t,r,u,f),n in failures.items()]}
    block=plan.get('environment_block')
    if isinstance(block,dict):
        result['environment_block']={'client':safe(block.get('client'),{'wechat','qq'}),'reason':safe(block.get('reason'),reasons)}
    for key in ('pause_reason','batch_reason'):
        if plan.get(key) is not None:result[key]=safe(plan[key],reasons)
    return result


def feedback(library,data_root=None):
    # Deliberate allowlist, never copy a report or arbitrary exception string.
    result={'build':BUILD,'system':platform.system(),'windows_release':platform.release(),
            'architecture':platform.machine(),'clients':{},'sent_automatically':False,
            'wechat_location':location_feedback()}
    from .qq_locations import LAST_DIAGNOSTICS,SAFE_ISSUES
    result['qq_location']={key:value for key,value in LAST_DIAGNOSTICS.items()
                           if key in ('candidate_count','roots_checked','existing_roots') and type(value) is int}
    result['qq_location']['issues']=[v for v in LAST_DIAGNOSTICS.get('issues',[]) if v in SAFE_ISSUES]
    for client in ('wechat','qq'):
        side=library.get('clients',{}).get(client,{})
        items=side.get('items',[]);states={};errors={}
        for item in items:
            state=item.get('original_state','discovered')
            state=state if state in {'ready','discovered','downloaded','unavailable'} else 'other'
            states[state]=states.get(state,0)+1
            reason=item.get('index_reason') or item.get('transfer_block_reason') or (item.get('reason') if state!='ready' else None)
            if reason:
                code=reason if isinstance(reason,str) and reason in SAFE_CODES else 'other'
                errors[code]=errors.get(code,0)+1
        result['clients'][client]={'observed':len(items),'states':states,'errors':errors,'complete_proven':side.get('complete') is True}
        if client=='wechat':
            from .wechat import LAST_UIA_DIAGNOSTIC
            result['clients'][client]['last_control_failure']=dict(LAST_UIA_DIAGNOSTIC)
        if client=='qq':
            from . import qq_cache
            from .qq_controls import MAIN_DIAGNOSTICS
            result['clients'][client]['cache_diagnostics']=qq_cache.safe_diagnostics(
                side.get('cache_diagnostics') or qq_cache.LAST_DIAGNOSTICS)
            result['clients'][client]['window_detection']={k:v for k,v in MAIN_DIAGNOSTICS.items()
                if (k=='candidate_count' and type(v) is int and 0<=v<=1000)
                or (k in ('native_disambiguation','selected') and type(v) is bool)}
        try:
            _,exe=sources.running_client(client)
            version=sources.win.file_version(exe)
            result['clients'][client]['version']=version if re.fullmatch(r'[0-9.]{3,24}',version) else 'unknown'
            result['clients'][client]['dpi']=sorted({w.dpi for w in sources.win.qq_windows(exe)})
            checked=compat.LAST_REPORTS.get(client,{})
            capability=compat.startup_report(client,version,probe=False)
            if checked.get('version')==version:
                for name,value in checked['features'].items():
                    if capability['features'][name]['state']=='unverified':capability['features'][name]=value.copy()
            result['clients'][client]['compatibility']=capability
        except Exception:result['clients'][client]['version']='not_detected'
        failure=side.get('last_read_failure') or side.get('preparation',{}).get('reason')
        if isinstance(failure,dict):failure=failure.get('reason')
        if failure:result['clients'][client]['read_failure']=failure if isinstance(failure,str) and failure in compat.REASONS else 'other'
        prep=side.get('preparation',{})
        if type(prep.get('seconds')) in (int,float):result['clients'][client]['preparation_seconds']=prep['seconds']
    if data_root is not None:result['last_task']=task_feedback(data_root)
    return result


def compatibility_text(clients=None,probe=True):
    clients=clients if clients is not None else discovery()['clients']
    lines=[]
    for client,label in [('wechat','微信'),('qq','QQ')]:
        info=clients.get(client)
        if info:
            report=compat.startup_report(client,info['version']) if probe else info.get('capabilities',compat.startup_report(client,info['version'],probe=False))
            compat.LAST_REPORTS[client]=report
            lines.append(label+'\n'+compat.describe(report))
        else:lines.append(label+'\n未识别客户端')
    if sources.LOCATION_DIAGNOSTICS:lines.append(location_text(sources.LOCATION_DIAGNOSTICS))
    return '\n\n'.join(lines)+'\n\n数据库认证/表结构在授权读取时检查；添加和结果以实际任务检查为准。'
