"""Read-only visual review of saved unresolved favorites. No client automation."""
import argparse
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from ui_style import BG,SURFACE,INK,MUTED,BORDER,SUCCESS,WARNING,ACCENT,apply
from ui_dialogs import prepare_window
from PIL import Image, ImageTk, ImageOps, ImageGrab


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def review(library_path, notes=None):
    library=read(library_path);side=library['clients']['qq'];rows=[];inventories={}
    for item in side['items']:
        if item.get('source_receipt_only'):continue
        prepared=(item.get('original_state')=='ready' and item.get('original_available')
                and bool(item.get('asset')) and not item.get('transfer_block_reason'))
        if prepared and not (notes or {}).get(item['id'],{}).get('show_ready'):continue
        row=dict(id=item['id'],position=item['position'],preview=item.get('preview'),
                 code=item.get('index_reason') or item.get('reason') or 'not_prepared',candidates=[],prepared=prepared)
        evidence_path=item.get('candidate_evidence')
        if evidence_path:
            try:
                evidence=read(evidence_path);inventory_path=evidence['inventory']
                if inventory_path not in inventories:inventories[inventory_path]=read(inventory_path)
                inventory=inventories[inventory_path]
                for entry in inventory['items']:
                    if entry['name'] in evidence.get('candidates',{}):
                        row['candidates'].append(dict(preview=entry.get('preview'),metadata=entry.get('metadata',{})))
                row['evidence']=str(evidence_path)
            except (OSError,ValueError,KeyError) as exc:
                row['evidence_error']=type(exc).__name__
        n=len(row['candidates'])
        row['reason']=(f'有 {n} 份文件的画面通过比较，尚不能唯一确定。' if n>1 else
                       '已看到收藏预览，但尚无通过完整对应检查的原件；不能据此判断文件丢失。')
        row['badge']='尚待对应'
        note=(notes or {}).get(item['id'],{})
        # Notes explain prior evidence; they never change readiness or attach files.
        for key in ('reason','badge','history','comparison_previews','priority','evidence_note'):
            if key in note:row[key]=note[key]
        rows.append(row)
    rows.sort(key=lambda r:(r.get('priority',1),r['position']))
    return dict(library=str(Path(library_path).resolve()),snapshot_at=side.get('snapshot_at'),
                observed=len(side['items']),pending=sum(not r['prepared'] for r in rows),rows=rows,
                client_operations=0,source_library_modified=False)


def preview(path,box):
    if not path:return None
    try:
        with Image.open(path) as im:
            frame=ImageOps.exif_transpose(im).convert('RGBA')
        # Saved tiny observations stay visibly pixelated, never fabricated detail.
        method=Image.Resampling.NEAREST if max(frame.size)<=80 else Image.Resampling.LANCZOS
        return ImageOps.contain(frame,box,method)
    except (OSError,ValueError):return None


