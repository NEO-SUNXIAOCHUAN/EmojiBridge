import './pocket-tools.css';

const icons={shape:'M4 4h10v10H4z M14 10a6 6 0 1 1-4 4',arrow:'M5 19 19 5M7 5h12v12',text:'M4 5h16M12 5v15M8 20h8',pen:'m4 16 11-11 4 4-11 11H4v-4Z M13 7l4 4',cut:'M8 3 5 8l3 5M16 3l3 5-3 5M4 20h16M8 17l4-4 4 4'};
export const toolIcon=name=>`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[name]}"/></svg>`;

export function mountPocketTools(api,safe){
 const nav=document.querySelector('.eb-nav'),bar=document.createElement('div');bar.className='pocket-drawing-tools';bar.setAttribute('role','group');bar.setAttribute('aria-label','桌面绘制工具');
 for(const [id,name] of Object.entries({shape:'基础形状',arrow:'箭头',text:'文字',pen:'画笔'})){
  const button=document.createElement('button');button.type='button';button.title=name+' · 在桌面绘制';button.setAttribute('aria-label',button.title);button.innerHTML=toolIcon(id);
  button.onclick=()=>safe(async()=>{button.disabled=true;try{await api.drawing(id)}finally{button.disabled=false}});bar.append(button);
 }
 nav.querySelector('.eb-tabs').after(bar);nav.querySelector('.eb-count').title='随手素材数量';
 let menu;
 const dismiss=()=>{menu?.remove();menu=null};
 document.addEventListener('contextmenu',event=>{
  const card=event.target.closest('.eb-item');if(!card)return;
  event.preventDefault();event.stopPropagation();dismiss();
  menu=document.createElement('div');menu.className='pocket-context';menu.setAttribute('role','menu');
  const button=document.createElement('button');button.setAttribute('role','menuitem');button.innerHTML=toolIcon('cut')+'<span>抠主体<small>自动模型 · 生成临时贴图</small></span>';
  const id=card.dataset.id;button.onclick=()=>{dismiss();safe(async()=>{const result=await api.cutoutItem({id});window.pocketNotice(result.message)})};menu.append(button);document.body.append(menu);
  const r=menu.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(event.clientX,innerWidth-r.width-8))+'px';menu.style.top=Math.max(8,Math.min(event.clientY,innerHeight-r.height-8))+'px';button.focus();
 });
 document.addEventListener('pointerdown',event=>{if(menu&&!menu.contains(event.target))dismiss()});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&menu){dismiss();event.stopImmediatePropagation();event.preventDefault()}},true);
 let last='';const timer=setInterval(async()=>{try{const state=await api.toolsState();if(state.text&&state.text!==last){last=state.text;window.pocketNotice(state.text)}}catch{}},700);
 window.addEventListener('beforeunload',()=>{clearInterval(timer);dismiss()},{once:true});
}
