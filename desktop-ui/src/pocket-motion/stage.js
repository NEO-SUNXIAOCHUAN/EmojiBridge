(function (root) {
  'use strict';
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const ease = x => { x = clamp(x); return x * x * (3 - 2 * x); };
  const lerp = (a, b, p) => a + (b - a) * p;
  const ink = '#edf0f7';
  function rr(c, x, y, w, h, r) { c.beginPath(); c.roundRect(x, y, w, h, r); }
  function txt(c, s, x, y, size = 16, color = ink, weight = 400, align = 'left') {
    c.fillStyle = color; c.font = weight + ' ' + size + 'px "Noto Sans SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif';
    c.textAlign = align; c.fillText(s, x, y);
  }
  function brand(c, kind, x, y, labelY = y + 63) {
    c.save();
    rr(c, x - 35, y - 35, 70, 70, 22);
    const g = c.createLinearGradient(x, y - 35, x, y + 35);
    g.addColorStop(0, kind === 'wechat' ? '#233d31' : '#203044'); g.addColorStop(1, '#151a22');
    c.fillStyle = g; c.fill(); c.strokeStyle = kind === 'wechat' ? '#344a3c' : '#354358'; c.lineWidth = 1; c.stroke();
    c.translate(x - 17, y - 17); c.scale(34 / 24, 34 / 24);
    c.fillStyle = kind === 'wechat' ? '#75da92' : '#e6efff';
    if (kind === 'local' || kind === 'material') {
      c.lineWidth=1.6;c.strokeStyle='#d8e6f4';c.beginPath();c.roundRect(1,2,22,19,3);c.stroke();
      c.beginPath();c.moveTo(3,18);c.lineTo(9,12);c.lineTo(13,16);c.lineTo(17,10);c.lineTo(22,17);c.stroke();
      c.fillStyle='#b9d2ee';c.beginPath();c.arc(8,8,2,0,Math.PI*2);c.fill();
    } else if (root.EmojiBridgeBrandPaths && typeof Path2D !== 'undefined' && root.EmojiBridgeBrandPaths[kind]) c.fill(new Path2D(root.EmojiBridgeBrandPaths[kind]));
    c.restore();
    txt(c, sourceLabel(kind), x, labelY, 17, '#b6bdce', 500, 'center');
  }
  function portal(c, x, ground, t, active = true) {
    const top = ground - 171, w = 69, h = 170;
    c.save();
    const glow = c.createRadialGradient(x, top + 88, 5, x, top + 88, 115);
    glow.addColorStop(0, active ? '#9c68fa22' : '#7061800c'); glow.addColorStop(1, '#9160d900');
    c.fillStyle = glow; c.fillRect(x - 130, top - 30, 260, 240);
    c.fillStyle = '#181421'; c.strokeStyle = '#443455'; c.lineWidth = 1;
    for (let i = 0; i < 7; i++) {
      for (const side of [-1, 1]) {
        const bx = x + side * 41 - 10;
        c.fillStyle = i % 2 ? '#231b2e' : '#1b1625';
        rr(c, bx, top + i * 24, 20, 23, 2); c.fill(); c.stroke();
        c.fillStyle = '#473053'; c.fillRect(bx + 3, top + i * 24 + 3, 5, 4);
      }
    }
    c.fillStyle = '#251d33'; rr(c, x - 49, top - 6, 98, 15, 3); c.fill(); c.stroke();
    rr(c, x - w / 2, top + 9, w, h - 12, 2);
    const fill = c.createLinearGradient(x - w / 2, top, x + w / 2, ground);
    fill.addColorStop(0, active ? '#563680' : '#292232'); fill.addColorStop(.5, active ? '#ae7cf053' : '#30283e'); fill.addColorStop(1, '#38204c');
    c.fillStyle = fill; c.fill(); c.save(); c.clip();
    for (let k = 0; k < 7; k++) {
      const yy = top + ((k * 35 - t * 15) % 190 + 190) % 190;
      c.strokeStyle = 'rgba(190,145,245,' + (active ? .13 : .04) + ')'; c.lineWidth = 2;
      c.beginPath(); c.moveTo(x - 40, yy); c.bezierCurveTo(x - 15, yy - 25, x + 10, yy + 20, x + 40, yy - 10); c.stroke();
    }
    c.restore();
    if (active) for (let j = 0; j < 10; j++) {
      const a = t * .45 + j * 2.399, r = 41 + Math.sin(j * 5.1) * 21;
      const px = x + Math.cos(a) * r, py = ground - 30 - ((j * 29 + t * 20) % 150);
      c.globalAlpha = .25 + .25 * Math.sin(t * 2 + j); c.fillStyle = '#c09aee'; c.fillRect(px, py, j % 3 ? 2 : 3, j % 3 ? 2 : 3);
    }
    c.restore();
  }
  function targetWater(c, x, ground, amount, time) {
    if (amount <= 0) return;
    c.save();
    c.translate(x, ground - 22);
    c.scale(amount, amount);
    const cols = 11, rows = 9, depth = 14;
    const project = (u, v, elevation = 0) => [(u - cols / 2) * 15 + (v - rows / 2) * 6, (v - rows / 2) * 6 - elevation];
    const quad = (points, fill) => {
      c.beginPath(); c.moveTo(...points[0]); points.slice(1).forEach(p => c.lineTo(...p)); c.closePath(); c.fillStyle = fill; c.fill();
    };
    const cell = (u, v, du, dv, elevation, fill) => quad([project(u,v,elevation),project(u+du,v,elevation),project(u+du,v+dv,elevation),project(u,v+dv,elevation)],fill);
    // The surface is a rectangular voxel basin with a dry central island. Its
    // texture is generated here, not sampled from a Minecraft game texture.
    const corners = [project(0,0),project(cols,0),project(cols,rows),project(0,rows)];
    quad(corners.map(p => [p[0],p[1]+depth]), '#112335');
    quad([corners[1],corners[2],[corners[2][0],corners[2][1]+depth],[corners[1][0],corners[1][1]+depth]], '#15334a');
    quad([corners[3],corners[2],[corners[2][0],corners[2][1]+depth],[corners[3][0],corners[3][1]+depth]], '#173b57');
    // Submerged darker blocks remain visible through the blue surface.
    for (let u=0;u<cols;u++) for(let v=0;v<rows;v++) {
      if(u>=4&&u<7&&v>=3&&v<6) continue;
      const seed=(u*17+v*31)%7;
      cell(u,v,1,1,0,seed<3?'#21435a':'#254d64');
      cell(u+.16,v+.18,.45,.47,-4,'rgba(10,34,51,.30)');
    }
    // Four small pixels per block, smoothly varying fields, and short broken
    // highlights give the water a slow fine-grained flow without random flashes.
    for(let pu=0;pu<cols*4;pu++) for(let pv=0;pv<rows*4;pv++) {
      const u=pu/4,v=pv/4;
      if(u>=4&&u<7&&v>=3&&v<6) continue;
      const field=Math.sin(pu*.47+time*.65)+Math.sin(pv*.63-time*.52)+.55*Math.sin((pu+pv)*.34+time*.36);
      const fleck=((pu*19+pv*37+(pu*pv)%13)%17)/17;
      const light=clamp((field+2.55)/5.1);
      const r=Math.round(37+light*22),g=Math.round(105+light*30),b=Math.round(158+light*30);
      cell(u,v,.25,.25,0,`rgba(${r},${g},${b},${.49+fleck*.15})`);
      if(field>1.55&&fleck>.45) cell(u,v,.25,.09,.2,`rgba(174,222,239,${(field-1.55)*.13})`);
    }
    // Pixel-cut surface edge, darker depth and intermittent underwater seams.
    for(let u=0;u<cols*2;u++) {
      const p=project(u/2,rows),q=project((u+1)/2,rows);
      quad([p,q,[q[0],q[1]+3],[p[0],p[1]+3]],u%3===0?'#467b99':'#326783');
      if(u%3===1) quad([[p[0],p[1]+6],[q[0],q[1]+6],[q[0],q[1]+10],[p[0],p[1]+10]],'rgba(22,75,111,.55)');
    }
    // There is water on every side: the island has no path or bridge to shore.
    const a=project(4,3),b=project(7,3),d=project(4,6),e=project(7,6),rise=24;
    quad([[b[0],b[1]-rise],[e[0],e[1]-rise],e,b], '#292b36');
    quad([[d[0],d[1]-rise],[e[0],e[1]-rise],e,d], '#343440');
    cell(4,3,3,3,rise,'#44404c');
    for(let u=4;u<7;u++) for(let v=3;v<6;v++) {
      cell(u+.04,v+.04,.92,.92,rise+.1,(u+v)%2?'#4b4653':'#403d48');
      cell(u+.15,v+.16,.30,.20,rise+.2,'rgba(147,129,162,.15)');
    }
    for(let u=4;u<7;u++) {
      const p=project(u,6),q=project(u+1,6);
      quad([[p[0],p[1]-21],[q[0]-1,q[1]-21],[q[0]-1,q[1]-19],[p[0],p[1]-19]],'#504957');
    }
    c.restore();
  }
  function motion(t, phase) {
    if (phase === 'spawning') return { x: 244, pose: 'lift', time: 0, alpha: ease((t - .12) / .28) };
    if (phase === 'working') {
      const q = Math.max(0,t) % 8;
      if (q < 1.15) return { x: 244, pose: 'lift', time: q, alpha: 1 };
      if (q < 3.45) return { x: lerp(244, 389, (q - 1.15) / 2.3), pose: 'carry', time: q - 1.15, alpha: 1 - ease((q - 3.12) / .33) };
      if (q < 3.8) return { x: 916, pose: 'carry', time: 0, alpha: 0 };
      if (q < 5.8) return { x: lerp(916, 1000, (q - 3.8) / 2), pose: 'carry', time: q - 3.8, alpha: ease((q - 3.8) / .33) };
      // A working loop waits while holding the crate. Only confirmed success
      // may set it down or produce success particles.
      return { x: 1000, pose: 'wait', time: q - 5.8, alpha: 1 - ease((q - 7.35) / .65) };
    }
    if (phase === 'waiting') return { x: 1000, pose: 'wait', time: t, alpha: 1 };
    if (phase === 'success') return { x: 1040, pose: 'success', time: Math.min(t, 1.3), alpha: 1 - ease((t-1.75)/.45) };
    if (phase === 'blocked') return { x: 976 - ease(t / .65) * 36, pose: 'blocked', time: Math.min(t, 1.45), alpha: 1 };
    if (phase === 'paused') return { x: 958, pose: 'wait', time: 0, alpha: 1 };
    return { x: 244, pose: 'wait', time: 0, alpha: 0 };
  }
  function sourceLabel(kind) { return kind === 'wechat' ? '微信' : kind === 'local' || kind === 'material' ? '素材' : 'QQ'; }
  function render(c, width, height, time, task = {}) {
    const s = { phase: 'idle', source: 'qq', target: 'wechat', completed: 0, total: null, failed: 0, ...task };
    time = Math.max(0, Number(time) || 0);
    const reduced = !!s.reduceMotion;
    const effectPhase = s.phase === 'paused' ? (s.pausedScenePhase || 'idle') : s.phase;
    const effectTime = s.phase === 'paused' ? Math.max(0, Number(s.pausedSceneElapsed ?? s.pausedElapsed) || 0) : time;
    const effectSettled = s.phase === 'paused' ? !!s.pausedSceneSettled : !!s.settled;
    const idle = effectPhase === 'idle' || effectPhase === 'queued' || effectPhase === 'cancelled' || (effectPhase === 'success' && effectSettled);
    const targetBlocked = s.phase === 'blocked';
    const ambientTime = reduced ? 0 : effectTime;
    const pearlTime = reduced ? 0 : Math.max(0, Number(s.pearlTime ?? ambientTime) || 0);
    c.save(); c.clearRect(0, 0, width, height); c.scale(width / 1280, height / 380);
    const bg = c.createLinearGradient(0, 0, 0, 380); bg.addColorStop(0, '#15151f'); bg.addColorStop(1, '#0d0e14');
    rr(c, .5, .5, 1279, 379, 25); c.fillStyle = bg; c.fill(); c.strokeStyle = '#30313d'; c.lineWidth = 1; c.stroke();
    const ground = 295;
    c.strokeStyle = '#34313c'; c.beginPath(); c.moveTo(90, ground + 3); c.lineTo(1190, ground + 3); c.stroke();
    c.fillStyle = '#a98cd30c'; c.fillRect(190, ground + 4, 900, 9);
    for (let i = 0; i < 13; i++) { c.fillStyle = i % 2 ? '#262330' : '#1c1b25'; c.fillRect(221 + i * 65, ground + 12, 44, 3); }
    const states = {
      idle: ['随时准备出发', '#aab6cb'], queued: ['已排队，尚未提交', '#aab6cb'], spawning: ['准备搬运', '#c9b1ef'], working: ['表情正在路上', '#c9b1ef'],
      waiting: ['已提交，等待确认', '#d8c691'], success: ['这批表情，已送达', '#9cdbb3'],
      blocked: ['搬运遇到阻碍', '#e4bc92'], paused: ['搬运已暂停', '#b8becc'], cancelled: ['搬运已停止', '#a4abbc']
    };
    const title = states[s.phase] || states.idle;
    c.fillStyle = title[1]; c.beginPath(); c.arc(40, 39, 3, 0, Math.PI * 2); c.fill();
    txt(c, title[0], 55, 45, 19, ink, 500);
    txt(c, sourceLabel(s.source) + '  →  ' + sourceLabel(s.target), 1238, 45, 15, '#8992a5', 400, 'right');
    const waterAmount = targetBlocked ? (reduced ? 1 : ease(time / .45)) : 0;
    const targetX = lerp(1170, 1136, waterAmount), targetY = lerp(220, 214, waterAmount);
    brand(c, s.source, 110, 220);
    const portalActive = !idle && !reduced && !targetBlocked;
    portal(c, 390, ground, ambientTime, portalActive); portal(c, 900, ground, ambientTime + 2, portalActive);
    if (targetBlocked) targetWater(c, targetX, ground, waterAmount, ambientTime);
    brand(c, s.target, targetX, targetY, lerp(283, 322, waterAmount));
    const fx = root.EmojiBridgeEffects;
    if (idle && fx) fx.drawPearl(c, {x: 640, y: 225, time: pearlTime, reducedMotion: reduced, alpha: 1});
    if (effectPhase === 'spawning' && fx && !reduced) {
      // The central idle pearl dissolves where it was; the character appears
      // at the source. No cross-screen pearl snap or forced waiting is needed.
      const vanish = 1-ease(effectTime/.18);
      fx.drawPearl(c,{x:640,y:225,time:pearlTime,alpha:vanish,shadow:false});
      c.save(); c.translate(640,246); c.scale(.45,.45);
      fx.drawTeleport(c,{x:0,y:0,time:effectTime,duration:.25,alpha:.48}); c.restore();
      fx.drawTeleport(c,{x:244,y:ground,time:effectTime,duration:.45});
    }
    const motionTime = reduced ? (targetBlocked ? 1.45 : s.phase === 'success' ? 1.3 : 0) : time;
    let m = s.visual || motion(motionTime, s.phase);
    if(reduced && !idle && s.phase !== 'success' && !targetBlocked) m={x:244,pose:'wait',time:0,alpha:1};
    const character = root.EmojiBridgeCharacter;
    if (!idle && character && m.alpha > 0) character.drawCharacter(c, { x: m.x, y: ground, scale: 41, pose: m.pose, time: m.time, facing: 1, alpha: m.alpha, shadow: true });
    if (effectPhase === 'success' && !effectSettled && !reduced && effectTime < 1.4) {
      for (let i = 0; i < 16; i++) {
        const a = i * 2.399, tt = clamp(effectTime / 1.4), radius = 8 + tt * 70;
        c.globalAlpha = Math.sin(Math.PI * tt); c.fillStyle = i % 2 ? '#cba0f7' : '#a2dfb5';
        c.fillRect(1055 + Math.cos(a) * radius, 190 + Math.sin(a) * radius + tt * tt * 40, 3, 3);
      }
      c.globalAlpha = 1;
    }
    let detail = s.detail;
    if (!detail) {
      if (s.phase === 'idle') detail = '选择表情，即可开始互通';
      else if (s.phase === 'spawning') detail = '任务已接收，正在准备';
      else if (s.phase === 'blocked') detail = '查看原因后继续 · 已完成的表情会保留';
      else if (s.phase === 'waiting') detail = '正在等待客户端结果';
      else if (s.phase === 'cancelled') detail = '已停止本次搬运';
      else if (s.phase === 'paused') detail = '继续时从当前位置接上';
      else if (s.total != null) detail = '已确认 ' + s.completed + ' / ' + s.total + (s.failed ? ' · 未完成 ' + s.failed : '');
      else detail = '正在处理所选表情';
    }
    txt(c, detail, 40, 348, 16, '#9ea6b9');
    const total = Number(s.total), ratio = total > 0 ? clamp(Number(s.completed) / total) : null;
    if(s.phase !== 'idle' && s.phase !== 'cancelled') {
      rr(c, 902, 339, 336, 4, 2); c.fillStyle = '#2a2834'; c.fill();
      if (ratio != null && ratio > 0) { rr(c, 902, 339, 336 * ratio, 4, 2); c.fillStyle = s.phase === 'success' ? '#9ed8b1' : '#ac8dd1'; c.fill(); }
      else if (ratio == null && s.phase === 'working') { rr(c, 902 + ((ambientTime * 45) % 240), 339, 96, 4, 2); c.fillStyle = '#8e78b0'; c.fill(); }
    }
    c.restore();
    return {phase:s.phase,pearlVisible:idle || effectPhase==='spawning' && effectTime<.18,characterVisible:!idle && m.alpha>0,waterVisible:targetBlocked,waterAmount,portalActive,targetX,targetY,visual:m};
  }
  // Desktop adapter: retain the reference geometry/materials in the existing
  // 118px strip, without squeezing a 380px demo screenshot into that strip.
  function renderCompact(c,w,h,t,s){
    c.clearRect(0,0,w,h);
    const reduced=!!s.reduceMotion, phase=s.phase==='paused'?(s.pausedScenePhase||'idle'):s.phase;
    const time=s.phase==='paused'?(s.pausedElapsed||0):t;
    const settled=s.phase==='paused'?s.pausedSceneSettled:s.settled;
    const idle=phase==='idle'||phase==='queued'||phase==='cancelled'||phase==='success'&&settled;
    const blocked=phase==='blocked',ambient=reduced||idle?0:time,ground=h-12;
    const inset=Math.max(0,(w-1000)/2),start=inset+44,end=w-inset-70,range=end-start;
    const at=(x,y,z,fn)=>{c.save();c.translate(x,y);c.scale(z,z);fn();c.restore()};
    c.strokeStyle='#34313c';c.beginPath();c.moveTo(start,ground);c.lineTo(blocked?end-64:end,ground);c.stroke();
    at(start,ground-36,.5,()=>brand(c,s.source,0,0));
    const amount=blocked?(reduced?1:ease(time/.45)):0;
    if(blocked)at(end,ground,.52,()=>targetWater(c,0,0,amount,ambient));
    at(end,ground-36-(blocked?5:0),.5,()=>brand(c,s.target,0,0,blocked?86:63));
    const portalActive=!idle&&!blocked&&!reduced;
    for(const f of [.28,.7])at(start+range*f,ground,.48,()=>portal(c,0,0,ambient+f*2,portalActive));
    // Idle replaces the CHARACTER, never the stage. Keep both destinations,
    // quiet portals and the ground visible after a result has settled too.
    if(idle){root.EmojiBridgeEffects?.drawPearl(c,{x:w/2,y:h/2-5,time:s.pearlTime||0,reducedMotion:reduced});return {pearlVisible:true,characterVisible:false,waterVisible:false,portalActive,platforms:2,portals:2};}
    const clock=reduced?(blocked?1.45:phase==='success'?1.3:0):time;
    let m=s.visual||motion(clock,phase),x=start+(m.x-110)/1060*range;
    if(blocked)x=end-90-8*ease(clock/.8);
    if(phase==='spawning'&&!reduced){
      root.EmojiBridgeEffects?.drawPearl(c,{x:w/2,y:h/2-5,time:s.pearlTime||0,alpha:1-ease(time/.18),shadow:false});
      at(w/2,h/2+16,.28,()=>root.EmojiBridgeEffects?.drawTeleport(c,{x:0,y:0,time,duration:.25,alpha:.48}));
      at(x,ground,.58,()=>root.EmojiBridgeEffects?.drawTeleport(c,{x:0,y:0,time,duration:.45}));
    }
    const characterResult=root.EmojiBridgeCharacter.drawCharacter(c,{x,y:ground,scale:24,pose:m.pose,time:m.time,alpha:reduced?1:m.alpha,facing:1,shadow:true});
    if((reduced||m.alpha>0)&&!characterResult?.bounds)throw new Error('搬运角色未实际绘制，任务继续；请检查动效资源');
    if(phase==='success'){
      if(!reduced&&time<1.4)for(let i=0;i<16;i++){const p=clamp(time/1.4),a=i*2.399,r=p*42;c.globalAlpha=1-p;c.fillStyle=i%2?'#cba0f7':'#a2dfb5';c.fillRect(x+Math.cos(a)*r,ground-54+Math.sin(a)*r+p*p*22,3,3);}
      c.globalAlpha=1;txt(c,'✓',end,ground-75,18,'#9cdbb3',600,'center');
    }
    if(blocked&&reduced)txt(c,'!',end-48,ground-66,18,'#e4bc92',600,'center');
    return {pearlVisible:phase==='spawning'&&time<.18,characterVisible:reduced||m.alpha>0,characterDrawn:!!characterResult?.bounds,characterBounds:characterResult?.bounds,waterVisible:blocked,visual:m,portalActive,platforms:2,portals:2};
  }
  root.EmojiBridgeStage = { render, renderCompact, motion, targetWater };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.EmojiBridgeStage;
})(typeof globalThis !== 'undefined' ? globalThis : this);
