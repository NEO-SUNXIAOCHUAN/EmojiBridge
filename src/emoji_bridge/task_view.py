"""User-facing task counts derived from durable item outcomes, never position."""
DONE={'desktop_confirmed','already_exists','add_executed'}


def summary(plan):
    jobs=plan.get('jobs',[]);total=len(jobs)
    completed=sum(j.get('status') in DONE for j in jobs)
    confirmed=sum(j.get('status')=='desktop_confirmed' or bool(j.get('collection_verified'))
                  or j.get('reason')=='exact_file_in_authenticated_local_favorites_index' for j in jobs)
    failed=sum(j.get('status')=='failed' for j in jobs)
    pending=sum(j.get('status')=='pending_confirmation' for j in jobs)
    remaining=total-completed
    cancelled=plan.get('run_state')=='cancelled'
    if cancelled:label=f'已取消 · 已处理 {completed}/{total}，其余已停止'
    elif completed==total and total:
        label=f'已完成 {completed}/{total}' if confirmed==total else f'已执行添加 {completed}/{total}'
    else:label=f'已停止 · 已处理 {completed}/{total}，还有 {remaining} 项未完成'
    if confirmed:label+=f' · 收藏已确认 {confirmed}'
    if not cancelled and completed and confirmed<completed:label+=f' · 收藏待确认 {completed-confirmed}'
    return {'total':total,'completed':completed,'confirmed':confirmed,'failed':failed,'pending':pending,
            'remaining':remaining,'cancelled':cancelled,'label':label,
            'needs_attention':not cancelled and (remaining>0 or confirmed<completed)}
