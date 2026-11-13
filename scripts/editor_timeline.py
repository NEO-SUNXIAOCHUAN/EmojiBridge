"""Editor playback strip reusing the clip timeline worker, zoom and pan."""
from PIL import Image
from video_timeline import ClipTimeline,clock
from ui_style import FONT,INK,MUTED,ACCENT


class AnimationCovers:
    def __init__(self,source,document=None,exclude=()):
        self.source=source;self.document=document;self.exclude=exclude;self.metadata={'duration':sum(source.durations)/1000}

    def get(self,seconds,width,cancel):
        index,_=self.source.frame_at(min(seconds*1000,sum(self.source.durations)-1))
        if self.document is None:
            image=self.source.frames[index].copy();image.thumbnail((width,width),Image.Resampling.LANCZOS);return image
        # Reuse the editor's display rasterizer; tiny covers must not allocate
        # and composite an entire full-resolution work for every scrub/refresh.
        from layout_editor import preview_layer
        from emoji_bridge.animated_edit import layer_frame,check_cancel
        scale=min(1,width/max(self.document.size));size=tuple(max(1,round(v*scale)) for v in self.document.size)
        image=self.document._state.base.resize(size,Image.Resampling.LANCZOS)
        for layer in self.document.layers:
            check_cancel(cancel)
            if layer['id'] in self.exclude or layer.get('visible') is False:continue
            if layer.get('animation'):layer={**layer,'image':layer_frame(layer,self.source,index)}
            elapsed=sum(self.source.durations[:index])
            if layer.get('text_motion'):layer={**layer,'_elapsed':elapsed}
            if layer.get('tracking'):
                from emoji_bridge.tracking import tracked_layer
                layer=tracked_layer(layer,elapsed)
            display=preview_layer(layer,scale)
            try:image.alpha_composite(display,tuple(round(v*scale) for v in layer['position']))
            finally:display.close()
        return image


class EditorTimeline(ClipTimeline):
    """Same range handles, pan and zoom as video; source layers remain intact."""
    def __init__(self,parent,changed):
        super().__init__(parent,changed)
        self.configure(height=86)
        self.pack_propagate(False)
        self.canvas.configure(height=86)
        self.canvas.pack_configure(fill='both',expand=True)

    @property
    def band_top(self):return 26
    @property
    def band_bottom(self):return max(48,self.canvas.winfo_height()-22)
    @property
    def footer_offset(self):return 16

