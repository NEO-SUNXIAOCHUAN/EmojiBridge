import {useRef,useState} from 'react';

// Event handlers and asynchronous listing refreshes share the latest selection.
// Copy is an explicit click effect, never a state-updater or render effect.
export function useSelectionState(initial){
 const [value,render]=useState(initial),current=useRef(value);
 const set=value=>{
  const next=typeof value==='function'?value(current.current):value;
  current.current=next;render(next);return next;
 };
 return [value,set,current];
}
