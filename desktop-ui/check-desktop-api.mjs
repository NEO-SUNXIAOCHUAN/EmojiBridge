import {test} from 'node:test';
import assert from 'node:assert/strict';
import {desktopCaller} from './src/desktop-api.mjs';
test('empty early bridge defers concurrent startup calls until actual readiness',async()=>{
 const host=new EventTarget();host.pywebview={api:{}};const call=desktopCaller(host);let hits=0;
 const pending=[call('status'),call('listing','dynamic')];
 await Promise.resolve();assert.equal(hits,0);
 host.pywebview.api={status:()=>{hits++;return 'ready'},listing:filter=>{hits++;return filter}};
 host.dispatchEvent(new Event('pywebviewready'));
 assert.deepEqual(await Promise.all(pending),['ready','dynamic']);assert.equal(hits,2);
});
test('late-mounted caller uses ready bridge; unknown method has an actionable error',async()=>{
 const host=new EventTarget();host.pywebview={api:{status:()=>true}};
 const call=desktopCaller(host);assert.equal(await call('status'),true);
 await assert.rejects(call('missing'),/桌面接口 missing/);
});
