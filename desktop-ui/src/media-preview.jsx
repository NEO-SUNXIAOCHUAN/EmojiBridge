import React,{useEffect,useState} from 'react';
let serial=0;
export const HOVER_DELAY=900;
// The library and collections share one bounded native decoder and identity
// fence. A departed hover can never paint or close its successor's stream.
export function useMediaPreview(call,ident,enabled=true,version='',prepare){
 const [value,setValue]=useState(null),[error,setError]=useState('');
 useEffect(()=>{
  setValue(null);setError('');if(!ident||!enabled)return;
  let live=true,timer,requested=false,initialFailure,deadline=performance.now(),lastFrame=performance.now();const generation=Date.now()*1000+(++serial%1000);
  const box=document.querySelector('.hover-preview .preview-image')?.getBoundingClientRect();
  const size=[box?.width||760,box?.height||560].map(n=>Math.ceil(n*Math.min(3,window.devicePixelRatio||1)));
  const run=async()=>{try{const frame=await call('preview_frame',ident,generation);if(!live)return;
   if(frame?.error){setError(frame.error);return}if(frame?.image){lastFrame=performance.now();setValue(frame);setError('')}
   if(!frame?.image&&!frame?.ended&&performance.now()-lastFrame>15000){setError('原件读取超时，可在详情重试');call('preview_stop',generation).catch(()=>{});return}
   if(!frame?.ended&&frame?.count!==1){deadline=Math.max(deadline,performance.now()-(frame?.duration||40))+(frame?.duration||40);timer=setTimeout(run,Math.max(0,deadline-performance.now()))}
  }catch(e){if(live)setError('预览暂不可用，移开后重试。')}};
  const started=performance.now();
  const start=()=>call('preview_start',ident,generation,size).then(ok=>{if(!live)return;if(ok===true){deadline=lastFrame=performance.now();run()}else if(ok?.error){setError(ok.error)}else if(performance.now()-started<90000){if(ok?.pending&&!requested){requested=true;initialFailure=ok.failure;prepare?.()}else if(ok?.failure&&ok.failure!==initialFailure){setError('本次原件准备未完成，可在详情重试；已有封面保留');return}if(ok?.message)setError(ok.message);timer=setTimeout(start,400)}else setError('原件尚未取得，可在详情重试；已有封面保留')}).catch(e=>{if(live)setError('预览暂不可用，移开后重试。')});
  start();
  return()=>{live=false;clearTimeout(timer);call('preview_stop',generation).catch(()=>{})};
 },[ident,enabled,version]);
 return {frame:value,error};
}
export function HoverPreview({item,frame,error,caption}){
 return <div className="hover-preview"><div className="preview-image"><img src={frame?.image||item.thumbnail} alt={item.name}/></div><b>{item.name}</b><small>{error||caption||(frame?.count>1?`${frame.index+1} / ${frame.count} 帧`:'')}</small></div>;
}
