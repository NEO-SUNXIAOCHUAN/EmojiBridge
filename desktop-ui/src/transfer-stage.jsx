import React,{useEffect,useRef,useState} from 'react';
import './pocket-motion/character.js';
import './pocket-motion/brands.js';
import './pocket-motion/effects.js';
import './pocket-motion/stage.js';
import './pocket-motion/controller.js';
import './transfer-stage.css';
import {playSound,stopSound} from './task-sounds';
export function TransferStage({transfer,visible,reduced=false}){
 const canvas=useRef(null),controller=useRef(null),[open,setOpen]=useState(true),[simple,setSimple]=useState(false),[loadError,setLoadError]=useState('');
 const state=transfer?.request_error||transfer?.scene||{phase:transfer?.active?'working':'idle',source:'local',target:transfer?.target||'wechat',total:null,completed:0};
 const [shown,setShown]=useState(state);
 const sound=useRef({key:null,spawned:false,growls:new Set(),started:0});
 useEffect(()=>{const onError=e=>setLoadError('搬运动效未加载；真实任务继续。'+e.message);try{controller.current=globalThis.EmojiBridgeMotion.createController(canvas.current,{...state,compact:true},{onPresentation:setShown,onError})}catch(e){onError(e)}return()=>controller.current?.destroy()},[]);
 useEffect(()=>{controller.current?.setTaskState(state);setShown(controller.current?.getPresentationState().scene||state)},[JSON.stringify(state)]);
 useEffect(()=>{controller.current?.setReducedMotion(simple||reduced?true:null)},[simple,reduced]);
 useEffect(()=>{const update=()=>controller.current?.setSuspended(!visible||!open||document.hidden||!!window.__emojiHostHidden||!!window.__emojiClosing);update();window.addEventListener('emoji-host-hidden',update);window.addEventListener('emoji-closing',update);window.addEventListener('emoji-closing-cancelled',update);document.addEventListener('visibilitychange',update);return()=>{window.removeEventListener('emoji-host-hidden',update);window.removeEventListener('emoji-closing',update);window.removeEventListener('emoji-closing-cancelled',update);document.removeEventListener('visibilitychange',update)}},[visible,open]);
 useEffect(()=>{
  const key=String(shown.taskId)+':'+String(shown.attempt),s=sound.current;
  if(s.key!==key){stopSound('enderman');s.key=key;s.spawned=false;s.growls=new Set();s.started=performance.now()}
  const usable=()=>visible&&open&&!document.hidden&&!window.__emojiHostHidden;
  if(shown.phase==='spawning'&&!s.spawned){s.spawned=true;if(usable())playSound('enderman','enderman-teleport-1')}
  if(!['spawning','working','waiting'].includes(shown.phase)||!usable())stopSound('enderman');
  if(shown.phase!=='working')return;
  const timer=setInterval(()=>{const seconds=(performance.now()-s.started)/1000;for(const [name,at] of [['enderman-growl-1',7],['enderman-growl-3',18]])if(seconds>=at&&!s.growls.has(name)){s.growls.add(name);if(usable())playSound('enderman',name,{gain:.727})}},500);
  return()=>clearInterval(timer);
 },[shown.taskId,shown.attempt,shown.phase,visible,open]);
 useEffect(()=>()=>stopSound('enderman'),[]);
 const names={qq:'QQ',wechat:'微信',local:'素材库'};
 const labels={idle:'选择表情，开始互通',queued:'已排队，尚未提交',spawning:'正在准备搬运',working:'正在搬运',waiting:'等待结果确认',success:'收藏已确认',blocked:'本次传输受阻',partial:'部分项目未完成',paused:'任务已暂停',cancelled:'已取消后续搬运'};
 const settled=shown.phase==='success'&&shown.settled;
 const summary=settled?`当前待机 · 上次任务完成 ${shown.completed} / ${shown.total}`:shown.phase==='idle'?'当前待机 · 选择表情开始互通':`${labels[shown.phase]||'等待任务状态'}${shown.total!=null?` · 已确认 ${shown.completed} / ${shown.total}`:''}`;
 return <section className={'transfer-stage '+(!open?'collapsed':'')}><div className="stage-heading"><button aria-expanded={open} onClick={()=>setOpen(!open)}>{open?'⌄':'›'} 搬运舞台</button><span title={summary}>{names[shown.source]||'素材库'} → {names[shown.target]||'微信'} · {summary}{shown.failed?` · 失败 ${shown.failed}`:''}{shown.waiting?` · 待确认 ${shown.waiting}`:''}</span><button aria-pressed={simple} onClick={()=>setSimple(!simple)}>{simple?'简洁模式':'减少动效'}</button></div><canvas ref={canvas} aria-label="搬运状态展示，数量以任务记录为准" style={{display:open?'block':'none'}}/>{transfer?.active&&<small>互通不锁鼠标；自动点击和视觉核验时，请勿点击、滚动、拖动或遮挡目标窗口。读取 QQ 收藏及补原件时请勿移动鼠标。</small>}{loadError&&<small role="alert">{loadError}</small>}{open&&shown.detail&&!settled&&<small>{shown.detail}</small>}</section>
}
