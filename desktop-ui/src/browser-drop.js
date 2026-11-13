// Preserve the real File objects before the drop event's protected data store
// is cleared. pywebview first tries native paths, then asks for these bytes.
const pending=new Map();
function installBridgeFallback(){
 const bridge=window.pywebview;
 if(!bridge||bridge.__emojiFileFallback)return;
 const send=bridge._jsApiCallback;
 bridge._jsApiCallback=function(name,params,id){
  try{return send.call(this,name,params,id)}catch(error){
   // WebView2 refuses AdditionalObjects for browser-created Files that do not
   // exist on disk. pywebview otherwise aborts the event before Python sees it.
   // Forward only the ordinary drop metadata; our bounded File reader supplies
   // the bytes. All other bridge calls retain their original error behavior.
   if(name!=='pywebviewEventHandler'||params?.event?.type!=='drop'||!params.event.emojiDropId||bridge.platform!=='edgechromium')throw error;
   return window.chrome.webview.postMessage([name,bridge.stringify(params),id]);
  }
 };
 bridge.__emojiFileFallback=true;
}
window.addEventListener('pywebviewready',installBridgeFallback,{once:true});
if(window.pywebview)installBridgeFallback();
document.addEventListener('drop',event=>{
 const files=[...(event.dataTransfer?.files||[])];if(!files.length)return;
 const id=crypto.randomUUID();event.emojiDropId=id;
 const timer=setTimeout(()=>pending.delete(id),60000);pending.set(id,{files,timer});
},true);
window.emojiDropRelease=id=>{const item=pending.get(id);if(item)clearTimeout(item.timer);pending.delete(id)};
window.emojiDropImport=async id=>{
 const item=pending.get(id);if(!item)return;
 window.emojiDropRelease(id);const api=window.pywebview.api;
 const notice=text=>{if(window.pocketNotice)window.pocketNotice(text);else api.drop_notice(text)};
 try{
  const batch=await api.drop_begin(item.files.map(f=>({name:f.name,size:f.size,type:f.type})));
  if(!batch.accepted){notice(batch.message);return}
  for(let index=0;index<item.files.length;index++){
   const file=item.files[index];let error='';
   try{
    for(let offset=0;offset<file.size;offset+=batch.chunk_size){
     const bytes=new Uint8Array(await file.slice(offset,offset+batch.chunk_size).arrayBuffer());
     let binary='';for(let n=0;n<bytes.length;n+=8192)binary+=String.fromCharCode(...bytes.subarray(n,n+8192));
     await api.drop_chunk(batch.token,index,offset,btoa(binary));
    }
   }catch(e){error='无法读取拖入的文件数据：'+String(e.message||e)}
   // Cancellation/expired tokens reject here too; never begin later files.
   await api.drop_finish(batch.token,index,error);
  }
 }catch(e){notice('拖入未完成：'+String(e.message||e))}
};
