// One voice per family. Audio is presentation only, never a task dependency.
const voices=new Map();
let settings={};
export function configureSounds(value){settings=value||{};for(const [family,v] of voices){v.audio.volume=volume(family)*v.gain;if(settings.sound_muted)stopSound(family)}}
function volume(family){return Math.max(0,Math.min(100,settings[family+'_volume']??(family==='xp'?35:22)))/100}
export function stopSound(family){const v=voices.get(family);if(v){voices.delete(family);v.audio.pause();v.audio.removeAttribute('src');v.audio.load()}}
export function playSound(family,name,{loop=false,gain=1}={}){
 stopSound(family);if(settings.sound_muted||volume(family)===0||document.hidden||window.__emojiHostHidden||window.__emojiClosing)return;
 const audio=new Audio('/motion/audio/'+family+'/'+name+'.wav');const voice={audio,gain};voices.set(family,voice);
 audio.loop=loop;audio.playbackRate=1;audio.volume=volume(family)*gain;
 audio.onended=()=>{if(voices.get(family)===voice)voices.delete(family)};
 audio.onerror=audio.onended;audio.play().catch(()=>{if(voices.get(family)===voice)stopSound(family)});
}
for(const event of ['pagehide','emoji-host-hidden','visibilitychange'])window.addEventListener(event,()=>{if(event==='pagehide'||document.hidden||window.__emojiHostHidden)for(const key of [...voices.keys()])stopSound(key)});
window.addEventListener('emoji-closing',()=>{for(const key of [...voices.keys()])stopSound(key);for(const a of document.querySelectorAll('audio,video'))a.pause()});
