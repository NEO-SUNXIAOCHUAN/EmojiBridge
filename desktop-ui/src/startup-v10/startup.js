/* V10: unread badge -> light -> unread badge; keep the accepted orbital relay. */
(function(root){
'use strict';
const W=1920,H=1080,DURATION=11.9,TAU=Math.PI*2,SHIFT=.46;
const clamp=x=>Math.max(0,Math.min(1,x)),range=(t,a,b)=>clamp((t-a)/(b-a));
const smooth=x=>{x=clamp(x);return x*x*(3-2*x)};
const soft=x=>{x=clamp(x);return x*x*x*(x*(x*6-15)+10)};
const ease=(t,a,b)=>soft(range(t,a,b)),mix=(a,b,p)=>a+(b-a)*p,pulse=(t,a,b)=>Math.sin(Math.PI*range(t,a,b))**2;
function keys(t,k){for(let i=1;i<k.length;i++)if(t<=k[i][0])return mix(k[i-1][1],k[i][1],smooth(range(t,k[i-1][0],k[i][0])));return k.at(-1)[1]}
function bez(a,b,c,d,p){const q=1-p;return{x:q*q*q*a.x+3*q*q*p*b.x+3*q*p*p*c.x+p*p*p*d.x,y:q*q*q*a.y+3*q*q*p*b.y+3*q*p*p*c.y+p*p*p*d.y}}
function hermite(a,b,va,vb,p,dt){const q=p*p,r=q*p;return{x:(2*r-3*q+1)*a.x+(r-2*q+p)*va.x*dt+(-2*r+3*q)*b.x+(r-q)*vb.x*dt,y:(2*r-3*q+1)*a.y+(r-2*q+p)*va.y*dt+(-2*r+3*q)*b.y+(r-q)*vb.y*dt}}
function rotate(x,y,a){return{x:x*Math.cos(a)-y*Math.sin(a),y:x*Math.sin(a)+y*Math.cos(a)}}
const O={x:960,y:526,rx:238,ry:83,tilt:-.17};
const ENTRY=2.65,EXIT=.38,EMIT=2.40,TOUCH=2.86,PUT=3.71,PLACE=4.21,RUN=4.41,RELEASE=5.06,ARRIVE=5.61,CARRYSTART=6.18,PIN=7.85;
function orbitPoint(angle){const p=rotate(O.rx*Math.cos(angle),O.ry*Math.sin(angle),O.tilt);return{x:O.x+p.x,y:O.y+p.y}}
function sourcePose(t){const entrance=ease(t,1.15,1.75),exit=ease(t,8.65,9.55),squeeze=keys(t,[[0,0],[1.72,0],[2.08,1],[2.35,1],[2.53,0]]);return{x:520-18*(1-entrance)-25*exit,y:493+14*(1-entrance),size:245,scale:mix(.90,1,entrance)*(1-.05*exit)*(1+.024*pulse(t,2.40,2.78)),alpha:entrance*(1-exit),rot:keys(t,[[0,0],[1.72,0],[2.10,-.065],[2.35,-.065],[2.53,.025],[2.80,0]]),squeeze}}
function targetPose(t){const entrance=ease(t,4.49,5.18),exit=ease(t,8.65,9.55);return{x:1420+18*(1-entrance)+25*exit,y:495,size:260,scale:mix(.92,1,entrance)*(1-.05*exit),alpha:entrance*(1-exit),squash:pulse(t,5.60,5.90),eyeOpen:keys(t,[[0,0],[5.66,0],[5.82,1],[6.00,1],[6.17,0]]),carry:range(t,CARRYSTART,PIN),settle:ease(t,PIN,8.28),exit}}
function pose(t){const m=t-SHIFT,intro=ease(t,.42,1.35),zoom=1+8*ease(t,9.78,10.98);return{x:960+keys(m,[[0,0],[2.6,0],[2.85,-5],[3.25,-3],[3.6,-10],[3.82,0],[4.30,-9],[4.6,11],[4.94,0]]),y:500+2*Math.sin(m*1.7)*(1-ease(t,9.05,9.45))+keys(m,[[0,0],[3.25,0],[3.6,7],[3.85,0]])+25*(zoom-1),size:480*mix(.74,1,intro)*zoom,zoom,rot:keys(m,[[0,0],[2.60,0],[2.82,-.13],[3.05,-.13],[3.25,.025],[3.58,-.11],[3.83,-.025],[4.12,-.14],[4.30,-.16],[4.60,.12],[4.91,-.028],[5.25,0]]),eyeOpen:keys(m,[[0,0],[2.60,0],[2.82,1],[3.05,1],[3.28,0]])}}
function shoulder(t){const p=pose(t),q=rotate(-142*p.size/512,-105*p.size/512,p.rot);return{x:p.x+q.x,y:p.y+q.y}}
function sourcePoint(t){return root.EmojiBridgeMoon.sourcePoint(sourcePose(t))}
function handPoint(t){return root.EmojiBridgeQQ.handPoint(targetPose(t))}
function badgePoint(t){return root.EmojiBridgeQQ.badgePoint(targetPose(t))}
function orbitAngle(t){return mix(ENTRY,EXIT,Math.pow(range(t,RUN,RELEASE),2.2))}
function exitVelocity(){const rate=(EXIT-ENTRY)*2.2/(RELEASE-RUN);return rotate(-O.rx*Math.sin(EXIT)*rate,O.ry*Math.cos(EXIT)*rate,O.tilt)}
function position(t){
 if(t<EMIT)return{...sourcePoint(t),phase:'unread-source'};
 if(t<TOUCH){const a=sourcePoint(EMIT),b=shoulder(TOUCH),p=soft(range(t,EMIT,TOUCH));return{...bez(a,{x:a.x+55,y:a.y-48},{x:b.x-55,y:b.y-25},b,p),phase:'inbound'}}
 if(t<PUT)return{...shoulder(t),phase:'discovery'};
 if(t<PLACE){const a=shoulder(PUT),b=orbitPoint(ENTRY),p=soft(range(t,PUT,PLACE));return{...bez(a,{x:a.x-35,y:a.y+30},{x:b.x-30,y:b.y-45},b,p),phase:'placing'}}
 if(t<RUN)return{...orbitPoint(ENTRY),phase:'resting',angle:ENTRY};
 if(t<RELEASE){const angle=orbitAngle(t);return{...orbitPoint(angle),phase:'orbit',angle}}
 if(t<ARRIVE){const p=range(t,RELEASE,ARRIVE);return{...hermite(orbitPoint(EXIT),handPoint(ARRIVE),exitVelocity(),{x:0,y:0},p,ARRIVE-RELEASE),phase:'outbound'}}
 if(t<PIN)return{...handPoint(t),phase:t<CARRYSTART?'received':'carried'};
 return{...badgePoint(t),phase:'pinned'};
}
function state(raw,reduce=false){const t=reduce?DURATION:Math.max(0,Math.min(DURATION,Number(raw)||0)),p=pose(t),target=targetPose(t);return{t,...p,source:sourcePose(t),target,packet:position(t),bodyAlpha:ease(t,.45,1.32)*(1-ease(t,10.76,10.98)),introEyes:ease(t,.03,.36)*(1-ease(t,1.10,1.32)),layered:t>=9.55,finalEyes:t>=9.55?1-ease(t,10.23,10.50):0,orbitAlpha:.70*ease(t,1.00,2.0)*(1-ease(t,9.05,9.60)),packetAlpha:ease(t,1.95,2.18)*(1-ease(t,8.65,9.55)),redness:t<TOUCH?1-ease(t,EMIT,2.70):ease(t,5.68,6.05),formed:ease(t,1.95,2.18),placed:pulse(t,4.16,4.54),ack:pulse(t,5.61,6.01),pinned:pulse(t,PIN,8.24),confused:ease(t,3.16,3.32)*(1-ease(t,3.58,3.77)),forward:ease(t,9.78,10.98),uiAlpha:1-Math.pow(1-ease(t,9.94,10.76),1.9),complete:t>=DURATION}}
function eyePair(c,size,open=0){c.save();c.scale(size/512,size/512);c.fillStyle='#d4e0e9';c.save();c.translate(-68,-19);c.rotate(.045);c.beginPath();c.roundRect(-42,-(20+14*open)/2,84,20+14*open,(20+14*open)/2);c.fill();c.restore();c.save();c.translate(70,-35);c.rotate(-.1);c.beginPath();c.roundRect(-41,-(24+14*open)/2,82,24+14*open,(24+14*open)/2);c.fill();c.restore();c.restore()}
function logo(c,s,assets){
 c.save();c.translate(s.x,s.y);c.rotate(s.rot);
 if(s.bodyAlpha>0){c.save();c.globalAlpha*=s.bodyAlpha;c.drawImage(s.layered?root.EmojiBridgeLogoLayers.prepare(c,assets.logo).body:assets.logo,-s.size/2,-s.size/2,s.size,s.size);if(s.eyeOpen>0){c.globalAlpha*=Math.min(1,s.eyeOpen*3);eyePair(c,s.size,s.eyeOpen)}c.restore()}
 if(s.introEyes>0){c.save();c.globalAlpha*=s.introEyes;eyePair(c,s.size);c.restore()}c.restore();
 if(s.confused>0){c.save();c.globalAlpha*=.42*s.confused;c.strokeStyle='#b9d2e3';c.lineWidth=2.3;c.lineCap='round';c.beginPath();c.moveTo(s.x+151,s.y-168);c.lineTo(s.x+160,s.y-180);c.moveTo(s.x+165,s.y-149);c.lineTo(s.x+179,s.y-152);c.stroke();c.restore()}
}
function orbit(c,s,front){
 if(!s.orbitAlpha)return;c.save();c.globalAlpha*=s.orbitAlpha;c.translate(O.x,O.y);c.rotate(O.tilt);c.strokeStyle=front?'#759cae':'#344b5f';c.lineWidth=front?2:1.5;c.beginPath();c.ellipse(0,0,O.rx,O.ry,0,front?0:Math.PI,front?Math.PI:TAU);c.stroke();
 if(front&&s.placed>0){c.globalAlpha*=s.placed;c.strokeStyle='#cdf7e7';c.lineWidth=3;c.beginPath();c.ellipse(0,0,O.rx,O.ry,0,ENTRY-.18,ENTRY+.16);c.stroke()}
 if(front&&s.packet.phase==='orbit'){c.strokeStyle='#b3ecdc';c.lineWidth=3;c.beginPath();c.ellipse(0,0,O.rx,O.ry,0,s.packet.angle,Math.min(ENTRY,s.packet.angle+.37));c.stroke()}c.restore();
}
function message(c,s){
 if(s.packetAlpha<=0)return;const p=s.packet,red=s.redness,r=(10+3.5*red)*(s.t<EMIT?mix(.30,1,s.formed):1);c.save();c.globalAlpha*=s.packetAlpha;
 if(red<1){c.save();c.globalAlpha*=1-red;const g=c.createRadialGradient(p.x,p.y,0,p.x,p.y,42);g.addColorStop(0,'rgba(148,255,225,.42)');g.addColorStop(.3,'rgba(142,245,220,.13)');g.addColorStop(1,'rgba(142,245,220,0)');c.fillStyle=g;c.beginPath();c.arc(p.x,p.y,42,0,TAU);c.fill();c.restore()}
 const rgb=[mix(163,238,red),mix(239,78,red),mix(217,93,red)].map(Math.round);c.fillStyle='rgb('+rgb.join(',')+')';c.beginPath();c.arc(p.x,p.y,r,0,TAU);c.fill();
 if(red<.01){c.fillStyle='#e6fff5';c.beginPath();c.arc(p.x-2.6,p.y-3,r*.38,0,TAU);c.fill()}
 c.restore();
}
function trail(c,s){if(!['inbound','outbound','orbit'].includes(s.packet.phase))return;c.save();c.lineCap='round';for(let i=16;i>0;i--){const a=position(Math.max(0,s.t-i*.006)),b=position(Math.max(0,s.t-(i-1)*.006));c.strokeStyle='rgba(167,240,219,'+(.30*(1-i/17)*s.packetAlpha*(1-s.redness))+')';c.lineWidth=2;c.beginPath();c.moveTo(a.x,a.y);c.lineTo(b.x,b.y);c.stroke()}c.restore()}
function forwardReveal(c,s,assets){
 if(s.uiAlpha<=0)return;
 // Cut the SAME approved silhouette from the overlay. The pixels underneath
 // are live DOM controls, never a screenshot, cached destination or demo page.
 // One alpha replacement preserves V10's original blue-to-page handoff.
 c.save();c.globalCompositeOperation='destination-out';c.globalAlpha=s.uiAlpha;
 c.drawImage(assets.logo,s.x-s.size/2,s.y-s.size/2,s.size,s.size);c.restore();
}
function draw(c,width,height,time,assets,options={}){
 const s=state(time,!!options.reduceMotion);c.save();c.setTransform(1,0,0,1,0,0);c.clearRect(0,0,width,height);
 if(s.forward>=1||options.reduceMotion){c.restore();return s}
 c.fillStyle='#0d121a';c.fillRect(0,0,width,height);const scale=Math.min(width/W,height/H);c.translate((width-W*scale)/2,(height-H*scale)/2);c.scale(scale,scale);
 const g=c.createRadialGradient(960,480,40,960,510,720);g.addColorStop(0,'rgba(53,78,110,.25)');g.addColorStop(.6,'rgba(31,51,75,.09)');g.addColorStop(1,'rgba(25,40,58,0)');c.fillStyle=g;c.fillRect(0,0,W,H);
 root.EmojiBridgeMoon.drawSource(c,s.source,assets);root.EmojiBridgeQQ.drawTarget(c,s.target,assets);orbit(c,s,false);logo(c,s,assets);orbit(c,s,true);trail(c,s);message(c,s);
 if(s.ack>0||s.pinned>0){c.save();c.globalAlpha*=Math.max(s.ack,s.pinned)*.45;c.strokeStyle=s.pinned>0?'#f0a6a9':'#caeee3';c.lineWidth=1.8;c.beginPath();c.arc(s.packet.x,s.packet.y,17+7*Math.max(s.ack,s.pinned),-2.5,.9);c.stroke();c.restore()}
 forwardReveal(c,s,assets);
 if(s.finalEyes>0){const eyes=root.EmojiBridgeLogoLayers.prepare(c,assets.logo).eyes;c.save();c.globalAlpha*=s.finalEyes;c.drawImage(eyes,720,260,480,480);c.restore()}
 c.restore();return s;
}
root.EmojiBridgeStartup={draw,state,pose,position,sourcePose,targetPose,sourcePoint,handPoint,badgePoint,orbitPoint,orbitAngle,shoulder,duration:DURATION,width:W,height:H,timing:{emit:EMIT,touch:TOUCH,put:PUT,place:PLACE,run:RUN,release:RELEASE,arrive:ARRIVE,carry:CARRYSTART,pin:PIN}};if(typeof module!=='undefined')module.exports=root.EmojiBridgeStartup;
})(globalThis);
