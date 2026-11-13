"""Coalesce pointer motion before Tk's native pane geometry work, not after it.

Use Tk's own sash constraints/capture. Release commits the latest pointer before
the widget's persistence handlers; no document or view-scale changes here.
"""
class SashMotion:
    def __init__(self, pane):
        self.pane=pane;self.pending=None;self.timer=None
        self.tag=f'SashMotion:{pane}'
        pane.bindtags((self.tag,)+pane.bindtags())
        for button in (1,2):
            pane.bind_class(self.tag,f'<B{button}-Motion>',lambda e,b=button:self.move(e,b))
            pane.bind_class(self.tag,f'<ButtonRelease-{button}>',lambda e:self.flush())
        pane.bind('<Destroy>',self.close,add='+')
    def move(self,event,button):
        self.pending=(event.x,event.y,1 if button==1 else 0)
        if self.timer is None:self.timer=self.pane.after(16,self.flush)
        return 'break'
    def flush(self):
        if self.timer is not None:self.pane.after_cancel(self.timer);self.timer=None
        pending=self.pending;self.pending=None
        if pending:
            self.pane.tk.call('::tk::panedwindow::DragSash',self.pane._w,*pending)
    def close(self,event):
        if event.widget is not self.pane:return
        if self.timer is not None:self.pane.after_cancel(self.timer);self.timer=None
        self.pending=None
        for button in (1,2):
            self.pane.unbind_class(self.tag,f'<B{button}-Motion>')
            self.pane.unbind_class(self.tag,f'<ButtonRelease-{button}>')
