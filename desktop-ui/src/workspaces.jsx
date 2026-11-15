import React,{useState,useEffect,useRef} from 'react';
import * as Menu from '@radix-ui/react-dropdown-menu';
import {motion} from 'motion/react';
import {ArrowLeft,Film,Layers,Download,Check,Monitor,FolderOpen,RefreshCw,Palette,ChevronRight,Scissors,Video} from 'lucide-react';

import {desktopCaller} from './desktop-api.mjs';
export const api=desktopCaller(window);
export function Action({icon:Icon,children,...p}){return <button {...p}>{Icon&&<Icon size={17}/>} {children}</button>}
// User-supplied A final icon; preserve its original canvas and colours.
export function EmojiMark(){return <img src="/brand.png" width="32" height="32" alt="" aria-hidden="true" draggable="false"/>}

// This rectangle is occupied by the real Tk HWND, not a canvas screenshot.
// The native surface is hidden for WebView dialogs to keep their focus/order.
export function NativeSlot({visible,view,pending,onBack,onError}){
 const area=useRef(null),last=useRef('');
 useEffect(()=>{let raf;last.current='';const update=()=>{cancelAnimationFrame(raf);raf=requestAnimationFrame(()=>{const r=area.current?.getBoundingClientRect();if(!r)return;const value={x:r.x,y:r.y,width:r.width,height:r.height,viewportWidth:innerWidth,viewportHeight:innerHeight,visible};const key=JSON.stringify(value);if(key===last.current)return;last.current=key;api('workspace_layout',value).catch(onError)})};const observer=new ResizeObserver(update);observer.observe(area.current);window.addEventListener('resize',update);update();return()=>{cancelAnimationFrame(raf);observer.disconnect();window.removeEventListener('resize',update)}},[visible,pending,view]);
 return <div className={"native-workspace "+(view==='editor'?'native-editor':'')}><div className="workspace-bar"><Action icon={ArrowLeft} onClick={onBack}>返回素材</Action><span>{({bridge:'表情互通',video:'视频与选段',settings:'兼容与高级设置'})[view]||'表情工厂'}</span><small>原件保留 · 草稿可继续编辑</small></div><div ref={area} className="native-slot">{pending&&<div className="workspace-loading"><div className="brand-mark"><EmojiMark/></div><b>正在打开工作区</b><span>载入素材和草稿…</span></div>}</div></div>
}

