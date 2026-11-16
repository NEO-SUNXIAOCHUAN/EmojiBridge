// Canvas geometry is shared by the preview and transparent output. No desktop
// capture, selection handles, or controls are ever painted into the output.
export function bounds(o){
 if(o.type==='text')return [o.x,o.y,o.x+o.boxWidth,o.y+o.boxHeight];
 const points=o.points||[[o.x,o.y],[o.x2,o.y2]],xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
 const p=o.type==='arrow'?Math.min(Math.hypot(o.x2-o.x,o.y2-o.y),Math.max(12,o.width*4))*.45+o.width/2+2:o.width/2+2;
 return [Math.min(...xs)-p,Math.min(...ys)-p,Math.max(...xs)+p,Math.max(...ys)+p];
}
export function center(o){const b=bounds(o);return [(b[0]+b[2])/2,(b[1]+b[3])/2]}
export function turn(point,pivot,angle){const c=Math.cos(angle),s=Math.sin(angle),x=point[0]-pivot[0],y=point[1]-pivot[1];return [pivot[0]+x*c-y*s,pivot[1]+x*s+y*c]}
export function local(o,p){return turn(p,center(o),-(o.angle||0))}
export function handles(o){const b=bounds(o),c=center(o),world=p=>turn(p,c,o.angle||0);return {rotate:world([c[0],b[1]-28]),resize:world([b[2],b[3]]),top:world([c[0],b[1]])}}
function segment(p,a,b){const dx=b[0]-a[0],dy=b[1]-a[1],t=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy||1)));return Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)}
export function hit(o,point){
 const p=local(o,point),b=bounds(o),tolerance=Math.max(8,o.width/2+4);
 if(o.type==='pen')return o.points.some((a,i)=>segment(p,a,o.points[Math.min(i+1,o.points.length-1)])<=tolerance);
 if(o.type==='arrow'||o.shape==='line')return segment(p,[o.x,o.y],[o.x2,o.y2])<=Math.max(tolerance,o.type==='arrow'?o.width*2:0);
 // Shape interiors are intentionally selectable, including unfilled rectangles.
 return p[0]>=b[0]-4&&p[0]<=b[2]+4&&p[1]>=b[1]-4&&p[1]<=b[3]+4;
}
export function scaleFromHandle(o,point){
 const b=bounds(o),p=local(o,point),c=center(o),ratio=Math.max(.1,Math.min(20,Math.max((p[0]-c[0])/Math.max(1,b[2]-c[0]),(p[1]-c[1])/Math.max(1,b[3]-c[1]))));
 const map=([x,y])=>[c[0]+(x-c[0])*ratio,c[1]+(y-c[1])*ratio];
 if(o.type==='text'){const [x,y]=map([o.x,o.y]);return {...o,x,y,fontSize:o.fontSize*ratio,boxWidth:o.boxWidth*ratio,boxHeight:o.boxHeight*ratio}}
 if(o.points)return {...o,points:o.points.map(map)};
 const [x,y]=map([o.x,o.y]),[x2,y2]=map([o.x2,o.y2]);return {...o,x,y,x2,y2};
}
export function selection(ctx,o){
 const b=bounds(o),c=center(o),h=handles(o);ctx.save();ctx.translate(...c);ctx.rotate(o.angle||0);ctx.translate(-c[0],-c[1]);
 ctx.strokeStyle='#a7ceff';ctx.lineWidth=1;ctx.setLineDash([4,3]);ctx.strokeRect(b[0],b[1],b[2]-b[0],b[3]-b[1]);ctx.setLineDash([]);ctx.restore();
 ctx.save();ctx.strokeStyle='#c8dfff';ctx.fillStyle='#182332';ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(...h.top);ctx.lineTo(...h.rotate);ctx.stroke();ctx.beginPath();ctx.arc(...h.rotate,6,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.fillRect(h.resize[0]-4,h.resize[1]-4,8,8);ctx.strokeRect(h.resize[0]-4,h.resize[1]-4,8,8);ctx.restore();
}
export function translate(o,dx,dy){
 return o.points?{...o,points:o.points.map(([x,y])=>[x+dx,y+dy])}:{...o,x:o.x+dx,y:o.y+dy,x2:o.x2+dx,y2:o.y2+dy};
}
export function resize(o,box){
 const old=bounds(o),sx=Math.max(4,box[2]-box[0])/Math.max(1,old[2]-old[0]),sy=Math.max(4,box[3]-box[1])/Math.max(1,old[3]-old[1]);
 const map=([x,y])=>[box[0]+(x-old[0])*sx,box[1]+(y-old[1])*sy];
 if(o.type==='text'){const fontSize=Math.max(10,Math.min(240,o.fontSize*Math.max(sx,sy))),ratio=fontSize/o.fontSize;return {...o,x:box[0],y:box[1],fontSize,boxWidth:o.boxWidth*ratio,boxHeight:o.boxHeight*ratio}}
 if(o.points)return {...o,points:o.points.map(map)};
 const [x,y]=map([o.x,o.y]),[x2,y2]=map([o.x2,o.y2]);return {...o,x,y,x2,y2};
}
export function render(ctx,o){
 ctx.save();ctx.lineCap='round';ctx.lineJoin='round';ctx.strokeStyle=o.color;ctx.fillStyle=o.color;ctx.lineWidth=o.width;
 const c=center(o);ctx.translate(...c);ctx.rotate(o.angle||0);ctx.translate(-c[0],-c[1]);
 if(o.type==='text'){
  ctx.font=`${o.fontSize}px "Microsoft YaHei UI", "Segoe UI", sans-serif`;ctx.textBaseline='top';
  const lines=o.text.split('\n'),pad=o.fill?6:0;
  if(o.fill){ctx.fillStyle=o.fillColor;ctx.fillRect(o.x-pad,o.y-pad,o.boxWidth+pad*2,o.boxHeight+pad*2);ctx.fillStyle=o.color}
  lines.forEach((line,i)=>ctx.fillText(line,o.x,o.y+i*o.fontSize*1.35));
 }else if(o.type==='pen'){
  ctx.beginPath();o.points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));
  if(o.points.length===1){const [x,y]=o.points[0];ctx.lineTo(x+.01,y+.01)}ctx.stroke();
 }else if(o.type==='arrow'){
  const dx=o.x2-o.x,dy=o.y2-o.y,length=Math.hypot(dx,dy);
  if(length>0){const ux=dx/length,uy=dy/length,head=Math.min(length,Math.max(12,o.width*4)),wing=head*.45;
   ctx.beginPath();ctx.moveTo(o.x,o.y);ctx.lineTo(o.x2-ux*head*.75,o.y2-uy*head*.75);ctx.stroke();
   ctx.beginPath();ctx.moveTo(o.x2,o.y2);ctx.lineTo(o.x2-ux*head-uy*wing,o.y2-uy*head+ux*wing);ctx.lineTo(o.x2-ux*head+uy*wing,o.y2-uy*head-ux*wing);ctx.closePath();ctx.fill();
  }
 }else{
  const x=Math.min(o.x,o.x2),y=Math.min(o.y,o.y2),w=Math.abs(o.x2-o.x),h=Math.abs(o.y2-o.y);
  ctx.beginPath();
  if(o.shape==='ellipse')ctx.ellipse(x+w/2,y+h/2,w/2,h/2,0,0,Math.PI*2);
  else if(o.shape==='triangle'){ctx.moveTo(x+w/2,y);ctx.lineTo(x+w,y+h);ctx.lineTo(x,y+h);ctx.closePath()}
  else if(o.shape==='line'){ctx.moveTo(o.x,o.y);ctx.lineTo(o.x2,o.y2)}
  else if(o.shape==='rounded')ctx.roundRect(x,y,w,h,Math.min(16,w/4,h/4));
  else ctx.rect(x,y,w,h);
  if(o.fill&&o.shape!=='line')ctx.fill();else ctx.stroke();
 }
 ctx.restore();
}
