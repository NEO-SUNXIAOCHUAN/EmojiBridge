import React,{useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Shapes,ArrowUpRight,Type,Pencil,Undo2,Redo2,X,Check,Play,Pause,Scissors,Square,RectangleHorizontal,Circle,Triangle,Minus} from 'lucide-react';
import {bounds,center,handles,hit,translate,scaleFromHandle,selection,render} from './annotation.mjs';
import './overlay.css';

const tools=[['shape','基础形状',Shapes],['arrow','箭头',ArrowUpRight],['text','文字',Type],['pen','画笔',Pencil]];
const colors=['#ffffff','#151820','#ef5350','#ffa94d','#f6d55c','#72d6a1','#78b9ff','#c7a4ff'];
function IconButton({label,icon:Icon,...props}){return <button title={label} aria-label={label} {...props}><Icon size={19} strokeWidth={1.7}/></button>}
function Actions({api}){
 const [state,setState]=useState(null),[error,setError]=useState('');
 useEffect(()=>{let gone=false;const refresh=async()=>{try{const s=await api.state();if(!gone){setState(s);if(!s.sticker)api.cancel()}}catch(e){if(!gone)setError(e.message)}};refresh();const t=setInterval(refresh,300);const key=e=>{if(e.key==='Escape')api.cancel()};window.addEventListener('keydown',key);return()=>{gone=true;clearInterval(t);window.removeEventListener('keydown',key)}},[]);
 const act=async name=>{setError('');try{await api[name]();setState(await api.state())}catch(e){setError(e.message)}};
 const job=state?.job,animated=state?.sticker?.count>1;
 return <main className="sticker-tools"><div className="sticker-buttons"><button disabled={!animated} onClick={()=>act('play')} title={animated?'播放或暂停这张 GIF':'静态图片，无需播放'}>{state?.sticker?.paused?<Play size={18}/>:<Pause size={18}/>}<span>{state?.sticker?.paused?'播放':'暂停'}</span></button><button onClick={()=>act(job?.active?'cancel_cutout':'cutout')}><Scissors size={18}/><span>{job?.active?'取消抠图':'抠主体'}</span></button><IconButton label="收起工具栏" icon={X} className="quiet close-tools" onClick={()=>api.cancel()}/></div><p role="status" className={error||job?.failed?'error':''}>{error||job?.text||'左上角单击固定 · 长按拖动旋转'}</p></main>
}

