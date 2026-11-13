/* Explicit playback only. One soundtrack at a time, shared across both pages. */
(() => {
 const players=new Map();
 function attach(root){
  const video=root.querySelector('video'),button=root.querySelector('[data-media-play]'),label=button.querySelector('[data-play-label]'),status=root.querySelector('[data-media-status]');
  let pending=false,version=0;
  const sound=()=>root.dataset.sound==='true';
  const defaultLabel=()=>sound()?'播放实录 · 含原声':'播放演示';
  const setStatus=s=>{if(status)status.textContent=s};
  const show=s=>{button.hidden=false;label.textContent=s};
  const api={
   reset(){version++;pending=false;video.pause();video.controls=false;root.dataset.state='idle';root.removeAttribute('aria-busy');show(defaultLabel());setStatus(sound()?'点击播放，聆听对应原声。':'点击播放，查看完整动作。')},
   async play(){
    if(pending)return;pending=true;const token=++version;
    players.forEach((p,v)=>{if(v!==video){p.cancel();v.pause()}});
    video.muted=!sound();video.volume=.72;root.dataset.state='loading';root.setAttribute('aria-busy','true');label.textContent='正在加载…';setStatus('正在准备视频。');
    if(video.error)video.load();
    if(video.ended)video.currentTime=0;
    try{await video.play();if(token!==version)return;video.controls=true;button.hidden=true;root.dataset.state='playing';setStatus(sound()?'原声已开启，可在播放器中静音。':'正在播放演示。');if(document.activeElement===button)video.focus({preventScroll:true})}
    catch(e){if(token===version){root.dataset.state='error';show('重新播放');setStatus('视频暂时无法播放，请重试。')}}
    finally{if(token===version){pending=false;root.removeAttribute('aria-busy')}}
   },
   cancel(){version++;pending=false;root.removeAttribute('aria-busy');if(root.dataset.state==='loading'){video.pause();root.dataset.state='idle';show(defaultLabel())}}
  };
  button.addEventListener('click',()=>api.play());video.tabIndex=0;
  video.addEventListener('play',()=>{players.forEach((p,v)=>{if(v!==video){p.cancel();v.pause()}});video.controls=true;button.hidden=true;root.dataset.state='playing'});
  video.addEventListener('pause',()=>{if(!pending&&['playing','paused'].includes(root.dataset.state)){root.dataset.state='paused';setStatus('已暂停，可从当前位置继续。')}});
  video.addEventListener('ended',()=>{root.dataset.state='ended';show('再看一遍');setStatus('播放结束。')});
  video.addEventListener('error',()=>{if(video.getAttribute('src')){root.dataset.state='error';show('重新播放');setStatus('视频加载失败，点击重试。')}});
  video.addEventListener('waiting',()=>{if(!video.paused)setStatus('正在缓冲…')});
  video.addEventListener('playing',()=>setStatus(video.muted?'正在播放 · 已静音':'正在播放 · 原声已开启'));
  players.set(video,api);api.reset();
  return api;
 }
 document.querySelectorAll('[data-media-player]').forEach(attach);
 const io=new IntersectionObserver(entries=>entries.forEach(e=>{if(!e.isIntersecting){players.get(e.target)?.cancel();e.target.pause()}}),{threshold:.05});players.forEach((_,v)=>io.observe(v));
 document.addEventListener('visibilitychange',()=>{if(document.hidden)players.forEach((p,v)=>{p.cancel();v.pause()})});
 window.demoMedia={reset:v=>players.get(v)?.reset(),play:v=>players.get(v)?.play(),pauseAll:()=>players.forEach((p,v)=>{p.cancel();v.pause()})};
})();
