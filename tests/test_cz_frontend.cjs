const {test}=require('node:test');
const assert=require('node:assert/strict');
const radar=require('../scripts/cz-radar.js');
const fs=require('node:fs');
const vm=require('node:vm');
const now=Date.parse('2025-01-01T01:00:00Z');
const post={id:'2000000000000000001',author:'cz_binance',text:'Buy BTC',published_at:'2025-01-01T00:50:00Z',first_seen_at:'2025-01-01T00:55:00Z',source:'twscrape',analysis:{level:'explicit',summary:'test',reasons:[]}};
const snapshot=()=>({schema_version:1,username:'cz_binance',snapshot_id:'abc',status:'ok',generated_at:'2025-01-01T00:59:00Z',sources:{},posts:[{...post}]});
test('large IDs remain strings; malformed IDs and schemas rejected',()=>{
  assert.equal(radar.validate(snapshot()).posts[0].id,post.id);
  for(const patch of [{id:'<script>'},{id:2000000000000000001},{author:'spoof'},{first_seen_at:'bad'}]){
    const s=snapshot();s.posts[0]={...post,...patch};assert.throws(()=>radar.validate(s));
  }
});
test('failed live prices never advance score or price timestamps',async()=>{
  const html=fs.readFileSync(require('node:path').join(__dirname,'../index.html'),'utf8');
  const code=html.slice(html.indexOf('async function refreshCrypto(){'),html.indexOf('\nfunction renderAll(){'));
  const btn={disabled:false};
  const data={fetched_at:'2025-01-01T00:00:00Z',assets:{BTC_USDT:{price:100,score:60}},fng:{value:20,date:'2024-12-31'}};
  const context=vm.createContext({DATA:data,CFG:{watchlist:{crypto:['BTC_USDT']}},$:()=>btn,
    fetch:async()=>{throw Error('network unavailable');},AbortController,setTimeout:()=>1,clearTimeout:()=>{},renderAll:()=>{}});
  await vm.runInContext(code+'\nrefreshCrypto();',context);
  assert.equal(data.fetched_at,'2025-01-01T00:00:00Z');
  assert.equal(data.assets.BTC_USDT.price,100);
  assert.equal(data.assets.BTC_USDT.price_updated_at,undefined);
  assert.match(data.live_refresh_message,/刷新失败/);
});
test('a quiet account is not stale; collector time governs status',()=>{
  const s=snapshot();s.posts[0].published_at='2024-01-01T00:00:00Z';
  assert.equal(radar.status(s,now), 'ok');
  s.generated_at='2025-01-01T00:00:00Z';assert.equal(radar.status(s,now), 'stale');
  s.status='unconfigured';assert.equal(radar.status(s,now), 'unconfigured');
});
test('no repeated, edited, backfilled or degraded toast',()=>{
  const started=now-600000;
  assert.equal(radar.notices(snapshot(),new Set(),started,now).length,1);
  assert.equal(radar.notices(snapshot(),new Set([post.id]),started,now).length,0);
  for(const patch of [{edited:true},{backfill:true},{source:'rss'},{published_at:'2024-01-01T00:00:00Z'}]){
    const s=snapshot();s.posts[0]={...post,...patch};assert.equal(radar.notices(s,new Set(),started,now).length,0);
  }
  const s=snapshot();s.status='degraded';assert.equal(radar.notices(s,new Set(),started,now).length,0);
});