function Draw({api,context}){
 const [tool,setTool]=useState(context.tool),[options,setOptions]=useState({shape:'rect',color:'#78b9ff',width:4,fontSize:32,fill:false,fillColor:'#20252e'});
 const [objects,setObjects]=useState([]),[selected,setSelected]=useState(-1),[history,setHistory]=useState([]),[future,setFuture]=useState([]);
 const [text,setText]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const canvas=useRef(),gesture=useRef(),latest=useRef(),preview=useRef({dirty:false,running:false,closed:false});
 latest.current={objects,selected,options,tool,text,busy,history,future};
 const publish=()=>{const p=preview.current;p.dirty=true;if(p.running||p.closed)return;p.running=true;
  requestAnimationFrame(async()=>{try{while(p.dirty&&!p.closed){p.dirty=false;
   const rects=[...document.querySelectorAll('.drawing-dock,.drawing-caption,.draw-text')].map(el=>{const r=el.getBoundingClientRect();return [r.x-3,r.y-3,r.width+6,r.height+6]});
   const ok=await api.preview(canvas.current.toDataURL('image/png'),rects,innerWidth,innerHeight);
   if(!ok){p.dirty=true;await new Promise(r=>setTimeout(r,70))}
  }}catch(e){setError('预览未完成：'+e.message)}finally{p.running=false}});
 };
 const paint=(items=latest.current.objects,mark=true)=>{
  const c=canvas.current;if(!c)return;const ctx=c.getContext('2d');ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,c.width,c.height);ctx.setTransform(c.width/innerWidth,0,0,c.height/innerHeight,0,0);
  items.forEach((o,i)=>{if(!mark||latest.current.text?.editIndex!==i)render(ctx,o)});
  const i=latest.current.selected;if(mark&&i>=0&&items[i])selection(ctx,items[i]);if(mark)publish();
 };
 useEffect(()=>paint(),[objects,selected,text,tool,error]);
 useEffect(()=>{const input=document.querySelector('.draw-text');if(!input)return;const observer=new ResizeObserver(publish);observer.observe(input);return()=>observer.disconnect()},[!!text]);
 useEffect(()=>{const redraw=()=>paint();window.addEventListener('resize',redraw);const observer=new ResizeObserver(publish);document.querySelectorAll('.drawing-dock,.drawing-caption').forEach(el=>observer.observe(el));return()=>{preview.current.closed=true;observer.disconnect();window.removeEventListener('resize',redraw)}},[]);
 const remember=()=>{const snapshot=latest.current.objects;setHistory(h=>[...h.slice(-49),snapshot]);setFuture([])};
 const commitText=()=>{
  const value=latest.current.text;if(!value)return latest.current.objects;
  setText(null);latest.current.text=null;if(!value.value.trim())return latest.current.objects;
  const ctx=canvas.current.getContext('2d');ctx.font=`${value.fontSize}px "Microsoft YaHei UI", "Segoe UI", sans-serif`;
  const item={...value,type:'text',text:value.value,boxWidth:Math.max(8,value.manualWidth||0,...value.value.split('\n').map(line=>ctx.measureText(line).width)),boxHeight:Math.max(value.manualHeight||0,value.value.split('\n').length*value.fontSize*1.35)};
  remember();const next=value.editIndex!=null?latest.current.objects.map((o,i)=>i===value.editIndex?item:o):[...latest.current.objects,item];setObjects(next);setSelected(value.editIndex??next.length-1);latest.current.objects=next;return next;
 };
 const chooseTool=id=>{commitText();setTool(id);setSelected(-1);setError('')};
 const change=(key,value)=>{
  setOptions(o=>({...o,[key]:value}));
  if(text){setText(t=>({...t,[key]:value}));return}
  if(selected>=0){remember();setObjects(rows=>rows.map((o,i)=>i===selected?{...o,[key]:value,...(key==='fontSize'&&o.type==='text'?{boxWidth:o.boxWidth*value/o.fontSize,boxHeight:o.boxHeight*value/o.fontSize}:{})}:o))}
 };
 const down=e=>{
  if(e.button!==0||latest.current.busy)return;e.preventDefault();setError('');
  const wasEditing=!!latest.current.text;if(wasEditing)commitText();
  const {tool,options,selected,objects:rows}=latest.current,x=e.clientX,y=e.clientY;
  let index=selected,old=rows[index],mode='new';
  if(old){const h=handles(old);if(Math.hypot(x-h.rotate[0],y-h.rotate[1])<12)mode='rotate';else if(Math.hypot(x-h.resize[0],y-h.resize[1])<12)mode='resize'}
  if(mode==='new'){index=rows.findLastIndex(o=>hit(o,[x,y]));old=rows[index];if(old)mode='move'}
  if(mode==='new'&&wasEditing)return;
  setSelected(index);
  if(old)setOptions(o=>({...o,...Object.fromEntries(['shape','color','width','fontSize','fill','fillColor'].filter(k=>old[k]!=null).map(k=>[k,old[k]]))}));
  if(mode==='new'&&tool==='text'){setText({...options,x:Math.min(x,innerWidth-24),y:Math.min(y,innerHeight-options.fontSize*1.35-8),value:''});return}
  if(!e.native&&e.pointerId!=null)canvas.current.setPointerCapture(e.pointerId);
  gesture.current={mode,x,y,index:mode==='new'?rows.length:index,original:old,rows,tool,options,changed:false};
 };
 const move=e=>{
  const g=gesture.current;if(!g)return;const x=e.clientX,y=e.clientY;
  if(!g.changed){if(Math.hypot(x-g.x,y-g.y)<(g.mode==='new'?7:2))return;remember();g.changed=true}
  setObjects(rows=>{const next=[...rows];
   if(g.mode==='move')next[g.index]=translate(g.original,x-g.x,y-g.y);
   else if(g.mode==='resize')next[g.index]=scaleFromHandle(g.original,[x,y]);
   else if(g.mode==='rotate'){const c=center(g.original);let angle=(g.original.angle||0)+Math.atan2(y-c[1],x-c[0])-Math.atan2(g.y-c[1],g.x-c[0]);if(e.shiftKey)angle=Math.round(angle/(Math.PI/12))*Math.PI/12;next[g.index]={...g.original,angle}}
   else {if(!next[g.index])next[g.index]={type:g.tool,...g.options,x:g.x,y:g.y,x2:x,y2:y,...(g.tool==='pen'?{points:[[g.x,g.y]]}:{})};
    if(g.tool==='pen')next[g.index]={...next[g.index],points:[...next[g.index].points,[x,y]]};
    else {let x2=x,y2=y;if(e.shiftKey){const size=Math.max(Math.abs(x-g.x),Math.abs(y-g.y));x2=g.x+Math.sign(x-g.x||1)*size;y2=g.y+Math.sign(y-g.y||1)*size}next[g.index]={...next[g.index],x2,y2}}
   }return next});setSelected(g.index);
 };
 const up=e=>{if(gesture.current?.changed&&e.kind!=='cancel')move(e);gesture.current=null;if(!e.native&&e.pointerId!=null&&canvas.current.hasPointerCapture(e.pointerId))canvas.current.releasePointerCapture(e.pointerId)};
 const double=e=>{const s=latest.current,index=s.objects.findLastIndex(o=>hit(o,[e.clientX,e.clientY])),item=s.objects[index];if(item?.type==='text'){setText({...item,value:item.text,editIndex:index});setSelected(-1)}};
 const handlers=useRef();handlers.current={down,move,up,double,cancel:up};
 useEffect(()=>{window.desktopPointer=e=>handlers.current[e.kind]?.({...e,clientX:e.x*innerWidth/context.width,clientY:e.y*innerHeight/context.height,button:0,native:true,preventDefault(){}});return()=>{delete window.desktopPointer}},[]);
 const undo=()=>{const s=latest.current;if(s.text){setText(null);return}if(!s.history.length)return;setFuture(f=>[s.objects,...f]);setObjects(s.history.at(-1));setHistory(s.history.slice(0,-1));setSelected(-1)};
 const redo=()=>{const s=latest.current;if(!s.future.length)return;setHistory(h=>[...h,s.objects]);setObjects(s.future[0]);setFuture(s.future.slice(1));setSelected(-1)};
 const finish=async()=>{if(latest.current.busy)return;const items=commitText();if(!items.length){setError('先在桌面画一点内容');return}setBusy(true);try{paint(items,false);await api.finish(canvas.current.toDataURL('image/png'))}catch(e){setError(e.message);paint()}finally{setBusy(false)}};
 useEffect(()=>{const key=e=>{if(e.isComposing)return;const typing=/INPUT|TEXTAREA|SELECT/.test(e.target.tagName);if(e.key==='Escape'){e.preventDefault();if(latest.current.text)setText(null);else api.cancel();return}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'&&!typing){e.preventDefault();e.shiftKey?redo():undo()}else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'&&!typing){e.preventDefault();redo()}else if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();finish()}else if((e.key==='Delete'||e.key==='Backspace')&&!typing&&latest.current.selected>=0){e.preventDefault();remember();setObjects(rows=>rows.filter((_,i)=>i!==latest.current.selected));setSelected(-1)}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key)},[]);
 const effectiveTool=text?'text':objects[selected]?.type||tool;
 let textWidth=14;if(text&&canvas.current){const ctx=canvas.current.getContext('2d');ctx.font=`${text.fontSize}px "Microsoft YaHei UI", "Segoe UI", sans-serif`;textWidth=Math.max(14,text.manualWidth||0,...text.value.split('\n').map(line=>ctx.measureText(line).width+6))}
 return <main className="draw-surface">
  <canvas ref={canvas} width={context.width} height={context.height} aria-label="桌面绘制画布" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onDoubleClick={double}/>
  {text&&<textarea autoFocus aria-label="输入贴图文字" className="draw-text" value={text.value} spellCheck={false} onPointerUp={e=>{const {offsetWidth,offsetHeight}=e.currentTarget;setText(t=>({...t,manualWidth:offsetWidth,manualHeight:offsetHeight}))}} onChange={e=>setText(t=>({...t,value:e.target.value}))} style={{left:text.x,top:text.y,width:textWidth,height:Math.max(text.manualHeight||0,text.value.split('\n').length*text.fontSize*1.35+4),maxWidth:innerWidth-text.x-8,color:text.color,caretColor:text.color,fontSize:text.fontSize,background:text.fill?text.fillColor:'#182332',transform:`rotate(${text.angle||0}rad)`,transformOrigin:'center'}}/>}
  <div className="drawing-caption">{text?'输入文字后点击画布确认':'点任意对象移动 · 上方圆点旋转 · 右下角缩放'}<span>空白处拖动新建 · 完成后仅贴到屏幕，不加入素材库</span></div>

  <section className="drawing-dock" aria-label="桌面绘制设置">
   <div className="drawing-options">
    {effectiveTool==='shape'&&<div className="option-group" aria-label="形状">{[['rect','矩形',Square],['rounded','圆角矩形',RectangleHorizontal],['ellipse','椭圆',Circle],['triangle','三角形',Triangle],['line','直线',Minus]].map(([id,label,Icon])=><IconButton key={id} label={label} icon={Icon} aria-pressed={options.shape===id} onClick={()=>change('shape',id)}/>)}</div>}
    <label className="size-option">{effectiveTool==='text'?'字号':'粗细'}<input aria-label={effectiveTool==='text'?'字号':'粗细'} type="range" min={effectiveTool==='text'?12:1} max={effectiveTool==='text'?144:32} value={effectiveTool==='text'?options.fontSize:options.width} onChange={e=>change(effectiveTool==='text'?'fontSize':'width',Number(e.target.value))}/><output>{effectiveTool==='text'?options.fontSize:options.width}</output></label>
    {(effectiveTool==='shape'||effectiveTool==='text')&&<label className="fill-option"><input type="checkbox" checked={options.fill} onChange={e=>change('fill',e.target.checked)}/>{effectiveTool==='text'?'填充背景':'填充'}</label>}
    {effectiveTool==='text'&&options.fill&&<input className="color-input" type="color" aria-label="文字填充颜色" value={options.fillColor} onChange={e=>change('fillColor',e.target.value)}/>}
    <div className="swatches" role="group" aria-label="颜色">{colors.map(color=><button key={color} title={color} aria-label={'颜色 '+color} aria-pressed={options.color===color} onClick={()=>change('color',color)} style={{'--swatch':color}}/>)}</div>
    <label className="color-picker" title="调色盘"><input type="color" aria-label="调色盘" value={options.color} onChange={e=>change('color',e.target.value)}/><span>调色</span></label>
   </div>
   <div className="drawing-toolbar"><div className="tool-group">{tools.map(([id,label,Icon])=><IconButton key={id} label={label} icon={Icon} aria-pressed={tool===id} onClick={()=>chooseTool(id)}/>)}</div><div className="tool-group"><IconButton label="撤销 (Ctrl+Z)" icon={Undo2} disabled={!history.length&&!text} onClick={undo}/><IconButton label="重做 (Ctrl+Y)" icon={Redo2} disabled={!future.length} onClick={redo}/></div><span className="drawing-status" role="status">{error|| (busy?'正在生成贴图…':`${objects.length} 个对象`)}</span><IconButton label="取消 (Esc)" icon={X} disabled={busy} onClick={()=>api.cancel()}/><button className="finish" disabled={busy} onClick={finish}><Check size={19}/>完成贴图</button></div>
  </section>
 </main>
}

async function ready(){const api=window.pywebview.api;const context=await api.context();createRoot(document.getElementById('root')).render(context.mode==='draw'?<Draw api={api} context={context}/>:<Actions api={api}/>)}
window.addEventListener('pywebviewready',ready,{once:true});
