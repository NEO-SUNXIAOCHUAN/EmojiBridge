"""Read-only bounded recovery of a submitted QQ batch, sharing every view.

This is not a collection scan and cannot authorize resubmission. Each match
must survive a native panel reopen; view alignment and ambiguous tiles fail
closed. Use only for an explicit recovery of unresolved submissions.
"""
from dataclasses import asdict
import time

from emoji_bridge.paging import native_observed_cells, align_scroll, page_anchors_match
from emoji_bridge.recognition import find_in_cells, distinguish_candidates
from emoji_bridge.client_geometry import qq_grid_rect,qq_panel_point,qq_panel_box,client_scale
from emoji_bridge.windows import scroll
from qq_export import first_panel, close_selected_panel, open_retained_panel
from qq_source_locator import snapshot


def observed_cells(q,grid,offset):
    return native_observed_cells(grid,offset,q.native_controls().read())


def matches(runners, grid, cells):
    result = []
    for runner in runners:
        runner.cancelled()
        hits = find_in_cells(grid, runner.refs, [c['rect'] for c in cells], runner.matcher,pixel_tolerance=2)
        if len(hits) > 1:
            hits, proof = distinguish_candidates(grid, runner.refs, hits,
                                                ((34,34,34),(253,253,253)))
            runner.report['candidate_spatial_check'] = proof
        result.append(hits)
    return result


def reopen_view(q,box,grid,cells,view,cancelled,deadline):
    """QQ can reopen at the top. Re-seek this bounded view, then re-prove it."""
    open_retained_panel(q);cancelled()
    fresh=snapshot(q,box)
    if page_anchors_match(grid,fresh,cells,-1)[0]:return fresh
    if view<=0 or not hasattr(type(q),'native_controls'):return None
    controls=q.native_controls();state=controls.read()
    # Only a positively observed reset to the import tile authorizes re-scroll.
    # Arbitrary reorder, hidden panel or geometry changes must still stop.
    if not state.get('at_top'):return None
    for _ in range(view):
        cancelled()
        if time.monotonic()>=deadline:return None
        scroll(q.window,q.exe,*qq_panel_point(box,410,160),-1)
        controls.settled(timeout=min(2,max(.1,deadline-time.monotonic())))
    fresh=snapshot(q,box)
    return fresh if page_anchors_match(grid,fresh,cells,-1)[0] else None


def recover(runners, pending, finish, *, max_views=12, timeout=24):
    from qq_batch_import import ambiguous_members
    if not pending:
        return
    q = runners[0].q
    pending = set(pending)
    for index in pending:
        runners[index].report['recovery_scope'] = 'shared bounded views; no add or send'
    runners[0].cancelled()
    _, box, _ = first_panel(q, cancel=runners[0].cancel)
    grid = snapshot(q, box)
    offset = 0
    deadline = time.monotonic() + timeout
    stop_reason = 'bounded_favorites_not_found_no_resubmit'
    for view in range(max_views):
        runners[0].cancelled()
        cells = observed_cells(q, grid, offset)
        hits = matches(runners, grid, cells)
        ambiguous = ambiguous_members(hits)
        found = [i for i in pending if len(hits[i]) == 1 and i not in ambiguous]
        for i in pending:
            runners[i].report.update(recovery_views=view+1, recovery_candidates=len(hits[i]))
        if found:
            close_selected_panel(q, box, runners[0].cancel)
            fresh=reopen_view(q,box,grid,cells,view,runners[0].cancelled,deadline)
            if fresh is None:
                stop_reason = 'reopened_favorite_view_changed_no_resubmit'
                break
            reopened = matches(runners, fresh, cells)
            ambiguous_after = ambiguous_members(reopened)
            for i in found:
                runner = runners[i]
                if len(reopened[i]) != 1 or i in ambiguous_after:
                    continue
                if any(abs(a-b) >= 20 for a,b in zip(hits[i][0].center, reopened[i][0].center)):
                    continue
                # An explicitly requested playback test cannot be replaced by
                # this membership-only recovery path.
                if getattr(runner, 'check_playback', False) and len(runner.refs) > 1:
                    runner.report['reason'] = 'membership_visible_playback_unverified'
                    continue
                grid.save(runner.evidence/'recovery-before-reopen.png')
                fresh.save(runner.evidence/'recovery-after-reopen.png')
                runner.report.update(collection_persisted=True, sample_seen=True,
                    favorite_match_after=[asdict(reopened[i][0])],
                    acceptance='favorite_membership_and_reopen_only',
                    animation={'status':'not_tested', 'playback_confirmed':False})
                finish(runner, True, True)
                pending.remove(i)
            grid = fresh
        if not pending:
            return
        if time.monotonic() >= deadline or view+1 >= max_views:
            break
        runners[0].cancelled()
        previous = grid
        scroll(q.window, q.exe, *qq_panel_point(box,410,160), -1)
        # Readiness polling is bounded and cancellable. It performs no input.
        settle = min(time.monotonic()+.65, deadline)
        while time.monotonic() < settle:
            runners[0].cancelled()
            time.sleep(min(.05, max(0, settle-time.monotonic())))
        grid = snapshot(q, box)
        try:
            movement = align_scroll(previous, grid, allow_still=True)
        except ValueError as exc:
            stop_reason = str(exc) + '_no_resubmit'
            break
        if not movement['pixels']:
            stop_reason = 'favorite_scroll_stalled_no_resubmit'
            break
        offset += movement['pixels']
    for i in pending:
        runners[i].report.update(status='pending_confirmation', reason=stop_reason)
