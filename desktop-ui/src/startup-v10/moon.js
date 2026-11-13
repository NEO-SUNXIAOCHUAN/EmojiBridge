/* V9 lunar sender: slightly rounder original bubbles within the existing footprint. */
(function(root){
 'use strict';
 const RAW_PATHS=["M4.77,20.83c0,3.73,1.97,7.09,5.06,9.36,.25,.18,.41,.47,.41,.81,0,.11-.02,.21-.05,.32-.25,.93-.64,2.43-.66,2.5-.03,.12-.08,.24-.08,.36,0,.27,.22,.5,.49,.5,.11,0,.19-.04,.28-.09l3.21-1.88c.24-.14,.5-.23,.78-.23,.15,0,.29,.02,.43,.07,1.5,.44,3.11,.68,4.78,.68,8.09,0,14.65-5.54,14.65-12.38s-6.56-12.38-14.65-12.38S4.77,13.99,4.77,20.83", "M4.77,20.83c0,3.73,1.97,7.09,5.06,9.36,.25,.18,.41,.47,.41,.81,0,.11-.02,.21-.05,.32-.25,.93-.64,2.43-.66,2.5-.03,.12-.08,.24-.08,.36,0,.27,.22,.5,.49,.5,.11,0,.19-.04,.28-.09l3.21-1.88c.24-.14,.5-.23,.78-.23,.15,0,.29,.02,.43,.07,1.5,.44,3.11,.68,4.78,.68,8.09,0,14.65-5.54,14.65-12.38s-6.56-12.38-14.65-12.38S4.77,13.99,4.77,20.83", "M20.82,30.03c0,5.7,5.46,10.31,12.2,10.31,1.39,0,2.74-.2,3.98-.57,.11-.03,.23-.05,.36-.05,.23,0,.45,.07,.65,.19l2.67,1.56c.07,.04,.15,.08,.23,.08,.22,0,.41-.18,.41-.41,0-.1-.04-.2-.07-.3-.02-.06-.34-1.3-.55-2.08-.02-.09-.04-.17-.04-.26,0-.28,.13-.52,.34-.67,2.57-1.89,4.22-4.69,4.22-7.79,0-5.7-5.46-10.31-12.2-10.31s-12.2,4.62-12.2,10.31", "M35.59,26.88c0,.92,.73,1.66,1.63,1.66s1.63-.74,1.63-1.66-.73-1.66-1.63-1.66-1.63,.74-1.63,1.66", "M27.43,26.88c0,.92,.73,1.66,1.63,1.66s1.63-.74,1.63-1.66-.73-1.66-1.63-1.66-1.63,.74-1.63,1.66", "M16.48,16.85c0,1.1-.88,1.99-1.96,1.99s-1.96-.89-1.96-1.99,.88-1.99,1.96-1.99,1.96,.89,1.96,1.99", "M26.28,16.85c0,1.1-.88,1.99-1.96,1.99s-1.96-.89-1.96-1.99,.88-1.99,1.96-1.99,1.96,.89,1.96,1.99"];
 const TAU=Math.PI*2,clamp=x=>Math.max(0,Math.min(1,Number(x)||0));
 let paths=null,cached=null,cachedCtor=null;
 function getPaths(){if(!paths)paths=RAW_PATHS.map(d=>new root.Path2D(d));return paths}
 function ellipse(c,x,y,rx,ry,a=0){c.beginPath();c.ellipse(x,y,rx,ry,a,0,TAU)}
 function crater(c,x,y,r,angle=0){c.save();c.translate(x,y);c.rotate(angle);const g=c.createLinearGradient(0,-r,0,r);g.addColorStop(0,'#829699');g.addColorStop(.42,'#a9b9b8');g.addColorStop(1,'#dce4df');ellipse(c,0,0,r,r*.70);c.fillStyle=g;c.fill();c.strokeStyle='rgba(78,103,111,.40)';c.lineWidth=.28;c.beginPath();c.ellipse(0,0,r,r*.70,0,Math.PI*1.02,TAU);c.stroke();c.strokeStyle='rgba(255,255,244,.87)';c.lineWidth=.33;c.beginPath();c.ellipse(0,0,r*.99,r*.70,0,.08,Math.PI-.05);c.stroke();c.restore()}
 // Round each original bubble gently and bring their centres closer vertically.
 // The outer cluster keeps its V7/V8 width and height instead of gaining mass.
 const MOON_Y=1.02;
 function cluster(c){c.translate(25,25);c.scale(1,MOON_Y);c.translate(-25,-25)}
 function bubble(c,front){const x=front?33.02:19.42,y=front?30.03:20.83;c.translate(x,front?29.55:21.25);c.scale(1,front?1.05:1.06);c.translate(-x,-y)}
 function lunarMark(c){
  const p=getPaths();c.save();cluster(c);
  c.save();bubble(c,false);
  const back=c.createLinearGradient(10,8,28,34);back.addColorStop(0,'#f0f2eb');back.addColorStop(.54,'#d9e1dd');back.addColorStop(1,'#aabbbd');c.fillStyle=back;c.fill(p[0]);
  c.save();c.clip(p[0]);crater(c,11.2,24.2,2.05,-.22);crater(c,20.5,11.6,1.65,.12);crater(c,20.2,28.6,2.55,-.18);c.restore();c.restore();
  c.save();bubble(c,true);
  const front=c.createLinearGradient(25,20,42,39);front.addColorStop(0,'#f6f7ef');front.addColorStop(.52,'#e0e6df');front.addColorStop(1,'#b6c6c5');c.fillStyle=front;c.fill(p[2]);
  c.save();c.clip(p[2]);crater(c,35.5,35.5,2.0,-.22);crater(c,25.8,32.2,1.25,.15);crater(c,36.5,22.3,1.12,-.12);c.restore();c.restore();c.restore();
 }
 function eyes(c,effort){const p=getPaths(),sy=1-.82*effort;
  function eye(path,cx,cy,middle,stretch){c.save();c.translate(middle+(cx-middle)*.98,cy);c.scale(1.04,1.04*sy*(1.04/MOON_Y)/stretch);c.translate(-cx,-cy);c.fill(path);c.restore()}
  c.save();cluster(c);c.save();bubble(c,false);
  c.fillStyle='#405359';eye(p[5],14.52,16.85,19.42,1.06);eye(p[6],24.32,16.85,19.42,1.06);c.restore();
  c.save();bubble(c,true);c.fillStyle='#46575b';eye(p[3],37.22,26.88,33.14,1.05);eye(p[4],29.06,26.88,33.14,1.05);c.restore();c.restore();
 }
 function surface(c){const ctor=c.canvas?.constructor;if(cached&&cachedCtor===ctor)return cached;let a=null;if(typeof root.OffscreenCanvas==='function')a=new root.OffscreenCanvas(900,900);else if(root.document?.createElement){a=root.document.createElement('canvas');a.width=a.height=900}else{try{a=new c.canvas.constructor(900,900)}catch{}}if(!a?.getContext)return null;const d=a.getContext('2d');d.scale(18,18);lunarMark(d);cached=a;cachedCtor=ctor;return a}
 function values(o={}){return{x:Number.isFinite(o.x)?o.x:520,y:Number.isFinite(o.y)?o.y:493,size:Number.isFinite(o.size)?o.size:245,scale:Number.isFinite(o.scale)?o.scale:1,rot:Number(o.rot)||0,squeeze:clamp(o.squeeze),alpha:o.alpha===undefined?1:clamp(o.alpha)}}
 function sourcePoint(opts={}){const o=values(opts),sx=o.size/50*o.scale*(1-.14*o.squeeze),sy=o.size/50*o.scale*(1+.07*o.squeeze),x=6.7*sx,y=-12.0*1.04*sy;return{x:o.x+x*Math.cos(o.rot)-y*Math.sin(o.rot),y:o.y+x*Math.sin(o.rot)+y*Math.cos(o.rot)}}
 function drawSource(c,opts={}){const o=values(opts);if(o.alpha<=0||o.scale<=0)return;const a=surface(c);c.save();c.globalAlpha*=o.alpha;c.translate(o.x,o.y);c.rotate(o.rot);c.scale(o.scale*(1-.14*o.squeeze),o.scale*(1+.07*o.squeeze));if(a)c.drawImage(a,-o.size/2,-o.size/2,o.size,o.size);else{c.save();c.scale(o.size/50,o.size/50);c.translate(-25,-25);lunarMark(c);c.restore()}c.scale(o.size/50,o.size/50);c.translate(-25,-25);eyes(c,o.squeeze);c.restore()}

 const api={drawSource,sourcePoint};root.EmojiBridgeMoon=api;if(typeof module!=='undefined')module.exports=api;
})(globalThis);
