(function(root){
  'use strict';
  const TAU=Math.PI*2,clamp=x=>Math.max(0,Math.min(1,x)),ease=x=>{x=clamp(x);return x*x*(3-2*x)};
  function poly(c,points,color){c.beginPath();c.moveTo(points[0][0],points[0][1]);for(let i=1;i<points.length;i++)c.lineTo(points[i][0],points[i][1]);c.closePath();c.fillStyle=color;c.fill();}
  // Native pixel geometry: cool teal round pearl, curved highlight, no iris.
  const PEARL_PERIOD=4.6, PEARL_AMPLITUDE=6.5;
  const pearlPixels=[
    '.....000000.....',
    '...0011111100...',
    '..012555553210..',
    '.01256776543210.',
    '.12567765433210.',
    '0125676543222110',
    '0125665432222110',
    '0125543322222110',
    '0124432222222110',
    '0123332222222110',
    '0123332222232110',
    '.12333322233210.',
    '.01233333333210.',
    '..012333333210..',
    '...0011111100...',
    '.....000000.....'
  ];
  const pearlPalette=['#092e2d','#103e39','#18534b','#256f60','#388c76','#57a88c','#8cc5a9','#c3dfbf'];
  // Merge adjacent cells into row runs once; animation does not rebuild geometry.
  const pearlRuns=[];
  pearlPixels.forEach((row,iy)=>{let ix=0;while(ix<row.length){const color=row[ix];let end=ix+1;while(end<row.length&&row[end]===color)end++;if(color!=='.')pearlRuns.push({x:(ix-8)*2.5,y:(iy-8)*2.5,w:(end-ix)*2.5,color:pearlPalette[Number(color)]});ix=end;}});
  function drawPearl(c,options={}){
    const {x=0,y=0,time=0,alpha=1,scale=1,reducedMotion=false,shadow=true}=options;
    if(alpha<=0)return;
    const bob=reducedMotion?0:Math.sin(time*TAU/PEARL_PERIOD)*PEARL_AMPLITUDE;
    c.save();c.globalAlpha*=alpha;c.translate(x,y);c.scale(scale,scale);
    // Fixed ground shadow grows slightly as the pearl approaches it.
    if(shadow){c.save();c.globalAlpha*=.17+bob*.003;c.fillStyle='#91b7ce';c.beginPath();c.ellipse(0,43,17+bob*.14,1.9+bob*.025,0,0,TAU);c.fill();c.restore();}
    c.translate(0,bob);
    const g=c.createRadialGradient(0,0,10,0,0,36);g.addColorStop(0,'rgba(137,105,210,.075)');g.addColorStop(.65,'rgba(112,81,176,.025)');g.addColorStop(1,'rgba(112,81,176,0)');c.fillStyle=g;c.fillRect(-36,-36,72,72);
    for(const run of pearlRuns){c.fillStyle=run.color;c.fillRect(run.x,run.y,run.w,2.5);}
    if(!reducedMotion){c.save();const inherited=c.globalAlpha;for(let i=0;i<3;i++){const q=(time/5+i/3)%1,a=i*2.3+q*.9,r=28+4*Math.sin(q*Math.PI);c.globalAlpha=inherited*Math.sin(q*Math.PI)*.28;c.fillStyle=i===1?'#c0a1ed':'#8d72b6';c.fillRect(Math.cos(a)*r,Math.sin(a)*r-5,1.5,1.5);}c.restore();}
    c.restore();
    return{left:x-scale*38,top:y+scale*(bob-38),right:x+scale*38,bottom:y+scale*Math.max(bob+38,shadow?46:0),bob};
  }
  function drawTeleport(c,options={}){
    const {x=0,y=0,time=0,duration=.45,alpha=1,scale=1,reducedMotion=false}=options;
    if(reducedMotion||alpha<=0||time<=0||time>=duration)return;
    const t=clamp(time/duration),p=ease(t),life=Math.sin(Math.PI*t);
    c.save();c.globalAlpha*=alpha;c.translate(x,y);c.scale(scale,scale);
    c.save();c.globalAlpha*=life*.3;c.strokeStyle='#bd8fe8';c.lineWidth=1.2;c.beginPath();c.ellipse(0,0,22+25*p,5+5*p,0,0,TAU);c.stroke();c.restore();
    for(let i=0;i<24;i++){
      const seed=(i*17%29)/29,angle=i*2.399963,rad=14+(1-p)*29+seed*10;
      const px=Math.cos(angle)*rad+(p-.5)*8*Math.sin(i*3.1);
      const py=-7-(i%7)*19-(1-p)*21+Math.sin(angle)*11;
      const local=life*(.45+seed*.45);c.globalAlpha=alpha*local;
      c.fillStyle=i%5===0?'#e7c9ff':i%3===0?'#a6c7b7':'#ac7bdf';const size=i%4===0?3:2;c.fillRect(px,py,size,size);
    }
    c.restore();return{left:x-60*scale,top:y-160*scale,right:x+60*scale,bottom:y+15*scale};
  }
  root.EmojiBridgeEffects={drawPearl,drawTeleport,PEARL_PERIOD,PEARL_AMPLITUDE};
  if(typeof module!=='undefined')module.exports=root.EmojiBridgeEffects;
})(typeof globalThis!=='undefined'?globalThis:this);
