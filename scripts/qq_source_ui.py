"""QQ source reads and destination imports share native window/entry controls."""
import time
from pathlib import Path

from qq_import import QQ
from emoji_bridge.qq_controls import FavoriteControls, discover_main
from emoji_bridge.source_focus import activate_source
from emoji_bridge.windows import (StopAutomation, qq_windows, user, guard, file_version,
                                  ensure_window_on_screen, scroll, pid_of, process_path, class_name)


class SourceQQ(QQ):
    def __init__(self, config, report, cancel=None):
        super().__init__(config, report)
        self.controls = None
        self.cancel = Path(cancel) if cancel else None

    def close(self):
        if self.controls:
            self.controls.close()
            self.controls = None

    def bind(self):
        super().bind()
        self.report['source_locator']='visual_favorite_observations' if self.controls._visual else 'native_favorite_controls'

    def panel_box(self, state=None):
        from emoji_bridge.client_geometry import qq_panel_box
        state=self.controls.read() if state is None else state
        return qq_panel_box(self.window,state)

    def panel(self):
        box=self.panel_box()
        return self.frame().crop(box), box, None

    def first_favorites_panel(self, limit=48, cancel=None):
        if cancel and Path(cancel).exists():
            raise StopAutomation('cancel_requested')
        state = self.controls.open()
        if state.get('backend')=='visual':state=self.controls.top(state)
        # The grid itself can appear before QQ has populated any favorites.
        # Observe it without toggling the panel again or treating it as empty.
        if not state.get('cells'):
            state = self.controls.wait(lambda s: bool(s.get('cells')),
                                       'qq_uia_favorites_loading_timeout', state, timeout=8)
        state = self.controls.top(state)
        return self.panel()

    def advance_favorites(self):
        """Reveal a nearby loaded cell, preserving visual overlap for identity."""
        state = self.controls.read()
        self.panel_box(state)
        if state.get('backend')=='visual':
            box=state['grid_rect'];x,y=self.window.rect[:2]
            scroll(self.window,self.exe,round((box[0]+box[2])/2-x),round((box[1]+box[3])/2-y),-1)
            time.sleep(.2)
            return self.controls.read()
        cells = state.get('cells', [])
        visible = [n for n, cell in enumerate(cells) if cell['fully_visible']]
        if not visible:
            raise StopAutomation('qq_uia_visible_cells_missing')
        # On the supported six-column grid this keeps at least a row of overlap.
        # Do not use the loaded tail: it may skip unread intermediate rows.
        index = min(visible[-1] + 1, len(cells) - 1)
        return self.controls.reveal(cells[index]['runtime_id'])

    def wait_for_favorite_growth(self, previous, timeout=8):
        """One bounded tail wait; a quiet loaded tail is not a server total."""
        started = time.monotonic()
        before = previous['loaded_cells']
        if previous.get('backend')=='visual':
            # No synthetic loaded count. Observe a bounded quiet tail; callers
            # retain partial results and never infer the cloud total from it.
            while time.monotonic()-started<min(timeout,2):
                self.controls.read();time.sleep(.1)
            return self.controls.read()
        while True:
            state = self.controls.read()  # identity, focus and cancel checked
            self.panel_box(state)
            after = state['loaded_cells']
            if after < before:
                raise StopAutomation('qq_uia_favorite_list_changed')
            elapsed = time.monotonic() - started
            if after > before or elapsed >= timeout:
                self.report.setdefault('loading_waits', []).append(dict(
                    before=before, after=after, seconds=round(elapsed, 3)))
                return state
            time.sleep(.1)

    def close_panel(self):
        self.controls.close_panel()

    def assert_panel(self, expected):
        if self.panel_box() != expected:
            raise StopAutomation('favorite_panel_anchor_changed')
