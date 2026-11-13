import React,{useEffect,useRef,useState} from 'react';
import {StartupRuntime} from './runtime';
import './startup.css';

export function StartupOverlay({ready,prefs,error,onRetry,onExit}){
 const canvas=useRef(null),player=useRef(null),current=useRef({ready,prefs,error});current.current={ready,prefs,error};
 const [state,setState]=useState({phase:'loading',text:'正在打开本地工作区…'}),[released,setReleased]=useState(false);
 useEffect(()=>{
  const app=document.querySelector('.app');if(app)app.inert=true;
  const release=()=>{if(app)app.inert=false;setReleased(true)};
  player.current=new StartupRuntime(canvas.current,(phase,text)=>setState({phase,text}),release);
  const keys=e=>{if(!player.current?.finished&&e.key==='Escape'&&!e.isComposing){e.preventDefault();player.current?.skip()}};
  window.addEventListener('keydown',keys);const close=()=>{player.current?.destroy();release()};window.addEventListener('emoji-closing',close);
  return()=>{player.current?.destroy();if(app)app.inert=false;window.removeEventListener('keydown',keys);window.removeEventListener('emoji-closing',close)};
 },[]);
 useEffect(()=>{if(prefs)player.current?.configure(prefs)},[prefs]);
 useEffect(()=>{
  let live=true,first=0,second=0;
  if(ready){document.fonts.ready.then(()=>{if(live)first=requestAnimationFrame(()=>{second=requestAnimationFrame(()=>{if(live)player.current?.setReady(true)})})})}
  else player.current?.setReady(false,error);
  return()=>{live=false;cancelAnimationFrame(first);cancelAnimationFrame(second)};
 },[ready,error]);
 if(state.phase==='done')return null;
 return <div className={'startup-overlay '+state.phase+' '+(released?'released':'')} aria-label="EmojiBridge 启动" aria-busy={!ready}>
  <canvas ref={canvas} aria-hidden="true"/>
  {!released&&<button className="startup-skip" onClick={()=>player.current?.skip()}>跳过 <small>Esc</small></button>}
  {state.phase!=='playing'&&!released&&<div className="startup-status" role={state.phase==='error'?'alert':'status'}><span>{state.text}</span>{state.phase==='error'&&<div><button onClick={onRetry}>重试准备</button><button onClick={onExit}>退出</button></div>}</div>}
 </div>;
}
