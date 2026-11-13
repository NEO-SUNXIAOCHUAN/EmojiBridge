import React,{useEffect,useRef} from 'react';
import './logo-layers';

// Uses the original pixels for both body and eyes; only eye height changes.
// This interaction owns one interruptible RAF, entirely separate from startup.
export function InteractiveBrand({reduced=false,onClick}){
 const ref=useRef(null),control=useRef(null);
 useEffect(()=>{
  const canvas=ref.current,c=canvas.getContext('2d'),image=new Image();let live=true,raf=0,last=0,amount=0,target=0,until=0,layers;
  const draw=()=>{const d=devicePixelRatio||1;canvas.width=32*d;canvas.height=32*d;c.setTransform(d/16,0,0,d/16,0,0);c.clearRect(0,0,512,512);
   if(!layers||amount<.001){c.drawImage(image,0,0,512,512);return}
   c.drawImage(layers.body,0,0);
   for(const [x,y,w,h] of [[137,195,103,65],[275,190,104,62]]){
    // Crop disjoint original eye areas, preserving angle, colour and spacing.
    const stretch=1+.7*amount;c.drawImage(layers.eyes,x,y,w,h,x,y+h*(1-stretch)/2,w,h*stretch);
   }
  };
  const tick=now=>{raf=0;if(!live||document.hidden)return;if(now>=until)target=0;const dt=Math.min(50,now-(last||now-16));last=now;amount+=(target-amount)*(1-Math.exp(-dt/65));draw();if(Math.abs(target-amount)>.001||now<until)raf=requestAnimationFrame(tick)};
  const react=level=>{if(!layers||!live)return;if(reduced){canvas.style.opacity='.84';clearTimeout(control.current?.timer);control.current.timer=setTimeout(()=>{if(live)canvas.style.opacity=''},120);return}target=level;until=performance.now()+(level>1?460:300);last=performance.now();if(!raf)raf=requestAnimationFrame(tick)};
  const stop=()=>{cancelAnimationFrame(raf);raf=0;amount=target=0;if(layers)draw()};
  control.current={react,timer:null};image.src='/startup-v10/EmojiBridge-A.png';image.decode().then(()=>{if(live){layers=globalThis.EmojiBridgeLogoLayers.prepare(c,image);draw()}}).catch(async()=>{image.src='/brand.png';try{await image.decode();if(live)draw()}catch{}});
  const visibility=()=>{if(document.hidden)stop()};document.addEventListener('visibilitychange',visibility);
  return()=>{live=false;stop();clearTimeout(control.current?.timer);document.removeEventListener('visibilitychange',visibility)};
 },[reduced]);
 return <button className="brand-interaction" aria-label="EmojiBridge · 返回素材库" onPointerEnter={()=>control.current?.react(1)} onClick={()=>{control.current?.react(1.5);onClick?.()}}><canvas ref={ref} style={{width:32,height:32}} aria-hidden="true"/></button>;
}
