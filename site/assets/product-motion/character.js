(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.EmojiBridgeCharacter = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const TAU = Math.PI * 2;
  const clamp = (v,a=0,b=1) => Math.max(a,Math.min(b,v));
  const ease = t => {t=clamp(t); return t*t*(3-2*t);};
  const lerp = (a,b,t) => a+(b-a)*t;
  const add = (a,b)=>a.map((v,i)=>v+b[i]);
  const sub = (a,b)=>a.map((v,i)=>v-b[i]);
  const mul = (a,n)=>a.map(v=>v*n);
  const dot = (a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const norm=a=>mul(a,1/Math.hypot(...a));
  const camera=[-.66,.16,.75];
  const faces=[
    {ids:[0,1,2,3],n:[0,0,-1],light:.62},
    {ids:[4,7,6,5],n:[0,0,1],light:1},
    {ids:[0,4,5,1],n:[0,-1,0],light:.55},
    {ids:[3,2,6,7],n:[0,1,0],light:1.36},
    {ids:[0,3,7,4],n:[-1,0,0],light:.81},
    {ids:[1,5,6,2],n:[1,0,0],light:.62}
  ];
  function shade(hex,f){const n=parseInt(hex.slice(1),16);return `rgb(${Math.min(255,Math.round((n>>16)*f))},${Math.min(255,Math.round(((n>>8)&255)*f))},${Math.min(255,Math.round((n&255)*f))})`;}
  function rotX(p,a){const c=Math.cos(a),s=Math.sin(a);return[p[0],p[1]*c-p[2]*s,p[1]*s+p[2]*c];}
  function rotY(p,a){const c=Math.cos(a),s=Math.sin(a);return[p[0]*c+p[2]*s,p[1],-p[0]*s+p[2]*c];}
  function rotZ(p,a){const c=Math.cos(a),s=Math.sin(a);return[p[0]*c-p[1]*s,p[0]*s+p[1]*c,p[2]];}
  function getPose(pose,time){
    const durations={idle:2,lift:1.15,carry:1.2,wait:2.4,success:1.3,blocked:1.45};
    const t=clamp(time/durations[pose]);
    let bob=.015*Math.sin(time*TAU/2),lean=0,look=0,crate=1,step=0,armOpen=0,shift=0,headYaw=0;
    let boxY=2.02,boxZ=.84;
    if(pose==='carry') {step=(time%1.2)/1.2;bob=.032*(1-Math.cos(step*TAU*2));lean=.035;look=.025;}
    if(pose==='idle') {boxY=2.02+bob;}
    if(pose==='lift'){
      const bend=Math.sin(Math.PI*ease(Math.min(t/.72,1)))*.34;
      lean=bend;bob-=bend*.42;look=bend*.25;
      const lift=ease((t-.25)/.6);boxY=lerp(.46,2.02,lift);boxZ=lerp(1.04,.84,lift);armOpen=1-lift;
    }
    if(pose==='wait'){const phase=time*TAU/2.4;bob=.015*Math.sin(phase);look=.06*Math.sin(phase);headYaw=.12*Math.sin(phase);boxY+=bob;}
    if(pose==='success'){
      const down=ease(t/.48);boxY=lerp(2.02,.45,down);boxZ=lerp(.84,1.08,down);
      lean=Math.sin(Math.PI*down)*.32;bob-=Math.sin(Math.PI*down)*.10;
      armOpen=down;look=.12*Math.sin(clamp((t-.55)/.45)*Math.PI);crate=1;
    }
    if(pose==='blocked'){
      const stop=ease(t/.25);shift=-.16*ease((t-.1)/.4);
      lean=-.1*Math.sin(t*Math.PI);look=.24*Math.sin(t*Math.PI);headYaw=-.10*Math.sin(t*Math.PI*2);
      bob=.018*Math.sin(t*Math.PI*2);boxZ-=.09*stop;
    }
    return{bob,lean,look,crate,step,armOpen,shift,headYaw,boxY,boxZ,t};
  }
  function drawCharacter(ctx, opts={}) {
    const {x=80,y=235,scale=52,pose='carry',time=0,facing=1,alpha=1,shadow=true,sticker=null}=opts;
    const state=getPose(pose,time), polys=[];
    const project=p=>[x+facing*(p[0]*.75+p[2]*.66)*scale,y+(-p[1]+(-p[0]*.66+p[2]*.75)*.15)*scale];
    const transform=p=>{
      let q=rotX(sub(p,[0,1.74,0]),state.lean);
      return add(q,[0,1.74+state.bob,state.shift]);
    };
    function polygon(vertices,colour,normal,extra={}){
      if(normal && dot(normal,camera)<-.001)return;
      polys.push({vertices,colour,depth:vertices.reduce((s,p)=>s+dot(p,camera),0)/vertices.length,...extra});
    }
    function box(center,size,colour,rotation=[0,0,0],texture=false,body=true){
      const xf=p=>{
        let q=rotZ(rotY(rotX(p,rotation[0]),rotation[1]),rotation[2]);q=add(q,center);return body?transform(q):q;
      };
      const normalXf=n=>{let q=rotZ(rotY(rotX(n,rotation[0]),rotation[1]),rotation[2]);return body?rotX(q,state.lean):q;};
      const [w,h,d]=size;
      const vs=[[-w/2,-h/2,-d/2],[w/2,-h/2,-d/2],[w/2,h/2,-d/2],[-w/2,h/2,-d/2],[-w/2,-h/2,d/2],[w/2,-h/2,d/2],[w/2,h/2,d/2],[-w/2,h/2,d/2]].map(xf);
      faces.forEach((f,idx)=>{
        const v=f.ids.map(i=>vs[i]),n=normalXf(f.n);if(dot(n,camera)<0)return;
        polygon(v,shade(colour,f.light),n,{outline:body?'rgba(123,91,153,.19)':'rgba(243,194,122,.20)'});
        if(texture){
          for(let k=0;k<3;k++){
            const u=.14+k*.27, a=.18+((k+idx)%3)*.2;
            const pt=(uu,vv)=>add(add(v[0],mul(sub(v[1],v[0]),uu)),mul(sub(v[3],v[0]),vv));
            polygon([pt(u,a),pt(u+.13,a),pt(u+.13,a+.20),pt(u,a+.20)],shade(colour,f.light*(1.12+(k%2)*.11)),n,{depth:dot(v[0],camera)+.005});
          }
        }
      });
      return xf;
    }
    function bone(a,b,w,d,colour,body=true){
      const ey=norm(sub(b,a)),ex=[1,0,0],ez=norm(cross(ex,ey)),center=mul(add(a,b),.5),len=Math.hypot(...sub(a,b));
      const xf=p=>{const q=add(center,add(add(mul(ex,p[0]),mul(ey,p[1])),mul(ez,p[2])));return body?transform(q):q;};
      const normalXf=n=>{const q=add(add(mul(ex,n[0]),mul(ey,n[1])),mul(ez,n[2]));return body?rotX(q,state.lean):q;};
      const v=[[-w/2,-len/2,-d/2],[w/2,-len/2,-d/2],[w/2,len/2,-d/2],[-w/2,len/2,-d/2],[-w/2,-len/2,d/2],[w/2,-len/2,d/2],[w/2,len/2,d/2],[-w/2,len/2,d/2]].map(xf);
      faces.forEach(f=>polygon(f.ids.map(i=>v[i]),shade(colour,f.light),normalXf(f.n),{outline:'rgba(110,88,145,.17)'}));
    }
    ctx.save();ctx.globalAlpha*=alpha;
    if(shadow){ctx.save();ctx.translate(x+facing*12,y+3);ctx.scale(1,.18);const g=ctx.createRadialGradient(0,0,0,0,0,scale*.76);g.addColorStop(0,'rgba(0,0,0,.27)');g.addColorStop(1,'rgba(0,0,0,0)');ctx.fillStyle=g;ctx.beginPath();ctx.arc(0,0,scale*.76,0,TAU);ctx.fill();ctx.restore();}
    // A planted half-cycle plus a lifted return creates a walk with a clear contact phase.
    const foot=(offset)=>{
      if(pose==='blocked'){
        const q=clamp((state.t-(offset<.5?.10:.30))/.30), retreat=.16*ease(q);
        return[0,.08+.065*Math.sin(Math.PI*q),(offset<.5?-.025:.045)-state.shift-retreat];
      }
      if(pose!=='carry')return[0,.08,offset<.5?-.025:.045];
      const phase=(state.step+offset)%1;
      if(phase<.5)return[0,.08,lerp(.40,-.40,phase*2)];
      const q=(phase-.5)*2;return[0,.08+.14*Math.sin(Math.PI*q),lerp(-.40,.40,ease(q))];
    };
    for(let i=0;i<2;i++){
      const sx=i===0?-.15:.15,f=foot(i*.5),a=[sx,1.79+state.bob,state.shift],b=[sx,f[1],f[2]+state.shift];
      bone(a,b,.145,.15,i===0?'#242031':'#1c1928',false);
      box([sx,f[1]-.01,f[2]+.045+state.shift],[.16,.14,.25],'#211c2d',[0,0,0],false,false);
    }
    box([0,2.30,0],[.48,1.08,.31],'#221d2f',[0,0,0],true);
    box([0,2.92,0],[.16,.18,.17],'#191524');
    const head=box([0,3.30,.015],[.64,.65,.62],'#282133',[state.look,state.headYaw,0],true);
    // Eyes are geometry on the forward plane, with soft bloom drawn only on the eyes.
    const eyeDepth=Math.max(...[[-.32,-.325,.32],[.32,-.325,.32],[.32,.325,.32],[-.32,.325,.32]].map(p=>dot(head(p),camera)))+.03;
    for(const eyeX of [-.18,.18]){
      const v=[[eyeX-.125,-.035,.314],[eyeX+.125,-.035,.314],[eyeX+.125,.075,.314],[eyeX-.125,.075,.314]].map(head);
      polygon(v,'#a56fff',null,{glow:'#c980ff',outline:null,depth:eyeDepth});
      const core=[[eyeX-.048,-.012,.317],[eyeX+.048,-.012,.317],[eyeX+.048,.058,.317],[eyeX-.048,.058,.317]].map(head);
      polygon(core,'#efd8ff',null,{glow:null,depth:eyeDepth+.01});
    }
    // Long, articulated arms settle beneath the parcel without changing the silhouette.
    const liftReach=pose==='lift'?1-ease((state.t-.25)/.6):pose==='success'?ease(state.t/.48):0;
    const release=pose==='success'?ease((state.t-.52)/.30):0;
    const c=[0,state.boxY+state.bob,state.boxZ+state.shift], size=.70;
    for(const sx of [-.35,.35]){
      const shoulder=transform([sx,2.79,0]);
      const elbow=transform([sx,lerp(lerp(1.97,1.42,liftReach),1.88,release),lerp(.24,.02,release)]);
      const wrist=[sx,lerp(c[1]-.20,.94+state.bob,release),lerp(c[2]-.16,.045+state.shift,release)];
      bone(shoulder,elbow,.15,.16,'#292236',false);bone(elbow,wrist,.145,.15,'#292236',false);
      box(wrist,[.17,.17,.20],'#33293f',[0,0,0],false,false);
    }
    const crateBox=(center,size,colour)=>box(center,size,colour,[0,0,0],false,false);
    const crateXf=crateBox(c,[size,size,size],'#94603d');
    // Raised wooden battens on the two visible faces and narrow grain breaks.
    for(const yy of [-.29,.29])crateBox(add(c,[0,yy,.366]),[.76,.105,.06],'#ba8451');
    for(const xx of [-.30,.30])crateBox(add(c,[xx,0,.367]),[.105,.63,.065],'#ad7549');
    for(const yy of [-.29,.29])crateBox(add(c,[-.367,yy,0]),[.06,.105,.76],'#98633c');
    for(const zz of [-.30,.30])crateBox(add(c,[-.368,0,zz]),[.065,.63,.105],'#a26b41');
    for(const yy of [-.12,.11]){
      const q=[[-.25,yy,.352],[.25,yy,.352],[.25,yy+.017,.352],[-.25,yy+.017,.352]].map(p=>add(p,c));
      polygon(q,'#66402e',[0,0,1]);
    }
    // Corner fasteners and central label: warm white mark remains legible at small size.
    for(const xx of [-.29,.29])for(const yy of [-.28,.28])crateBox(add(c,[xx,yy,.407]),[.035,.035,.012],'#50372e');
    const label=[[-.115,-.12,.355],[.115,-.12,.355],[.115,.12,.355],[-.115,.12,.355]].map(p=>add(p,c));
    polygon(label,'#e1c69b',[0,0,1],{sticker:sticker||null,label:!sticker});
    polys.sort((a,b)=>a.depth-b.depth);
    for(const p of polys){
      const points=p.vertices.map(project);ctx.beginPath();ctx.moveTo(...points[0]);points.slice(1).forEach(q=>ctx.lineTo(...q));ctx.closePath();
      ctx.fillStyle=p.colour;
      if(p.glow){ctx.shadowColor=p.glow;ctx.shadowBlur=scale*.10;}
      ctx.fill();ctx.shadowBlur=0;
      if(p.outline){ctx.strokeStyle=p.outline;ctx.lineWidth=Math.max(.35,scale*.008);ctx.stroke();}
      if(p.sticker){
        ctx.save();ctx.beginPath();ctx.moveTo(...points[0]);points.slice(1).forEach(q=>ctx.lineTo(...q));ctx.closePath();ctx.clip();
        const a=points[0],b=points[1],d=points[3];ctx.transform((b[0]-a[0])/32,(b[1]-a[1])/32,(a[0]-d[0])/32,(a[1]-d[1])/32,d[0],d[1]);
        ctx.drawImage(p.sticker,0,0,32,32);ctx.restore();
      }
      if(p.label){const cc=project(add(c,[0,0,.36]));ctx.fillStyle='#654c3e';ctx.beginPath();ctx.arc(cc[0]-facing*scale*.032,cc[1]-scale*.02,Math.max(.6,scale*.012),0,TAU);ctx.arc(cc[0]+facing*scale*.032,cc[1]-scale*.02,Math.max(.6,scale*.012),0,TAU);ctx.fill();}
    }
    ctx.restore();
    return {bounds:{left:x-scale*.6,right:x+scale*1.2,top:y-scale*3.7,bottom:y+scale*.20},cycleDuration:1.2};
  }
  return {drawCharacter,getPose,actions:{idle:{duration:2,loop:true},lift:{duration:1.15,loop:false},carry:{duration:1.2,loop:true},wait:{duration:2.4,loop:true},success:{duration:1.3,loop:false},blocked:{duration:1.45,loop:false}}};
});
