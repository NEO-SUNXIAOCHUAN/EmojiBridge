import {useMediaPreview,HoverPreview,HOVER_DELAY} from './media-preview';
import React,{useState,useEffect,useRef} from 'react';
import './collections.css';
import {TransferStage} from './transfer-stage';
import * as Dialog from '@radix-ui/react-dialog';
import {Check,RefreshCw,Layers,Columns2,Grid2X2,Info,AlertCircle} from 'lucide-react';
import {readLabel,emptyLabel} from './collection-read-state.mjs';
import {AccountPanels} from './account-panels';
import {emptySelection,selectedIds,selectRows,toggleRow,reconcileSelection,transferRows,selectedReady} from './collection-selection.mjs';

export function CollectionsPage({visible,call,onSetup,onLibrary,onLegacy,transfer,onTransfer,onResults,reduced=false}){
 const [data,setData]=useState({items:[],sides:{},total:0}),[platform,setPlatform]=useState(''),[split,setSplit]=useState(false),[selections,setSelections]=useState(emptySelection),[error,setError]=useState(''),[detail,setDetail]=useState(null),[limit,setLimit]=useState(80);
 const detailTrigger=useRef(null);
 const selected=selectedIds(selections,platform);
 const [relation,setRelation]=useState(''),[recent,setRecent]=useState(false),[order,setOrder]=useState('source'),[historical,setHistorical]=useState(false);
 const running=useRef(false),generation=useRef(0),scope=useRef(null),previous=useRef([]);
 const snapshot=useRef('');
 const load=async()=>{if(running.current||document.hidden)return;running.current=true;const ticket=++generation.current;try{const value=await call('collection_listing');if(ticket!==generation.current)return;const encoded=JSON.stringify(value);if(encoded===snapshot.current)return;snapshot.current=encoded;const all=[...new Map([...value.items,...(value.local_items||[]),...(value.history_items||[])].map(i=>[i.id,i])).values()];if(scope.current!==value.account_scope){setSelections(emptySelection());setHistorical(false);scope.current=value.account_scope}else{setSelections(old=>reconcileSelection(old,previous.current,all))}previous.current=all;setData(value);setDetail(old=>old?(all.find(i=>i.id===old.id)||old):null)}catch(e){setError(String(e))}finally{running.current=false}};
 useEffect(()=>{if(!visible)return;load();const timer=setInterval(load,1500);const focus=()=>load();window.addEventListener('focus',focus);return()=>{clearInterval(timer);window.removeEventListener('focus',focus)}},[visible]);
 const action=async(client,kind,ids=[],retry=false)=>{try{setError('');await call('collection_action',client,kind,ids,retry);await load()}catch(e){setError(String(e))}};
 const [hoverItem,setHoverItem]=useState(null),hoverTimer=useRef(null);
 const [shownDocument,setShownDocument]=useState(!document.hidden);
 useEffect(()=>{const visibility=()=>setShownDocument(!document.hidden);document.addEventListener('visibilitychange',visibility);return()=>document.removeEventListener('visibilitychange',visibility)},[]);
 const currentHover=hoverItem&&[...data.items,...(data.local_items||[]),...(data.history_items||[])].find(i=>i.id===hoverItem.id);
 // Cover regeneration is not a media change. Restarting here used to blank an
 // already-playing GIF whenever an unrelated enrichment published its cover.
 const hoverVersion=currentHover?JSON.stringify([data.account_scope,currentHover.members?.map(m=>[m.client,m.id,m.observation_key,m.asset,m.managed_original,m.source_sha256])]):'';
 const {frame:hoverFrame,error:hoverError}=useMediaPreview(call,currentHover?'collection:'+currentHover.id:null,visible&&shownDocument,hoverVersion,()=>queuePreview([currentHover],true,true));
 const clearHover=()=>{clearTimeout(hoverTimer.current);setHoverItem(null)};
 useEffect(()=>{clearHover();return()=>clearTimeout(hoverTimer.current)},[visible,data.account_scope,platform,relation,historical]);
 const allItems=[...new Map([...data.items,...(data.local_items||[]),...(data.history_items||[])].map(i=>[i.id,i])).values()];
 const shown=(historical?(data.history_items||[]):platform==='local'?(data.local_items||[]):platform?data.items:allItems.filter(i=>!i.historical_only)).filter(i=>(!platform||i.clients.includes(platform))&&(!recent||i.recent_kind)&&(!relation||relation==='duplicate'&&i.duplicate||relation==='cross'&&i.source_counts?.qq>0&&i.source_counts?.wechat>0&&i.identity_verified||relation==='same'&&i.identity_verified&&(i.source_counts?.qq>1||i.source_counts?.wechat>1)||relation==='suspected'&&i.suspected_with?.length>0||relation===i.comparison));
 if(order==='recent')shown.sort((a,b)=>(b.first_discovered_at||'').localeCompare(a.first_discovered_at||'')||a.id.localeCompare(b.id));
 const checkIncomplete=Object.values(data.sides).some(s=>s.state?.needs_update||s.state?.failed||s.check?.result==='incomplete'||s.check?.result==='cancelled');
 const discovery=data.discovery||{},hasNew=!!(discovery.new_content||discovery.new_sources||discovery.new_observations);
 const previewAttempts=useRef(new Set()),previewQueue=useRef(new Map());
 const queuePreview=(items,priority=false,retry=false)=>{for(const item of items){
  if(item.preview_quality==='original_cover'&&!retry)continue;
  for(const m of item.members.filter(m=>m.client!=='local'&&!m.unseen)){
   const key=m.client+':'+m.id;if(retry)previewAttempts.current.delete(key);
   if(!previewAttempts.current.has(key)&&(retry||m.enrichment_state!=='failed')){const prior=previewQueue.current.get(key);previewQueue.current.set(key,{client:m.client,id:m.id,priority:priority||!!prior?.priority,retry:retry||!!prior?.retry})}
  }
 }};
 useEffect(()=>{previewAttempts.current.clear();previewQueue.current.clear()},[data.account_scope]);
 useEffect(()=>{if(data.task?.action)return;
  // A cancelled/yielded batch has not attempted every accepted row. Requeue
  // only unfinished rows; user cancellation remains gated by preview_paused.
  for(const item of allItems)for(const m of item.members)if(!m.enrichment_state)
   previewAttempts.current.delete(m.client+':'+m.id);
 },[data.task?.request,data.task?.action]);
 useEffect(()=>{if(!visible||transfer?.active)return;let live=true,busy=false;
  const flush=async()=>{if(!live||busy||document.hidden)return;
   const entries=[...previewQueue.current].filter(([k,v])=>!data.task?.action||data.task.action==='enrich'&&v.priority).sort((a,b)=>Number(b[1].priority)-Number(a[1].priority));
   const first=entries.find(([k,v])=>!data.sides[v.client]?.preview_paused||v.retry);if(!first)return;
   const group=entries.filter(([k,v])=>v.client===first[1].client&&v.priority===first[1].priority).slice(0,18);busy=true;
   try{const accepted=await call('collection_enrich',data.account_scope,first[1].client,group.map(([k,v])=>v.id),group.some(([k,v])=>v.retry),!!first[1].priority);
    if(accepted)for(const [k] of group){previewAttempts.current.add(k);previewQueue.current.delete(k)}
   }catch(e){if(live)setError(String(e))}finally{busy=false}
  };const first=setTimeout(flush,350),timer=setInterval(flush,1000);return()=>{live=false;clearTimeout(first);clearInterval(timer)};
 },[visible,data.account_scope,data.task?.action,transfer?.active,JSON.stringify(data.sides)]);
 useEffect(()=>{if(!visible)return;queuePreview(allItems.filter(i=>selected.includes(i.id)||i.id===detail?.id),true);
  const idle=setTimeout(()=>queuePreview(allItems.filter(i=>!i.historical_only&&i.preview_quality!=='original_cover'&&!i.members.some(m=>previewAttempts.current.has(m.client+':'+m.id))).slice(0,36)),1800);return()=>clearTimeout(idle);
 },[visible,snapshot.current,selected.join(','),detail?.id]);
 const retryPreview=item=>{queuePreview([item],true,true);setError('');};
 useEffect(()=>{if(currentHover&&visible)queuePreview([currentHover],true)},[hoverItem?.id,visible]);

 const importSelected=async()=>{for(const c of ['qq','wechat']){if(platform&&platform!==c)continue;const ids=allItems.filter(i=>(selections[c]||[]).includes(i.id)).flatMap(i=>i.members.filter(m=>m.client===c&&!m.unseen).map(m=>m.id));if(ids.length)await action(c,'import',[...new Set(ids)])}};
 const picked=allItems.filter(i=>selected.includes(i.id)),sources=new Set(['qq','wechat','local'].filter(c=>selectedIds(selections,c).length));
 const ready=picked.filter(i=>selectedReady(i,selections,platform)).length,preferred=platform==='qq'?'wechat':platform==='wechat'?'qq':sources.size===1?(sources.has('qq')?'wechat':sources.has('wechat')?'qq':null):null;
 const candidates=(target,source=platform)=>transferRows(allItems,selections,target,source);
 const start=(target,source=platform)=>{const rows=candidates(target,source);if(!rows.length){setError('请先勾选'+(source==='qq'?' QQ ':source==='wechat'?'微信':'对应来源的')+'表情，再转移。');return;}
  const opposite=target==='qq'?'wechat':'qq';
  const ids=rows.map(i=>(!source||source==='local')&&!(selections[opposite]||[]).includes(i.id)&&i.material_id?'local:'+i.material_id:i.id);
  if(ids.every(id=>id.startsWith('local:')))onTransfer('library',target,ids.map(id=>id.slice(6)),data.account_scope);
  else onTransfer('collections',target,ids,data.account_scope,source||null);
 };
 const showDetail=(event,item)=>{event.stopPropagation();detailTrigger.current=event.currentTarget;setDetail(item)};
 const clientName=c=>({qq:'QQ',wechat:'微信',local:'本地'}[c]||'来源未知');
 const card=(item,onlySource=platform)=>{
  const title=item.display_name??item.name;
  const unavailable=!item.ready&&!item.historical_only;
  const failed=item.members.some(m=>['failed','unavailable','unsupported'].includes(m.original_state));
  const deliveryIssue=Object.entries(item.target_states||{}).find(([c,state])=>/失败|暂停|待.*确认|待核验/.test(state));
  const status=[item.duplicate?`确认重复 ${item.source_count} 份`:item.comparison==='suspected'?'疑似相似':item.comparison==='pending'?'待比对':'',unavailable?(failed?'原件异常':'待取原件'):''].filter(Boolean).join('；');
  return <article onPointerEnter={()=>{clearTimeout(hoverTimer.current);hoverTimer.current=setTimeout(()=>setHoverItem(item),HOVER_DELAY)}} onPointerLeave={clearHover} key={item.id} data-collection-id={item.id} className={'asset collection-card '+(selectedIds(selections,onlySource).includes(item.id)?'selected':'')} tabIndex={0} role="checkbox" aria-label={`${item.name}；${item.clients.map(clientName).join('、')}；${status||'查看详情'}`} aria-checked={selectedIds(selections,onlySource).includes(item.id)} onClick={()=>setSelections(old=>toggleRow(old,item,onlySource))} onKeyDown={e=>{if(e.target!==e.currentTarget)return;if(e.key===' '){e.preventDefault();e.currentTarget.click()}else if(e.key==='Enter'){e.preventDefault();showDetail(e,item)}}}>
   <div className="asset-image"><CollectionPreview item={item} active={visible&&!transfer?.active} onLoadPreview={queuePreview} onRetry={()=>retryPreview(item)}/>{item.frames>1&&<span className="collection-motion-label" title={`动画 · ${item.frames} 帧；封面相同不代表完整内容相同`}>GIF</span>}<span className="tick"><Check size={12}/></span>
    <div className="image-actions">
    {item.duplicate?<button className="relation-badge confirmed" aria-label={`确认重复 ${item.source_count} 份，展开来源`} title={item.duplicate_labels.join(' · ')} onClick={e=>showDetail(e,item)}>×{item.source_count}</button>:item.comparison==='suspected'?<button className="relation-badge" aria-label="疑似相似，展开来源" title="疑似相似，尚未确认重复" onClick={e=>showDetail(e,item)}>≈</button>:null}
    <button className="card-details" aria-label={'详情：'+item.name} title="预览与详情 · Enter" onClick={e=>showDetail(e,item)}><Info size={15}/></button>
    </div>
   </div>
  </article>;
 };
 return <section className={"collections-page"+(selected.length?" has-selection":"")} style={{display:visible?'flex':'none'}}>
 <header><div className="heading"><div><h1>表情互通</h1><p className="muted">选择表情转到 QQ 或微信，也可加入素材库继续编辑。</p></div><button className="primary account-settings" onClick={onLegacy}>账号设置</button><button onClick={onResults}>互通记录</button></div>
 <AccountPanels sides={data.sides}><div className="client-summaries">{['qq','wechat'].map(c=>{const s=data.sides[c]||{};return <div className="source-account" key={c}>
  <div className="source-account-heading"><b>{c==='qq'?'QQ':'微信'}</b><span>{s.account?'本人账号 · '+String(s.account).slice(-3):'未选择账号'} · {s.count||0} 项</span><button className="source-update" disabled={!data.connected||s.state?.active||transfer?.active} onClick={()=>{previewAttempts.current.clear();action(c,'refresh')}}><RefreshCw size={14}/>更新</button></div>
  <div className="source-account-state"><small>{readLabel(s)}{s.read_at?' · '+new Date(s.read_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):''}</small>{s.state?.active&&<button className="source-cancel" onClick={()=>action(c,'cancel')}>取消</button>}<button className={'source-transfer '+(candidates(c==='qq'?'wechat':'qq',c).length?'primary':'')} disabled={!!transfer?.active||!candidates(c==='qq'?'wechat':'qq',c).length} title={"转移所选"+(c==='qq'?' QQ 表情到微信':'微信表情到 QQ')} onClick={()=>start(c==='qq'?'wechat':'qq',c)}>{c==='qq'?'转到微信':'转到 QQ'}</button></div>
  {(s.state?.active||s.state?.failed)&&<p className={'source-status '+(s.state?.failed?'inline-error':'')}>{s.state?.text}</p>}
  <div className="source-account-actions">{s.preview_paused&&<button onClick={()=>{const item=allItems.find(i=>i.clients.includes(c)&&i.preview_quality!=='original_cover');if(item)retryPreview(item)}}>继续补齐预览</button>}</div>
  <details className="source-diagnostics"><summary>读取详情</summary><p>账号：{s.account||"未选择"}</p><p>{s.scope} · 原件可用 {s.ready||0} · 历史未见 {s.historical||0}</p><p>{s.state?.text}</p><p>仅点更新时读取收藏；本地预览与收藏核验分别处理。</p></details>
 </div>})}</div></AccountPanels>
 <div className="subheading"><div className="segments">{[['','全部'],['qq','QQ'],['wechat','微信'],['local','本地素材']].map(([v,t])=><button key={v} className={platform===v?'active':''} onClick={()=>{setPlatform(v);setSplit(false);setLimit(80)}}>{t}</button>)}</div><select aria-label="重复表情筛选" value={relation} onChange={e=>{setRelation(e.target.value);setLimit(80)}}>{[['','全部关系'],['duplicate','重复表情'],['cross','QQ、微信都有'],['same','同平台多份'],['suspected','疑似相似'],['pending','待比对']].map(([v,t])=><option key={v} value={v}>{t}</option>)}</select><select aria-label="表情排序" value={order} onChange={e=>setOrder(e.target.value)}><option value="source">来源顺序</option><option value="recent">最近发现</option></select><span title="来源统计为本账号已读列表，包含明确标注的未重读尾部；历史未见项另列，不作为重复份数。">当前来源 {data.source_count||0} 条 · 当前内容 {data.total} 组 · 确认重复 {data.duplicate_groups||0} 组</span><button aria-pressed={historical} onClick={()=>{setHistorical(!historical);setRecent(false);setLimit(80)}}>{historical?"返回当前记录":`历史未见 ${data.history_total||0} 组`}</button><details className="collection-select"><summary>选择范围</summary><button onClick={()=>setSelections(old=>selectRows(old,shown.slice(0,limit),platform))}>选择已显示 {Math.min(limit,shown.length)} 项</button><button onClick={()=>setSelections(old=>selectRows(old,shown,platform))}>选择全部匹配 {shown.length} 项</button><button onClick={()=>setSelections(old=>selectRows(old,[],platform))}>清空选择</button></details><button onClick={()=>{setSplit(!split);setPlatform('')}}>{split?<Grid2X2 size={15}/>:<Columns2 size={15}/>} {split?'合并网格':'双栏对照'}</button></div>
 {data.connected&&<details className="source-diagnostics"><summary>比对与历史 · 待比对 {data.comparison?.pending||0}</summary><p>精确比对 {data.comparison?.exact||0} / {data.source_count||0} 条；历史未见 {data.history_total||0} 组。缺少完整原件不能认定没有重复。点击更新核对当前来源，不会再次发送。</p></details>}
 {hasNew&&<div className="discovery-status"><span>发现 {discovery.new_content||0} 项新内容 · 新增来源 {discovery.new_sources||0}</span><button onClick={()=>{setRecent(!recent);setOrder('recent');setHistorical(false)}}>{recent?'返回全部':'查看新增'}</button></div>}
 </header>
 {transfer?.can_resume&&!transfer.active&&<div className="discovery-status collection-resume"><span>{transfer.text}</span><button onClick={()=>onTransfer('resume',transfer.target,[transfer.path])}>继续 / 重试未完成</button></div>}
 {error&&<div className="collection-error"><AlertCircle size={16}/>{error}</div>}
 <div className="collection-content scroll-zone" onScroll={clearHover}>{!data.connected&&!shown.length?<div className="empty"><Layers size={36}/><h2>连接本人的收藏</h2><p>选择账号后先显示本机保存的读取记录；更新不会自动导入整个收藏。</p><button className="primary" onClick={onSetup}>选择账号</button></div>:!shown.length?<div className="empty"><h2>{emptyLabel(data.sides,platform,error,!!data.items.length)}</h2><p>{data.items.length?'可切换到全部来源查看已有记录。':'上方显示各来源的读取状态；已有原件仍保留。'}</p></div>:split?<div className="collection-compare">{['qq','wechat'].map(c=><section key={c}><h2>{c==='qq'?'QQ':c==='local'?'本地':'微信'}</h2><div className="grid">{shown.filter(i=>i.clients.includes(c)).slice(0,limit).map(item=>card(item,c))}</div></section>)}</div>:<div className="grid">{shown.slice(0,limit).map(item=>card(item))}</div>}{shown.length>limit&&<button className="load-more" onClick={()=>setLimit(n=>n+80)}>继续显示（已显示 {limit} / {shown.length}）</button>}</div>
 {currentHover&&visible&&shownDocument&&<HoverPreview item={currentHover} frame={hoverFrame} error={hoverError}/>}
 <TransferStage transfer={transfer} visible={visible} reduced={reduced}/>
 <div className="collection-actions"><div className="transfer-counts" title="可处理数量依据已保存的完整原件核验；执行前再次校验完整文件和来源，失效项不会提交。"><b>{selected.length?`${platform==='qq'?'QQ · ':platform==='wechat'?'微信 · ':platform==='local'?'本地 · ':''}已选 ${selected.length} 项`:'请先选择表情'}</b><small>{selected.length?`原件可处理 ${ready} · 待获取/核对 ${picked.length-ready} · 目标已确认 QQ ${picked.filter(i=>i.confirmed_targets?.includes('qq')).length} / 微信 ${picked.filter(i=>i.confirmed_targets?.includes('wechat')).length}`:'原件会在执行前复核；QQ 仅添加收藏，微信使用本人的文件传输助手。'}{picked.some(i=>i.historical_only)?' · 历史未见项仅供查看，请更新来源后操作':''}{selected.some(id=>!shown.slice(0,limit).some(i=>i.id===id))?' · 含当前未显示项':''}</small></div><button className={preferred==='wechat'?'primary':''} disabled={!candidates('wechat').length||transfer?.active} onClick={()=>start('wechat')}>转到微信</button><button className={preferred==='qq'?'primary':''} disabled={!candidates('qq').length||transfer?.active} onClick={()=>start('qq')}>转到 QQ</button><button disabled={!picked.some(i=>!i.historical_only)||transfer?.active} onClick={importSelected}>加入素材库</button><button disabled={!selected.length} onClick={()=>setSelections(old=>selectRows(old,[],platform))}>清空</button><button onClick={()=>onLibrary(data.imported_items||[])}>在素材库查看</button></div>

 {detail&&<Dialog.Root open onOpenChange={open=>{if(!open)setDetail(null)}}><Dialog.Portal><Dialog.Overlay className="shade"/><Dialog.Content className="modal collection-detail" aria-describedby={undefined} onCloseAutoFocus={e=>{e.preventDefault();detailTrigger.current?.focus()}}><Dialog.Title>来源与读取范围</Dialog.Title><button onClick={()=>setDetail(null)}>关闭详情</button><h2>{detail.name}</h2><div className="detail-preview"><CollectionPreview item={detail} active={visible} size={960} onLoadPreview={queuePreview} onRetry={()=>retryPreview(detail)}/></div><p>{detail.frames>1?"GIF · 网格为封面，原件动画保留":"静态封面"} · {detail.preview_quality==='original_cover'?'完整原件清晰封面':'当前为缓存封面，后台补齐原件'}</p><button onClick={()=>retryPreview(detail)}>重新获取清晰预览</button>{detail.members.filter(m=>m.enrichment_error).map(m=><p key={m.client+m.id} className="inline-error">{m.enrichment_error}</p>)}<label className="detail-copy">名称<input readOnly aria-label="原始名称，可复制" value={detail.name} onFocus={e=>e.target.select()}/></label>{Object.entries(detail.target_states||{}).map(([c,state])=><p key={c}>{clientName(c)}：{state}</p>)}<p>{detail.original_label} · {detail.states?.join(' · ')}</p><p>{detail.duplicate_labels?.join(' · ')} · 本次 {detail.source_count} 条来源记录。历史未读到项不代表删除，不计入重复份数。</p><p>完整内容才确认重复；疑似相似保留独立卡片，待原件补齐后比对。来源不等于目标已收藏。聊天表情无法拖入时，可先添加到微信表情，再刷新列表加入素材库。</p>{detail.suspected_with?.length>0&&<div><b>疑似关联 · 尚未合并</b><p>完整候选文件相同，但部分条目只有外观关联，不能确认收藏中的精确版本。</p>{detail.suspected_with.map(id=>{const other=allItems.find(i=>i.id===id);return other&&<button key={id} onClick={()=>setDetail(other)}>查看 {other.clients.map(c=>c==='qq'?'QQ':c==='local'?'本地':'微信').join(' / ')} · {other.name}</button>})}</div>}{detail.members.map(m=><div key={m.client+m.id}><b>{m.client==='qq'?'QQ':m.client==='local'?'本地素材':'微信'} · {m.account} · {m.original_label}</b><p>{m.unseen?'历史记录 · 本次未读到 · ':''}{m.read_at||'时间未知'} · {m.scope||'范围待核对'}</p><p>首次发现：{m.first_discovered_at||'此前记录，时间未知'}（不是收藏时间）</p><label className="detail-copy">{m.name||'来源记录'}<input readOnly aria-label="来源编号，可复制" value={m.id} onFocus={e=>e.target.select()}/></label><small>{m.prior_observations?` · 已关联 ${m.prior_observations} 份此前读取记录（不增加当前份数）`:''}</small></div>)}</Dialog.Content></Dialog.Portal></Dialog.Root>}
 </section>;
}


