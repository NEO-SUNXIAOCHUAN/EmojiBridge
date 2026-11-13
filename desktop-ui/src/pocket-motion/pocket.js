(function(global){
  'use strict';
  const paths={bridge:'M4 15V8.5a3 3 0 0 1 6 0V15m4-6V8.5a3 3 0 0 1 6 0V15M4 11h16M7 18h10',pin:'m9 3 6 0-1 5 3 3v2H7v-2l3-3-1-5Zm3 10v7',collapse:'m7 10 5 5 5-5',expand:'m7 14 5-5 5 5',close:'m6 6 12 12M18 6 6 18',search:'M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13Zm5-1 4.5 4.5',star:'m12 3 2.7 5.5 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1-4.4-4.3 6.1-.9Z',check:'m5 12 4 4 10-10',add:'M12 5v14M5 12h14',sticker:'M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8l-6 6H6a2 2 0 0 1-2-2V6Zm10 14v-4a2 2 0 0 1 2-2h4',copy:'M9 9h11v11H9V9ZM5 15H4V4h11v1',drag:'M12 3v18M3 12h18m-12-6 3-3 3 3m-9 3-3 3 3 3m3 3 3 3 3-3m3-9 3 3-3 3',tray:'M4 8h16l2 10H2L4 8Zm-1 6h5l2 3h4l2-3h5M12 3v8m-3-3 3 3 3-3',grid:'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z'};
  const svg=(name)=>'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="'+paths[name]+'"/></svg>';
  const esc=(s)=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const safeImage=(value)=>{const s=String(value||'');return /^(data:image\/(png|jpeg|gif|webp|svg\+xml);|blob:|https?:|file:|assets\/|\.\.?\/)/i.test(s)?s:'';};
  const fileData=(file)=>new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve({name:file.name,type:file.type,data:r.result});r.onerror=()=>reject(new Error('文件读取失败'));r.readAsDataURL(file);});
  function mount(target,options={}){
    const root=typeof target==='string'?document.querySelector(target):target;
    if(!root)throw new Error('Pocket mount target is missing');
    const host=options.host||global.EmojiBridgePocketHost||{};
    let items=[...(options.items||[])],selected=new Set(),tab='recent',query='',pinned=false,collapsed=false,toastTimer,dragDepth=0,destroyed=false;
    root.innerHTML=`<section class="eb-pocket" aria-label="随手素材"><header class="eb-header"><div class="eb-logo">${svg('bridge')}</div><div class="eb-title-wrap"><div class="eb-title">随手素材</div><div class="eb-subtitle">EMOJIBRIDGE</div></div><div class="eb-window-actions"><button class="eb-icon-button eb-pin" title="临时置顶" aria-label="临时置顶" aria-pressed="false">${svg('pin')}</button><button class="eb-icon-button eb-collapse" title="收起" aria-label="收起" aria-expanded="true">${svg('collapse')}</button><button class="eb-icon-button danger eb-close" title="关闭素材窗" aria-label="关闭素材窗">${svg('close')}</button></div></header><div class="eb-body"><div class="eb-search-wrap"><label class="eb-search">${svg('search')}<input type="search" placeholder="找一张表情…" aria-label="搜索素材"><span class="eb-key">⌘ /</span></label></div><div class="eb-nav"><div class="eb-tabs" role="tablist" aria-label="素材范围"><button class="eb-tab active" role="tab" aria-selected="true" data-tab="recent" title="最近添加的 24 项">最近</button><button class="eb-tab" role="tab" aria-selected="false" data-tab="favorite">常用</button><button class="eb-tab" role="tab" aria-selected="false" data-tab="all">全部</button></div><span class="eb-count"></span></div><div class="eb-view"><div class="eb-grid" role="listbox" aria-label="素材列表" aria-multiselectable="true"></div><div class="eb-empty" hidden>${svg('grid')}<span>还没有找到素材</span><small>换个词，或者拖入一张图片</small></div></div><footer class="eb-footer"></footer></div><div class="eb-drop-overlay"><div class="eb-drop-symbol">${svg('tray')}</div><div class="eb-drop-title">松手，加入素材库</div><div class="eb-drop-copy">图片与 GIF，原样收好</div></div><div class="eb-toast" role="status" aria-live="polite"></div><input class="eb-hidden-input" type="file" multiple accept="image/png,image/jpeg,image/gif,image/webp"></section>`;
    const shell=root.querySelector('.eb-pocket'),grid=root.querySelector('.eb-grid'),empty=root.querySelector('.eb-empty'),footer=root.querySelector('.eb-footer'),search=root.querySelector('input[type=search]'),input=root.querySelector('input[type=file]'),toastEl=root.querySelector('.eb-toast');
    root.querySelector('.eb-key').textContent=/Mac|iPhone|iPad/.test(navigator.platform)?'⌘ /':'Ctrl /';
    const toast=(message)=>{clearTimeout(toastTimer);toastEl.textContent=message;toastEl.classList.add('visible');toastTimer=setTimeout(()=>toastEl.classList.remove('visible'),2700);};
    async function call(name,...args){if(typeof host[name]!=='function'){throw new Error('这个操作需要桌面端支持');}return await host[name](...args);}
    const currentItems=()=>items.filter(i=>tab!=='favorite'||i.favorite).filter(i=>!query||host.filterChanged||(i.name+' '+(i.format||'')).toLowerCase().includes(query)).sort((a,b)=>tab==='recent'?String(b.addedAt||'').localeCompare(String(a.addedAt||'')):0);
    const getSelection=()=>items.filter(i=>selected.has(i.id));
    let footerKey="";
    function renderFooter(){
      const picked=getSelection();const key=JSON.stringify(picked.map(i=>[i.id,i.name,i.src,i.format]));if(key===footerKey)return;footerKey=key;
      if(!picked.length){footer.innerHTML=`<div class="eb-footer-hint">${svg('tray')}<span>拖入收集 · 选中后即可使用</span></div><button class="eb-add" title="导入图片" aria-label="导入图片">${svg('add')}</button>`;footer.querySelector('.eb-add').onclick=()=>call('chooseImport').catch(e=>toast(e.message));return;}
      const first=picked[0];footer.innerHTML=`<div class="eb-selection"><img class="eb-selection-thumb" src="${esc(safeImage(first.src))}" alt=""><div><div class="eb-selection-name">${esc(picked.length===1?first.name:('已选 '+picked.length+' 项'))}</div><div class="eb-selection-meta">${esc(picked.length===1?(first.format||'图片'): '可批量悬浮')}</div></div></div><button class="eb-action primary eb-open-sticker">${svg('sticker')}贴到屏幕</button><button class="eb-action eb-action-square eb-copy" title="复制素材" aria-label="复制素材" ${picked.length!==1?'disabled':''}>${svg('copy')}</button><button class="eb-action eb-action-square eb-drag" title="拖出使用" aria-label="拖出使用" ${picked.length!==1?'disabled':''} draggable="${picked.length===1}">${svg('drag')}</button>`;
      footer.querySelector('.eb-open-sticker').onclick=async()=>{try{for(const item of picked)await call('openSticker',item);toast(host.capabilities?.nativeWindow?'贴图已放到屏幕上':'已在当前页面打开贴图');}catch(e){toast(e.message);}};
      footer.querySelector('.eb-copy').onclick=async()=>{try{const result=await call('copyItem',first);toast(result?.message||'已复制');}catch(e){toast(e.message);}};
      const dragBtn=footer.querySelector('.eb-drag');
      if(host.capabilities?.nativeWindow&&!host.capabilities?.nativeDrag){dragBtn.disabled=true;dragBtn.draggable=false;dragBtn.title='桌面原件拖出待接入';dragBtn.setAttribute('aria-label','桌面原件拖出待接入');}
      else{dragBtn.ondragstart=e=>startDrag(e,first);dragBtn.onmouseenter=()=>call('prepareItem',first).catch(e=>toast(e.message));dragBtn.onclick=()=>toast('按住此按钮，拖到接收图片的窗口');}
    }
    function choose(id,event){if(event.ctrlKey||event.metaKey){selected.has(id)?selected.delete(id):selected.add(id);}else selected=new Set(selected.has(id)&&selected.size===1?[]:[id]);grid.querySelectorAll('.eb-item').forEach(el=>{const on=selected.has(el.dataset.id);el.classList.toggle('selected',on);el.setAttribute('aria-selected',String(on));});renderFooter();}
    function render(){
      if(destroyed)return;const list=currentItems();root.querySelector('.eb-count').textContent=list.length+' 项素材';empty.hidden=list.length>0;empty.style.display=list.length?'none':'flex';grid.style.display=list.length?'grid':'none';
      const view=root.querySelector('.eb-view'),oldScroll=view.scrollTop;
      const anchor=[...grid.children].find(e=>e.offsetTop+e.offsetHeight>=oldScroll),anchorId=anchor?.dataset.id,anchorDelta=anchor?anchor.offsetTop-oldScroll:0;
      const nodes=new Map([...grid.children].map(el=>[el.dataset.id,el]));
      list.forEach((item,index)=>{
        let el=nodes.get(item.id);nodes.delete(item.id);
        if(!el){
          el=document.createElement('div');el.className='eb-item';el.tabIndex=0;el.setAttribute('role','option');el.dataset.id=item.id;
          el.innerHTML=`<img alt="" loading="lazy" decoding="async"><span class="eb-check">${svg('check')}</span><button class="eb-star">${svg('star')}</button><span class="eb-format"></span><button class="eb-retry" hidden>预览重试</button>`;
          el.onclick=e=>choose(el._item.id,e);el.onkeydown=e=>{if(e.target!==el)return;if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(el._item.id,e)}};
          el.ondblclick=async()=>{try{await call('openSticker',el._item)}catch(e){toast(e.message)}};
          el.draggable=!(host.capabilities?.nativeWindow&&!host.capabilities?.nativeDrag);el.ondragstart=e=>startDrag(e,el._item);
          // Prepare only after a short intentional hover, never every crossed card.
          let prepare;el.onpointerenter=()=>{prepare=setTimeout(()=>call('prepareItem',el._item).catch(()=>{}),160)};
          el.onpointerleave=()=>clearTimeout(prepare);
          const img=el.querySelector('img'),retry=el.querySelector('.eb-retry');
          img.onerror=()=>{el.classList.add('preview-failed');retry.hidden=false};img.onload=()=>{el.classList.remove('preview-failed');retry.hidden=true};
          retry.onclick=e=>{e.stopPropagation();img.src=safeImage(el._item.src)+(el._item.src.includes('?')?'&':'?')+'retry='+Date.now()};
          el.querySelector('.eb-star').onclick=async e=>{e.stopPropagation();const item=el._item,desired=!item.favorite;try{await call('setFavorite',item.id,desired);item.favorite=desired;render()}catch(e){toast(e.message)}};
        }
        el._item=item;el.classList.toggle('selected',selected.has(item.id));el.setAttribute('aria-selected',String(selected.has(item.id)));el.setAttribute('aria-label',item.name);el.title=item.name;
        const img=el.querySelector('img'),src=safeImage(item.src);if(img.getAttribute('src')!==src&&!img.src.includes('retry='))img.src=src;
        const star=el.querySelector('.eb-star');star.classList.toggle('favorite',!!item.favorite);star.title=item.favorite?'取消常用':'加入常用';star.setAttribute('aria-label',star.title);star.setAttribute('aria-pressed',String(!!item.favorite));
        const badge=el.querySelector('.eb-format');badge.textContent=item.format==='GIF'?'GIF':'';badge.hidden=item.format!=='GIF';
        if(grid.children[index]!==el)grid.insertBefore(el,grid.children[index]||null);
      });
      nodes.forEach(el=>el.remove());
      if(oldScroll>0&&anchorId){const kept=[...grid.children].find(el=>el.dataset.id===anchorId);view.scrollTop=kept?kept.offsetTop-anchorDelta:oldScroll}
      renderFooter();
    }
    function startDrag(event,item){
      if(host.capabilities?.nativeWindow&&!host.capabilities?.nativeDrag){event.preventDefault();toast('桌面原件拖出待接入');return;}
      if(host.capabilities?.nativeDrag){event.preventDefault();call('dragItem',item).catch(e=>toast(e.message));return;}
      event.dataTransfer.effectAllowed='copy';event.dataTransfer.setData('text/uri-list',new URL(item.src,document.baseURI).href);event.dataTransfer.setData('text/plain',item.name);if(item.src.startsWith('data:'))event.dataTransfer.setData('DownloadURL',(item.format==='GIF'?'image/gif':'image/png')+':'+item.name+':'+item.src);shell.classList.remove('drag-over');dragDepth=0;
    }
    function setItems(next){items=[...next];selected=new Set([...selected].filter(id=>items.some(i=>i.id===id)));render();}
    function renderTabs(){root.querySelectorAll('.eb-tab').forEach(el=>{const active=el.dataset.tab===tab;el.classList.toggle('active',active);el.setAttribute('aria-selected',String(active));});}
    root.querySelectorAll('.eb-tab').forEach(el=>el.onclick=()=>{tab=el.dataset.tab;renderTabs();host.filterChanged?.(query,tab);render();});
    search.oninput=()=>{query=search.value.trim().toLowerCase();host.filterChanged?.(query,tab);render();};input.onchange=()=>{};
    function nativeToggle(button,method,draw){let desired=false,settled=false,running=false;button.onclick=async()=>{if(button.classList.contains('eb-pin')&&!running)settled=button.getAttribute('aria-pressed')==='true';desired=button.classList.contains('eb-pin')?button.getAttribute('aria-pressed')!=='true':!desired;draw(desired);if(running)return;running=true;try{while(!destroyed&&settled!==desired){const next=desired;await call(method,next);settled=next}}catch(e){desired=settled;draw(settled);toast(e.message)}finally{running=false}};}
    nativeToggle(root.querySelector('.eb-pin'),'setPinned',value=>{pinned=value;const b=root.querySelector('.eb-pin');b.classList.toggle('active',value);b.setAttribute('aria-pressed',String(value));b.title=value?'取消临时置顶':'临时置顶'});
    nativeToggle(root.querySelector('.eb-collapse'),'setCollapsed',value=>{collapsed=value;shell.classList.toggle('collapsed',value);const b=root.querySelector('.eb-collapse');b.innerHTML=svg(value?'expand':'collapse');b.title=value?'展开':'收起';b.setAttribute('aria-label',b.title);b.setAttribute('aria-expanded',String(!value))});
    root.querySelector('.eb-close').onclick=async()=>{try{await call('close');if(!host.capabilities?.nativeWindow){shell.classList.add('closed');const b=document.createElement('button');b.className='eb-reopen';b.textContent='重新打开素材窗';root.appendChild(b);b.onclick=()=>{shell.classList.remove('closed');b.remove();};}}catch(e){toast(e.message);}};
    const isFiles=e=>e.dataTransfer&&[...e.dataTransfer.types].some(t=>t==='Files');
    shell.addEventListener('dragenter',e=>{if(!isFiles(e))return;e.preventDefault();dragDepth++;shell.classList.add('drag-over');});shell.addEventListener('dragover',e=>{if(!isFiles(e))return;e.preventDefault();e.dataTransfer.dropEffect='copy';});shell.addEventListener('dragleave',e=>{if(!isFiles(e))return;dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)shell.classList.remove('drag-over');});shell.addEventListener('drop',e=>{if(!isFiles(e))return;e.preventDefault();dragDepth=0;shell.classList.remove('drag-over');// Native DOM handler receives original filesystem paths.
});
    const keyboard=e=>{if((e.ctrlKey||e.metaKey)&&e.key==='/'){e.preventDefault();search.focus();}else if(e.key==='Escape'&&document.activeElement===search){search.value='';query='';search.blur();host.filterChanged?.(query,tab);render();}};document.addEventListener('keydown',keyboard);
    render();if(!items.length&&typeof host.getItems==='function')call('getItems').then(setItems).catch(e=>toast(e.message));
    return {setItems,getSelection,toast,destroy(){destroyed=true;clearTimeout(toastTimer);document.removeEventListener('keydown',keyboard);root.innerHTML='';}};
  }
  global.EmojiBridgePocket={mount};
})(window);
