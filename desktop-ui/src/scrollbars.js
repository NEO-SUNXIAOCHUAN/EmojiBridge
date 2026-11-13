// Common passive scroll activity for the real pages, sheets and pocket window.
// Native scrollbars retain their keyboard, wheel, capture and accessibility.
import './scrollbars.css';
export function installScrollActivity(doc=document){
 if(doc.__scrollActivity)return doc.__scrollActivity;
 const timers=new Map();let grabbed=null,hovered=null;
 const scrollable=n=>n instanceof Element&&n.scrollHeight>n.clientHeight+1&&/auto|scroll/.test(getComputedStyle(n).overflowY)||n instanceof Element&&n.scrollWidth>n.clientWidth+1&&/auto|scroll/.test(getComputedStyle(n).overflowX);
 const arm=n=>{clearTimeout(timers.get(n));if(n===grabbed||n===hovered)return;timers.set(n,setTimeout(()=>{n.removeAttribute('data-scroll-active');timers.delete(n)},1000))};
 const show=n=>{if(!n)return;clearTimeout(timers.get(n));n.setAttribute('data-scroll-active','');arm(n)};
 const owner=target=>{for(let n=target;n instanceof Element;n=n.parentElement)if(scrollable(n))return n;return null};
 const scroll=e=>show(e.target instanceof Element?e.target:null);
 const move=e=>{const n=owner(e.target),r=n?.getBoundingClientRect();const next=n&&((n.scrollHeight>n.clientHeight+1&&e.clientX>=r.right-18)||(n.scrollWidth>n.clientWidth+1&&e.clientY>=r.bottom-18))?n:null;if(hovered&&hovered!==next){const old=hovered;hovered=next;arm(old)}else hovered=next;if(next)show(next)};
 const down=e=>{move(e);if(hovered){grabbed=hovered;show(grabbed)}};
 const up=()=>{const n=grabbed;grabbed=null;if(n)arm(n)};
 const leave=()=>{const n=hovered;hovered=null;if(n)arm(n)};
 const key=e=>{if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','PageUp','PageDown','Home','End'].includes(e.key))show(owner(e.target))};
 doc.addEventListener('scroll',scroll,true);doc.addEventListener('pointermove',move,{passive:true});doc.addEventListener('pointerdown',down,true);doc.addEventListener('pointerup',up,true);doc.addEventListener('pointercancel',up,true);doc.addEventListener('keydown',key,true);doc.documentElement.addEventListener('pointerleave',leave);
 const close=()=>{for(const t of timers.values())clearTimeout(t);timers.clear();doc.removeEventListener('scroll',scroll,true);doc.removeEventListener('pointermove',move);doc.removeEventListener('pointerdown',down,true);doc.removeEventListener('pointerup',up,true);doc.removeEventListener('pointercancel',up,true);doc.removeEventListener('keydown',key,true);doc.documentElement.removeEventListener('pointerleave',leave);delete doc.__scrollActivity};
 doc.__scrollActivity=close;return close;
}
installScrollActivity();
