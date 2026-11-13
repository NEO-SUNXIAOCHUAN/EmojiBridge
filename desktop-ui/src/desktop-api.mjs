// pywebview creates api={} before populating its functions. Wait for its
// completion event, not merely the existence of that intermediate object.
export function desktopCaller(host) {
 let ready;
 return async (name,...args)=>{
  if(typeof host.pywebview?.api?.status!=='function'){
   ready??=new Promise(resolve=>host.addEventListener('pywebviewready',resolve,{once:true}));
   await ready;
  }
  const method=host.pywebview?.api?.[name];
  if(typeof method!=='function')throw new Error(`桌面接口 ${name} 尚不可用，请重新打开软件。`);
  try{return await method(...args)}catch(error){
   const message=String(error?.message||error).replace(/wxid_[A-Za-z0-9_-]+/g,'[微信账号]').replace(/(?:[a-z]:[\\/]|\\\\)[^\r\n'"<>]+/gi,'[本机路径]');
   throw new Error(message);
  }
 };
}
