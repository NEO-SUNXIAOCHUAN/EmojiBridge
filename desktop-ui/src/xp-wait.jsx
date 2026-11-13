import React,{useEffect,useRef,useState} from 'react';
import {createPresentation} from './xp-v9/presentation.cjs';
import {renderer} from './xp-v9/render';
import {configureSounds,playSound,stopSound} from './task-sounds';
export function XPWait({tasks,prefs,suppressed=false,rect,background}){
 const visible=!!rect&&!suppressed;
 const canvas=useRef(null),logic=useRef(null),paint=useRef(null),raf=useRef(0),latest=useRef({}),wasVisible=useRef(false),idlePaint=useRef(false),silent=useRef(false),[error,setError]=useState('');latest.current={prefs,suppressed:!visible};
 useEffect(()=>{configureSounds(prefs)},[prefs]);
 useEffect(()=>{
  let live=true,hidden=document.hidden||!!window.__emojiHostHidden;
  const effect=e=>{if(e.type==='presentation-stop'||e.type==='running-stop')stopSound('xp');if(hidden||latest.current.suppressed||silent.current)return;if(e.type==='presentation-start')playSound('xp','xp-original-4-16',{loop:true});if(e.type==='success-sound')playSound('xp','xp-complete',{gain:.54})};
  const p=logic.current=createPresentation({onEffect:effect});
  const frame=()=>{cancelAnimationFrame(raf.current);if(!live||hidden||latest.current.suppressed||window.__emojiClosing)return;const s=p.sample();if(s.phase!=='idle'||!idlePaint.current){paint.current?.(s,latest.current.prefs.reduce_motion);idlePaint.current=s.phase==='idle'&&!!paint.current;canvas.current?.setAttribute('aria-label',s.phase==='idle'?'待机，0级空经验条':`任务等待 ${s.levelText} 级；不是完成百分比`)}if(s.phase!=='idle')raf.current=requestAnimationFrame(frame)};
  logic.current.wake=frame;
  renderer(canvas.current).then(fn=>{if(live){paint.current=fn;frame()}}).catch(()=>{if(live)setError('等待动效资源未加载；任务继续正常执行')});
  const visibility=()=>{hidden=document.hidden||!!window.__emojiHostHidden;if(hidden){cancelAnimationFrame(raf.current);stopSound('xp')}else{frame();/* No catch-up sound after hiding. */}};
  document.addEventListener('visibilitychange',visibility);window.addEventListener('emoji-host-hidden',visibility);
  return()=>{live=false;cancelAnimationFrame(raf.current);p.dispose();stopSound('xp');document.removeEventListener('visibilitychange',visibility);window.removeEventListener('emoji-host-hidden',visibility)};
 },[]);
 useEffect(()=>{const p=logic.current;if(!p)return;silent.current=!visible||!wasVisible.current;wasVisible.current=visible;
  const eligible=tasks.filter(t=>t?.xp_eligible===true),value=eligible.find(t=>t.active)||eligible.find(t=>t.id===p.id)||eligible.find(t=>t.end_age>=0&&t.end_age<2);
  if(value)p.update(value);
  if(!visible){cancelAnimationFrame(raf.current);stopSound('xp')}else p.wake?.();silent.current=false;
 },[tasks,visible]);
 useEffect(()=>{idlePaint.current=false;logic.current?.wake?.()},[rect?.width,rect?.height,background,prefs.reduce_motion]);
 return <div className="xp-wait" style={{...rect,background}} hidden={!visible} title={error||'经验等级表示本次实际处理秒数，不代表总进度'}>{error?<small>{error}</small>:<canvas ref={canvas} role="img"/>}</div>;
}
