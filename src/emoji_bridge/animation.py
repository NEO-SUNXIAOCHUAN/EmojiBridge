"""Classify known diagnostic GIF frames; pixel changes alone never prove playback."""
import numpy as np
from PIL import Image


def classify_frame(crop, references, max_error=0.055):
    width,height=crop.size
    # Check two flat interior patches of the known strip. Border resampling and
    # QQ's hover tint must not be mistaken for frame changes. Identity is checked
    # separately in the invariant top of the same favorite cell.
    boxes=[(round(width*x1/320),round(height*222/320),
            round(width*x2/320),round(height*253/320)) for x1,x2 in ((36,108),(204,276))]
    actual=np.concatenate([np.asarray(crop.convert('RGB').crop(b),dtype=np.float32).reshape(-1,3) for b in boxes])
    errors=[]
    for ref in references:
        target=ref.resize(crop.size,Image.Resampling.LANCZOS)
        pixels=np.concatenate([np.asarray(target.crop(b),dtype=np.float32).reshape(-1,3) for b in boxes])
        errors.append(float(np.mean(np.abs(actual-pixels))/255))
    order=np.argsort(errors)
    best=int(order[0])
    unique=len(order)>1 and errors[int(order[1])]-errors[best]>=0.015
    return (best if errors[best]<=max_error and unique else None),errors[best]


def playback_confirmed(observations, reference_count):
    states=[x for x in observations if x is not None]
    transitions=sum(a!=b for a,b in zip(states,states[1:]))
    return reference_count>1 and len(set(states))==reference_count and transitions>=reference_count-1
