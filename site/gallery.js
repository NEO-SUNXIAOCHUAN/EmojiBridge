(() => {
  const works=[
    ['joe','我被打死了','竖排配文'],['girl','你怎么这么帅','对白框配文'],['guts-angry','气死我了！！','竖排与文字颜色'],['guts-pirates','我要砍死你们这帮海盗','双侧竖排与描边'],['house','我家没了','竖排与文字描边'],['lion','我去琦玉老弟这么牛逼','横排与文字描边'],['kira','哈哈，原来佐梨是吸血鬼','多行配文'],['debate','批量收藏 > 一个个导入','文字、图片与图形组合'],['tags','制作一些梗图','标签排版与图层组合']
  ].map(([id,title,kind])=>({id,title,kind,src:['debate','tags'].includes(id)?`assets/${id}.png`:`assets/comics/${id}.webp`,blank:['debate','tags'].includes(id)?null:`assets/comics/${id}-blank.webp`}));
  const $=s=>document.querySelector(s),deck=$('#comic-deck'),thumbs=$('#comic-thumbnails'),dialog=$('#comic-dialog');
  let selected=1,before=false,revealAnimation=null;const reduced=()=>window.emojiPreview?.state.reduced||matchMedia('(prefers-reduced-motion: reduce)').matches;
  works.forEach((work,index)=>{const button=document.createElement('button');button.className='comic-thumb';button.setAttribute('aria-label',`查看：${work.title}`);button.innerHTML=`<img src="assets/thumbs/${work.id}.webp" alt="" loading="lazy">`;button.onclick=()=>select(index);thumbs.append(button)});
  function updateDialog(){const w=works[selected];$('#dialog-title').textContent=w.title;$('#dialog-kind').textContent=w.kind;$('#comic-full').src=w.src;$('#comic-full').alt=`漫画配文作品：${w.title}`;$('#dialog-count').textContent=`${selected+1} / ${works.length}`}
  function select(index){
    const restoreFocus=deck.contains(document.activeElement);
    const previous=new Map([...deck.children].map(b=>[b.dataset.id,getComputedStyle(b).transform]));
    selected=(index+works.length)%works.length;before=false;revealAnimation?.cancel();deck.replaceChildren();
    for(let distance=-2;distance<=2;distance++){const idx=(selected+distance+works.length)%works.length,w=works[idx],button=document.createElement('button');button.className='comic-card'+(distance===0?' is-selected':'');button.dataset.away=String(Math.abs(distance)===2);button.setAttribute('aria-label',distance===0?`放大查看：${w.title}`:`选择：${w.title}`);button.style.cssText=`--offset:${distance*235}px;--tilt:${distance*7}deg;--scale:${1-Math.abs(distance)*.15};--layer:${5-Math.abs(distance)}`;button.innerHTML=`<img src="${w.src}" alt="" draggable="false"><img class="complete" src="${w.src}" alt="${w.title}" draggable="false">`;button.onclick=()=>distance===0?open():select(idx);deck.append(button)}
    const w=works[selected];$('#comic-title').textContent=w.title;$('#comic-kind').textContent=w.kind;$('#gallery-count').textContent=`${String(selected+1).padStart(2,'0')} / ${String(works.length).padStart(2,'0')}`;
    $('#comic-before').disabled=!w.blank;$('#comic-replay').disabled=!w.blank;$('#comic-before').setAttribute('aria-pressed','false');$('#comic-before').textContent='看配字前';
    [...thumbs.children].forEach((b,i)=>b.setAttribute('aria-pressed',String(i===selected)));
    const thumb=thumbs.children[selected];thumbs.scrollTo({left:Math.max(0,thumb.offsetLeft-thumbs.offsetLeft-thumbs.clientWidth/2+thumb.offsetWidth/2),behavior:reduced()?'instant':'smooth'});
    [...deck.children].forEach((b,k)=>{b.dataset.id=works[(selected+k-2+works.length)%works.length].id;const from=previous.get(b.dataset.id);if(!reduced()&&previous.size){if(from)b.animate([{transform:from},{transform:getComputedStyle(b).transform}],{duration:480,easing:'cubic-bezier(.2,.7,.2,1)'});else b.animate([{opacity:0},{opacity:getComputedStyle(b).opacity}],{duration:350})}});
    if(restoreFocus)deck.querySelector(".is-selected").focus({preventScroll:true});
    if(dialog.open)updateDialog();
  }
  function open(){updateDialog();dialog.showModal()}
  $('#comic-prev').onclick=()=>select(selected-1);$('#comic-next').onclick=()=>select(selected+1);$('#comic-expand').onclick=open;$('#comic-close').onclick=()=>dialog.close();$('#dialog-prev').onclick=()=>select(selected-1);$('#dialog-next').onclick=()=>select(selected+1);
  $('#comic-before').onclick=()=>{revealAnimation?.cancel();const blank=works[selected].blank;if(blank)deck.querySelector('.is-selected img').src=blank;before=!before;deck.querySelector('.is-selected .complete').style.clipPath=before?'inset(0 100% 0 0)':'inset(0)';$('#comic-before').textContent=before?'看配字后':'看配字前';$('#comic-before').setAttribute('aria-pressed',String(before))};
  $('#comic-replay').onclick=()=>{before=false;$('#comic-before').textContent='看配字前';$('#comic-before').setAttribute('aria-pressed','false');revealAnimation?.cancel();const blank=works[selected].blank;if(blank)deck.querySelector('.is-selected img').src=blank;const image=deck.querySelector('.is-selected .complete');image.style.clipPath='inset(0)';if(!reduced())revealAnimation=image.animate([{clipPath:'inset(0 100% 0 0)'},{clipPath:'inset(0)'}],{duration:1250,easing:'cubic-bezier(.22,.5,.2,1)'})};
  document.addEventListener('emoji-motion-change',e=>{if(e.detail.reduced){revealAnimation?.cancel();deck.querySelectorAll('*').forEach(el=>el.getAnimations().forEach(a=>a.cancel()));}});
  $('#motion-toggle').addEventListener('click',()=>{if(reduced())revealAnimation?.cancel()});
  dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close()}});
  function arrows(e){if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();select(selected+(e.key==='ArrowLeft'?-1:1))}}
  $('#work-type').addEventListener('keydown',arrows);dialog.addEventListener('keydown',arrows);
  window.comicGallery={select,get selected(){return selected},works};
  const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){select(selected);observer.disconnect()}},{rootMargin:"180px"});observer.observe($("#work-type"));
})();
