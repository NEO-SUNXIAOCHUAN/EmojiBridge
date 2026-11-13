"""Cutout entry: mark first, submit only with an explicit button."""
from scribble_tools import ScribbleTools as CutoutTools


def attach(editor):
    if getattr(editor, 'cutout', None):
        return editor.cutout
    editor.cutout = CutoutTools(editor)
    return editor.cutout
