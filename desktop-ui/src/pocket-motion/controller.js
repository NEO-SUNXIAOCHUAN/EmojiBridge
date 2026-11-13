/* Presentation state only. This file never starts a transfer or infers success. */
(function(root){
  'use strict';
  const SPAWN_SECONDS=.45, SETTLE_SECONDS=2.2;
  const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k);
  const text=v=>v==null?'':String(v);
  const statusOf=o=>text(o.status??o.phase??'idle').toLowerCase();
  const manualReasons=new Set(['','manual','user','user_pause','user_paused','manual_pause','manual_paused','用户暂停','手动暂停','cancelled','canceled','user_cancel']);
  const pendingReasons=new Set(['waiting_confirmation','pending_confirmation','awaiting_confirmation','waiting_for_user','client_processing','awaiting_result']);
  const working=new Set(['working','running','preparing','transferring','fetching_original','processing']);
  const waiting=new Set(['waiting','pending','pending_confirmation','submitted','awaiting_confirmation']);
  const failure=new Set(['blocked','failed','failure','error','interrupted']);
  function hasError(s){
    const state=statusOf(s);
    if(failure.has(state))return true;
    if(s.blockingError===true||typeof s.blockingError==='string'&&s.blockingError.length>0||s.blockingError&&typeof s.blockingError==='object')return true;
    if(s.errorCode!=null&&text(s.errorCode).trim()!=='')return true;
    if(s.error&&s.error!==false)return true;
    if((state==='partial'||state==='completed_with_errors')&&Number(s.failed)>0)return true;
    if(state==='paused'){
      const reason=text(s.pauseReason??s.reason).toLowerCase();
      if(!manualReasons.has(reason)&&!pendingReasons.has(reason))return true;
      if(Number(s.failed)>0&&reason==='')return true;
    }
    return false;
  }
  function createModel(initial={},options={}){
    const now=options.now||(()=>root.performance?.now?.()??Date.now());
    const motion=options.motion||((time,phase)=>root.EmojiBridgeStage?.motion?.(time,phase)||{x:244,pose:'wait',time,alpha:1});
    let raw={status:'idle',completed:0,total:null,failed:0},phase='idle',elapsed=0,last=now(),suspended=false,reduced=false,pearlTime=0;
    let taskId=null,attempt=0,lastSeq=null,errorLatch=null,paused=null,successSeen=false,lastRetryToken=null;
    const retiredTasks=new Map();
    function sync(){
      const current=now(),delta=Math.max(0,(current-last)/1000);last=current;
      if(!suspended&&phase!=='paused'){elapsed+=delta;pearlTime+=delta;}
      if(phase==='spawning'&&elapsed>=SPAWN_SECONDS){elapsed-=SPAWN_SECONDS;phase='working';}
    }
    function enter(next){if(phase!==next){phase=next;elapsed=0;}}
    function clearResult(){errorLatch=null;successSeen=false;paused=null;}
    function update(next={}){
      sync();
      if(!next||typeof next!=='object')return{accepted:false,reason:'invalid_snapshot'};
      const incomingId=own(next,'taskId')?text(next.taskId):taskId;
      let incomingAttempt=own(next,'attempt')?Number(next.attempt):attempt;
      if(!Number.isFinite(incomingAttempt)||incomingAttempt<0)return{accepted:false,reason:'invalid_attempt'};
      const switching=incomingId!==taskId;
      if(switching&&taskId!==null&&!next.newTask)return{accepted:false,reason:'task_identity_mismatch'};
      if(switching&&retiredTasks.has(incomingId)&&
          (incomingAttempt<=retiredTasks.get(incomingId)||!working.has(statusOf(next))&&statusOf(next)!=='queued'))return{accepted:false,reason:'retired_task'};
      if(!switching&&incomingAttempt<attempt)return{accepted:false,reason:'stale_attempt'};
      const retryToken=next.retry===true&&(own(next,'eventId')||own(next,'seq'))?[incomingId,own(next,'attempt')?next.attempt:'implicit',next.eventId??next.seq].join(':'):null;
      if(retryToken!==null&&retryToken===lastRetryToken)return{accepted:false,reason:'duplicate_retry_command'};
      let fresh=switching||incomingAttempt>attempt;
      if(next.retry===true&&!fresh){incomingAttempt=attempt+1;fresh=true;}
      const seq=own(next,'seq')?Number(next.seq):null;
      if(seq!==null&&!Number.isFinite(seq))return{accepted:false,reason:'invalid_sequence'};
      if(!fresh&&seq!==null&&lastSeq!==null&&seq<=lastSeq)return{accepted:false,reason:'duplicate_or_stale_sequence'};
      if(fresh){
        if(switching&&taskId!==null)retiredTasks.set(taskId,attempt);
        if(retiredTasks.size>64)retiredTasks.delete(retiredTasks.keys().next().value);
        if(switching)lastRetryToken=null;
        taskId=incomingId;attempt=incomingAttempt;lastSeq=null;clearResult();
        raw={status:'idle',completed:0,total:null,failed:0};phase='idle';elapsed=0;
      }
      let incomingStatus=own(next,'status')?text(next.status):own(next,'phase')?text(next.phase):null;
      if(next.retry===true&&incomingStatus===null)incomingStatus='working';
      if(next.acknowledge===true&&incomingStatus===null)incomingStatus='idle';
      const candidate={...raw,...next,status:incomingStatus??raw.status,taskId,attempt};
      // Command metadata is not task state; an old retry flag must never survive.
      delete candidate.retry;delete candidate.newTask;delete candidate.acknowledge;
      const st=statusOf(candidate);
      const cancelled=st==='cancelled'||st==='canceled';
      if(next.acknowledge===true||cancelled){errorLatch=null;paused=null;candidate.error=null;candidate.errorCode=null;candidate.blockingError=false;candidate.reason=null;candidate.pauseReason=null;}
      // A confirmed result cannot regress to working from a late same-attempt callback.
      if(successSeen&&!fresh&&!errorLatch&&(working.has(st)||waiting.has(st)||st==='paused'||st==='queued')&&!hasError(candidate))return{accepted:false,reason:'terminal_regression'};
      if(seq!==null)lastSeq=seq;
      if(retryToken!==null)lastRetryToken=retryToken;
      raw=candidate;
      if(own(next,'reduceMotion'))reduced=!!next.reduceMotion;
      if(!cancelled&&hasError(candidate))errorLatch={errorCode:candidate.errorCode??null,error:candidate.error??null,reason:candidate.pauseReason??candidate.reason??null};
      if(errorLatch){paused=null;enter('blocked');return{accepted:true,reason:'blocking_error'};}
      if(cancelled){enter('cancelled');return{accepted:true,reason:'cancelled'};}
      // Generic job completion may only mean submission finished. A host must
      // supply target confirmation, or an explicitly normalized success state.
      if(st==='success'||st==='confirmed'||st==='completed'&&candidate.confirmed===true){
        paused=null;
        if(!successSeen){phase='success';elapsed=0;successSeen=true;}
        else if(phase!=='success'){phase='success';elapsed=SETTLE_SECONDS;}
        return{accepted:true,reason:'confirmed_success'};
      }
      if(st==='queued'){enter('queued');paused=null;return{accepted:true,reason:'queued_no_submission'};}
      if(st==='paused'){
        if(pendingReasons.has(text(candidate.pauseReason??candidate.reason).toLowerCase())){enter('waiting');paused=null;return{accepted:true,reason:'awaiting_confirmation'};}
        if(phase!=='paused'){
          paused={phase,elapsed,settled:phase==='success'&&elapsed>=SETTLE_SECONDS||phase==='cancelled'&&elapsed>=.35,visual:{...(raw.visual||motion(elapsed,phase))}};
          enter('paused');
        }
        return{accepted:true,reason:'manual_pause'};
      }
      if(working.has(st)){
        if(phase==='paused'&&paused&&(paused.phase==='working'||paused.phase==='spawning')){phase=paused.phase;elapsed=paused.elapsed;paused=null;}
        else if(phase==='idle'||phase==='queued'||phase==='cancelled'||fresh){phase='spawning';elapsed=0;paused=null;}
        else if(phase!=='spawning'&&phase!=='working'){enter('working');paused=null;}
        return{accepted:true,reason:'active'};
      }
      if(waiting.has(st)||st==='partial'||st==='completed_with_errors'||st==='completed'){
        if(phase==='paused'&&paused?.phase==='waiting'){phase='waiting';elapsed=paused.elapsed;paused=null;}
        else {enter('waiting');paused=null;}
        return{accepted:true,reason:'awaiting_confirmation'};
      }
      if(st!=='idle'){enter('waiting');paused=null;return{accepted:true,reason:'unknown_status_waiting'};}
      enter('idle');paused=null;return{accepted:true,reason:'idle'};
    }
    function sample(){
      sync();
      const settled=phase==='success'&&elapsed>=SETTLE_SECONDS||phase==='cancelled'&&elapsed>=.35;
      const scene={...raw,rawStatus:raw.status,phase,settled,reduceMotion:reduced,pearlTime,taskId,attempt};
      if(errorLatch){scene.blockingError=true;scene.errorCode=errorLatch.errorCode;scene.failureReason=errorLatch.reason;}
      if(phase==='paused'&&paused){scene.visual={...paused.visual};scene.pausedScenePhase=paused.phase;scene.pausedElapsed=paused.elapsed;scene.pausedSceneElapsed=paused.elapsed;scene.pausedSceneSettled=paused.settled;}
      // Visible pearls and water are intentionally animated. Frozen/hidden/reduced
      // states do not schedule a frame loop; a new real event redraws once.
      return{scene,elapsed,animate:!suspended&&!reduced&&phase!=='paused'&&phase!=='queued',suspended};
    }
    function setSuspended(value){sync();suspended=!!value;last=now();}
    function setReducedMotion(value){sync();reduced=!!value;}
    function getTaskState(){return{...raw,taskId,attempt,lastSeq};}
    update(initial);
    return{update,sample,setSuspended,setReducedMotion,getTaskState};
  }
  function createController(canvas,initial={},options={}){
    const doc=options.document||root.document;
    const raf=options.requestAnimationFrame||root.requestAnimationFrame.bind(root),caf=options.cancelAnimationFrame||root.cancelAnimationFrame.bind(root);
    const media=options.mediaQuery||(root.matchMedia?root.matchMedia('(prefers-reduced-motion: reduce)'):{matches:false,addEventListener(){},removeEventListener(){}});
    const stage=options.stage||root.EmojiBridgeStage;
    if(!stage?.render)throw new Error('Load stage.js before creating the motion controller.');
    if(!options.stage&&(!root.EmojiBridgeCharacter?.drawCharacter||!root.EmojiBridgeEffects?.drawPearl))throw new Error('搬运角色资源未完整加载，任务不受影响，请重开界面');
    const model=createModel(initial,{now:options.now,motion:stage.motion}),ctx=canvas.getContext('2d');
    let frame=0,settleTimer=0,folded=false,hidden=!!doc?.hidden,destroyed=false,reduceOverride=null,presentationKey=null;
    const delay=options.setTimeout||root.setTimeout.bind(root),undelay=options.clearTimeout||root.clearTimeout.bind(root);
    const setSuspension=()=>model.setSuspended(folded||hidden);
    const effectiveReduced=()=>reduceOverride===null?!!media.matches:reduceOverride;
    model.setReducedMotion(effectiveReduced());setSuspension();
    function size(){
      const ratio=Math.min(Number(options.devicePixelRatio??root.devicePixelRatio)||1,2);
      const width=Math.max(1,canvas.clientWidth||800),height=initial.compact?(canvas.clientHeight||118):width*380/1280;
      if(canvas.width!==Math.round(width*ratio)||canvas.height!==Math.round(height*ratio)){canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);}
    }
    function cancelFrame(){if(frame)caf(frame);frame=0;if(settleTimer)undelay(settleTimer);settleTimer=0;}
    function draw(){
      if(destroyed||folded||hidden)return;
      size();const value=model.sample();
      try{
        if(initial.compact&&stage.renderCompact){const ratio=canvas.width/Math.max(1,canvas.clientWidth||800);ctx.setTransform(ratio,0,0,ratio,0,0);stage.renderCompact(ctx,canvas.width/ratio,canvas.height/ratio,value.elapsed,value.scene);}
        else stage.render(ctx,canvas.width,canvas.height,value.elapsed,value.scene);
      }catch(error){cancelFrame();options.onError?.(error);return;}
      // Notify only semantic transitions, not every frame. The heading can
      // show "idle / last result" when the short result animation settles.
      const key=JSON.stringify([value.scene.taskId,value.scene.attempt,value.scene.phase,value.scene.settled,value.scene.reduceMotion]);
      if(key!==presentationKey){presentationKey=key;options.onPresentation?.(value.scene);}
      if(value.animate&&!frame)frame=raf(tick);
      else if(value.scene.reduceMotion&&!value.scene.settled&&['success','cancelled'].includes(value.scene.phase)&&!settleTimer){
        const duration=value.scene.phase==='success'?SETTLE_SECONDS:.35;
        settleTimer=delay(()=>{settleTimer=0;draw()},Math.max(1,(duration-value.elapsed)*1000+5));
      }
    }
    function tick(){frame=0;draw();}
    function wake(){cancelFrame();draw();}
    function visibilityChanged(){hidden=!!doc.hidden;setSuspension();wake();}
    function reducedChanged(){model.setReducedMotion(effectiveReduced());wake();}
    doc?.addEventListener('visibilitychange',visibilityChanged);media.addEventListener('change',reducedChanged);
    const Observer=options.ResizeObserver||root.ResizeObserver;
    const observer=Observer?new Observer(()=>wake()):null;observer?.observe(canvas);
    draw();
    return{
      setTaskState(next){if(destroyed)return{accepted:false,reason:'destroyed'};const result=model.update(next);wake();return result;},
      setSuspended(value){if(destroyed)return;folded=!!value;setSuspension();wake();},
      setReducedMotion(value){if(destroyed)return;reduceOverride=value==null?null:!!value;model.setReducedMotion(effectiveReduced());wake();},
      getTaskState:()=>model.getTaskState(),
      getPresentationState:()=>model.sample(),
      destroy(){if(destroyed)return;destroyed=true;cancelFrame();model.setSuspended(true);observer?.disconnect();doc?.removeEventListener('visibilitychange',visibilityChanged);media.removeEventListener('change',reducedChanged);}
    };
  }
  root.EmojiBridgeMotion={createModel,createController,hasError,SPAWN_SECONDS,SETTLE_SECONDS};
  if(typeof module!=='undefined'&&module.exports)module.exports=root.EmojiBridgeMotion;
})(typeof globalThis!=='undefined'?globalThis:this);
