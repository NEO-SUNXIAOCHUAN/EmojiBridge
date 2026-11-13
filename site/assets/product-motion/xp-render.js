import createMotion from './xp-motion.js';
const digits=await fetch(new URL('./xp/digits.json',import.meta.url)).then(r=>r.json());
export async function renderer(canvas){
 const names={empty:'experience_bar_background',full:'experience_bar_progress',orb:'experience_orb',glass:'glass_bottle',bottle:'experience_bottle'};
 const imgs={};await Promise.all(Object.entries(names).map(async([k,n])=>{const im=new Image();im.src=new URL('./xp/'+n+'.png',import.meta.url).href;await im.decode();imgs[k]=im}));
 const small=document.createElement('canvas');small.width=small.height=16;const s=small.getContext('2d');s.drawImage(imgs.bottle,0,0,16,16);const pixels=s.getImageData(0,0,16,16).data,mask=[];
 for(let y=0;y<16;y++)for(let x=0;x<16;x++){const a=pixels[(y*16+x)*4+3]/255;if(a)mask.push({x,y,a})}
 const sprites=Array.from({length:3},(_,tile)=>Array.from({length:16},(_,tint)=>{const c=document.createElement('canvas');c.width=c.height=16;const g=c.getContext('2d');g.imageSmoothingEnabled=false;g.drawImage(imgs.orb,tile*16,0,16,16,0,0,16,16);g.globalCompositeOperation='source-atop';g.fillStyle=`rgba(${125+tint*8},255,30,.5)`;g.fillRect(0,0,16,16);return c}));
 const ctx=canvas.getContext('2d'),w=720,h=180,x=87,y=82,scale=3;canvas.width=w;canvas.height=h;let motion,level;
 function number(n){const text=String(n),size=4,left=(w-(text.length*6-1)*size)/2;for(let i=0;i<text.length;i++){const d=digits[text[i]];if(!d)continue;for(let row=0;row<7;row++)for(let col=0;col<5;col++)if(d.rows[row][col]==='1'){ctx.fillStyle='#173600';ctx.fillRect(left+i*6*size+col*size+2,y-40+row*size+2,size,size);ctx.fillStyle='#80ff20';ctx.fillRect(left+i*6*size+col*size,y-40+row*size,size,size)}}}
 function bar(f){ctx.drawImage(imgs.empty,x,y,546,15);const p=Math.floor(182*Math.max(0,Math.min(1,f)));if(p)ctx.drawImage(imgs.full,0,0,p,5,x,y,p*3,15)}
 function orb(p){ctx.globalAlpha=p.alpha;ctx.drawImage(sprites[p.tile%3][p.tint%16],Math.round(p.x)-8,Math.round(p.y)-8,16,16);ctx.globalAlpha=1}
 return (state,reduced=false)=>{
 ctx.clearRect(0,0,w,h);ctx.imageSmoothingEnabled=false;
 if(state.phase!=='closing'){
  bar(state.barFraction);number(state.level);
  if(state.phase==='running'&&!reduced)for(let i=0;i<30;i++){const p=((state.elapsedSeconds*.7+i*.173)%1),side=i%2?-1:1,sx=w/2+side*(250+(i%5)*12),sy=y-44-(i%4)*10;orb({x:sx+(w/2-sx)*p*p,y:sy+(y+5-sy)*p,alpha:Math.sin(p*Math.PI)*.85,tile:i%3,tint:Math.floor((Math.sin(state.elapsedSeconds*5+i)+1)*7.5)})}
  return;
 }
 if(level!==state.completionLevel){level=state.completionLevel;motion=createMotion({elapsedSeconds:state.elapsedSeconds})}
 if(reduced){bar(0);number(state.completionLevel);return}
 const m=motion.sample(state.closingElapsed,w,x,y,scale);bar(m.fraction);number(m.remaining);
 if(m.alpha>0){ctx.save();ctx.translate(m.x,m.y);ctx.rotate(m.angle);ctx.globalAlpha=m.alpha*(1-m.full);ctx.drawImage(imgs.glass,-24,-24,48,48);ctx.globalAlpha=m.alpha*m.full;ctx.drawImage(imgs.bottle,-24,-24,48,48);
  if(m.full>0){const t=state.closingElapsed-motion.timeline.tilted,center=23-((t*16)%29);for(const p of mask){const strength=Math.pow(Math.max(0,1-Math.abs(p.x+.65*p.y-center)/4.5),1.2);if(!strength)continue;const b=.5+.5*Math.sin(t*3+p.y*.25);ctx.fillStyle=`rgb(${Math.round(159-56*b)},${Math.round(94+14*b)},${Math.round(225+20*b)})`;ctx.globalAlpha=m.alpha*m.full*p.a*.68*strength;ctx.fillRect(-24+p.x*3,-24+p.y*3,3,3)}}ctx.restore();
 }
 for(const p of m.orbs)orb(p);
 };
}
