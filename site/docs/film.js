(() => {
 const video=document.querySelector('#film'),buttons=[...document.querySelectorAll('[data-seek]')];let seekVersion=0;
 buttons.forEach(button=>button.onclick=async()=>{
  const version=++seekVersion,time=Number(button.dataset.seek);
  if(video.readyState<1){video.load();await new Promise(resolve=>video.addEventListener('loadedmetadata',resolve,{once:true}))}
  if(version!==seekVersion)return;video.currentTime=time;window.demoMedia.play(video);
  video.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth',block:'center'});
 });
 video.addEventListener('timeupdate',()=>{const index=buttons.findLastIndex(b=>Number(b.dataset.seek)<=video.currentTime);buttons.forEach((b,i)=>b.setAttribute('aria-current',String(i===index)))});
})();
