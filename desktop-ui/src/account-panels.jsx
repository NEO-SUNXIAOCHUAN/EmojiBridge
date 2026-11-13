import React,{useState,useRef,useEffect,useId} from 'react';
import {ChevronDown,ChevronUp,GripHorizontal} from 'lucide-react';
import {readLabel} from './collection-read-state.mjs';

const KEY='emojibridge.account-panel-layout';
function savedLayout(){
 try{const v=JSON.parse(localStorage.getItem(KEY));return {collapsed:v?.collapsed===true,height:Number.isFinite(v?.height)?Math.max(96,Math.min(360,v.height)):null}}catch{return {collapsed:false,height:null}}
}

export function AccountPanels({children,sides}){
 const [layout,setLayout]=useState(savedLayout),[viewport,setViewport]=useState(window.innerHeight);
 const body=useRef(null),drag=useRef(null),id=useId();
 const maximum=Math.max(120,Math.min(360,Math.floor(viewport*.38)));
 const height=Math.min(layout.height??120,maximum);
 useEffect(()=>{const resize=()=>setViewport(window.innerHeight);window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize)},[]);
 useEffect(()=>{try{localStorage.setItem(KEY,JSON.stringify(layout))}catch{}},[layout]);
 const resizeTo=value=>setLayout(old=>({...old,height:Math.max(96,Math.min(maximum,value))}));
 const reset=()=>setLayout(old=>({...old,height:null}));
 const end=()=>{drag.current=null};
 return <section className={'account-panels'+(layout.collapsed?' is-collapsed':'')} aria-label="账号与读取">
  <div className="account-panel-toolbar">
   {layout.collapsed?<div className="account-compact-status">{['qq','wechat'].map(c=><span key={c} className={sides[c]?.state?.failed?'inline-error':''} title={sides[c]?.state?.text||readLabel(sides[c]||{})}><b>{c==='qq'?'QQ':'微信'}</b> {sides[c]?.count||0} 项 · {readLabel(sides[c]||{})}</span>)}</div>:<span>账号与读取</span>}
   {layout.height!==null&&!layout.collapsed&&<button className="account-reset" onClick={reset}>恢复高度</button>}
   <button aria-expanded={!layout.collapsed} aria-controls={id} onClick={()=>setLayout(old=>({...old,collapsed:!old.collapsed}))}>{layout.collapsed?<ChevronDown size={14}/>:<ChevronUp size={14}/>}<span>{layout.collapsed?'展开账号':'收起账号'}</span></button>
  </div>
  <div id={id} ref={body} className="account-panel-body" hidden={layout.collapsed} style={{height}}>{children}</div>
  {!layout.collapsed&&<div className="account-resize" role="separator" tabIndex={0} aria-label="调整账号区域高度" aria-orientation="horizontal" aria-controls={id} aria-valuemin={96} aria-valuemax={maximum} aria-valuenow={height} title="上下拖动调整高度；双击恢复。方向键微调。"
   onPointerDown={e=>{if(e.button!==0)return;e.preventDefault();e.currentTarget.focus();e.currentTarget.setPointerCapture(e.pointerId);drag.current={y:e.clientY,height:body.current.getBoundingClientRect().height}}}
   onPointerMove={e=>{if(drag.current)resizeTo(drag.current.height+e.clientY-drag.current.y)}} onPointerUp={end} onPointerCancel={end} onLostPointerCapture={end} onDoubleClick={reset}
   onKeyDown={e=>{const step=e.shiftKey?32:16;if(e.key==='ArrowUp'||e.key==='ArrowDown'){e.preventDefault();resizeTo(height+(e.key==='ArrowDown'?step:-step))}else if(e.key==='Home'||e.key==='End'){e.preventDefault();resizeTo(e.key==='Home'?96:maximum)}else if(e.key==='Enter'){e.preventDefault();reset()}}}><GripHorizontal size={20}/></div>}
 </section>;
}