export function SettingsPage({prefs,onChange,safe,status,onAdvanced,onLab,labEnabled}){
 const [promo,setPromo]=useState(null);
 const [components,setComponents]=useState([]);
 useEffect(()=>{safe(async()=>setComponents(await api('component_status')))},[status.task.active]);
 useEffect(()=>{api('promo_status').then(setPromo)},[]);
 const [info,setInfo]=useState(null);const [hotkey,setHotkey]=useState('Ctrl+Shift+E');
 const [keyStatus,setKeyStatus]=useState('');const [checkNote,setCheckNote]=useState('');
 const keyUpdate=v=>{setHotkey(v.key||'');setKeyStatus(v.error|| (v.enabled?'已启用 '+v.active_key:'快捷键未启用'))};
 useEffect(()=>{api('drawer_settings').then(keyUpdate)},[]);
 const refresh=()=>safe(async()=>setInfo(await api('dependency_status')));
 useEffect(()=>{refresh()},[status.task.active]);
 const choices=[['startup_motion','开机动画','冷启动播放已定稿 V10；可随时跳过。'],['startup_sound','开机音效','只在开机动画中播放一份同步音轨。'],['reduce_motion','减少动效','保留即时反馈，关闭装饰性位移。'],['glass','浮层玻璃','导航与工具浮层使用少量透明材质。'],['always_scrollbars','始终显示滚动条','默认沿用 Windows 的可访问性偏好。']];
 return <section className="settings-page scroll-zone"><h1>设置</h1><p className="page-lead">显示、操作与本地组件，集中在这里。</p><div className="settings-columns"><div><h2>外观与反馈</h2><div className="settings-card">{choices.map(([key,label,detail])=><label key={key} className="setting"><div><b>{label}</b><small>{detail}</small></div><input role="switch" aria-label={label} type="checkbox" checked={key.startsWith('startup_')?prefs[key]!==false:!!prefs[key]} onChange={e=>onChange(key,e.target.checked)}/></label>)}</div><h2>声音</h2><div className="settings-card"><label className="setting"><b>全部静音</b><input role="switch" aria-label="全部静音" type="checkbox" checked={!!prefs.sound_muted} onChange={e=>onChange('sound_muted',e.target.checked)}/></label>{[['xp_volume','经验条',35],['enderman_volume','末影人',22]].map(([key,label,value])=><label className="setting" key={key}><b>{label}</b><input type="range" min="0" max="100" aria-label={label+'音量'} value={prefs[key]??value} onChange={e=>onChange(key,Number(e.target.value))}/><output>{prefs[key]??value}%</output></label>)}</div><h2>随手素材与悬浮贴图</h2><div className="settings-card setting-note"><label htmlFor="drawer-key">随手素材快捷键</label><div className="setting-controls"><input id="drawer-key" aria-label="随手素材快捷键" value={hotkey} onChange={e=>setHotkey(e.target.value)}/><Action onClick={()=>safe(()=>api("drawer_settings",hotkey).then(keyUpdate))}>应用</Action><Action onClick={()=>safe(()=>api("drawer_settings","").then(keyUpdate))}>停用</Action></div><small>{keyStatus} · 输入组合键后应用，冲突时保留原快捷键。</small><Action onClick={()=>safe(()=>api("open_drawer"))}>打开随手素材</Action><Action onClick={()=>safe(()=>api("adjust_stickers"))}>调整贴图（解除固定）</Action><Action onClick={()=>safe(()=>api("recover_stickers"))}>找回屏幕外贴图</Action><Action onClick={()=>safe(()=>api("reclaim_stickers"))}>收回全部贴图</Action><span>最近、常用和全部；共用素材库原件。</span></div><h2>本地保存</h2><div className="settings-card setting-note"><FolderOpen size={21}/><b>素材、原件和草稿</b><code>{info?.library||'正在读取位置…'}</code><span>移动导入前的文件，不影响库内已保存的素材。</span><Action disabled={status.task.active} onClick={()=>safe(()=>api("repair_library"))}>检查并修复素材</Action><Action onClick={()=>safe(async()=>{await navigator.clipboard.writeText(await api("library_repair_report"));setCheckNote('检查结果已复制，可发给开发者；不含账号和完整路径。')})}>复制检查结果</Action>{checkNote&&<small role="status">{checkNote}</small>}<small>保留素材和草稿；重建坏预览，只恢复内容完全相同的随包原件。个人原件缺失或拒绝访问会单独列出。</small><Action disabled={status.task.active} onClick={()=>safe(()=>api("restore_examples"))}>恢复内置示例</Action>{promo&&<><b>宣传片同款</b><small>{promo.main_materials} 份主素材按内容去重入库；原文件同时随包保留。</small><Action disabled={status.task.active} onClick={()=>safe(()=>api("install_promo_projects"))}>导入宣传片可编辑示例</Action><small>15 份草稿和 2 个本地模板，按需导入，不覆盖已有作品。</small></>}</div></div><div><h2>可选组件</h2><p>默认抠图、视频和互通随软件提供。扩展功能按需安装，下载 ZIP 后直接导入。</p><div className="settings-card">{components.map(item=><div className="dependency" key={item.id}><div className="dependency-heading"><div><b>{item.title}</b><small>{item.purpose}</small></div></div><p>{({installed:'已安装',missing:'未安装',incompatible:'已有组件版本不兼容',corrupt:'文件校验失败'})[item.state]} · {item.version}<br/>下载 {(item.bytes/1048576).toFixed(1)} MB · 安装 {(item.unpacked_bytes/1048576).toFixed(1)} MB</p><div className="setting-controls"><Action icon={Download} onClick={()=>safe(()=>api('component_download',item.id))}>下载组件</Action><Action disabled={status.task.active} icon={FolderOpen} onClick={()=>safe(()=>api('component_import',item.id))}>导入已下载组件包</Action></div></div>)}</div><p className="settings-footnote">导入时校验版本和文件，可取消；旧组件与作品保留。导入完成后重新打开对应工具，已加载旧组件时请重启软件。</p><Action disabled={status.task.active} onClick={()=>safe(()=>api('component_verify'))}>校验已安装组件</Action><h2>创作组件</h2><div className="settings-card">{[['video','视频转换','FFmpeg · 视频选段 / GIF / MP4'],['cutout','主体抠图','U²-Net · 本机处理，不上传素材']].map(([key,label,detail])=>{const ready=info&&(key==='video'?info.video:info.cutout&&info.model);return <div className="dependency" key={key}><div className="dependency-heading"><span className={ready?'ready-mark':'missing-mark'}>{ready?<Check size={17}/>:<Download size={17}/>}</span><div><b>{label}</b><small>{detail}</small></div></div><div className="dependency-bottom"><span>{info?(ready?'已找到本地组件':'组件缺失，请完整解压软件'):'正在检查…'}</span><Action disabled={status.task.active} icon={ready?RefreshCw:Download} onClick={()=>ready?refresh():safe(()=>api('prepare_dependency',key))}>{ready?'检查组件':'准备组件'}</Action></div></div>})}</div><div className="settings-footnote">准备时显示进度，可取消；网络失败后可再次点击重试。已有文件直接复用。</div><Action onClick={onAdvanced} icon={Monitor}>兼容与旧草稿入口 <ChevronRight size={15}/></Action>{labEnabled&&<Action icon={Palette} onClick={onLab}>设计候选预览</Action>}</div></div></section>
}

