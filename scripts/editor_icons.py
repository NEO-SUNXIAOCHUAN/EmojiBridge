"""Small original line icons; no icon font dependency or bitmap downloads."""
from PIL import Image,ImageDraw,ImageTk
from ui_style import INK


def tool_icons(master,size=22):
    from ui_dpi import px
    size=px(master,size)
    result={}
    for name in ('select','text','material','shape','background','transform','cutout','paint','effect'):
        im=Image.new('RGBA',(72,72));d=ImageDraw.Draw(im);color=INK
        if name=='select':d.line([(18,12),(18,57),(30,45),(40,63),(48,59),(38,41),(56,41),(18,12)],fill=color,width=4)
        elif name=='text':
            d.line([(15,18),(57,18)],fill=color,width=5);d.line([(36,18),(36,57)],fill=color,width=5);d.line([(24,57),(48,57)],fill=color,width=4)
        elif name=='material':
            d.rounded_rectangle((10,14,62,58),radius=4,outline=color,width=4);d.line([(13,53),(30,34),(42,45),(51,36),(61,49)],fill=color,width=4);d.ellipse((44,23,51,30),fill=color)
        elif name=='shape':d.rectangle((10,13,44,47),outline=color,width=4);d.ellipse((30,30,62,62),outline=color,width=4)
        elif name=='background':
            d.rectangle((12,12,60,60),outline=color,width=4)
            for x,y in ((14,14),(37,37)):d.rectangle((x,y,x+21,y+21),fill=color)
        elif name=='transform':
            d.arc((12,12,60,60),30,310,fill=color,width=4);d.line([(52,9),(59,23),(45,23)],fill=color,width=4)
        elif name=='paint':
            d.polygon([(25,40),(48,13),(60,23),(36,48)],outline=color,width=4)
            d.arc((12,38,37,62),0,290,fill=color,width=4);d.line([(12,58),(8,62),(25,62)],fill=color,width=4)
        elif name=='effect':
            d.polygon([(36,8),(47,28),(64,36),(47,44),(36,64),(25,44),(8,36),(25,28)],outline=color,width=4)
        else:
            d.line([(20,12),(58,57)],fill=color,width=4);d.line([(53,12),(15,57)],fill=color,width=4)
            d.ellipse((8,48,25,65),outline=color,width=4);d.ellipse((48,48,65,65),outline=color,width=4)
        result[name]=ImageTk.PhotoImage(im.resize((size,size),Image.Resampling.LANCZOS),master=master)
    return result
