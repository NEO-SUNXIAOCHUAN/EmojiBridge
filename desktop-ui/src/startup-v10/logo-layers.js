/* Runtime-only separation of the approved logo for its fixed-eye entrance.
 * The original file is never changed. All drawing before the entrance uses it.
 */
(function(root){
 'use strict';
 const cache=new WeakMap();
 function canvasLike(c,w,h){
  if(typeof root.OffscreenCanvas==='function')return new root.OffscreenCanvas(w,h);
  if(root.document?.createElement){const a=root.document.createElement('canvas');a.width=w;a.height=h;return a}
  try{return new c.canvas.constructor(w,h)}catch{return null}
 }
 function prepare(c,img){
  const ctor=c.canvas?.constructor;const byCtor=cache.get(img);if(byCtor?.has(ctor))return byCtor.get(ctor);
  const w=img.width||512,h=img.height||512,body=canvasLike(c,w,h),eyes=canvasLike(c,w,h);
  if(!body||!eyes)return null;
  const b=body.getContext('2d'),e=eyes.getContext('2d');b.drawImage(img,0,0,w,h);
  const source=b.getImageData(0,0,w,h),out=b.createImageData(w,h),eye=e.createImageData(w,h);
  out.data.set(source.data);const src=source.data,dst=out.data,ed=eye.data;
  // These tight regions contain only the two white marks. They do not intersect
  // the outer silhouette; all original alpha and all other texture stay intact.
  const regions=[[140,218,237,257],[278,197,374,243]];
  const idx=(x,y)=>(y*w+x)*4;
  function blueAt(x,y,ch){let sum=0,n=0;for(let dy=-1;dy<=1;dy++)for(let dx=-2;dx<=2;dx++){const xx=Math.max(0,Math.min(w-1,x+dx)),yy=Math.max(0,Math.min(h-1,y+dy));sum+=src[idx(xx,yy)+ch];n++}return sum/n}
  for(const [x0,y0,x1,y1] of regions){
   const seed=new Uint8Array(w*h),distance=new Uint8Array(w*h);distance.fill(255);
   for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){const i=idx(x,y);if(src[i]>90&&src[i+1]>100&&src[i+2]>120){seed[y*w+x]=1;distance[y*w+x]=0}}
   for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++)if(seed[y*w+x]){
    for(let dy=-3;dy<=3;dy++)for(let dx=-3;dx<=3;dx++){const xx=x+dx,yy=y+dy;if(xx<x0||xx>=x1||yy<y0||yy>=y1)continue;const d=Math.max(Math.abs(dx),Math.abs(dy));distance[yy*w+xx]=Math.min(distance[yy*w+xx],d)}
   }
   for(let x=x0;x<x1;x++){
    let top=y1,bottom=y0;for(let y=y0;y<y1;y++)if(distance[y*w+x]<=3){top=Math.min(top,y);bottom=Math.max(bottom,y)}
    if(top>bottom)continue;const ya=Math.max(0,top-3),yb=Math.min(h-1,bottom+3),a=[0,1,2].map(ch=>blueAt(x,ya,ch)),z=[0,1,2].map(ch=>blueAt(x,yb,ch));
    for(let y=top;y<=bottom;y++){
     const d=distance[y*w+x];if(d>3)continue;const weight=d<=1?1:d===2?.62:.18,p=(y-ya)/(yb-ya),i=idx(x,y);
     for(let ch=0;ch<3;ch++)dst[i+ch]=Math.round(src[i+ch]*(1-weight)+(a[ch]+(z[ch]-a[ch])*p)*weight);
    }
   }
   // Unmatte the same original white marks against the repaired local blue.
   // Opaque cores retain the source RGB; only antialiased edges need alpha.
   for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){
    const i=idx(x,y),delta=src[i]-dst[i];let alpha;
    if(delta>5){alpha=Math.max(0,Math.min(1,delta/Math.max(1,207-dst[i])));if(alpha>.95)alpha=1}
    else if(delta< -2){alpha=Math.max(...[0,1,2].map(ch=>(dst[i+ch]-src[i+ch])/Math.max(1,dst[i+ch])))}
    else continue;
    if(alpha<.035)continue;
    for(let ch=0;ch<3;ch++)ed[i+ch]=Math.round(Math.max(0,Math.min(255,dst[i+ch]+(src[i+ch]-dst[i+ch])/alpha)));
    ed[i+3]=Math.round(alpha*255);
   }
  }
  b.putImageData(out,0,0);e.putImageData(eye,0,0);
  const cached={body,eyes},entries=byCtor||new Map();entries.set(ctor,cached);cache.set(img,entries);return cached;
 }
 const api={prepare};root.EmojiBridgeLogoLayers=api;if(typeof module!=='undefined')module.exports=api;
})(globalThis);