export function CreatePage({items,onEdit,onVideo,onRecord,onLibrary,onResume,onFactory,onDraft}){
 const [drafts,setDrafts]=useState([]),[error,setError]=useState('');
 useEffect(()=>{api('drafts').then(setDrafts).catch(e=>setError(String(e)))},[]);
 const remove=id=>api('drafts',id).then(setDrafts).catch(e=>setError(String(e)));
 return <section className="create-page scroll-zone"><h1>创作</h1><p className="page-lead">静态、动态图层与片段，在同一套工具里编辑。</p><div className="create-actions"><button onClick={onFactory}><Layers size={25}/><b>表情工厂</b><span>模板与动态效果同栏 · 在同一作品继续编辑</span><ChevronRight size={18}/></button><button onClick={onLibrary}><Layers size={25}/><b>从素材开始</b><span>单张编辑，多张自由拼接</span><ChevronRight size={18}/></button><button onClick={onVideo}><Film size={25}/><b>视频选段</b><span>调整范围，生成 GIF 或取帧</span><ChevronRight size={18}/></button><button onClick={onRecord}><Video size={25}/><b>区域录屏</b><span>主动框选区域，录制后选段</span><ChevronRight size={18}/></button></div>{error&&<p className="inline-error">{error}</p>}<div className="create-section"><h2>继续手头的创作</h2><Action icon={ArrowLeft} onClick={onResume}>继续编辑</Action></div><div className="recent-strip">{drafts.map(i=><DraftCard key={i.id} item={i} onOpen={()=>onDraft(i.id)} onRemove={()=>remove(i.id)}/>)}</div></section>
}

