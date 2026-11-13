export function readLabel(side={}) {
 const state=side.state||{},check=side.check||{};
 if(state.active&&state.action==='refresh')return state.text||'正在读取收藏';
 if(check.result==='cancelled')return '读取已取消';
 if(check.result==='incomplete'||check.result==='deferred'||(state.failed&&state.action==='refresh'))return '读取未完成，可重试';
 if(check.result==='success')return check.count===0?'本次读取为空':'已读取';
 return side.read_at?'已有读取记录':'尚未读取';
}
export function emptyLabel(sides,platform,error,hasOther) {
 if(error)return '读取未完成';
 if(platform==='local')return '还没有本地素材';
 const selected=platform?[sides[platform]||{}]:Object.values(sides);
 const labels=selected.map(readLabel);
 if(selected.some(s=>s.state?.active&&s.state.action==='refresh'))return '正在读取收藏';
 if(labels.some(s=>s.includes('未完成')))return '读取未完成，可重试';
 if(labels.includes('读取已取消'))return '读取已取消';
 if(hasOther)return '此来源暂无记录';
 return selected.some(s=>s.check?.result==='success')?'本次读取没有发现表情':'还没有读取记录';
}
