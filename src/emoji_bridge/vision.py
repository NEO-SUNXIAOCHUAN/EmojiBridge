"""Small deterministic template matcher; no model, OCR, network or fixed clicks."""
from dataclasses import dataclass
import numpy as np
from PIL import Image


@dataclass
class Match:
    x: int
    y: int
    width: int
    height: int
    error: float

    @property
    def center(self):
        return (self.x+self.width//2, self.y+self.height//2)


def matches(image: Image.Image, template: Image.Image, max_error=0.035, count=2):
    src = np.asarray(image.convert('RGB'), dtype=np.float32)
    ref = np.asarray(template.convert('RGB'), dtype=np.float32)
    h, width = ref.shape[:2]
    rows, cols = src.shape[0]-h+1, src.shape[1]-width+1
    if rows <= 0 or cols <= 0:
        return []
    # Sample contrasting foreground as well as background. Full pixels verify candidates.
    contrast = np.max(np.abs(ref-ref[0, 0]), axis=2)
    points = np.argwhere(contrast > 25)
    if len(points) < 8:
        return []
    points = points[np.linspace(0, len(points)-1, min(64, len(points)), dtype=int)]
    grid = np.array([(y, x) for y in np.linspace(0, h-1, 6, dtype=int)
                    for x in np.linspace(0, width-1, 6, dtype=int)])
    points = np.concatenate([points, grid])
    scores = np.zeros((rows, cols), dtype=np.float32)
    # Planar channels avoid a strided three-element reduction at every image
    # location. Proposals and full-pixel acceptance use the same thresholds.
    planar=np.ascontiguousarray(np.moveaxis(src,-1,0))
    for y, x in points:
        delta=np.abs(planar[:,y:y+rows,x:x+cols]-ref[y,x,:,None,None])
        scores += (delta[0]+delta[1]+delta[2])/3
    scores /= len(points)*255
    out = []
    for _ in range(12):
        y, x = np.unravel_index(np.argmin(scores), scores.shape)
        if scores[y, x] > max_error:
            break
        err = float(np.mean(np.abs(src[y:y+h, x:x+width]-ref))/255)
        scores[max(0,y-h//2):min(rows,y+h//2+1),
               max(0,x-width//2):min(cols,x+width//2+1)] = np.inf
        if err <= max_error:
            out.append(Match(int(x),int(y),width,h,err))
            if len(out) == count:
                break
    return out
