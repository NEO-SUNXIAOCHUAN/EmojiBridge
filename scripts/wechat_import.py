"""Repeatable WeChat single-sample import via the user's File Transfer Assistant."""
import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from emoji_bridge.paths import DATA_ROOT as ROOT, APP_ROOT
from emoji_bridge.client_sources import executable
from PIL import Image
from emoji_bridge.wechat import WeChat
from emoji_bridge.windows import StopAutomation,qq_windows,dialog_action,guard,capture,click,user
from emoji_bridge.state import validate_sample,sha,save_json,single_instance
from emoji_bridge.vision import matches
from emoji_bridge.animation import classify_frame,playback_confirmed
from qq_import import prepare


def find_picture(picture,source,sizes):
    found=[]
    for size in sizes:
        ref=source.resize((size,size),Image.Resampling.LANCZOS)
        if source.info.get('stable_height'):
            ref=ref.crop((0,0,size,round(size*source.info['stable_height']/320)))
        for m in matches(picture,ref,max_error=.055,count=3):
            m.height=size
            if not any(abs(m.x-p.x)<15 and abs(m.y-p.y)<15 for p in found):found.append(m)
    return found


def relative(rect,window):return tuple(round(v-origin) for v,origin in zip(rect,window.rect[:2]*2))


def verify(q,source,evidence,report,references=None):
    grid,popup,box=q.panel(open_if_closed=True)
    found=find_picture(grid,source,(72,70,74))
    report['favorite_candidates_before']=len(found)
    report['sample_seen_in_favorites']=bool(found)
    grid.save(evidence/'favorite-before-reopen.png')
    if len(found)!=1:
        q.close_popup(popup);return False
    report['favorite_match_before']=asdict(found[0])
    q.close_popup(popup)
    grid,popup,box=q.panel(open_if_closed=True)
    found=find_picture(grid,source,(72,70,74))
    grid.save(evidence/'favorite-after-reopen.png')
    report['favorite_match_after']=[asdict(m) for m in found]
    report['desktop_evidence']=[str(evidence/'favorite-before-reopen.png'),str(evidence/'favorite-after-reopen.png')]
    passed=len(found)==1
    if passed:report['collection_persisted']=True
    if passed and references:
        hit=found[0];states=[];observations=[];saved={}
        started=time.monotonic()
        while time.monotonic()-started<6:
            guard(popup,q.exe)
            cell=capture(popup).crop(box).crop((hit.x,hit.y,hit.x+hit.width,hit.y+hit.height))
            identity=find_picture(cell,source,(hit.width,))
            index,error=classify_frame(cell,references) if len(identity)==1 else (None,None)
            states.append(index);observations.append({'elapsed':round(time.monotonic()-started,3),'frame':index,'error':error})
            if index is not None and index not in saved:
                path=evidence/('animation-state-'+str(index)+'.png');cell.save(path);saved[index]=str(path)
            time.sleep(.17)
        q.uia('panel',popup)
        passed=playback_confirmed(states,len(references))
        report['animation']={'confirmed':passed,'observed_frames':sorted(set(s for s in states if s is not None)),'observations':observations,'evidence':saved}
    q.close_popup(popup)
    return passed


