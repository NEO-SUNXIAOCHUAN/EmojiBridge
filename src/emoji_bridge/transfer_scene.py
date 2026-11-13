"""Presentation-only projection of durable evidence; never runs jobs."""
def scene(plan,active=False):
    jobs=plan.get('jobs',[]);target=plan.get('target','wechat')
    sources={j['source_ref']['client'] for j in jobs if j.get('source_ref',{}).get('client')}
    source=next(iter(sources)) if len(sources)==1 else plan.get('source_client','local')
    completed=sum(bool(j.get('collection_verified') or j.get('status') in ('desktop_confirmed','already_exists')) for j in jobs)
    failed=sum(j.get('status')=='failed' for j in jobs)
    waiting=sum(j.get('status') in ('add_executed','batch_message_sent') or j.get('reason') in ('waiting_confirmation','pending_confirmation','awaiting_confirmation','client_processing','awaiting_result') or j.get('submission_state')=='may_have_started' or j.get('file_submission') in ('send_requested','submitted_to_client','send_pending') for j in jobs if not j.get('collection_verified') and j.get('status') not in ('desktop_confirmed','already_exists'))
    original=any(j.get('status') in ('waiting_original','acquiring_original') for j in jobs)
    state=plan.get('run_state','');reason=plan.get('pause_reason','')
    block_client=plan.get('environment_block',{}).get('client')
    source_blocked=bool(original or (block_client and block_client!=target))
    successful=lambda j: bool(j.get('collection_verified') or j.get('status') in ('desktop_confirmed','already_exists'))
    pending_reasons=('waiting_confirmation','pending_confirmation','awaiting_confirmation','client_processing','awaiting_result','historical_membership_requires_verification')
    def has_issue(job):
        # The adapter records this as progress, not an error. A subsequent
        # failed verification supplies its own reason and still blocks.
        if job.get('status')=='add_executed' and job.get('reason')=='add_action_completed':return False
        if job.get('reason') in pending_reasons and job.get('status')!='failed':return False
        return bool(job.get('reason') or job.get('status') in ('failed','waiting_original'))
    issues=[j.get('reason') or j.get('status') for j in jobs if not successful(j) and has_issue(j)]
    manual=reason in ('user_paused','manual_pause','pause_requested')
    normal_wait=reason in pending_reasons
    # Execution pause is not a visual freeze when an error caused that pause.
    # The basin means THIS transfer is obstructed, not a platform-wide outage.
    blocked=bool((issues or plan.get('environment_block') or reason and not manual and not normal_wait) and
                 (not active or state in ('paused','output_failed','failed')))
    if state=='cancelled':phase='cancelled'
    elif jobs and completed==len(jobs):phase='success'
    elif blocked:phase='blocked'
    elif manual and state=='paused':phase='paused'
    elif normal_wait or waiting and (not active or plan.get('stage') in ('checking_result','waiting_media') or any(j.get('status') in ('add_executed','pending_confirmation') for j in jobs)):phase='waiting'
    elif state=='paused':phase='paused'
    elif failed and not active:phase='blocked'
    elif active:phase='working'
    else:phase='idle'
    detail=''
    if phase=='blocked':
        code=(issues[0] if issues else '') if manual or normal_wait else reason or (issues[0] if issues else '')
        messages={'heart_not_uniquely_identified':'未能确认 QQ 收藏入口，请打开“我的收藏”后继续。',
            'qq_chat_not_open':'QQ 未打开聊天输入区，请打开本人测试会话后继续；文件未提交。',
            'plus_not_uniquely_identified':'QQ 导入按钮未唯一识别，请让收藏首屏完整显示后继续。',
            'waiting_original':'原件尚未取得，请获取原件后继续。',
            'another_client_run_is_active':'另一项任务正在使用客户端，请等待或查看该任务。'}
        messages.update(foreground_changed='前台已切到其他窗口；请让目标客户端保持前台后继续，已提交项会先核验。',
            bounded_favorites_not_found_no_resubmit='本次核验范围内尚未确认这些表情，请查看收藏后继续；不会自动重发。',
            reopened_favorite_view_changed_no_resubmit='收藏面板重开后位置发生变化，请保持收藏面板后继续核验。',
            favorite_scroll_stalled_no_resubmit='收藏列表未继续滚动，请检查面板后继续；未确认项不会重发。',
            earlier_batch_members_need_verification='前一批仍有结果待核验，核验后再提交剩余素材。',
            favorite_or_animation_not_confirmed_no_retry='收藏中的候选仍不唯一；先核验已有结果，不会再次提交。')
        from .compatibility import REASONS
        detail=messages.get(code,REASONS.get(code,'本次传输受阻，请查看任务原因并处理后继续；已成功项保留。'))
    return dict(phase=phase,source=source,target=target,total=len(jobs),completed=completed,failed=failed,waiting=waiting,
                sourceBlocked=source_blocked,targetBlocked=phase=='blocked',detail=detail,
                confirmed=bool(jobs and completed==len(jobs)),blockingError=phase=='blocked',
                errorCode=(code or 'transfer_blocked') if phase=='blocked' else None,
                pauseReason=reason if phase in ('paused','waiting') else None,
                eventKey=str(plan.get('created',plan.get('id','')))+'|'+target+'|'+phase+'|'+str(reason or issues))
