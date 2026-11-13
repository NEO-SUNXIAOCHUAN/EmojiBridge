// Selection belongs to its source, even when exact content groups merge.
export const SOURCES=['qq','wechat','local'];
export const emptySelection=()=>Object.fromEntries(SOURCES.map(c=>[c,[]]));
export const selectedIds=(state,source='')=>source?(state[source]||[]):[...new Set(SOURCES.flatMap(c=>state[c]||[]))];
const members=(row,c)=>(row.members||[]).filter(m=>m.client===c&&!m.unseen);
export function selectRows(state,rows,source=''){
 const next={...state};
 for(const c of source?[source]:SOURCES)next[c]=rows.filter(row=>members(row,c).length).map(row=>row.id);
 return next;
}
export function toggleRow(state,row,source=''){
 const next={...state},remove=selectedIds(state,source).includes(row.id);
 for(const c of source?[source]:SOURCES){
  if(!members(row,c).length)continue;
  next[c]=remove?(state[c]||[]).filter(id=>id!==row.id):[...new Set([...(state[c]||[]),row.id])];
 }
 return next;
}
export function reconcileSelection(state,before,after){
 const next=emptySelection();
 for(const c of SOURCES){
  const old=new Set(state[c]||[]);
  const identities=new Set(before.filter(r=>old.has(r.id)).flatMap(r=>members(r,c).map(m=>m.observation_key||m.id)));
  next[c]=after.filter(r=>members(r,c).some(m=>old.has(r.id)||identities.has(m.observation_key||m.id))).map(r=>r.id);
 }
 return next;
}
export function transferRows(rows,state,target,source=''){
 const opposite=target==='qq'?'wechat':'qq';
 if(source&&source!==opposite&&source!=='local')return [];
 const ids=new Set([...(source==='local'?[]:state[opposite]||[]),...(!source||source==='local'?state.local||[]:[])]);
 return rows.filter(r=>!r.historical_only&&ids.has(r.id));
}
export function selectedReady(row,state,source=''){
 return (source?[source]:SOURCES).some(c=>(state[c]||[]).includes(row.id)&&members(row,c).some(m=>m.original_ready));
}
