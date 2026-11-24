const CACHE='smartfactory-shell-v3';
const SHELL=['/login','/static/style.css','/static/app.js','/manifest.webmanifest'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
 const u=new URL(e.request.url);
 if(e.request.method==='GET' && e.request.mode==='navigate'){
  e.respondWith(fetch(e.request).then(r=>{if(r.ok&&u.pathname==='/')caches.open(CACHE).then(c=>c.put('/',r.clone()));return r}).catch(()=>caches.match('/')||caches.match('/login')));
 } else if(e.request.method==='GET' && (u.pathname.startsWith('/static/')||u.pathname==='/manifest.webmanifest')){
  e.respondWith(caches.match(e.request).then(c=>c||fetch(e.request).then(r=>{const copy=r.clone();caches.open(CACHE).then(x=>x.put(e.request,copy));return r})));
 }
});
