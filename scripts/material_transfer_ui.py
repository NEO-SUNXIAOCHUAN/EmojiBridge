"""Explicit client use from the offline library, with existing account isolation."""
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk
from ui_dialogs import messagebox
from ui_style import apply,disclosure,MUTED

APP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(APP / 'src'), str(APP / 'scripts')]
from emoji_bridge import paths
from emoji_bridge.client_sources import known_folder
from emoji_bridge.pilot import setup
from emoji_bridge.state import single_instance


def create_task(root, path, profile, *, on_close=None, can_start=None, autostart=False, on_update=None, on_locate=None,on_resume=None, headless=False):
    from emoji_bridge.catalog import read
    from emoji_bridge.state import save_json
    from material_transfer import run, plan_stage, refresh_target, account_label, recovery_text
    from bridge_ui import App as BridgeApp
    plan = read(path)
    if plan.get('profile') and Path(plan['profile']) != profile:
        raise ValueError('此任务属于之前选择的账号配置，请重新选择相同配置。')
    if not headless:
        root.title('素材库 · 添加收藏'); root.geometry('780x500')
    apply(root)
    # The modern host uses the same executor without mounting a second page.
    # An unmounted frame owns the legacy view only; it never takes focus/space.
    frame = ttk.Frame(root, padding=20)
    if not headless:frame.pack(fill='both', expand=True)
    ttk.Label(frame, text=f"向 {'微信文件传输助手' if plan['target']=='wechat' else 'QQ 个人收藏'} 添加 {len(plan['jobs'])} 张素材", font=('Microsoft YaHei UI', 15)).pack(anchor='w')
    ttk.Label(frame, text='每批最多 5 张；成功跳过，待确认先核验。导出不计为收藏成功。', wraplength=720).pack(anchor='w', pady=10)
    ttk.Label(frame, text=f'目标账号目录：{account_label(profile,plan["target"])} · 仅本人会话 / 个人收藏').pack(anchor='w')
    status = tk.StringVar(value='正在启动；自动操作期间请暂时保持客户端窗口，可随时取消。' if autostart else recovery_text(plan))
    ttk.Label(frame, textvariable=status, wraplength=720).pack(anchor='w')
    bar = ttk.Progressbar(frame, maximum=len(plan['jobs'])); bar.pack(fill='x', pady=12)
    rows = ttk.Treeview(frame, columns=('name','stage'), show='headings', height=6)
    rows.heading('name',text='本次作品'); rows.heading('stage',text='真实状态')
    rows.column('name',width=330); rows.column('stage',width=280); rows.pack(fill='x')
    detail = disclosure(frame,'任务详情与兼容参数')
    text = tk.Text(detail, height=8, wrap='word'); text.pack(fill='both', expand=True)
    events = queue.Queue(); state = {'busy': False, 'closed': False, 'generation':0}

    def notify(value):
        if on_update:
            try:on_update(value,status.get())
            except Exception:
                import logging
                logging.getLogger(__name__).exception('transfer_notification_failed')

    def display(value):
        state['plan']=value
        if headless:
            notify(value)
            return
        if value.get('waiting_for') and state['busy']:
            from emoji_bridge.state import waiting_text
            status.set(waiting_text(value['waiting_for']))
        summary = BridgeApp.queue_summary(None, value)
        if value.get('pause_reason'):
            summary += '\n停止原因：' + value['pause_reason']
        if value.get('waiting_for'):
            import json
            summary+='\n资源等待详情：'+json.dumps(value['waiting_for'],ensure_ascii=False)
        adapted=[j for j in value['jobs'] if j.get('conversion',{}).get('lossy')]
        if adapted:summary+=f'\n{len(adapted)} 项使用独立兼容副本，保留完整时长；原件未覆盖。这不是客户端容量上限或收藏结果。'
        from emoji_bridge.compatibility_copy import describe
        for job in value['jobs']:
            if job.get('prepared_metadata'):summary+='\n'+job['name']+'：'+describe(job['prepared_metadata'])
        refresh=value.get('target_refresh',{})
        if refresh:summary+='\n收藏列表刷新：'+({'done':'已完成','running':'正在读取','failed':'失败，作品及收藏结果保留；可手动重新扫描'}.get(refresh.get('state'),'未完成'))
        selected=rows.selection();rows.delete(*rows.get_children())
        for job in value['jobs']:
            rows.insert('', 'end', iid=job['id'], values=(job['name'],plan_stage(value,job)))
        rows.selection_set([ident for ident in selected if rows.exists(ident)])
        text.configure(state='normal');text.delete('1.0', 'end'); text.insert('1.0', summary);text.configure(state='disabled')
        bar['value'] = sum(j['status'] in ('desktop_confirmed', 'already_exists', 'add_executed') for j in value['jobs'])
        notify(value)

    def start():
        if state['busy'] or state['closed']:
            return
        latest=read(path)
        if latest.get('work_revision') and not latest.get('work_material'):
            status.set('此作品尚未生成有效成品；请回编辑器查看草稿并重新选择目标，未提交客户端。');return
        if can_start and not can_start():
            status.set('互通准备或其他任务尚未结束，请等待或先取消。'); return
        from wechat_retry import confirmation_candidates,approve
        previous=read(path);retry=confirmation_candidates(previous,profile)
        if retry:
            ids=[v['item_id'] for v in retry]
            names='、'.join(j['name'] for j in previous['jobs'] if j['item_id'] in ids)
            if not messagebox.askyesno('恢复发送前中断',
                f'这些素材的记录停在发送之前：{names}\n\n请确认没有手动发送过，且已移除旧草稿。'
                '\n确认后继续这些项；已经发送过请选“否”。',parent=root):return
            approve(path,ids,confirmed=True,root=profile)
        # Clear the old token before exposing Cancel; the worker cannot erase a new click.
        path.with_suffix('.cancel').unlink(missing_ok=True)
        state['generation']+=1;generation=state['generation'];state['close_requested']=False
        state['busy'] = True; status.set('准备所选素材 → 检查客户端 → 添加 → 确认结果。'); start_button.state(['disabled'])
        notify(previous)
        def work():
            from emoji_bridge.state import WaitingCancelled
            try:
                result = run(path, profile, resume=True, clear_cancel=False, progress=lambda v: events.put((generation,'progress', v.copy())))
                events.put((generation,'done', result))
            except WaitingCancelled as exc:
                events.put((generation,'error',str(exc)))
            except Exception as exc:
                latest=read(path);latest.update(run_state='cancelled' if path.with_suffix('.cancel').exists() else 'paused',pause_reason=str(exc));save_json(path,latest)
                events.put((generation,'error', str(exc)))
            finally:
                # Ownership follows the real executor, never a successful Tk
                # redraw. A destroyed/broken view cannot leave the task busy.
                try:state['plan']=read(path)
                finally:state['busy']=False
        try:threading.Thread(target=work, daemon=True, name='material-transfer').start()
        except Exception as exc:
            state['busy']=False;start_button.state(['!disabled'])
            previous.update(run_state='paused',pause_reason='任务未启动：'+str(exc));save_json(path,previous)
            status.set('任务未启动，可重试。');display(previous)

    def cancel():
        path.with_suffix('.cancel').touch()
        status.set('正在取消；已发送内容不撤回，已完成进度保留。' if state['busy'] else '任务已停止；已完成进度保留，继续时先核验未确定项。')
        notify(read(path))

    def refresh():
        if state['busy'] or (can_start and not can_start()):return
        path.with_suffix('.cancel').unlink(missing_ok=True)
        state['generation']+=1;generation=state['generation'];state['close_requested']=False
        state['busy']=True;start_button.state(['disabled'])
        status.set('仅重新扫描收藏列表，不发送或再次添加。')
        def work():
            try:
                value=read(path)
                try:value['target_refresh']=refresh_target(value['target'],path.with_suffix('.cancel'))
                except Exception as exc:value['target_refresh']={'state':'failed','reason':str(exc)}
                save_json(path,value);state['plan']=value;events.put((generation,'done',value))
            except Exception as exc:events.put((generation,'error',str(exc)))
            finally:
                state['busy']=False
        try:threading.Thread(target=work,daemon=True,name='material-result-refresh').start()
        except Exception as exc:
            state['busy']=False;start_button.state(['!disabled'])
            status.set('更新未启动，可重试。');notify(read(path))

    def close():
        if state['closed']:return
        if state['busy']:
            state['close_requested']=True;cancel(); return
        state['closed'] = True
        if state.get('poll_id'):root.after_cancel(state['poll_id']);state['poll_id']=None
        root.unbind('<Destroy>',destroy_binding)
        if on_close:on_close()
        elif not headless:root.destroy()
        if headless:frame.destroy()

    def destroyed(event):
        if event.widget is not root:return
        state['closed']=True
        if state.get('poll_id'):root.after_cancel(state['poll_id']);state['poll_id']=None
        if state['busy']:path.with_suffix('.cancel').touch()
    destroy_binding=root.bind('<Destroy>',destroyed,add='+')

    def poll():
        if state['closed']:
            return
        try:
            while not events.empty():
                generation, kind, value = events.get_nowait()
                if generation!=state['generation']:continue
                if kind in ('done', 'error'):
                    start_button.state(['!disabled'])
                    status.set(recovery_text(value) if kind == 'done' else '停止：' + value)
                    display(value if kind=='done' else read(path))
                elif kind=='progress':display(value)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('transfer_view_update_failed')
        finally:
            if state.get('close_requested') and not state['busy']:close()
            if not state['closed']:state['poll_id']=root.after(100, poll)

    row = ttk.Frame(frame); row.pack(fill='x', pady=12)
    start_button = ttk.Button(row, text='继续 / 重试未完成', command=lambda:on_resume(path) if on_resume else start()); start_button.pack(side='left')
    ttk.Button(row, text='取消任务', command=cancel).pack(side='left', padx=8)
    ttk.Button(row, text='重新扫描收藏', command=lambda:on_resume(path,True) if on_resume else refresh()).pack(side='left',padx=4)
    if on_locate:
        ttk.Button(row,text='定位库内作品',command=lambda:on_locate([j['item_id'] for j in read(path)['jobs'] if not rows.selection() or j['id'] in rows.selection()])).pack(side='left',padx=6)
    ttk.Button(row, text='关闭', command=close).pack(side='right')
    # Keep the bridge's previous queue pointer untouched; the library owns this task.
    save_json(profile / 'runtime-data/T005/material-last-task.json', {'plan': str(path)})
    display(plan)
    if not headless:root.protocol('WM_DELETE_WINDOW', close)
    poll()
    # Reserve synchronously at the final target click; subsequent clicks see busy.
    if autostart:start()
    return {'state':state,'cancel':cancel,'close':close,'start':start,'status':status,'frame':frame,'rows':rows,'path':path,'display':display,'refresh':refresh}


def main():
    path = Path(sys.argv[1]).resolve()
    root = tk.Tk()
    base = known_folder('local_app_data') / 'EmojiBridgePilot'
    try:
        with single_instance(base / 'pilot.lock'):
            profile = setup(root, base)
            if profile is None:
                root.destroy(); return
            paths.configure_data_root(profile)
            create_task(root, path, profile, autostart='--start' in sys.argv)
            root.mainloop()
    except Exception as exc:
        messagebox.showerror('素材任务未启动', str(exc), parent=root)
        root.destroy()


if __name__ == '__main__':
    main()
