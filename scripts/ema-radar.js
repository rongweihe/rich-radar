/* 均线雷达使用独立数据与刷新状态，避免趋势信号影响原来的恐慌评分。 */
(function(root){
  'use strict';
  const DAY=86400000;

  function emaSeries(closes, period){
    const values=Array(closes.length).fill(null);
    if(closes.length<period)return values;
    // 与服务端使用相同的 SMA 种子和递推公式，保证离线快照与浏览器结果一致。
    values[period-1]=closes.slice(0,period).reduce((a,b)=>a+b,0)/period;
    const alpha=2/(period+1);
    for(let i=period;i<closes.length;i++)values[i]=closes[i]*alpha+values[i-1]*(1-alpha);
    return values;
  }

  function analyze(rowsAll,kind){
    const byDay=new Map();
    for(const row of rowsAll){
      if(row.done!==true)continue;
      const date=new Date(row.d+'T00:00:00Z');
      if(!/^\d{4}-\d{2}-\d{2}$/.test(row.d)||!Number.isFinite(date.getTime())||date.toISOString().slice(0,10)!==row.d)throw Error('日 K 日期无效');
      if(!Number.isFinite(row.c)||row.c<=0)throw Error('已收盘 K 线价格无效');
      byDay.set(row.d,row);
    }
    const rows=[...byDay.values()].sort((a,b)=>a.d.localeCompare(b.d));
    if(!rows.length)throw Error('没有已收盘日 K');
    // 加密每天都有日 K；缺失日期不能被当作连续站上均线的天数。
    if(kind==='crypto'&&rows.some((r,i)=>i>0&&(Date.parse(r.d)-Date.parse(rows[i-1].d))/DAY!==1))throw Error('日 K 历史存在缺口');
    const closes=rows.map(r=>r.c), fast=emaSeries(closes,20), slow=emaSeries(closes,200), last=rows.length-1;
    let state='insufficient',count=0,lowerBound=false,crossed=false,since=null,calendarDays=0;
    if(slow[last]!=null){
      state=fast[last]>slow[last]?'above':fast[last]<slow[last]?'below':'equal';
      if(state==='above'){
        let start=last;
        while(start>=199&&fast[start]>slow[start])start--;
        count=last-start;
        // 没有看到前一次非上方状态时，只能确认持续天数的下界，不能宣称当天上穿。
        lowerBound=start<199; since=rows[start+1].d; crossed=count===1&&!lowerBound;
        calendarDays=(Date.parse(rows[last].d)-Date.parse(since))/DAY+1;
      }
    }
    return {kind,last_bar:rows[last].d,first_bar:rows[0].d,bars:rows.length,close:closes[last],
      ema20:fast[last],ema200:slow[last],state,gap_pct:slow[last]?(fast[last]/slow[last]-1)*100:null,
      above_bars:count,calendar_days:calendarDays,above_since:since,lower_bound:lowerBound,just_crossed:crossed,
      chart:rows.slice(Math.max(199,last-59)).map((r,i)=>({d:r.d,ema20:fast[Math.max(199,last-59)+i],ema200:slow[Math.max(199,last-59)+i]}))};
  }

  function gateRows(data,now=Date.now()){
    if(!Array.isArray(data))throw Error('Gate 返回无效 K 线数据');
    return data.map(k=>({d:new Date(Number(k[0])*1000).toISOString().slice(0,10),c:Number(k[2]),
      done:String(k[7]).toLowerCase()==='true'&&Number(k[0])*1000+DAY<=now}));
  }

  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=value=>Number.isFinite(value)?value.toLocaleString('en-US',{maximumFractionDigits:value>=1000?2:4}):'—';
  const names={BTC_USDT:'Bitcoin',SOL_USDT:'Solana',LINK_USDT:'Chainlink',AAVE_USDT:'Aave',NEAR_USDT:'NEAR Protocol',ZEC_USDT:'Zcash',UNI_USDT:'Uniswap',CRCL:'Circle'};
  let config,snapshot={assets:{},errors:[]},pending=null,loading=false,filter='all',snapshotError='';
  const $=s=>document.querySelector(s);

  async function fetchJSON(url){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
    try{
      const response=await fetch(url,{signal:controller.signal,cache:'no-store'});
      if(!response.ok)throw Error('HTTP '+response.status);
      return await response.json();
    }finally{clearTimeout(timer);}
  }

  function isStale(asset){
    // 美股含周末休市，给予较宽窗口；仍始终展示实际最后收盘日期。
    return !asset.last_bar||Date.now()-Date.parse(asset.last_bar+'T00:00:00Z')>(asset.kind==='stock'?5:2)*DAY;
  }

  function chart(asset,symbol){
    const points=(asset.chart||[]).filter(p=>Number.isFinite(p.ema20)&&Number.isFinite(p.ema200));
    if(points.length<2)return '<div class="ema-chart-empty">均线历史不足，暂不绘图</div>';
    const values=points.flatMap(p=>[p.ema20,p.ema200]),min=Math.min(...values),max=Math.max(...values),range=max-min||1;
    const path=key=>points.map((p,i)=>`${i?'L':'M'}${(4+i/(points.length-1)*292).toFixed(2)},${(66-(p[key]-min)/range*58).toFixed(2)}`).join(' ');
    return `<svg class="ema-chart" viewBox="0 0 300 74" role="img" aria-label="${esc(symbol)} 最近 ${points.length} 根日 K 的 EMA20 与 EMA200"><path d="M4 68H296" stroke="var(--line)"/><path d="${path('ema200')}" fill="none" stroke="var(--blue)" stroke-width="2" stroke-dasharray="4 3"/><path d="${path('ema20')}" fill="none" stroke="var(--green)" stroke-width="2"/></svg>`;
  }

  function render(){
    const symbols=[...config.crypto,...config.stocks];
    const errors=new Map((snapshot.errors||[]).map(e=>[e.symbol,e.message]));
    const active=symbols.filter(s=>snapshot.assets[s]?.state==='above'&&!isStale(snapshot.assets[s])&&!errors.has(s));
    const unresolved=symbols.filter(s=>!snapshot.assets[s]||snapshot.assets[s].state==='insufficient'||isStale(snapshot.assets[s])||errors.has(s));
    const aboveNames=active.map(s=>s.replace('_USDT',''));
    $('#emaSummary').classList.toggle('has-signal',active.length>0);
    // 数据未知或刷新失败不能被解释为“没有上方信号”，汇总需明确显示待确认数量。
    $('#emaSummary').innerHTML=`<span class="ema-summary-icon" aria-hidden="true">${active.length?'↗':'◎'}</span><div><strong>${active.length?`${active.length} / ${symbols.length} 个资产 EMA20 高于 EMA200`:unresolved.length?'均线信号待确认':'等待均线上方信号'}</strong><p>${active.length?esc(aboveNames.join(' · '))+' · 已收盘日 K 确认':unresolved.length?'等待完整或最新日 K；已有快照见下方卡片':'当前已确认数据暂无上方信号'}${unresolved.length?' · '+unresolved.length+' 项待确认':''}${errors.size?' · '+errors.size+' 项刷新失败':''}</p></div>`;
    const button=$('#emaRefreshBtn'); button.disabled=loading; button.textContent=loading?'刷新日 K 中…':'↻ 刷新均线';
    $('#emaStatus').textContent=loading?'正在读取加密日 K；CRCL 使用每日自动更新快照':snapshotError||'加密打开页面时更新 · CRCL 每日快照 · 以各卡片收盘日期为准';
    $('#emaCards').innerHTML=symbols.filter(s=>filter!=='above'||snapshot.assets[s]?.state==='above').map(sym=>{
      const a=snapshot.assets[sym],symbol=sym.replace('_USDT',''),kind=config.stocks.includes(sym)?'stock':'crypto';
      const error=errors.get(sym),stale=a&&isStale(a),valid=a&&a.state!=='insufficient';
      // 过期或抓取失败的快照保留数值，但不作为当前有效的绿色提示信号。
      const confirmed=valid&&a.state==='above'&&!stale&&!error;
      const label=!a?(loading?'加载中':'数据不可用'):!valid?'历史不足 200 根':a.state==='above'?(confirmed?(a.just_crossed?'↗ 最新收盘上穿':'↗ EMA20 在上方'):'快照 · EMA20 在上方'):a.state==='below'?'EMA20 在下方':'两线持平';
      let duration='等待上穿 EMA200',detail='以最新完整日 K 确认趋势';
      if(!a){duration='—';detail=error?'抓取失败，可点击刷新重试':'暂无快照，联网后刷新';}
      else if(!valid){duration=`${a.bars} / 200 根日 K`;detail='历史不足，不生成趋势信号';}
      else if(a.state==='above'){
        const prefix=a.lower_bound?'至少 ':'';
        duration=`已在上方 ${prefix}${a.above_bars} ${kind==='stock'?'个交易日':'天'}`;
        detail=(a.lower_bound?'窗口内未见上穿 · 自 ': '上穿日期 ')+a.above_since;
        if(kind==='stock')detail+=` · 跨 ${prefix}${a.calendar_days} 个自然日`;
      }else if(a.state==='equal'){duration='EMA20 = EMA200';detail='相等时不触发上方信号';}
      const badge=error?'刷新失败 · 保留快照':stale?'快照较旧':'';
      const gap=Number.isFinite(a?.gap_pct)?`${a.gap_pct>0?'+':''}${a.gap_pct.toFixed(2)}%`:'—';
      return `<article class="ema-card ${confirmed?'signal':''}" data-ema-symbol="${esc(sym)}">
        <div class="ema-card-head"><div class="aname">${esc(symbol)}<small>${esc(names[sym]||symbol)} · ${kind==='stock'?'美股 / USD':'加密 / USDT'}</small></div><span class="pill ${confirmed?'g':valid&&a.state==='below'?'a':''}">${label}</span></div>
        <div class="ema-values"><div><span>EMA 20</span><strong>${num(a?.ema20)}</strong></div><div><span>EMA 200</span><strong>${num(a?.ema200)}</strong></div></div>
        <div class="ema-duration">${esc(duration)}</div><div class="ema-detail">${esc(detail)}</div>
        ${a?chart(a,symbol):'<div class="ema-chart-empty">等待日 K 数据</div>'}
        <div class="ema-gap"><span>两线差幅 <b class="${confirmed?'chg-pos':''}">${gap}</b></span><span>收盘 ${num(a?.close)}</span></div>
        <div class="ema-meta">收盘日 ${esc(a?.last_bar||'—')}${badge?` · <span class="flag">${badge}</span>`:''}<br>${esc(a?.source||(kind==='stock'?'Yahoo Finance · 每日快照':'Gate.io · 现货日 K'))}${error?`<br><span class="ema-error">${esc(error)}</span>`:''}</div>
      </article>`;
    }).join('')||'<div class="ema-no-results">暂无 EMA20 在上方的资产，切换「全部」查看。</div>';
  }

  function refresh(){
    if(pending)return pending;
    // 共用进行中的刷新任务，避免连点按钮造成旧响应覆盖新数据。
    pending=(async()=>{
      loading=true; render();
      try{
        // CRCL 无浏览器 CORS，重新读取服务端快照；失败时保留原值和原日期。
        try{
          const saved=await fetchJSON('data/ema.json');
          if(!saved.assets||typeof saved.assets!=='object'||!Array.isArray(saved.errors))throw Error('快照格式无效');
          snapshot=saved;snapshotError='';
        }catch(error){snapshotError='快照读取失败，保留已有数据；加密继续尝试在线刷新';}
        await Promise.all(config.crypto.map(async sym=>{
          try{
            const data=await fetchJSON(`https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=${encodeURIComponent(sym)}&interval=1d&limit=${config.history_bars}`);
            const result=analyze(gateRows(data),'crypto');
            snapshot.assets[sym]={...result,source:'Gate.io · 现货日 K · USDT',fetched_at:new Date().toISOString()};
            snapshot.errors=(snapshot.errors||[]).filter(e=>e.symbol!==sym);
          }catch(error){
            snapshot.errors=(snapshot.errors||[]).filter(e=>e.symbol!==sym);
            snapshot.errors.push({symbol:sym,message:error.name==='AbortError'?'请求超时，请重试':error.message});
          }
          render();
        }));
      }finally{loading=false;pending=null;render();}
    })();
    return pending;
  }

  function mount(cfg){
    config=cfg.ema_radar;
    snapshot=JSON.parse($('#__ema').textContent);
    $('#emaRefreshBtn').onclick=refresh;
    $('#emaTabs').onclick=event=>{
      const tab=event.target.closest('button[data-ema-filter]');if(!tab)return;
      filter=tab.dataset.emaFilter;
      $('#emaTabs').querySelectorAll('button').forEach(b=>{const on=b===tab;b.classList.toggle('on',on);b.setAttribute('aria-pressed',String(on));});
      render();
    };
    render();refresh();
  }

  const api={emaSeries,analyze,gateRows,mount,refresh};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.EMARadar=api;
})(typeof globalThis!=='undefined'?globalThis:this);