function CollectionPreview({item,active,onLoadPreview,onRetry,size}){
 const ref=useRef(null);const [failed,setFailed]=useState(false),[visible,setVisible]=useState(false),[pixels,setPixels]=useState(size||384),[retry,setRetry]=useState(0),[display,setDisplay]=useState(null);
 useEffect(()=>{const observer=new IntersectionObserver(entries=>setVisible(entries[0].isIntersecting),{rootMargin:'80px'});if(ref.current)observer.observe(ref.current);const resize=new ResizeObserver(()=>{if(!size&&ref.current)setPixels(Math.min(640,Math.max(192,Math.ceil(ref.current.clientWidth*devicePixelRatio/64)*64)))});resize.observe(ref.current);return()=>{observer.disconnect();resize.disconnect()}},[size]);
 useEffect(()=>{if(!active||!visible)return;onLoadPreview([item],true)},[active,visible,item.id,item.preview_quality]);
 const url=item.has_preview?item.thumbnail+'&size='+pixels+'&retry='+retry:null;
 useEffect(()=>{if(!url||!visible)return;let live=true;const image=new Image();setFailed(false);image.onload=()=>{if(live)setDisplay(url)};image.onerror=()=>{if(live)setFailed(true)};image.src=url;return()=>{live=false;image.onload=image.onerror=null}},[url,visible]);
 return <div className="collection-preview" ref={ref}>{display?<img src={display} draggable="false" alt=""/>:<div><button title={failed?'预览读取失败，点击重试':'尚无预览，点击重新获取'} aria-label="重新获取预览" onClick={e=>{e.stopPropagation();setRetry(n=>n+1);onRetry()}}><RefreshCw size={18}/></button></div>}{failed&&display&&<button className="preview-retry" title="清晰预览未取得，保留上次可用图；点击重试" aria-label="重试清晰预览" onClick={e=>{e.stopPropagation();setRetry(n=>n+1);onRetry()}}><RefreshCw size={14}/></button>}</div>;
}
