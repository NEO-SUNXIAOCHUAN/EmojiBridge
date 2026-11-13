"""Sparse immutable current-frame paint, keeping the original animation source."""
from collections.abc import Sequence
from dataclasses import dataclass
from .animated_edit import GifSource

class PatchedFrames(Sequence):
    def __init__(self,frames,patches):self.frames=frames;self.patches=dict(patches)
    def __len__(self):return len(self.frames)
    def __getitem__(self,index):
        if isinstance(index,slice):return [self[i] for i in range(*index.indices(len(self)))]
        return self.patches[index] if index in self.patches else self.frames[index]

@dataclass(frozen=True,eq=False)
class PaintedSource(GifSource):
    master:object
    patches:dict

def revised(source,index,frame):
    master=source.master if isinstance(source,PaintedSource) else source
    patches={**(source.patches if isinstance(source,PaintedSource) else {}),index:frame}
    return PaintedSource(master.original,PatchedFrames(master.frames,patches),master.durations,master.loop,master,patches)
