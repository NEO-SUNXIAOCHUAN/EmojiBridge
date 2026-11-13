/* Tencent original QQ paths with separately articulated original wing contours. */
(function(root){
 'use strict';
 const RAW_PATHS=["M25,43.86c-3.36,0-6.45-1.13-8.44-2.81-1.01,.3-2.3,.79-3.12,1.39-.7,.51-.61,1.04-.48,1.25,.55,.93,9.47,.59,12.04,.3v-.14Zm0,0c3.36,0,6.45-1.13,8.44-2.81,1.01,.3,2.3,.79,3.12,1.39,.7,.51,.61,1.04,.48,1.25-.55,.93-9.47,.59-12.04,.3v-.14Z","M25.02,23.7c5.55-.04,10.01-1.11,11.52-1.53,.36-.1,.55-.27,.55-.27,0-.05,.02-.9,.02-1.34,0-7.42-3.5-14.87-12.11-14.87-8.61,0-12.11,7.45-12.11,14.87,0,.44,.02,1.29,.02,1.34,0,0,.16,.17,.44,.25,1.39,.39,5.93,1.52,11.62,1.56h.04Zm15.09,6.18c-.34-1.11-.81-2.4-1.29-3.64,0,0-.27-.03-.41,0-4.27,1.24-9.45,2.03-13.39,1.98h-.04c-3.92,.05-9.06-.73-13.32-1.96-.16-.05-.48-.03-.48-.03-.48,1.24-.95,2.53-1.29,3.64-1.64,5.28-1.11,7.47-.71,7.52,.87,.11,3.38-3.98,3.38-3.98,0,4.15,3.75,10.52,12.32,10.58h.23c8.58-.06,12.32-6.43,12.32-10.58,0,0,2.51,4.08,3.38,3.98,.4-.05,.94-2.24-.71-7.52","M21.94,16.65c-1.17,.05-2.17-1.28-2.23-2.97-.06-1.69,.83-3.11,2-3.16,1.17-.05,2.16,1.28,2.23,2.97,.06,1.69-.83,3.11-2,3.16m8.36-2.97c-.06,1.69-1.06,3.02-2.23,2.97-1.17-.05-2.06-1.47-2-3.16,.06-1.69,1.06-3.02,2.23-2.97,1.17,.05,2.06,1.47,2,3.16","M32.37,19.04c-.31-.69-3.46-1.46-7.35-1.46h-.04c-3.89,0-7.03,.77-7.35,1.46-.01,.03-.02,.06-.02,.1,0,.05,.02,.09,.04,.13,.26,.38,3.75,2.28,7.33,2.28h.04c3.57,0,7.06-1.89,7.33-2.28,.03-.04,.04-.09,.04-.13,0-.03,0-.07-.02-.1","M23.37,13.7c.05,.67-.31,1.26-.82,1.33-.51,.06-.96-.42-1.01-1.09-.05-.67,.31-1.26,.82-1.33,.51-.07,.96,.42,1.01,1.09m3.21,.22c.1-.18,.81-1.16,2.26-.8,.38,.09,.56,.23,.6,.28,.06,.08,.07,.19,.01,.35-.11,.3-.34,.29-.47,.23-.08-.04-1.1-.71-2.03,.29-.06,.07-.18,.09-.29,.01-.11-.08-.15-.25-.09-.37","M25.02,27.99h-.04c-2.68,.03-5.94-.32-9.09-.94-.27,1.56-.43,3.52-.29,5.86,.35,5.92,3.87,9.63,9.29,9.69h.22c5.42-.05,8.94-3.77,9.29-9.69,.14-2.34-.02-4.3-.29-5.87-3.15,.62-6.4,.98-9.09,.94","M17.38,27.49v5.82s2.67,.54,5.34,.17v-5.37c-1.69-.1-3.52-.31-5.34-.62","M37.09,21.9s-5.19,1.64-12.07,1.68h-.04c-6.87-.05-12.05-1.68-12.07-1.68l-1.74,4.34c4.35,1.31,9.73,2.15,13.8,2.11h.04c4.07,.05,9.46-.8,13.8-2.11l-1.74-4.34Z"];
 const TAU=Math.PI*2,clamp=n=>Math.max(0,Math.min(1,Number(n)||0));
 const mix=(a,b,p)=>a+(b-a)*p,range=(t,a,b)=>clamp((t-a)/(b-a));
 const smooth=p=>{p=clamp(p);return p*p*p*(p*(p*6-15)+10)};
 const L={x:13.1,y:23.6},R={x:36.9,y:23.6};
 const LT={x:8.4375,y:37.375},RT={x:41.5625,y:37.375};
 const HANDOVER={x:25.8,y:32.2},BADGE={x:35.8,y:7.0};
 const polar=(a,r,p)=>({x:p.x+Math.cos(a)*r,y:p.y+Math.sin(a)*r});
 const angle=(p,q)=>Math.atan2(q.y-p.y,q.x-p.x),dist=(p,q)=>Math.hypot(q.x-p.x,q.y-p.y);
 const LA0=angle(L,LT),LR0=dist(L,LT),RA0=angle(R,RT),RR0=dist(R,RT);
 const blend=(a,b,p)=>({x:mix(a.x,b.x,p),y:mix(a.y,b.y,p)});
 const cubic=(a,b,c,d,p)=>{const q=1-p;return{x:q*q*q*a.x+3*q*q*p*b.x+3*q*p*p*c.x+p*p*p*d.x,y:q*q*q*a.y+3*q*q*p*b.y+3*q*p*p*c.y+p*p*p*d.y}};
 let paths;
 function getPaths(){
  if(paths)return paths;
  // Outer Bezier segments are taken directly from the original black compound path.
  // Only the shoulder closure is added inside the torso where it is occluded.
  const left='M13.1,23.6 L11.18,26.23 C10.70,27.47 10.23,28.76 9.89,29.87 C8.25,35.15 8.78,37.34 9.18,37.39 C10.05,37.50 12.56,33.41 12.56,33.41 Z';
  const right='M36.9,23.6 L38.82,26.24 C39.30,27.48 39.77,28.77 40.11,29.88 C41.76,35.16 41.22,37.35 40.82,37.40 C39.95,37.50 37.43,33.41 37.43,33.41 Z';
  const torso='M11.66,26.26 C15.92,27.49 21.06,28.27 24.98,28.22 H25.02 C28.96,28.27 34.14,27.48 38.41,26.24 L37.43,33.41 C37.43,37.56 33.68,43.93 25.11,43.99 H24.88 C16.31,43.93 12.56,37.56 12.56,33.41 Z';
  paths={original:RAW_PATHS.map(d=>new root.Path2D(d)),left:new root.Path2D(left),right:new root.Path2D(right),torso:new root.Path2D(torso),head:new root.Path2D(RAW_PATHS[1].split('Zm15.09')[0]+'Z'),leftPupil:new root.Path2D(RAW_PATHS[4].split('m3.21')[0]+'Z')};
  return paths;
 }
 function values(o={}){return{x:Number.isFinite(o.x)?o.x:1420,y:Number.isFinite(o.y)?o.y:495,size:Number.isFinite(o.size)?o.size:310,scale:Number.isFinite(o.scale)?o.scale:1,alpha:o.alpha===undefined?1:clamp(o.alpha),squash:clamp(o.squash),carry:clamp(o.carry),settle:clamp(o.settle),exit:clamp(o.exit),eyeOpen:clamp(o.eyeOpen)}}
 function localRig(o){
  const c=o.carry;
  // Small catch-to-chest gesture, a brief shared hold, then the receiving
  // flipper carries along the outside of the cheek. The face remains clear.
  const offer=smooth(range(c,0,.35)),receive=smooth(range(c,.12,.35));
  let left=cubic(LT,{x:12.2,y:38.5},{x:20.4,y:34.0},HANDOVER,offer);
  let right=cubic(RT,{x:37.8,y:38.5},{x:30.4,y:34.0},HANDOVER,receive);
  let hand=left;
  if(c>=.42){
   const p=smooth(range(c,.42,1));
   // A single continuous curve leads out from the belly and up around the
   // shoulder. It never crosses the beak/eyes or goes over the crown.
   right=cubic(HANDOVER,{x:53.2,y:35.8},{x:46.7,y:12.1},BADGE,p);
   hand=right;
   left=cubic(HANDOVER,{x:19.0,y:34.0},{x:12.7,y:37.8},LT,smooth(range(c,.45,.79)));
  }
  const beforeSettle=right;
  if(o.settle>0){
   // Reverse the short outer arc after the badge has attached. Only the wing
   // withdraws; handPoint stays at the attachment position for continuity.
   right=cubic(beforeSettle,{x:47.2,y:12.2},{x:46.2,y:31.3},RT,smooth(o.settle));
   left=blend(left,LT,smooth(o.settle));
  }
  return{left,right,hand};
 }
 function toWorld(point,o){
  const sx=1+.02*o.squash,sy=1-.025*o.squash;
  const x=25+(point.x-25)*sx,y=44.2+(point.y-44.2)*sy;
  const k=o.size/50*o.scale;return{x:o.x+(x-25)*k,y:o.y+(y-25)*k};
 }
 function handPoint(opts={}){const o=values(opts);return toWorld(localRig(o).hand,o)}
 function badgePoint(opts={}){const o=values(opts);return toWorld(BADGE,o)}
 function ellipse(c,x,y,rx,ry){c.beginPath();c.ellipse(x,y,rx,ry,0,0,TAU)}
 function ice(c,o){
  const k=o.size/310*o.scale;
  c.save();c.translate(o.x,o.y+130*k);c.scale(k,k);
  ellipse(c,0,30,94,9);c.fillStyle='rgba(0,0,0,.18)';c.fill();
  const front=c.createLinearGradient(0,0,0,31);front.addColorStop(0,'#567b94');front.addColorStop(1,'#30495d');
  c.beginPath();c.moveTo(-105,-1);c.quadraticCurveTo(0,26,105,-1);c.lineTo(87,22);c.quadraticCurveTo(0,43,-89,21);c.closePath();c.fillStyle=front;c.fill();
  const top=c.createLinearGradient(-75,-15,75,15);top.addColorStop(0,'#b6cddb');top.addColorStop(.55,'#8bacbf');top.addColorStop(1,'#62869e');
  c.beginPath();c.moveTo(-105,-1);c.quadraticCurveTo(-85,-18,-28,-21);c.quadraticCurveTo(59,-27,105,-1);c.quadraticCurveTo(0,27,-105,-1);c.closePath();c.fillStyle=top;c.fill();
  c.strokeStyle='rgba(227,243,246,.57)';c.lineWidth=1.6;c.beginPath();c.moveTo(-99,-2);c.quadraticCurveTo(-63,-25,-3,-22);c.stroke();
  c.strokeStyle='rgba(205,226,236,.37)';c.lineWidth=1.4;c.beginPath();c.moveTo(48,-13);c.lineTo(35,-2);c.lineTo(56,9);c.stroke();
  ellipse(c,0,0,53,8);c.fillStyle='rgba(15,36,51,.20)';c.fill();c.restore();
 }
 function drawWing(c,path,pivot,tip,restTip,moving){
  // At rest retain the exact Tencent contour. During the gesture the same
  // narrow flipper bends as a soft tapered shape instead of an angular lever.
  const a0=angle(pivot,restTip),a=angle(pivot,tip),r0=dist(pivot,restTip),r=dist(pivot,tip);
  const flex=smooth(range(dist(tip,restTip),.2,3.6));
  if(flex<1){
   c.save();c.globalAlpha*=1-flex;c.translate(pivot.x,pivot.y);c.rotate(a);c.scale(r/r0,1);c.rotate(-a0);c.translate(-pivot.x,-pivot.y);c.fillStyle='#000';c.fill(path);c.restore();
  }
  if(flex<=0)return;
  const side=pivot.x<25?-1:1;
  const control={x:mix(pivot.x,tip.x,.55)+side*2.2,y:mix(pivot.y,tip.y,.55)};
  const tangent=(p,q)=>{const d=Math.hypot(q.x-p.x,q.y-p.y)||1;return{x:(q.x-p.x)/d,y:(q.y-p.y)/d}};
  const u=tangent(pivot,control),v=tangent(control,tip),w=tangent(pivot,tip);
  const n={x:-u.y,y:u.x},m={x:-v.y,y:v.x},z={x:-w.y,y:w.x};
  const half=2.1;
  c.save();c.globalAlpha*=flex;c.beginPath();
  c.moveTo(pivot.x+n.x*half,pivot.y+n.y*half);
  c.quadraticCurveTo(control.x+z.x*1.8,control.y+z.y*1.8,tip.x+m.x*.45,tip.y+m.y*.45);
  c.quadraticCurveTo(tip.x+v.x*.55,tip.y+v.y*.55,tip.x-m.x*.45,tip.y-m.y*.45);
  c.quadraticCurveTo(control.x-z.x*1.8,control.y-z.y*1.8,pivot.x-n.x*half,pivot.y-n.y*half);
  c.closePath();c.fillStyle='#000';c.fill();
  if(moving>0){c.strokeStyle='rgba(77,95,111,'+(moving*.17)+')';c.lineWidth=.12;c.lineJoin='round';c.stroke()}
  c.restore();
 }
 // Only the brief receive expression changes: the original wink opens as one
 // continuous contour, so there is never a ghost pupil or a doubled eye.
 const WINK_START={x:26.58,y:13.92};
 const WINK_CURVES=[
  [.10,-.18,.81,-1.16,2.26,-.80],
  [.38,.09,.56,.23,.60,.28],
  [.06,.08,.07,.19,.01,.35],
  [-.11,.30,-.34,.29,-.47,.23],
  [-.08,-.04,-1.10,-.71,-2.03,.29],
  [-.06,.07,-.18,.09,-.29,.01],
  [-.11,-.08,-.15,-.25,-.09,-.37]
 ];
 const OPEN_ANGLES=[1,1.65,1.85,2.05,2.25,2.65,2.90,3].map(n=>n*Math.PI);
 function eyeWhites(c,p,open){
  c.fillStyle='#fff';
  if(open<=0){c.fill(p.original[2]);return}
  c.save();c.translate(25,13.60);c.scale(1,1+.12*open);c.translate(-25,-13.60);c.fill(p.original[2]);c.restore();
 }
 function pupils(c,p,open){
  c.fillStyle='#000';
  if(open<=0){c.fill(p.original[4]);return}
  // A slight lower-left glance acknowledges the light in the receiving hand.
  c.save();c.translate(-.45*open,.22*open);c.fill(p.leftPupil);c.restore();
  const cx=27.93,cy=14.12,rx=.94,ry=1.22;
  const at=a=>({x:cx+rx*Math.cos(a),y:cy+ry*Math.sin(a)});
  const start=at(OPEN_ANGLES[0]);let old={...WINK_START};
  c.beginPath();c.moveTo(mix(old.x,start.x,open),mix(old.y,start.y,open));
  for(let i=0;i<WINK_CURVES.length;i++){
   const d=WINK_CURVES[i],a=OPEN_ANGLES[i],b=OPEN_ANGLES[i+1],k=4/3*Math.tan((b-a)/4),p0=at(a),p1=at(b);
   const t1={x:p0.x-k*rx*Math.sin(a),y:p0.y+k*ry*Math.cos(a)};
   const t2={x:p1.x+k*rx*Math.sin(b),y:p1.y-k*ry*Math.cos(b)};
   c.bezierCurveTo(mix(old.x+d[0],t1.x,open),mix(old.y+d[1],t1.y,open),mix(old.x+d[2],t2.x,open),mix(old.y+d[3],t2.y,open),mix(old.x+d[4],p1.x,open),mix(old.y+d[5],p1.y,open));
   old={x:old.x+d[4],y:old.y+d[5]};
  }
  c.closePath();c.fill();
 }
 function drawTarget(c,opts={},assets={}){
  const o=values(opts);if(!o.alpha||o.scale<=0)return;
  const p=getPaths(),r=localRig(o),moving=Math.sin(Math.PI*o.carry)*(1-o.settle);
  c.save();c.globalAlpha*=o.alpha;ice(c,o);
  const halo=c.createRadialGradient(o.x,o.y+10,14,o.x,o.y+10,160*o.scale);halo.addColorStop(0,'rgba(77,104,130,.18)');halo.addColorStop(.58,'rgba(60,89,114,.09)');halo.addColorStop(1,'rgba(60,89,114,0)');c.fillStyle=halo;c.fillRect(o.x-170*o.scale,o.y-170*o.scale,340*o.scale,340*o.scale);
  c.translate(o.x,o.y);c.scale(o.size/50*o.scale,o.size/50*o.scale);c.translate(-25,-25);
  c.translate(25,44.2);c.scale(1+.02*o.squash,1-.025*o.squash);c.translate(-25,-44.2);
  c.fillStyle='#faab07';c.fill(p.original[0]);
  c.fillStyle='#000';c.fill(p.head);c.fill(p.torso);
  c.fillStyle='#fff';c.fill(p.original[5]);
  // Articulated wings pass in front of the torso, while unchanged face layers stay clear.
  drawWing(c,p.left,L,r.left,LT,moving);
  drawWing(c,p.right,R,r.right,RT,moving);
  eyeWhites(c,p,o.eyeOpen);
  c.fillStyle='#faab07';c.fill(p.original[3]);
  pupils(c,p,o.eyeOpen);
  c.fillStyle='#eb1923';c.fill(p.original[6]);c.fill(p.original[7]);
  c.restore();
 }
 const api={drawTarget,handPoint,badgePoint};root.EmojiBridgeQQ=api;if(typeof module!=='undefined')module.exports=api;
})(globalThis);
