import './pocket-motion/pocket.js';
import './pocket-motion/pocket.css';
import './pocket-window.css';
import './scrollbars';
import './browser-drop';
import {mountPocketTools} from './pocket-tools';

function ready(){
 const api=window.pywebview.api,edge=location.pathname==='/edge.html';
 const safe=async fn=>{try{return await fn()}catch(e){window.pocketNotice(String(e.message||e))}};
 let component,revision=null,query='',view='recent',limit=80,sequence=0,timer,loading=false,lastTask='',lastStickerError='';
 window.pocketNotice=text=>{if(component)component.toast(text);const info=document.querySelector('.pocket-status');if(info)info.textContent=text};
 const load=async(force=false)=>{
  const ticket=++sequence;
  try{const data=await api.listing(query,view,limit,force?null:revision);if(ticket!==sequence)return;
   if(!data.unchanged){revision=data.revision;component?.setItems(data.items);const more=document.querySelector('.pocket-more');if(more){more.hidden=data.items.length>=data.total;more.textContent=`继续显示 · ${data.items.length} / ${data.total}`}}
  }catch(e){window.pocketNotice('读取失败，可点刷新重试：'+e.message)}
 };
 if(edge){
  document.body.innerHTML='<main class="edge-port"><div class="pywebview-drag-region">收纳口 <button id="close" aria-label="关闭收纳口">×</button></div><b>拖入图片 / GIF</b><small class="pocket-status">原件直接加入素材库</small></main>';
  document.querySelector('#close').onclick=()=>api.close();
 }else{
  const host={capabilities:{nativeWindow:true,nativeDrag:true},...Object.fromEntries(['chooseImport','setFavorite','openSticker','copyItem','dragItem','prepareItem','setPinned','setCollapsed','close'].map(name=>[name,(...args)=>api[name](...args)])),
   filterChanged:(q,v)=>{query=q;view=v;limit=80;clearTimeout(timer);timer=setTimeout(()=>load(true),120)}};
  component=window.EmojiBridgePocket.mount('#root',{host});
  mountPocketTools(api,safe);
  document.querySelector('.eb-collapse').onclick=()=>safe(()=>api.hide());
  document.querySelector('.eb-collapse').title='收起 · 快捷键可唤回';
  document.querySelector('.eb-title-wrap').classList.add('pywebview-drag-region');
  const extra=document.createElement('nav');extra.className='pocket-utility';
  extra.innerHTML='<button data-action="chooseImport">导入</button><button data-action="paste">粘贴</button><button data-action="adjustStickers">调整贴图</button><button data-action="recoverStickers">找回贴图</button><button data-action="hideAllStickers">全部收回</button><button data-action="refresh">刷新</button>';
  document.querySelector('.eb-nav').after(extra);
  extra.querySelectorAll('button').forEach(button=>button.onclick=()=>safe(async()=>{const name=button.dataset.action;if(name==='refresh'){await load(true);return}const result=await api[name]();if(result?.accepted===false)window.pocketNotice(result.message);if(result?.closed!==undefined)window.pocketNotice('已收回 '+result.closed+' 张贴图')}));
  const more=document.createElement('button');more.className='pocket-more';more.hidden=true;more.onclick=()=>{limit+=80;load(true)};document.querySelector('.eb-view').append(more);
  const status=document.createElement('details');status.className='pocket-task';status.innerHTML='<summary class="pocket-status">正在读取本地素材…</summary><div class="pocket-results"></div><button class="pocket-cancel" hidden>取消导入</button>';
  document.querySelector('.eb-footer').before(status);status.querySelector('button').onclick=()=>api.cancel();
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!e.isComposing){e.preventDefault();safe(()=>api.hide());return}if(e.ctrlKey&&e.key.toLowerCase()==='v'&&!/INPUT|TEXTAREA/.test(document.activeElement.tagName)){e.preventDefault();safe(()=>api.paste())}});
  load(true);
 }
 let depth=0;
 document.addEventListener('dragenter',e=>{if(![...(e.dataTransfer?.types||[])].includes('Files'))return;depth++;document.body.classList.add('drop-active')});
 document.addEventListener('dragleave',()=>{if(--depth<=0)document.body.classList.remove('drop-active')});
 document.addEventListener('drop',()=>{depth=0;document.body.classList.remove('drop-active')});
 const poll=setInterval(async()=>{
  if(loading||document.hidden)return;loading=true;
  try{const s=await api.state(),task=s.task;document.body.dataset.reduced=String(s.reduced_motion||false);document.documentElement.dataset.reduceMotion=String(!!s.reduced_motion);document.documentElement.dataset.scrollbars=s.always_scrollbars?'always':'auto';const pin=document.querySelector('.eb-pin');if(pin){pin.classList.toggle('active',s.pinned);pin.setAttribute('aria-pressed',String(s.pinned));pin.title=s.pinned?'取消临时置顶':'临时置顶'}if(!edge&&s.revision!==revision)await load();
   if(task.text!==lastTask){lastTask=task.text;document.querySelector('.pocket-status').textContent=task.text;
    const results=document.querySelector('.pocket-results');if(results){results.replaceChildren(...(task.import_results||[]).map(row=>{const el=document.createElement('div');el.textContent=row.name+' · '+({added:'新增',existing:'已有',failed:'失败'}[row.state]||row.state)+(row.reason?'：'+row.reason:'');return el}))}}
   if(s.sticker_error&&s.sticker_error!==lastStickerError){lastStickerError=s.sticker_error;window.pocketNotice('贴图播放已暂停：'+s.sticker_error)}
   const cancel=document.querySelector('.pocket-cancel');if(cancel)cancel.hidden=!task.active;
  }catch(e){window.pocketNotice(e.message)}finally{loading=false}
 },650);
 window.addEventListener('beforeunload',()=>{clearInterval(poll);clearTimeout(timer);component?.destroy()});
}
window.addEventListener('pywebviewready',ready,{once:true});
