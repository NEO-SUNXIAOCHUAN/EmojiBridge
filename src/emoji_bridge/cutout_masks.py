"""Original frames plus independently editable, frame-specific masks."""
from collections.abc import Sequence
from PIL import ImageChops


class MaskedFrames(Sequence):
    def __init__(self,originals,masks,overrides=None):
        if len(originals)!=len(masks):raise ValueError('主体原帧与蒙版数量不同')
        self.originals=originals;self.masks=masks;self.overrides=dict(overrides or {})

    def __len__(self):return len(self.originals)

    def mask(self,index):
        return self.overrides[index] if index in self.overrides else self.masks[index].convert('L')

    def __getitem__(self,index):
        if isinstance(index,slice):return [self[i] for i in range(*index.indices(len(self))) ]
        original=self.originals[index].copy();original.putalpha(ImageChops.multiply(original.getchannel('A'),self.mask(index)));return original

    def revised(self,index,mask):
        return MaskedFrames(self.originals,self.masks,{**self.overrides,index:mask})