class ReviewWindow:
    def __init__(self,root,report):
        self.root=root;self.report=report;self.images=[];self.cards=[];self.draw_after=None
        root.title('表情互通 · 本轮准备结果（只读查看）' if any(r['prepared'] for r in report['rows']) else '表情互通 · 未对应项目（只读查看）')
        width=min(1180,root.winfo_screenwidth()-60);height=min(950,root.winfo_screenheight()-100)
        root.geometry(f'{width}x{height}+30+40');root.minsize(700,500)
        apply(root);root.configure(bg=BG)
        title_text='本轮项目已准备：外观匹配，完整文件已保留' if report['rows'] and not report['pending'] else '这些收藏已经看到了，卡在“对应完整原件”'
        title=tk.Label(root,text=title_text,font=('Microsoft YaHei UI',18,'bold'),
                       bg=BG,fg=INK);title.pack(anchor='w',padx=18,pady=(14,6))
        tk.Label(root,text=f'QQ 保存列表：{report["observed"]} 项；本窗口展示 {len(report["rows"])} 项，仍待对应 {report["pending"]} 项。读取时间：{report["snapshot_at"]}',
                 bg=BG,fg=MUTED,font=('Microsoft YaHei UI',10)).pack(anchor='w',padx=18)
        tk.Label(root,text='点击卡片看原因和候选对照。这里是收藏面板预览的放大图，不是可搬运原件。',
                 bg=BG,fg=MUTED,font=('Microsoft YaHei UI',10)).pack(anchor='w',padx=18,pady=(4,10))
        area=tk.Frame(root,bg=BG);area.pack(fill='both',expand=True,padx=14)
        self.canvas=tk.Canvas(area,bg=BG,highlightthickness=0,yscrollincrement=35)
        from ui_scroll import OverlayScrollbar
        bar=OverlayScrollbar(self.canvas);self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',self.schedule_draw)
        self.canvas.bind('<Button-1>',self.open_card)
        self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units'))
        tk.Label(root,text='只查看已保存的记录；不重新扫描，不发送，不添加，不改变收藏状态。',
                 bg=BG,fg=MUTED,font=('Microsoft YaHei UI',10)).pack(anchor='w',padx=18,pady=10)

    def schedule_draw(self,event):
        if self.draw_after:self.root.after_cancel(self.draw_after)
        self.draw_after=self.root.after(50,self.draw)

    def draw(self):
        self.draw_after=None;c=self.canvas;c.delete('all');self.images=[];self.cards=[]
        cols=4 if c.winfo_width()>=1000 else 3
        w=c.winfo_width()/cols;h=252
        for n,row in enumerate(self.report['rows']):
            x=(n%cols)*w+5;y=(n//cols)*h+5
            c.create_rectangle(x,y,x+w-10,y+h-10,fill=SURFACE,outline=BORDER)
            c.create_text(x+12,y+10,anchor='nw',text=f'QQ 第 {row["position"]} 项',font=('Microsoft YaHei UI',12,'bold'),fill=INK)
            image=preview(row['preview'],(116,116))
            if image:
                photo=ImageTk.PhotoImage(image);self.images.append(photo)
                c.create_image(x+w/2-5,y+94,image=photo)
            else:c.create_text(x+w/2-5,y+94,text='保存预览不可用',fill=WARNING)
            color=SUCCESS if row['prepared'] else ACCENT if row.get('history') else WARNING
            c.create_text(x+12,y+158,anchor='nw',text=row['badge'],fill=color,font=('Microsoft YaHei UI',10,'bold'))
            c.create_text(x+12,y+183,anchor='nw',text=row['reason'],width=w-34,fill=MUTED,font=('Microsoft YaHei UI',9))
            self.cards.append((x,y,x+w-10,y+h-10,row))
        c.configure(scrollregion=(0,0,c.winfo_width(),((len(self.cards)+cols-1)//cols)*h))

    def open_card(self,event):
        x=self.canvas.canvasx(event.x);y=self.canvas.canvasy(event.y)
        for l,t,r,b,row in self.cards:
            if l<=x<=r and t<=y<=b:self.detail(row);return

    def detail(self,row):
        win=tk.Toplevel(self.root);win.title(f'QQ 第 {row["position"]} 项 · '+('准备结果' if row['prepared'] else '为什么尚未对应'))
        win.geometry('880x590');win.configure(bg=BG);win.images=[];prepare_window(win,self.root)
        tk.Label(win,text=f'第 {row["position"]} 项：{row["badge"]}',font=('Microsoft YaHei UI',17,'bold'),
                 bg=BG,fg=INK).pack(anchor='w',padx=18,pady=14)
        tk.Label(win,text=row['reason'],wraplength=820,justify='left',font=('Microsoft YaHei UI',11),
                 bg=BG,fg=MUTED).pack(anchor='w',padx=18)
        images=tk.Frame(win,bg=BG);images.pack(fill='x',padx=18,pady=15)
        entries=[dict(preview=row['preview'],caption='收藏面板中的这一张\n保存的小预览，放大显示')]
        entries += [dict(entry,caption=f'候选文件 {n+1}\n'+('选择结果见上方说明' if row['prepared'] else '仅展示预览，尚未选定')) for n,entry in enumerate(row['candidates'])]
        entries += row.get('comparison_previews',[])
        for entry in entries[:4]:
            box=tk.Frame(images,bg=SURFACE);box.pack(side='left',padx=(0,12))
            im=preview(entry.get('preview'),(190,210))
            if im:
                photo=ImageTk.PhotoImage(im);win.images.append(photo)
                tk.Label(box,image=photo,bg=SURFACE,fg=INK,width=195,height=220).pack()
            else:tk.Label(box,text='暂无保存预览',bg=SURFACE,fg=INK,width=24,height=12).pack()
            tk.Label(box,text=entry['caption'],bg=SURFACE,fg=INK,font=('Microsoft YaHei UI',9),wraplength=195).pack(pady=5)
        explanation=row.get('history') or '尚没有足够证据把这条收藏唯一对应到完整原件；不代表收藏本身已坏或不存在。'
        tk.Label(win,text=explanation,wraplength=820,justify='left',bg=BG,fg=MUTED,
                 font=('Microsoft YaHei UI',11)).pack(anchor='w',padx=18,pady=8)
        if row.get('evidence_note'):
            tk.Label(win,text=row['evidence_note'],wraplength=820,justify='left',bg=BG,fg=MUTED,
                     font=('Microsoft YaHei UI',9)).pack(anchor='w',padx=18)
        ttk.Button(win,text='关闭对照',command=win.destroy).pack(side='bottom',pady=12)


def main():
    p=argparse.ArgumentParser();p.add_argument('--library',type=Path,required=True)
    p.add_argument('--notes',type=Path);p.add_argument('--report',type=Path);p.add_argument('--screenshot',type=Path)
    args=p.parse_args();report=review(args.library,read(args.notes) if args.notes else None)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    root=tk.Tk();app=ReviewWindow(root,report)
    if args.screenshot:
        def capture():
            root.update_idletasks();args.screenshot.parent.mkdir(parents=True,exist_ok=True)
            ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),
                                root.winfo_rooty()+root.winfo_height()),all_screens=True).save(args.screenshot)
        root.after(1200,capture)
    root.mainloop()


if __name__=='__main__':main()
