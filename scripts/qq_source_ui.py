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
        self.report['source_locator']='native_favorite_controls'

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