def run(q,args,report,evidence):
    manifest=validate_sample(args.file,args.manifest)
    with Image.open(args.file) as im:
        count=getattr(im,'n_frames',1)
        if im.format!='GIF' or im.size!=(320,320) or count not in (1,4):raise StopAutomation('diagnostic_gif_required')
        references=[]
        if count>1:
            for index in range(count):im.seek(index);references.append(im.convert('RGB'))
            if len({f.tobytes() for f in references})!=count:raise StopAutomation('animation_frames_not_distinct')
            im.seek(0)
        source=im.convert('RGB')
        if references:source.info['stable_height']=200
    report['sample']=manifest
    ledger=ROOT/'runtime-data/T003/wechat'/(manifest['sha256']+'.json')
    prior=json.loads(ledger.read_text(encoding='utf8')) if ledger.exists() else None
    report['prior_state']=prior.get('status') if prior else None
    q.bind()
    if verify(q,source,evidence,report,references):
        report.update(status='already_exists',desktop_confirmed=True)
        save_json(ledger,{'status':'desktop_confirmed','sample':manifest});return
    if report.get('sample_seen_in_favorites'):
        report.update(status='pending_confirmation',reason='favorite_seen_but_not_verified_no_add');return
    resuming=args.command=='resume-staged' and prior and prior['status'] in ('send_pending','input_staged')
    sent_resume=args.command=='resume-sent' and prior and prior['status']=='send_click_pending'
    if args.command=='verify' or (prior and not resuming and not sent_resume):
        report.update(status='pending_confirmation',reason='no_confirmed_favorite_no_resend');return
    if args.command=='resume-staged' and not resuming:raise StopAutomation('no_resumable_staged_input')
    if args.command=='resume-sent' and not sent_resume:raise StopAutomation('no_resumable_sent_input')
    # Record before opening a file: choosing a file may send immediately in a
    # client version. Any interruption from here prevents an automatic resend.
    if not resuming and not sent_resume:
        snap=q.uia()
        if not snap['input_empty']:raise StopAutomation('composer_not_empty')
        save_json(ledger,{'status':'input_pending','sample':manifest})
        q.control('open-file')
        dialogs=[w for w in qq_windows(q.exe) if w.kind=='#32770' and w.pid==q.window.pid]
        if len(dialogs)!=1:raise StopAutomation('file_dialog_not_unique')
        def before_choose():
            if sha(args.file)!=manifest['sha256']:raise StopAutomation('source_changed')
            save_json(ledger,{'status':'send_pending','sample':manifest})
            report['submission_started']=True
        report['file_selection']=dialog_action(dialogs[0],q.window,q.exe,'Choose',args.file,before_choose)
        time.sleep(1)
    # Only observed states can continue; unknown modal or focus changes stop.
    snap=q.uia()
    composer=relative(snap['input'],q.window)
    input_hits=find_picture(q.frame().crop(composer),source,(120,118,122,72,64,60,56,48,40))
    if not snap['input_empty']:
        if sent_resume:raise StopAutomation('sent_resume_requires_empty_composer')
        q.frame().crop(composer).save(evidence/'staged-composer.png')
        report['composer_matches']=[asdict(m) for m in input_hits]
        if len(input_hits)!=1 or not snap.get('input_only_object') or not snap['send_enabled']:
            report.update(status='pending_confirmation',reason='staged_media_requires_identity_check');return
        save_json(ledger,{'status':'input_staged','sample':manifest})
        # Recheck the nonce card and single-object input immediately before send.
        send_meta=q.uia('send');current=relative(send_meta['input'],q.window)
        fresh=find_picture(q.frame().crop(current),source,(input_hits[0].width,))
        if current!=composer or len(fresh)!=1 or fresh[0].center!=input_hits[0].center:raise StopAutomation('staged_sample_changed')
        save_json(ledger,{'status':'send_click_pending','sample':manifest})
        report['submission_started']=True
        target=relative(send_meta['target'],q.window)
        click(q.window,q.exe,(target[0]+target[2])//2,(target[1]+target[3])//2)
        time.sleep(.8)
        snap=q.uia();composer=relative(snap['input'],q.window)
        if not snap['input_empty']:raise StopAutomation('input_not_cleared_after_send_no_retry')
    # If selection already sent, identify this exact nonce card in our own chat.
    header=relative(snap['header'],q.window)
    chat=(composer[0],header[3]+8,composer[2],composer[1]-8)
    hits=find_picture(q.frame().crop(chat),source,(160,156,150,144,140,136,132,128,120,100,80,72))
    if len(hits)!=1:
        report.update(status='pending_confirmation',reason='sent_card_not_uniquely_identified',message_matches=len(hits));return
    report['message_match']=asdict(hits[0])
    image=hits[0]
    # Own-chat identity and sample position are rechecked immediately before menu.
    q.uia()
    fresh=find_picture(q.frame().crop(chat),source,(image.width,))
    if len(fresh)!=1 or fresh[0].center!=image.center:raise StopAutomation('message_moved')
    click(q.window,q.exe,chat[0]+image.center[0],chat[1]+image.center[1],right=True)
    time.sleep(.4)
    menu=q.popup(menu=True);target=q.uia('menu',menu)['target']
    save_json(ledger,{'status':'favorite_pending','sample':manifest})
    report['submission_started']=True
    click(menu,q.exe,round((target[0]+target[2])/2)-menu.rect[0],round((target[1]+target[3])/2)-menu.rect[1],owner=q.window)
    time.sleep(.8)
    if verify(q,source,evidence,report,references):report.update(status='desktop_confirmed',desktop_confirmed=True)
    else:report.update(status='pending_confirmation',reason='favorite_not_confirmed_no_retry')
    save_json(ledger,{'status':report['status'],'sample':manifest})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','probe','add','verify','resume-staged','resume-sent'))
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--file',type=Path);parser.add_argument('--manifest',type=Path)
    parser.add_argument('--animated',action='store_true')
    args=parser.parse_args()
    if args.command=='prepare':
        m=prepare(animated=args.animated);path=Path(m['sample'])
        if not args.animated:
            gif=path.with_suffix('.gif')
            with Image.open(path) as im:im.save(gif,'GIF')
            m.update(sample=str(gif),sha256=sha(gif),format='GIF',conversion='PNG encoded as actual single-frame GIF; PNG retained')
        save_json(path.parent/'manifest.json',m);print(json.dumps(m,ensure_ascii=False,indent=2));return 0
    folder=ROOT/'reports/T003'/('wechat-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir(parents=True)
    evidence=ROOT/'private/T003/evidence'/folder.name;evidence.mkdir(parents=True)
    report={'command':args.command,'started':datetime.now().astimezone().isoformat(),'phone':'not_confirmed'}
    try:
        with single_instance(ROOT/'runtime-data/T003/client-ui.lock'):
            q=WeChat(args.exe or executable('wechat'),report)
            if args.command=='probe':report.update(snapshot=q.bind(),status='probe_passed')
            else:
                if args.file is None or args.manifest is None:raise StopAutomation('file_and_manifest_required')
                run(q,args,report,evidence)
    except (StopAutomation,OSError,ValueError,subprocess.TimeoutExpired) as exc:
        report.update(status='pending_confirmation' if report.get('submission_started') else 'blocked',reason=str(exc))
    finally:
        report['finished']=datetime.now().astimezone().isoformat();save_json(folder/'result.json',report)
    print(json.dumps({'status':report['status'],'reason':report.get('reason'),'report':str(folder/'result.json')},ensure_ascii=False,indent=2))
    return 0 if report['status'] in ('desktop_confirmed','already_exists','probe_passed') else 2


if __name__=='__main__':raise SystemExit(main())
