"""Scalable rounded ttk surfaces. Keep native focus, commands and keyboard behavior."""
from PIL import Image, ImageDraw, ImageTk
from ui_dpi import px


def rounded_elements(root, style, tokens):
    # Tk's primary-button trough binding only repeats +/-1, and never starts
    # dragging. Use its existing Jump binding for press-anywhere scrubbing;
    # native capture, release and keyboard bindings stay intact.
    root.tk.call('bind','TScale','<Button-1>','ttk::scale::Jump %W %x %y')
    # Each embedded page reapplies the shared theme. Image elements live for
    # the interpreter, but style values must be restored on every application.
    for name in ('Horizontal.TScale','Horizontal.TProgressbar'):
        style.configure(name,background=tokens['surface'],borderwidth=0,
                        bordercolor=tokens['surface'],lightcolor=tokens['surface'],darkcolor=tokens['surface'])
        style.map(name,background=[('!disabled',tokens['surface']),('disabled',tokens['surface'])])
    if 'Midnight.Button' in style.element_names():
        return
    photos = []
    def image(fill, line=None, radius=8, background=None):
        source = Image.new('RGBA', (96,96),background or tokens['background'])
        ImageDraw.Draw(source).rounded_rectangle((1,1,94,94), radius*3, fill=fill, outline=line, width=3)
        photo = ImageTk.PhotoImage(source.resize((px(root,32),px(root,32)), Image.Resampling.LANCZOS), master=root)
        photos.append(photo)
        return photo
    surface=tokens['surface']; raised=tokens['raised']; selected=tokens['selected']
    for element, normal, hover, pressed in (
        ('Midnight.Button',surface,raised,selected),
        ('Midnight.Primary',tokens['primary'],'#f7f7fa','#c8c8d1'),
        ('Midnight.Tool',tokens['background'],surface,selected),
    ):
        style.element_create(element, 'image', image(normal),
            ('disabled',image(surface)), ('pressed',image(pressed)),
            ('focus',image(normal,tokens['accent'])), ('selected',image(selected)),
            ('active',image(hover)), border=px(root,12), padding=0, sticky='nsew')
    def button(element):
        return [(element,{'sticky':'nsew','children':[('Button.padding',{'sticky':'nsew','children':[('Button.label',{'sticky':'nsew'})]})]})]
    style.layout('TButton',button('Midnight.Button'))
    for name in ('Editor.Primary.TButton','Video.Primary.TButton'):
        style.layout(name,button('Midnight.Primary'))
    style.layout('Editor.Tool.TButton',button('Midnight.Tool'))
    style.element_create('Midnight.PanelButton','image',image(raised,background=surface),
        ('disabled',image(surface,background=surface)),('pressed',image(selected,background=surface)),
        ('focus',image(raised,tokens['accent'],background=surface)),
        ('active',image(selected,background=surface)),border=px(root,12),padding=0,sticky='nsew')
    style.layout('Panel.TButton',button('Midnight.PanelButton'))
    style.configure('Panel.TButton',background=surface)
    style.map('Panel.TButton',background=[('!disabled',surface),('disabled',surface)])
    # ttk paints a widget rectangle before the image. Match that rectangle to
    # the workspace so the alpha corners do not expose a square/white backing.
    for name in ('TButton','TMenubutton','Editor.Primary.TButton','Video.Primary.TButton','Editor.Tool.TButton'):
        style.configure(name,background=tokens['background'])
        style.map(name,background=[('disabled',tokens['background']),('!disabled',tokens['background'])])
    style.configure('TEntry',background=tokens['background'])
    style.element_create('Midnight.Field','image',image(surface,tokens['border'],10),
        ('disabled',image(tokens['background'],tokens['border'],10)),
        ('focus',image(surface,tokens['accent'],10)),border=px(root,11),padding=0,sticky='nsew')
    style.layout('TEntry',[('Midnight.Field',{'sticky':'nsew','children':[('Entry.padding',{'sticky':'nsew','children':[('Entry.textarea',{'sticky':'nsew'})]})]})])
    # Retain ttk's arrow element names: the class bindings use identify() to
    # distinguish stepping/opening from text selection and IME composition.
    style.layout('TSpinbox',[('Midnight.Field',{'sticky':'nsew','children':[('Spinbox.padding',{'sticky':'nsew','children':[
        ('null',{'side':'right','sticky':'','children':[
            ('Spinbox.uparrow',{'side':'top','sticky':'e'}),
            ('Spinbox.downarrow',{'side':'bottom','sticky':'e'})]}),
        ('Spinbox.textarea',{'sticky':'nsew'})]})]})])
    style.layout('TCombobox',[('Midnight.Field',{'sticky':'nsew','children':[('Combobox.padding',{'sticky':'nsew','children':[
        ('Combobox.downarrow',{'side':'right','sticky':'ns'}),
        ('Combobox.textarea',{'sticky':'nsew'})]})]})])
    for name in ('TCombobox','TSpinbox'):
        style.configure(name,background=tokens['background'],arrowsize=12,padding=(9,5),bordercolor=surface,lightcolor=surface,darkcolor=surface)
        style.map(name,background=[('!disabled',tokens['background'])],arrowcolor=[('disabled',tokens['muted']),('active',tokens['ink'])])
    style.layout('Input.TFrame',[('Midnight.Field',{'sticky':'nsew'})])
    def rail(fill, knob=False):
        source=Image.new('RGBA',(72,72))
        d=ImageDraw.Draw(source)
        if knob:d.ellipse((12,12,60,60),fill=fill)
        else:d.rounded_rectangle((2,30,70,42),radius=6,fill=fill)
        photo=ImageTk.PhotoImage(source.resize((px(root,24),px(root,24)),Image.Resampling.LANCZOS),master=root)
        photos.append(photo);return photo
    # Keep the *slider/*trough suffixes used by ttk's normal mouse and keyboard
    # bindings. The 24px hit area surrounds a visually quiet 4px track.
    style.element_create('Midnight.Scale.trough','image',rail(tokens['border']),border=px(root,5),sticky='ew')
    style.element_create('Midnight.Scale.slider','image',rail(tokens['ink'],True),
                         ('disabled',rail(tokens['muted'],True)),('pressed',rail(tokens['accent'],True)),
                         ('focus',rail(tokens['accent'],True)),('active',rail(tokens['accent'],True)))
    style.layout('Horizontal.TScale',[('Midnight.Scale.trough',{'sticky':'ew','children':[
        ('Midnight.Scale.slider',{'side':'left','sticky':''})]})])
    for part,color in [('trough',surface),('pbar',tokens['accent'])]:
        source=Image.new('RGBA',(24,24));ImageDraw.Draw(source).rounded_rectangle((0,0,23,23),radius=11,fill=color)
        photo=ImageTk.PhotoImage(source.resize((px(root,8),px(root,8)),Image.Resampling.LANCZOS),master=root);photos.append(photo)
        style.element_create('Midnight.Progressbar.'+part,'image',photo,border=px(root,3),sticky='nsew')
    style.layout('Horizontal.TProgressbar',[('Midnight.Progressbar.trough',{'sticky':'ew','children':[
        ('Midnight.Progressbar.pbar',{'side':'left','sticky':'ns'})]})])
    style.layout('TMenubutton',[('Midnight.Button',{'sticky':'nsew','children':[('Menubutton.padding',{'sticky':'nsew','children':[('Menubutton.indicator',{'side':'right','sticky':''}),('Menubutton.label',{'sticky':'nswe'})]})]})])
    style.element_create('Midnight.Tab','image',image(tokens['background']),
        ('selected',image(raised)),('active',image(surface)),border=px(root,11),padding=0,sticky='nsew')
    tabs=[('Midnight.Tab',{'sticky':'nsew','children':[('Notebook.padding',{'sticky':'nsew','children':[('Notebook.label',{'sticky':'nsew'})]})]})]
    for name in ('TNotebook.Tab','Editor.TNotebook.Tab'):
        style.layout(name,tabs)
        style.map(name,foreground=[('selected',tokens['ink']),('!selected',tokens['muted'])])
    root._midnight_images=photos
