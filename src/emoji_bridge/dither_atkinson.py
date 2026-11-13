"""Atkinson diffusion adapted from hitherdither (MIT, Henrik Blidh).

Source: hitherdither/diffusion.py, blob 65185dd1d2cfe3813a40180d884ec50b48dfbead.
This reference path is deliberately applied after the requested pixel reduction.
"""
import numpy as np
from PIL import Image

def atkinson(image,colors):
    pixels=np.array(image,dtype=np.float32);palette=np.array(colors,dtype=np.float32)
    for y in range(pixels.shape[0]):
        for x in range(pixels.shape[1]):
            old=np.clip(pixels[y,x],0,255);new=palette[np.argmin(np.sum((palette-old)**2,axis=1))];error=(old-new)/8;pixels[y,x]=new
            for dx,dy in ((1,0),(2,0),(-1,1),(0,1),(1,1),(0,2)):
                nx,ny=x+dx,y+dy
                if 0<=nx<pixels.shape[1] and ny<pixels.shape[0]:pixels[ny,nx]+=error
    return Image.fromarray(pixels.astype('uint8'))
