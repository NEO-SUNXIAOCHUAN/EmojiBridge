"""Bounded checker cache for the display, independent of exported pixels."""
from PIL import Image,ImageDraw


class Backdrop:
    def __init__(self):self.pattern=None;self.light=None;self.source=None;self.solid=None
    def solid_color(self,source):
        if self.source is not source:
            self.source=source;extrema=source.getextrema()
            self.solid=tuple(a for a,b in extrema) if all(a==b for a,b in extrema) else None
        return self.solid
    def checker(self,size,offset=(0,0),light=False):
        ox,oy=(v%32 for v in offset);needed=(size[0]+ox,size[1]+oy)
        if self.pattern is None or self.light!=light or any(a>b for a,b in zip(needed,self.pattern.size)) or self.pattern.width*self.pattern.height>max(1,size[0]*size[1])*4:
            width,height=(max(32,((v+127)//128)*128) for v in needed)
            tile=Image.new('RGB',(32,32),'#ffffff' if light else '#24272e');d=ImageDraw.Draw(tile)
            color='#e5eaf1' if light else '#30343c';d.rectangle((16,0,31,15),fill=color);d.rectangle((0,16,15,31),fill=color)
            pattern=Image.new('RGB',(width,height));pattern.paste(tile)
            x=32
            while x<width:pattern.paste(pattern.crop((0,0,min(x,width-x),32)),(x,0));x*=2
            y=32
            while y<height:pattern.paste(pattern.crop((0,0,width,min(y,height-y))),(0,y));y*=2
            self.pattern=pattern;self.light=light
        return self.pattern.crop((ox,oy,ox+size[0],oy+size[1]))
