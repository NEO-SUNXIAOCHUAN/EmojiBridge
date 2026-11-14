"""Repeatable QQ local import spike. Run --help; no message sending is implemented."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
from emoji_bridge.client_sources import qq_profile
from PIL import Image, ImageDraw, ImageFont
from emoji_bridge.vision import Match,matches
from emoji_bridge.state import sha,save_json,single_instance,validate_sample,may_submit
from emoji_bridge.animation import classify_frame,playback_confirmed
from emoji_bridge.qq_controls import select_main_candidate
from emoji_bridge.windows import (StopAutomation, qq_windows, activate, guard,
                                  capture, click, user, dialog_action, file_version,hover,restore_pointer,restorable_main,ensure_window_on_screen)


class QQ:
    def __init__(self, config, report):
        self.config = config
        self.exe = Path(config['exe'])
        self.report = report
        self.profile = Path(config['profile_dir'])
        self.window = None
        self.controls = None

    def close(self):
        if self.controls:self.controls.close();self.controls=None

    def native_controls(self):
        from emoji_bridge.qq_controls import FavoriteControls
        if self.controls is None:self.controls=FavoriteControls(self.window,self.exe,getattr(self,'cancel',None))
        return self.controls

    def bind(self):
        from emoji_bridge.qq_window import bind_window
        from emoji_bridge.client_sources import settings
        disabled=settings().get('disabled_sources',{}).get('qq')
        if disabled:raise StopAutomation(disabled)
        self.close()
        self.window=bind_window(self.exe,self.config['version'],self.report,
                                getattr(self,'cancel',None),self.window)
        self.native_controls().ready()
        # Both paths require the same current, unique semantic toolbar.
        self.smile()

    def frame(self):
        guard(self.window, self.exe)
        return capture(self.window)

    def icon(self, frame, key, roi, max_error=0.035):
        variants=self.config.get('variants',{}).get(key,[key])
        candidates=[]
        for variant in variants:
            source = self.profile / (variant + '.png')
            if sha(source) != self.config['templates'][variant]:
                raise StopAutomation('calibration_template_changed')
            from emoji_bridge.client_geometry import client_scale
            factor=client_scale(self.window.dpi)/client_scale(self.config['dpi'])
            with Image.open(source) as original:
                template=original.convert('RGB')
            if factor!=1:
                template=template.resize(tuple(round(n*factor) for n in template.size),Image.Resampling.LANCZOS)
            candidates.extend(matches(frame.crop(roi),template,max_error))
        candidates.sort(key=lambda hit:hit.error)
        found=[]
        for hit in candidates:
            if not any(abs(hit.x-p.x)<=2 and abs(hit.y-p.y)<=2 for p in found):
                found.append(hit)
        self.report.setdefault('recognition',{})[key]={'roi':list(roi),'candidate_count':len(found),
            'matches':[asdict(hit) for hit in found],'max_error':max_error}
        if len(found) != 1:
            raise StopAutomation(key + '_not_uniquely_identified')
        hit = found[0]
        hit.x += roi[0]
        hit.y += roi[1]
        return hit

    def smile(self):
        state=self.native_controls().read('panel')
        self.report['toolbar']={k:state.get(k) for k in ('backend','toolbar_ready','toolbar_rect','panel_open')}
        if not state.get('toolbar_ready'):raise StopAutomation('qq_chat_not_open')
        return self.native_hit(state['toolbar_rect'])

    def native_hit(self,rect):
        guard(self.window,self.exe)
        x,y,right,bottom=self.window.rect
        box=tuple(round(v-(x if i%2==0 else y)) for i,v in enumerate(rect))
        if not (0<=box[0]<box[2]<=right-x and 0<=box[1]<box[3]<=bottom-y):
            raise StopAutomation('favorite_panel_geometry_changed')
        return Match(box[0],box[1],box[2]-box[0],box[3]-box[1],0)

    def click_icon(self, hit, key, roi):
        # Re-identify immediately before clicking. A saved coordinate alone is never enough.
        fresh = self.smile() if key=='smile' else self.panel()[2] if key=='plus' else self.icon(self.frame(), key, roi)
        if fresh.center != hit.center:
            raise StopAutomation('control_moved')
        click(self.window, self.exe, *fresh.center)
        time.sleep(0.35)

    def panel(self):
        # The personal-favorites grid proves the selected tab. A decorative
        # heart's offset/colour does not. Query only panel geometry (no scan).
        state=self.native_controls().read()
        self.report['favorite_panel']={k:state.get(k) for k in ('backend','favorites_open','panel_rect','grid_rect','import_rect','import_ready','favorite_tab_rect')}
        trace=self.report.setdefault('panel_observations',[])
        observation={**self.report['favorite_panel'],'seconds':round(time.monotonic(),3)}
        if not trace or any(trace[-1].get(k)!=observation.get(k) for k in self.report['favorite_panel']):
            trace.append(observation)
            del trace[:-24]
        if not state.get('favorites_open'):raise StopAutomation('qq_uia_personal_favorites_not_open')
        if not state.get('import_ready'):raise StopAutomation('qq_uia_top_not_observed')
        frame=self.frame();x,y=self.window.rect[:2]
        def local(rect):return tuple(round(v-(x if i%2==0 else y)) for i,v in enumerate(rect))
        box=local(state['panel_rect']);grid=local(state['grid_rect']);tile=local(state['import_rect'])
        def contains(a,b):return a[0]<=b[0]<b[2]<=a[2] and a[1]<=b[1]<b[3]<=a[3]
        if not contains((0,0,frame.width,frame.height),box) or not contains(box,grid) or not contains(grid,tile):
            raise StopAutomation('favorite_panel_geometry_changed')
        from emoji_bridge.client_geometry import qq_panel_box
        qq_panel_box(self.window,state)
        from emoji_bridge.client_geometry import qq_native_grid_cells
        self.last_cells=qq_native_grid_cells(state)
        # Import is the unique native sticker-list__import inside the verified
        # personal grid, not a scaled picture of a plus or an individual sticker.
        plus=self.native_hit(state['import_rect'])
        self.import_roi=tile
        return frame.crop(box), box, plus

    def wait_panel(self,timeout=3):
        deadline=time.monotonic()+timeout
        while True:
            if getattr(self,'cancel',None) and Path(self.cancel).exists():raise StopAutomation('cancel_requested')
            try:return self.panel()
            except StopAutomation as err:
                if str(err) not in ('plus_not_uniquely_identified','qq_uia_top_not_observed','qq_uia_personal_favorites_not_open','favorite_panel_geometry_changed','qq_visual_chat_toolbar_not_unique') or time.monotonic()>=deadline:raise
                # Import progress can temporarily change the panel geometry.
                # Observe only; toggling here closes a panel that is still open.
                time.sleep(.15)

    def open_panel(self):
        try:
            return self.panel()
        except StopAutomation as err:
            if str(err) not in ('plus_not_uniquely_identified', 'heart_not_uniquely_identified','favorite_panel_geometry_changed','qq_uia_personal_favorites_not_open','qq_uia_top_not_observed'):
                raise
        # The destination must navigate too: a remembered store/standard tab
        # is not a failed import. Use the existing semantic favorite controls,
        # never toggle the smile blindly or invoke an individual sticker.
        controls=self.native_controls();state=controls.open()
        self.report['favorite_navigation_before']={k:state.get(k) for k in ('at_top','import_ready','import_rect','grid_rect','loaded_cells')}
        state=controls.top(state)
        self.report['favorite_navigation']={'method':'visual_personal_favorites' if state.get('backend')=='visual' else 'native_personal_favorites',
            'actions':list(controls.actions),'favorites_open':True,'at_top':state.get('at_top'),
            'sticker_invocations':0}
        # Fresh native membership and geometry still gate the file picker.
        return self.wait_panel()

    def reopen_panel(self):
        self.panel()
        hit = self.smile()
        self.click_icon(hit, 'smile', tuple(self.config['toolbar_roi']))
        # Closing can briefly retain the grid while removing its import tile.
        # Observe actual closure instead of treating that transition as failure.
        self.native_controls().wait(lambda s:not s.get('panel_open'),'qq_uia_panel_did_not_close')
        hit = self.smile()
        self.click_icon(hit, 'smile', tuple(self.config['toolbar_roi']))
        return self.open_panel()

    def picker(self):
        _, _, plus = self.panel()
        self.click_icon(plus, 'plus', self.import_roi)
        for _ in range(30):
            found = [w for w in qq_windows(self.exe) if w.kind == '#32770'
                     and w.pid == self.window.pid]
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                raise StopAutomation('multiple_file_dialogs')
            time.sleep(0.1)
        raise StopAutomation('file_dialog_not_found')

    def dialog_action(self, dialog, action, file=None, before_submit=None):
        return dialog_action(dialog,self.window,self.exe,action,file,before_submit)


def find_sample(panel, source):
    """Only the anchored favorite grid is searched, never the conversation behind it."""
    scale=panel.width/450
    origin=round(8*scale)
    grid = panel.crop(tuple(round(v*scale) for v in (8,8,442,290)))
    candidates = []
    for size in dict.fromkeys(round(v*scale) for v in (58,60,56,62,54,64,50)):
        ref = source.resize((size,size),Image.Resampling.LANCZOS)
        if source.info.get('stable_height'):
            ref=ref.crop((0,0,size,round(size*source.info['stable_height']/source.height)))
        for hit in matches(grid,ref,max_error=0.055,count=3):
            hit.height=size
            hit.x+=origin;hit.y+=origin
            candidates.append(hit)
    candidates.sort(key=lambda x:x.error)
    distinct=[]
    for hit in candidates:
        if not any(abs(hit.center[0]-p.center[0])<25*scale and abs(hit.center[1]-p.center[1])<25*scale for p in distinct):
            distinct.append(hit)
    return distinct


def verify_animation(qq, panel_box, hit, references, evidence, report):
    x,y=panel_box[0]+hit.x,panel_box[1]+hit.y
    region=(x,y,x+hit.width,y+hit.height)
    previous,expected=hover(qq.window,qq.exe,x+hit.width//2,y+hit.height//2)
    observations=[];states=[];saved={}
    start=time.monotonic()
    try:
        while time.monotonic()-start<6:
            crop=qq.frame().crop(region)
            index,error=classify_frame(crop,references)
            states.append(index)
            observations.append({'elapsed':round(time.monotonic()-start,3),'frame':index,'error':error})
            if index is not None and index not in saved:
                path=evidence/('animation-state-'+str(index)+'.png');crop.save(path)
                saved[index]=str(path)
            time.sleep(0.17)
        # Keep the sample bounded by a confirmed favorite panel at the end, too.
        qq.panel()
    finally:
        restore_pointer(previous,expected)
    passed=playback_confirmed(states,len(references))
    report['animation']={'confirmed':passed,'reference_frames':len(references),
        'observed_frames':sorted(set(x for x in states if x is not None)),
        'observations':observations,'evidence':saved,'method':'hover only; classify known animation states inside favorite cell after panel reopen'}
    return passed


def verify_collection(qq, source, evidence, report, references=None):
    panel, _, _ = qq.open_panel()
    first = find_sample(panel,source)
    if len(first)!=1:
        report['match_count'] = len(first)
        return False
    panel.save(evidence/'favorite-before-reopen.png')
    report['match_before_reopen'] = asdict(first[0])
    panel, panel_box, _ = qq.reopen_panel()
    second = find_sample(panel,source)
    panel.save(evidence/'favorite-after-reopen.png')
    if len(second)!=1:
        report['match_after_reopen_count'] = len(second)
        return False
    report['match_after_reopen'] = asdict(second[0])
    report['desktop_evidence'] = [str(evidence/'favorite-before-reopen.png'),
                                  str(evidence/'favorite-after-reopen.png')]
    report['collection_persisted']=True
    return not references or verify_animation(qq,panel_box,second[0],references,evidence,report)


def add_or_verify(qq, args, report, evidence):
    manifest = validate_sample(args.file,args.manifest)
    with Image.open(args.file) as opened:
        count=getattr(opened,'n_frames',1)
        if opened.format not in ('PNG','GIF') or opened.size!=(320,320) or count not in (1,4):
            raise StopAutomation('unsupported_test_card')
        references=[]
        if count>1:
            for n in range(count):
                opened.seek(n);opened.load();references.append(opened.convert('RGB'))
            if len({hashlib.sha256(f.tobytes()).hexdigest() for f in references})!=count:
                raise StopAutomation('diagnostic_animation_frames_not_distinct')
            opened.seek(0)
        opened.load()
        source=opened.convert('RGB')
        if references:source.info['stable_height']=200
    report['sample'] = manifest
    ledger = ROOT/'runtime-data/T003/qq'/ (manifest['sha256']+'.json')
    prior = json.loads(ledger.read_text(encoding='utf-8')) if ledger.exists() else None
    report['prior_state'] = prior['status'] if prior else None
    qq.bind()
    panel,_,_ = qq.open_panel()
    found = find_sample(panel,source)
    if found:
        if len(found)==1 and verify_collection(qq,source,evidence,report,references):
            report.update(status='already_exists',desktop_confirmed=True,phone='not_confirmed')
            save_json(ledger,{'status':'desktop_confirmed','sample':manifest,'last_report':str(evidence)})
        else:
            report.update(status='pending_confirmation',reason='animation_not_confirmed' if report.get('collection_persisted') else 'favorite_match_not_unique_or_not_persistent')
        return
    if args.command=='verify' or not may_submit(prior):
        report.update(status='pending_confirmation',reason='no_unique_visible_match_no_resubmit')
        return
    # The sample has a new program-generated nonce and no submitted journal entry.
    panel.save(evidence/'favorite-before-import.png')
    report['fresh_sample_not_in_visible_grid']=True
    dialog=qq.picker()
    # Separate selection from the irreversible submission boundary.
    save_json(ledger,{'status':'selection_pending','sample':manifest,
                      'time':datetime.now().astimezone().isoformat(),'report':str(evidence)})
    report['dialog']=asdict(dialog)
    def before_submit():
        if sha(args.file)!=manifest['sha256']:
            raise StopAutomation('source_changed_before_submission')
        save_json(ledger,{'status':'submission_pending','sample':manifest,
                          'time':datetime.now().astimezone().isoformat(),'report':str(evidence)})
        report['submission_started']=True
    report['dialog_selection']=qq.dialog_action(dialog,'Choose',args.file,before_submit)
    report['input_path']=str(args.file)
    # QQ may close its favorite panel while the import animation finishes.
    # Allow that transition before reopening once; never toggle on each poll.
    time.sleep(1.2)
    # Only poll results. Never repeat Choose after a timeout.
    deadline=time.monotonic()+20
    matched=False
    while time.monotonic()<deadline:
        if user.GetForegroundWindow()!=qq.window.hwnd:
            # The exact, still-open modal can finish normally; any other focus means stop.
            if user.GetForegroundWindow()!=dialog.hwnd:
                raise StopAutomation('foreground_changed_after_submission')
            time.sleep(0.25)
            continue
        panel,_,_=qq.open_panel() if not report.get('result_panel_opened') else qq.panel()
        report['result_panel_opened']=True
        found=find_sample(panel,source)
        if len(found)==1:
            matched=True
            break
        if len(found)>1:
            break
        time.sleep(0.35)
    if matched and verify_collection(qq,source,evidence,report,references):
        report.update(status='desktop_confirmed',desktop_confirmed=True,phone='not_confirmed')
    else:
        report.update(status='pending_confirmation',reason='favorite_not_confirmed_no_resubmit')
    save_json(ledger,{'status':report['status'],'sample':manifest,'report':str(evidence),
                      'desktop_confirmed':report.get('desktop_confirmed',False)})


def prepare(animated=False):
    nonce = secrets.token_hex(8)
    folder = ROOT / 'private' / 'T003' / ('sample-' + nonce)
    folder.mkdir(parents=True)
    picture = Image.new('RGB', (320, 320), '#12202e')
    draw = ImageDraw.Draw(picture)
    # Unique, large colored cells survive thumbnailing; a visible label aids manual review.
    palette = ['#ffcc35', '#41cdda', '#f25b82', '#6d7ef2', '#faf7ef']
    for y in range(7):
        for x in range(7):
            value = hashlib.sha256(f'{nonce}:{x}:{y}'.encode()).digest()[0]
            draw.rectangle((20+x*40,20+y*36,57+x*40,53+y*36),fill=palette[value%len(palette)])
    font = ImageFont.load_default(size=20)
    draw.text((20,282), 'T003 '+nonce[:8], fill='white', font=font)
    path = folder / ('T003-' + nonce + ('.gif' if animated else '.png'))
    if animated:
        frames=[]
        for index in range(4):
            frame=picture.copy();d=ImageDraw.Draw(frame)
            d.rectangle((20,211,299,269),fill=palette[index])
            d.text((134,226),str(index+1),fill='black',font=font)
            frames.append(frame)
        frames[0].save(path,save_all=True,append_images=frames[1:],duration=600,loop=0,optimize=False,disposal=2)
    else:picture.save(path)
    manifest = {'sample':str(path), 'sha256':sha(path), 'nonce':nonce,
                'created':datetime.now().astimezone().isoformat(),
                'provenance':'new unique program-generated test card; never imported by this program',
                'format':'GIF' if animated else 'PNG','size':[320,320],
                'frame_count':4 if animated else 1,'duration_ms':2400 if animated else 0}
    save_json(folder/'manifest.json',manifest)
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=['prepare', 'probe', 'inspect-panel', 'inspect-picker','add','verify'])
    ap.add_argument('--config',type=Path)
    ap.add_argument('--file',type=Path,help='Absolute path of a newly prepared test card')
    ap.add_argument('--manifest',type=Path,help='Manifest emitted by prepare')
    ap.add_argument('--animated',action='store_true',help='Prepare a four-state diagnostic GIF')
    args = ap.parse_args()
    if args.command == 'prepare':
        print(json.dumps(prepare(args.animated),ensure_ascii=False,indent=2)); return 0
    report = {'command':args.command,'started':datetime.now().astimezone().isoformat()}
    folder = ROOT/'reports/T003'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder.mkdir(parents=True)
    evidence = ROOT/'private/T003/evidence'/folder.name
    evidence.mkdir(parents=True)
    try:
        with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
            config=json.loads(args.config.read_text(encoding='utf-8')) if args.config else qq_profile()
            if not Path(config['profile_dir']).is_absolute():
                config['profile_dir']=str((args.config.parent/config['profile_dir']).resolve())
            qq = QQ(config, report)
            report['windows'] = [asdict(w) for w in qq_windows(qq.exe)]
            if args.command in ('add','verify'):
                if args.file is None or args.manifest is None:
                    raise StopAutomation('file_and_manifest_required')
                add_or_verify(qq,args,report,evidence)
            else:
                qq.bind()
                report['toolbar_identified'] = True
                if args.command in ('inspect-panel','inspect-picker'):
                    panel, box, _ = qq.open_panel()
                    panel.save(evidence/'panel.png')
                    report['panel_crop'] = str(evidence/'panel.png')
                    report['panel_box'] = box
                    if args.command == 'inspect-picker':
                        dialog = qq.picker()
                        report['dialog'] = asdict(dialog)
                        report['dialog_probe'] = qq.dialog_action(dialog,'Probe')
                        report['dialog_cancel'] = qq.dialog_action(dialog,'Cancel')
                report['status'] = 'probe_passed'
    except (StopAutomation,RuntimeError,ValueError,OSError,KeyError) as exc:
        report.update(status='pending_confirmation' if report.get('submission_started') else 'blocked',
                      reason=str(exc))
    finally:
        report['finished']=datetime.now().astimezone().isoformat()
        save_json(folder/'result.json',report)
    print(json.dumps({'status':report['status'],'reason':report.get('reason'),
                      'report':str(folder/'result.json'),
                      'evidence':report.get('desktop_evidence')},ensure_ascii=False,indent=2))
    return 0 if report['status'] in ('probe_passed','desktop_confirmed','already_exists') else 2


if __name__ == '__main__':
    raise SystemExit(main())