function DraftCard({item:i,onOpen,onRemove}){
 const [open,setOpen]=useState(false),button=useRef(null);
 return <Menu.Root open={open} onOpenChange={setOpen}><Menu.Trigger asChild><button ref={button} onClick={e=>{e.preventDefault();onOpen()}} onPointerDown={e=>e.preventDefault()} onContextMenu={e=>{e.preventDefault();setOpen(true)}} onKeyDown={e=>{if(e.key==='ContextMenu'||e.shiftKey&&e.key==='F10'){e.preventDefault();setOpen(true)}else if(e.key==='Enter'||e.key===' '){e.preventDefault();onOpen()}}} aria-label={i.name+'，继续编辑；右键管理草稿'}><img src={i.thumbnail} alt=""/><b>{i.name}</b><small>{i.animated?'动态图层':'静态素材'} · 打开编辑</small></button></Menu.Trigger><Menu.Portal><Menu.Content className="menu" onCloseAutoFocus={e=>{e.preventDefault();button.current?.focus()}}><Menu.Item onSelect={onOpen}>继续编辑</Menu.Item><Menu.Item onSelect={onRemove}>删除此草稿</Menu.Item></Menu.Content></Menu.Portal></Menu.Root>;
}

// A broad invisible drag target surrounds the narrow overlay thumb. Scrolling
// never shifts the content; the native wheel/touchpad behavior remains intact.
export function ScrollThumb({target,always=false,version}){
 const [state,setState]=useState({top:0,height:0,needed:false,active:false});const timer=useRef(null),grab=useRef(null),held=useRef(false),focused=useRef(false),activity=useRef(()=>{});
 useEffect(()=>{const node=target.current;if(!node)return;
  const update=()=>{const h=node.clientHeight,total=node.scrollHeight,thumb=Math.min(h,Math.max(32,h*h/Math.max(1,total)));setState(old=>({...old,top:Math.max(0,node.scrollTop)/Math.max(1,total-h)*(h-thumb),height:thumb,needed:total>h+2}))};
  const active=()=>{clearTimeout(timer.current);update();setState(s=>({...s,active:true}));if(!grab.current&&!held.current&&!focused.current)timer.current=setTimeout(()=>setState(s=>({...s,active:false})),1000)};activity.current=active;
  const edge=e=>{if(e.clientX>=node.getBoundingClientRect().right-18)active()};
  const observer=new ResizeObserver(update);observer.observe(node);node.addEventListener('scroll',active);node.addEventListener('pointermove',edge);update();
  return()=>{observer.disconnect();node.removeEventListener('scroll',active);node.removeEventListener('pointermove',edge);clearTimeout(timer.current)}
 },[version]);
 if(!state.needed)return null;
 const release=()=>{grab.current=null;activity.current()};
 return <div className={'overlay-scroll '+(always||state.active?'visible':'')} role="scrollbar" tabIndex={0} aria-label="素材滚动" aria-controls="library-content" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(state.top/Math.max(1,(target.current?.clientHeight||1)-state.height)*100)}
 onPointerEnter={()=>{held.current=true;activity.current()}} onPointerLeave={()=>{held.current=false;activity.current()}} onFocus={()=>{focused.current=true;activity.current()}} onBlur={()=>{focused.current=false;activity.current()}}
 onKeyDown={e=>{const n=target.current;if(['ArrowDown','ArrowUp','PageDown','PageUp','Home','End'].includes(e.key)){e.preventDefault();n.scrollTop=e.key==='Home'?0:e.key==='End'?n.scrollHeight:n.scrollTop+({ArrowDown:60,ArrowUp:-60,PageDown:n.clientHeight,PageUp:-n.clientHeight})[e.key];activity.current()}}}
 onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);grab.current={y:e.clientY,scroll:target.current.scrollTop};activity.current()}}
 onPointerMove={e=>{if(grab.current)target.current.scrollTop=grab.current.scroll+(e.clientY-grab.current.y)*(target.current.scrollHeight-target.current.clientHeight)/Math.max(1,target.current.clientHeight-state.height)}} onPointerUp={release} onPointerCancel={release}><span style={{height:state.height,transform:`translateY(${state.top}px)`}}/></div>
}
