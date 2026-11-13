import './logo-layers.js';
import './moon.js';
import './qq-rig.js';
import './startup.js';

// One player per host document. Page switches and tray restoration never own it.
export class StartupRuntime {
 constructor(canvas, report, release) {
  this.canvas=canvas;this.report=report;this.release=release;this.elapsed=0;
  this.frames=[];this.draws=[];this.raf=0;this.finished=false;this.started=false;
  this.ready=false;this.hostHidden=!!window.__emojiHostHidden;this.hidden=document.hidden||this.hostHidden;this.prefs=null;this.start=0;
  this.metrics={version:10,created:performance.now(),events:[],frames:this.frames,draws:this.draws};
  globalThis.__emojiStartup=this.metrics;
  this.visibility=()=>this.setHidden(document.hidden||this.hostHidden);
  this.hostVisibility=e=>{this.hostHidden=!!e.detail;this.visibility()};
  window.addEventListener('emoji-host-hidden',this.hostVisibility);
  document.addEventListener('visibilitychange',this.visibility);
  this.pagehide=()=>this.destroy();window.addEventListener('pagehide',this.pagehide);
  this.size=new ResizeObserver(()=>this.draw(this.time()));this.size.observe(canvas);
  this.timer=setTimeout(()=>{if(!this.ready&&!this.finished)this.setReady(false,'首屏准备超时，请重试或退出；已有素材和草稿保留。')},20000);
  this.abort=new AbortController();
  this.load();
 }
 time(){return this.started&&!this.hidden&&!this.waiting&&!this.finished&&!this.bypass?this.elapsed+(performance.now()-this.start)/1000:this.elapsed}
 event(name,extra={}){this.metrics.events.push({name,ms:performance.now(),time:this.time(),...extra})}
 async load(){
  try {
   this.logo=new Image();this.logo.src='/startup-v10/EmojiBridge-A.png';
   await Promise.race([this.logo.decode(),new Promise((_,reject)=>{this.assetTimer=setTimeout(()=>reject(Error('启动资源加载超时')),5000)})]);clearTimeout(this.assetTimer);
   if(this.finished)return;
   if(this.logo.naturalWidth!==512||this.logo.naturalHeight!==512)throw Error('启动图标尺寸不符');
   globalThis.EmojiBridgeLogoLayers.prepare(this.canvas.getContext('2d'),this.logo);
   // Moon's cached paths/surface are prepared before the first timed frame.
   globalThis.EmojiBridgeStartup.draw(this.canvas.getContext('2d'),this.canvas.width,this.canvas.height,1.8,{logo:this.logo});
   this.loaded=true;this.draw(0);this.event('assets_ready');this.tryStart();
  }catch(e){this.event('render_failed',{reason:String(e)});this.degraded=true;this.report('loading','启动动画不可用，正在打开真实工作区…');this.tryStart()}
 }
 configure(prefs){this.prefs=prefs;this.tryStart()}
 setReady(value,error=''){
  this.ready=value;this.coreError=error;
  if(error&&!value){this.elapsed=this.time();this.waiting=true;cancelAnimationFrame(this.raf);this.raf=0;this.stopAudio();this.report('error',error);this.event('core_error',{reason:error})}
  if(value){clearTimeout(this.timer);if(!this.metrics.coreReady){this.metrics.coreReady=performance.now();this.event('core_ready')}
   if(this.waiting){this.waiting=false;this.start=performance.now();this.lastFrame=0;this.report('playing','');this.playAudio(this.elapsed);this.schedule()}
   this.tryStart();}
 }
 tryStart(){
  if(this.finished)return;
  if(this.skipped||this.degraded||this.prefs&&(this.prefs.startup_motion===false||this.prefs.reduce_motion||matchMedia('(prefers-reduced-motion: reduce)').matches)){
   if(!this.bypass){this.elapsed=this.time();this.bypass=true}cancelAnimationFrame(this.raf);this.raf=0;
   this.stopAudio();if(this.ready)this.finish(this.skipped?'skipped':this.degraded?'degraded':'reduced');return;
  }
  if(!this.loaded||!this.prefs||this.started||this.coreError)return;
  if(this.prefs.startup_sound!==false&&!this.audioPrepared){
   if(!this.audioPreparing){this.audioPreparing=true;this.prepareAudio().finally(()=>{this.audioPrepared=true;this.tryStart()})}return;
  }
  this.started=true;this.start=performance.now();this.event('started');this.report('playing','');
  this.playAudio(0);this.schedule();
 }
 async prepareAudio(){
  if(this.prefs.startup_sound===false||this.finished)return;
  try{
   const load=async()=>{this.audio=new AudioContext();await this.audio.resume();
    const response=await fetch('/startup-v10/startup-v10-sfx.wav',{signal:this.abort.signal});if(!response.ok)throw Error('sound_missing');
    this.buffer=await this.audio.decodeAudioData(await response.arrayBuffer());};
   await Promise.race([load(),new Promise((_,reject)=>{this.audioTimer=setTimeout(()=>reject(Error('sound_timeout')),2000)})]);
   this.event('audio_ready');
  }catch(e){this.event('audio_unavailable',{reason:String(e)})}
  finally{clearTimeout(this.audioTimer)}
 }
 playAudio(offset){
  this.stopAudio();if(!this.buffer||this.finished||this.bypass||this.prefs.startup_sound===false||offset>=11.9)return;
  this.audio.resume().then(()=>{
   if(this.finished||this.hidden||this.waiting||this.bypass||this.source)return;
   const now=this.elapsed+(performance.now()-this.start)/1000;
   if(now>=11.9)return;
   const source=this.audio.createBufferSource();source.buffer=this.buffer;source.connect(this.audio.destination);
   source.start(0,now);this.source=source;this.event('audio_start',{offset:now});
  }).catch(e=>this.event('audio_unavailable',{reason:String(e)}));
 }
 stopAudio(){if(this.source){try{this.source.stop();this.source.disconnect()}catch{}this.source=null}}
 schedule(){if(!this.raf&&!this.hidden&&!this.finished&&!this.waiting&&!this.bypass)this.raf=requestAnimationFrame(now=>this.tick(now))}
 tick(now){
  this.raf=0;if(this.finished||this.hidden)return;
  const time=this.elapsed+(now-this.start)/1000;
  if(this.lastFrame){this.frames.push([time,now-this.lastFrame]);if(this.frames.length>3600)this.frames.shift()}
  this.lastFrame=now;
  if(time>=9.94&&!this.ready){this.elapsed=9.94;this.waiting=true;this.stopAudio();this.draw(9.94);this.report('loading','正在准备真实工作区…');this.event('waiting_for_core');return}
  try{this.draw(time)}catch(e){this.degraded=true;this.event('render_failed',{reason:String(e)});this.stopAudio();this.tryStart();return}
  // At this point the approved silhouette has revealed the live controls.
  // Input is released now, independently of the reference's final hold/audio.
  if(time>=10.98&&!this.metrics.interactive){this.metrics.interactive=now;this.event('interactive');this.release()}
  if(time>=11.9){this.finish('complete');return}this.schedule();
 }
 draw(time){
  if(!this.loaded||this.finished)return;
  const r=this.canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;
  const w=Math.max(1,Math.round(r.width*dpr)),h=Math.max(1,Math.round(r.height*dpr));
  if(this.canvas.width!==w||this.canvas.height!==h){this.canvas.width=w;this.canvas.height=h;this.metrics.viewport={width:r.width,height:r.height,dpr}}
  const start=performance.now();globalThis.EmojiBridgeStartup.draw(this.canvas.getContext('2d'),w,h,time,{logo:this.logo});
  this.draws.push([time,performance.now()-start]);if(this.draws.length>3600)this.draws.shift();
 }
 setHidden(hidden){
  if(hidden===this.hidden||this.finished)return;
  this.hidden=hidden;
  if(hidden){if(this.started&&!this.waiting)this.elapsed+=(performance.now()-this.start)/1000;cancelAnimationFrame(this.raf);this.raf=0;this.stopAudio();this.audio?.suspend().catch(()=>{});this.event('hidden')}
  else{this.start=performance.now();this.lastFrame=0;this.event('visible');if(this.started&&!this.waiting){this.playAudio(this.elapsed);this.schedule()}}
 }
 skip(){if(this.finished)return;this.skipped=true;this.event('skip');this.report(this.coreError?'error':'loading',this.coreError||'正在打开真实工作区…');this.tryStart()}
 finish(reason){
  if(this.finished)return;this.elapsed=this.time();this.finished=true;this.event('finished',{reason});this.metrics.interactive ||= performance.now();
  this.cleanup();this.release();this.report('done','');
 }
 cleanup(){clearTimeout(this.timer);clearTimeout(this.assetTimer);clearTimeout(this.audioTimer);this.abort.abort();cancelAnimationFrame(this.raf);this.raf=0;this.stopAudio();this.audio?.close().catch(()=>{});this.size.disconnect();document.removeEventListener('visibilitychange',this.visibility);window.removeEventListener('emoji-host-hidden',this.hostVisibility);window.removeEventListener('pagehide',this.pagehide)}
 destroy(){if(!this.finished){this.finished=true;this.event('closed');this.cleanup()}}
}
