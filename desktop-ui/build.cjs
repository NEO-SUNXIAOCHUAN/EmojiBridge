const fs=require('fs'),path=require('path');
const out=path.resolve(__dirname,'../assets/desktop');fs.mkdirSync(out,{recursive:true});
require('esbuild').buildSync({entryPoints:[path.join(__dirname,'src/main.jsx')],bundle:true,minify:true,sourcemap:false,outfile:path.join(out,'main.js'),target:'chrome110',jsx:'automatic',legalComments:'eof'});
fs.writeFileSync(path.join(out,'index.html'),'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EmojiBridge</title><link rel="stylesheet" href="/main.css"><div id="root"></div><script src="/main.js"></script></html>');
require('esbuild').buildSync({entryPoints:[path.join(__dirname,'src/pocket-entry.js')],bundle:true,minify:true,outfile:path.join(out,'pocket.js'),target:'chrome110',legalComments:'eof'});
for(const name of ['pocket','edge'])fs.writeFileSync(path.join(out,name+'.html'),'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EmojiBridge 随手素材</title><link rel="stylesheet" href="/pocket.css"><div id="root"></div><script src="/pocket.js"></script></html>');
require('esbuild').buildSync({entryPoints:[path.join(__dirname,'src/overlay.jsx')],bundle:true,minify:true,outfile:path.join(out,'overlay.js'),target:'chrome110',jsx:'automatic',legalComments:'eof'});
fs.writeFileSync(path.join(out,'overlay.html'),'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EmojiBridge 桌面工具</title><link rel="stylesheet" href="/overlay.css"><div id="root"></div><script src="/overlay.js"></script></html>');
// Distribute actual dependency notices beside the bundle, including transitive code.
const licenses=[];const seen=new Set();
function collect(dir){let info;try{info=JSON.parse(fs.readFileSync(path.join(dir,'package.json')))}catch{return}
 const id=info.name+'@'+info.version;if(seen.has(id))return;seen.add(id);
 for(const file of fs.readdirSync(dir).filter(n=>/^licen[cs]e(?:\.|$)/i.test(n))){try{licenses.push('\n'+id+'\n'+fs.readFileSync(path.join(dir,file),'utf8'))}catch{}}
 for(const name of Object.keys(info.dependencies||{})){try{collect(path.dirname(require.resolve(name+'/package.json',{paths:[dir]})))}catch{try{let p=path.dirname(require.resolve(name,{paths:[dir]}));while(!fs.existsSync(path.join(p,'package.json')))p=path.dirname(p);collect(p)}catch{}}}
}
for(const name of ['react','react-dom','motion','@radix-ui/react-dialog','@radix-ui/react-dropdown-menu','lucide-react','liquid-glass-react']){let p=path.dirname(require.resolve(name));while(!fs.existsSync(path.join(p,'package.json')))p=path.dirname(p);collect(p)}
licenses.push(fs.readFileSync(path.join(__dirname,'src/pocket-motion/NOTICE.md'),'utf8'));
licenses.push(fs.readFileSync(path.join(__dirname,'src/startup-v10/NOTICE.md'),'utf8'));
fs.writeFileSync(path.join(out,'THIRD_PARTY.txt'),licenses.join('\n'));
