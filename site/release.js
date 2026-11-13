(() => {
 const repo='https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge';
 const install='下载后完整解压，双击 EmojiBridge.exe。好用的话，欢迎在 GitHub 点个 Star。';
 // A download becomes available only after a real, public Release supplies it.
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),6500);
 fetch('https://api.github.com/repos/NEO-SUNXIAOCHUAN/EmojiBridge/releases/latest',{signal:controller.signal,headers:{Accept:'application/vnd.github+json'}})
 .then(r=>{if(!r.ok)throw new Error('release-not-ready');return r.json()})
 .then(release=>{
  if(release.draft||release.prerelease||!Array.isArray(release.assets))return;
  const safe=a=>a?.browser_download_url?.startsWith(repo+'/releases/download/');
  const core=release.assets.find(a=>/core.*\.zip$/i.test(a.name)&&safe(a));
  if(!core)return;
  const full=release.assets.find(a=>/full-ready.*\.zip$/i.test(a.name)&&safe(a));
  const materials=release.assets.find(a=>/promo-assets.*\.zip$/i.test(a.name)&&safe(a));
  document.querySelectorAll('.nav-download').forEach(a=>a.textContent='下载 Windows 版 ↗');
  const status=document.querySelector('.release-note');if(status)status.textContent=`${release.tag_name} · Windows x64`;
  const button=document.querySelector('#download-info');
  if(button){const a=document.createElement('a');a.className=button.className;a.textContent='下载 Windows 版 ↗';a.href=core.browser_download_url;a.onclick=()=>{const hint=document.querySelector('#download-followup');if(hint){hint.hidden=false;hint.textContent=install}};button.replaceWith(a)}
  const details=document.querySelector('#release-details');if(details){details.hidden=false;details.replaceChildren();const h=document.createElement('h3');h.textContent='选择你的下载';details.append(h);[core,full].filter(Boolean).forEach(asset=>{const a=document.createElement('a');a.href=asset.browser_download_url;a.textContent=`${asset===core?'主程序':'完整包（含模板扩展）'} · ${(asset.size/1048576).toFixed(0)} MB`;a.style.marginRight='24px';details.append(a)});const p=document.createElement('p');p.textContent='两种软件包选一个即可。完整解压后启动，保留同目录运行文件。';details.append(p)}
  if(materials){document.querySelectorAll('.material-download').forEach(a=>a.href=materials.browser_download_url)}
 }).catch(()=>{}).finally(()=>clearTimeout(timer));
})();
