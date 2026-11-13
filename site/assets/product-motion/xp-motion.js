// No DOM, clocks, promises, audio, or unbounded allocation. Seconds are monotonic
// task time captured at a genuine success event; motion time is since success.
const clamp=x=>Math.max(0,Math.min(1,x));
const smooth=x=>{x=clamp(x);return x*x*x*(x*(x*6-15)+10);};
const lerp=(a,b,t)=>a+(b-a)*t;
const cubic=(a,b,c,d,u)=>{const v=1-u;return v*v*v*a+3*v*v*u*b+3*v*u*u*c+u*u*u*d;};
function createMotion(options={}){
  const raw=Number(options.elapsedSeconds);
  const elapsedSeconds=Number.isFinite(raw)?Math.min(Number.MAX_SAFE_INTEGER,Math.max(0,raw)):0;
  // Decimal seconds never produce a fabricated extra level. The minimum is
  // only a success-animation presentation rule, never an 8-second task delay.
  const level=Math.max(8,Math.floor(elapsedSeconds));
  const absorbDuration=1.65+Math.min(.6,Math.max(0,Math.log2(level/8))*.15);
  const timeline=Object.freeze({appear:1.36,tilted:2.16,absorbEnd:2.16+absorbDuration,upright:2.44+absorbDuration,exit:2.44+absorbDuration,gone:3.09+absorbDuration,end:3.45+absorbDuration});
  // Low levels reverse the original per-level bar. High levels use grouped
  // drains to avoid dozens of flashes per second; number remains true XP.
  const barCycles=level<=32?level:12;
  const groupCount=Math.min(16,Math.max(8,level)),particleCount=groupCount*3;
  const arrivals=Array.from({length:groupCount},(_,i)=>timeline.tilted+.24+(absorbDuration-.24)*i/(groupCount-1));
  function bottlePose(time,w,barY){
    const size=48,baseX=w/2+166,baseY=barY+43;
    let x=w+30,y=baseY+8,angle=0,alpha=0;
    if(time>=timeline.appear&&time<timeline.tilted){
      const raw=clamp((time-timeline.appear)/(timeline.tilted-timeline.appear)),u=smooth(raw);
      x=lerp(w+30,baseX-3,u);y=lerp(baseY+8,baseY-2,u)-4*Math.sin(Math.PI*u);
      angle=-32*Math.PI/180*smooth((raw-.3)/.7);alpha=smooth(raw/.28);
    }else if(time>=timeline.tilted&&time<timeline.absorbEnd){
      const u=(time-timeline.tilted)/absorbDuration,env=Math.sin(Math.PI*u)**2;
      x=baseX-3-1.2*env;y=baseY-2+.7*Math.sin(2*Math.PI*u)*env;angle=-32*Math.PI/180;alpha=1;
    }else if(time>=timeline.absorbEnd&&time<timeline.upright){
      const u=smooth((time-timeline.absorbEnd)/(timeline.upright-timeline.absorbEnd));
      x=baseX-3*(1-u);y=baseY-2*(1-u);angle=-32*Math.PI/180*(1-u);alpha=1;
    }else if(time>=timeline.exit&&time<timeline.gone){
      const raw=clamp((time-timeline.exit)/(timeline.gone-timeline.exit)),u=smooth(raw);
      x=cubic(baseX,baseX+35,w-10,w+30,u);y=cubic(baseY,baseY-8,baseY-17,baseY-25,u);
      angle=.045*Math.sin(Math.PI*u);alpha=1-smooth((raw-.55)/.45);
    }
    // Small 1px impact pulse, independent of the potentially 999+ level count.
    for(let i=0;i<arrivals.length;i++){
      const dt=time-arrivals[i];if(dt<0||dt>.105)continue;
      const u=dt/.105,env=Math.sin(Math.PI*u)**2;
      x+=(i%2?1:-1)*.85*Math.sin(2*Math.PI*u)*env;y-=.7*env;
      angle+=(i%2?1:-1)*.012*Math.sin(2*Math.PI*u)*env;
    }
    const mouthLocalY=-18;
    return{x,y,angle,alpha,size,mouth:{x:x-mouthLocalY*Math.sin(angle),y:y+mouthLocalY*Math.cos(angle)}};
  }
  function sample(time,w=720,barX=87,barY=142,scale=3){
    time=Number.isFinite(time)?time:0;
    const pose=bottlePose(time,w,barY),u=clamp((time-timeline.tilted)/absorbDuration);
    const amount=level*(1-u),nearest=Math.round(amount);
    const remaining=u===1?0:Math.abs(amount-nearest)<1e-8?nearest:Math.floor(amount);
    const barAmount=barCycles*(1-u),nearBar=Math.round(barAmount);
    const fraction=(u===0||u===1||Math.abs(barAmount-nearBar)<1e-8)?0:barAmount-Math.floor(barAmount);
    const full=smooth((u-.73)/.27),orbs=[];
    if(u>0&&u<1){
      for(let group=0;group<groupCount;group++)for(let member=0;member<3;member++){
        const arrival=arrivals[group],flight=Math.min(.4+(group%3)*.055+member*.035,arrival-timeline.tilted),born=arrival-flight,p=(time-born)/flight;
        if(p<0||p>=1)continue;
        const i=group*3+member,sx=member===0?w/2+((group%5)-2)*5:barX+26+(i*71)%(182*scale-52),sy=member===0?barY-21:barY+2;
        const tx=pose.mouth.x,ty=pose.mouth.y,ax=Math.sin(pose.angle),ay=-Math.cos(pose.angle);
        const move=p*p*(.35+.65*p),x=cubic(sx,sx+Math.min(90,(tx-sx)*.32),tx+ax*(19+member*4),tx,move),y=cubic(sy,sy-13-member*6,ty+ay*(19+member*4),ty,move);
        orbs.push({x,y,alpha:smooth(p/.16)*(1-smooth((p-.97)/.03)),tint:Math.round((Math.sin(time*9+i*1.63)+1)*7.5),tile:i%3,group,arrival});
      }
    }
    const phase=time<timeline.appear?'result':time<timeline.tilted?'enter':time<timeline.absorbEnd?'absorb':time<timeline.upright?'upright':time<timeline.gone?'exit':'idle';
    return{...pose,time,remaining,fraction,amount,absorbed:level-amount,full,orbs,phase,level,barCycles};
  }
  return Object.freeze({sample,pose:bottlePose,timeline,arrivals,level,elapsedSeconds,particleCount,barCycles});
}
export default createMotion;
