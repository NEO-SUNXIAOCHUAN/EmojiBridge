// One ordered queue per window, shared by the library and bridge surfaces.
// A slow preparation must finish before a later request writes the clipboard.
let tail=Promise.resolve();
export function queueClipboard(work){
 const result=tail.then(work);
 tail=result.catch(()=>{});
 return result;
}
