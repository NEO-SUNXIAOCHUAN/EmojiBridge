(() => {
  const $ = s => document.querySelector(s);
  const mq = matchMedia('(prefers-reduced-motion: reduce)');
  let reduced = mq.matches, progress = 0, target = 0, animation = 0, activeWork = 'type';
  const clamp = n => Math.max(0, Math.min(1, n));
  const smooth = n => {n=clamp(n);return n*n*(3-2*n)};
  const ramp = (p,a,b) => smooth((p-a)/(b-a));
  const mix = (a,b,p) => a+(b-a)*p;
  const color = (a,b,p) => `rgb(${a.map((v,i)=>Math.round(mix(v,b[i],p))).join(',')})`;
  const sticker = $('#flying-sticker'), stage = $('#stage');
  function draw(p) {
    progress=clamp(p);
    const fade=ramp(p,.24,.68), a=stage.getBoundingClientRect(), pic=$('.product-image').getBoundingClientRect(), dest=$('.chat-slot').getBoundingClientRect();
    // Coordinates are measured from the real source plate and the destination slot.
    const from={x:pic.left-a.left+pic.width*.4126157,y:pic.top-a.top+pic.height*.2849826,w:pic.width*.355324};
    const to={x:dest.left-a.left+3,y:dest.top-a.top+3,w:dest.width-6};
    const lift=Math.sin(p*Math.PI), x=mix(from.x,to.x,p)-lift*a.width*.17, y=mix(from.y,to.y,p)-lift*a.height*.26;
    const w=mix(from.w,to.w,p)+lift*a.width*.035;
    Object.assign(sticker.style,{left:x+'px',top:y+'px',width:w+'px',transform:`rotate(${Math.sin(p*2*Math.PI)*-8}deg) scale(${1+lift*.035})`});
    $('.sticker-check').style.opacity=1-ramp(p,0,.17);
    $('.product-window').style.opacity=1;
    $('.product-window').style.clipPath=`inset(0 ${fade*100}% 0 0)`;
    $('.wechat-window').style.opacity=1;
    $('.wechat-window').style.clipPath=`inset(0 0 0 ${(1-fade)*100}%)`;
    $('.wechat-window').style.visibility=p>.01?'visible':'hidden';
    $('.wechat-window').setAttribute('aria-hidden',p<.7?'true':'false');
    $('.qq-word').style.opacity=1-ramp(p,.05,.4);
    $('.wechat-word').style.opacity=ramp(p,.6,.92);
    $('.collection-success').style.opacity=ramp(p,.86,1);
    $('.arrival-note').style.opacity=ramp(p,.8,1);
    // A single ribbon carries the platform color through the motion, then folds away.
    const qq=$('.qq-word').getBoundingClientRect();
    const cx=mix((qq.left+qq.width*.5-a.left)/a.width*1200,(x+w*.5)/a.width*1200,ramp(p,0,.72));
    const cy=mix((qq.top+qq.height*.59-a.top)/a.height*680,(y-8)/a.height*680,ramp(p,0,.72));
    const half=mix(qq.width*.57/a.width*1200,w/a.width*510,ramp(p,.1,.7));
    const thick=mix(20,5,ramp(p,.15,.85));
    const wave=Math.sin(p*Math.PI)*58;
    const d=`M ${cx-half} ${cy-7} C ${cx-half*.5} ${cy+13-wave} ${cx+half*.4} ${cy+13+wave} ${cx+half} ${cy-7} L ${cx+half+7} ${cy+thick} C ${cx+half*.4} ${cy+thick+20+wave} ${cx-half*.4} ${cy+thick+20-wave} ${cx-half-8} ${cy+thick} Z`;
    $('#silk-path').setAttribute('d',d);
    const tailX=cx-half*.45;
    $('#silk-tail').setAttribute('d',`M ${tailX} ${cy+10} L ${tailX+29} ${cy+13} L ${tailX+29+wave*.5} ${cy+57-wave*.2} Q ${tailX+10} ${cy+61-wave*.2} ${tailX} ${cy+55-wave*.2} Z`);
    const green=ramp(p,.37,.82);
    $('#silk-dark').setAttribute('stop-color',color([169,20,36],[63,128,94],green));
    $('#silk-light').setAttribute('stop-color',color([250,52,67],[166,224,190],green));
    $('#silk-end').setAttribute('stop-color',color([232,32,45],[91,177,133],green));
    $('#silk-tail').setAttribute('fill',color([205,23,39],[80,149,112],green));
    $('.scarf-motion').style.opacity=1-ramp(p,.68,.97);
    const word=$('#flight-word');
    Object.assign(word.style,{left:x+w*.3+'px',top:y-40+'px',color:color([240,80,85],[130,205,168],green),opacity:ramp(p,.32,.5)*(1-ramp(p,.75,.93)),transform:`translateY(${-lift*9}px) rotate(${-lift*6}deg)`});
    stage.dataset.destination=p>.5?'wechat':'qq';
  }
  function setTarget(next) {
    target=next; cancelAnimationFrame(animation);
    $('#to-qq').setAttribute('aria-pressed',String(next===0));
    $('#to-wechat').setAttribute('aria-pressed',String(next===1));
    $('#transfer').innerHTML=next===1?'带回 QQ <span aria-hidden="true">↙</span>':'带去微信 <span aria-hidden="true">↗</span>';
    $('#demo-status').textContent=reduced?(next?'已切换到微信收藏示意。':'已切换到 QQ 来源示意。'):(next?'把这份快乐，带去微信。':'微信里的快乐，也能带回来。');
    const start=progress,startTime=performance.now(), duration=2400*Math.max(.35,Math.abs(target-start));
    if(reduced){draw(target);finish();return}
    function tick(now){const p=clamp((now-startTime)/duration);draw(mix(start,target,smooth(p)));if(p<1)animation=requestAnimationFrame(tick);else finish()}
    animation=requestAnimationFrame(tick);
  }
  function finish(){ $('#scene-label').textContent=target?'在微信，也能接着聊。':'在 QQ 发现的快乐。';$('#demo-status').textContent=target?'微信收藏已落定。也可以再带回 QQ。':'选中喜欢的表情，让它去微信。'; }
  $('#transfer').onclick=()=>setTarget(target?0:1);
  $('#to-qq').onclick=()=>setTarget(0);
  $('#to-wechat').onclick=()=>setTarget(1);
  $('#try-demo').onclick=()=>{stage.scrollIntoView({behavior:reduced?'instant':'smooth',block:'center'});setTarget(target?0:1)};
  // Images animate only while their section is visible; there is a page-wide stop control.
  const visible=new Set();
  function syncMedia(){document.querySelectorAll('img[data-animated]').forEach(img=>{const active=!reduced&&visible.has(img)&&!img.closest('[hidden]');const source=active?img.dataset.animated:img.dataset.still;if(img.getAttribute('src')!==source)img.src=source});}
  const observer=new IntersectionObserver(entries=>{entries.forEach(e=>{e.isIntersecting?visible.add(e.target):visible.delete(e.target)});syncMedia()},{threshold:.12});
  document.querySelectorAll('img[data-animated]').forEach(img=>observer.observe(img));
  function setReduced(value){reduced=value;document.body.classList.toggle('reduced',value);$('#motion-toggle').textContent=value?'允许动态':'减少动态';$('#motion-toggle').setAttribute('aria-pressed',String(value));document.dispatchEvent(new CustomEvent('emoji-motion-change',{detail:{reduced:value}}));if(value){cancelAnimationFrame(animation);draw(target);document.querySelectorAll('video').forEach(v=>v.pause())}syncMedia()}
  $('#motion-toggle').onclick=()=>setReduced(!reduced); mq.addEventListener('change',e=>setReduced(e.matches));
  document.querySelectorAll('[data-work]').forEach(button=>button.onclick=()=>{window.demoMedia?.pauseAll();activeWork=button.dataset.work;document.querySelectorAll('[data-work]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));document.querySelectorAll('.work-panel').forEach(p=>p.hidden=p.id!==`work-${activeWork}`);document.querySelectorAll('.work-panel video').forEach(v=>v.pause());const descriptions={collect:['评论区看到喜欢的表情，拖进随手素材。收下来，接着用。','评论区拖入 / 随手素材 / 继续创作'],type:['改文字、摆图层、拼画面。做一张有自己风格的梗图。','文字 / 基础图形 / 多图拼接'],bounce:['给表情一点弹性。调整动效，再导出属于你的版本。','Q 弹 / 旋转 / 参数调整'],clip:['保留最有意思的几秒，让名场面在聊天里循环。','视频截取 / 画面裁剪 / GIF 导出']};$('#work-description').textContent=descriptions[activeWork][0];$('#work-tools').textContent=descriptions[activeWork][1];if(activeWork==='bounce'&&!reduced)$('#bounce-video').play().catch(()=>{});else $('#bounce-video').pause();syncMedia()});
  $('#pocket-play').onclick=()=>{const v=$('#pocket-video');if(v.paused)window.demoMedia.play(v);else v.pause()};
  $('#pocket-video').addEventListener('play',()=>$('#pocket-play').innerHTML='暂停实录 <span aria-hidden="true">Ⅱ</span>');
  $('#pocket-video').addEventListener('pause',()=>$('#pocket-play').innerHTML='播放贴屏实录 <span aria-hidden="true">▷</span>');
  const videoObserver=new IntersectionObserver(entries=>entries.forEach(e=>{if(!e.isIntersecting)e.target.pause()}),{threshold:.05});document.querySelectorAll('video').forEach(v=>videoObserver.observe(v));
  $('#download-info').onclick=()=>{const hint=$('#download-followup');if(hint){hint.hidden=false;hint.textContent='下载后完整解压，双击 EmojiBridge.exe。好用的话，欢迎点个 Star。'}};

  window.addEventListener('resize',()=>draw(progress));
  window.addEventListener('load',()=>{draw(progress);setReduced(reduced)});
  // Deterministic capture hook: no networking, account access or software control.
  window.emojiPreview={draw,setTarget,setReduced,get state(){return {progress,target,reduced,activeWork}}};
  draw(0);
})();
