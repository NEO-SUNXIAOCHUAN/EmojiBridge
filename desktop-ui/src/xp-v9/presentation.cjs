// Adapt backend monotonic elapsed time, not refresh counts, to the supplied V9.
const {createLifecycle}=require('./lifecycle.cjs');
const createMotion=require('./motion.cjs');
function createPresentation({now=()=>performance.now()/1000,onEffect=()=>{}}={}){
 let id=null,token=null,base=0,at=now(),start=0,running=false;const retired=new Set();
 const clock=()=>base+(now()-at);
 const life=createLifecycle({now:clock,closingDuration:n=>createMotion({elapsedSeconds:n}).timeline.end,onEffect});
 function retire(){if(id){retired.add(id);if(retired.size>32)retired.delete(retired.values().next().value)}}
 return {update(task){
   if(!task?.id||retired.has(task.id))return false;
   if(task.id!==id){if(!task.active&&!(task.end_age>=0&&task.end_age<2))return false;retire();life.reset();id=task.id;base=clock();at=now();start=base;token=life.start();running=true}
   if(!running)return false;
   base=start+Math.max(0,Number(task.elapsed)||0);at=now();
   if(!task.active){running=false;if(task.state==='success')life.complete(token);else if(task.state==='cancelled')life.cancel(token);else life.error(token)}
   return true;
 },sample:()=>life.sample(),reset(){retire();id=null;running=false;life.reset()},dispose:()=>life.dispose(),get id(){return id}};
}
module.exports={createPresentation};
