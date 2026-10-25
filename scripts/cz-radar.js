/* Independent CZ feed. External content is rendered as text, never feed HTML. */
(function(root){
  'use strict';
  const LEVELS={explicit:'明确买入倾向',opportunity:'逆向机会表达',implicit:'疑似长期暗示',review:'相关表达 · 待核对',none:'未命中',excluded:'已排除'};
  const STATUS={ok:'最近检查正常',degraded:'监控降级 · 覆盖待确认',error:'采集异常 · 保留历史',unconfigured:'尚未配置数据源',disabled:'监控已停用',stale:'检查已过期 · 状态待确认'};
  const CODES={ok:'成功',source_error:'来源请求失败 / 会话可能失效',timeout:'请求超时',empty_response:'空响应，不能确认无新帖',dependency_missing:'采集依赖未安装',partial_feed:'RSS 部分内容不可解析',invalid_items:'部分内容校验失败',cooldown:'失败退避中',unconfigured:'未配置',disabled:'停用'};
  const matched=p=>['explicit','opportunity','implicit','review'].includes(p.analysis.level);
  const validDate=value=>typeof value==='string'&&Number.isFinite(Date.parse(value));
  function validate(data){
    if(!data||data.schema_version!==1||data.username!=='cz_binance'||typeof data.snapshot_id!=='string'||!Array.isArray(data.posts)||data.posts.length>1000||!Object.hasOwn(STATUS,data.status)||!data.sources||typeof data.sources!=='object')throw Error('快照结构无效');
    if(data.generated_at!==null&&!validDate(data.generated_at))throw Error('快照时间无效');
    for(const s of Object.values(data.sources))if(!s||typeof s!=='object')throw Error('来源状态无效');
    for(const p of data.posts){
      if(typeof p.id!=='string'||!/^\d{1,25}$/.test(p.id)||p.author!=='cz_binance'||typeof p.text!=='string'||p.text.length>30000||!validDate(p.published_at)||!validDate(p.first_seen_at)||!p.analysis||!Object.hasOwn(LEVELS,p.analysis.level)||typeof p.analysis.summary!=='string'||!Array.isArray(p.analysis.reasons)||!p.analysis.reasons.every(x=>typeof x==='string'))throw Error('推文结构无效');
    }
    return data;
  }
  function status(data,now=Date.now(),staleMinutes=45){
    if(['unconfigured','disabled'].includes(data.status))return data.status;
    if(!validDate(data.generated_at)||now-Date.parse(data.generated_at)>staleMinutes*60000||Date.parse(data.generated_at)>now+300000)return 'stale';
    return data.status;
  }
  function notices(data,known,started,now=Date.now(),ageMinutes=60){
    if(data.status!=='ok')return [];
    return data.posts.filter(p=>matched(p)&&!known.has(p.id)&&!p.edited&&!p.backfill&&p.source==='twscrape'&&Date.parse(p.first_seen_at)>started&&now-Date.parse(p.published_at)<=ageMinutes*60000);
  }
  function mount(cfg={}){
    const host=document.getElementById('czRadar');
    if(!host||host.dataset.mounted)return;
    host.dataset.mounted='true';
    let data=null,pending=false,filter='signals',loadError='',initialized=false,known=new Set();
    const started=Date.now(),refreshSeconds=Math.max(30,Number(cfg.refresh_seconds)||60);
    const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
    const time=value=>validDate(value)?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Singapore',hour12:false}):'—';
    const heading=el('div','cz-heading'),titles=el('div');
    titles.append(el('div','lab','CZ / SOCIAL SIGNALS'),el('h3','','CZ 言论雷达'));
    const refresh=el('button','btn','↻ 检查最新快照');refresh.type='button';heading.append(titles,refresh);
    const intro=el('p','note','观察 @cz_binance 的机会表达与长期叙述。规则只解释原文线索，不预测上涨；后台约每 15 分钟尝试采集。');
    const health=el('div','cz-health');health.setAttribute('role','status');
    const toast=el('div','cz-toast');toast.setAttribute('role','status');toast.setAttribute('aria-live','polite');toast.hidden=true;
    const controls=el('div','cz-controls'),signals=el('button','btn','仅看命中'),all=el('button','btn','最近原文');
    for(const b of [signals,all])b.type='button';controls.append(signals,all);
    const cards=el('div','cz-grid'),meta=el('div','cz-meta');
    host.replaceChildren(heading,intro,health,toast,controls,cards,meta);
    function render(){
      refresh.disabled=pending;refresh.textContent=pending?'读取快照中…':'↻ 检查最新快照';
      signals.setAttribute('aria-pressed',String(filter==='signals'));all.setAttribute('aria-pressed',String(filter==='all'));
      cards.replaceChildren();meta.replaceChildren();
      if(!data){health.textContent=loadError||'正在读取 CZ 快照…';health.dataset.state='unconfigured';return;}
      const state=status(data,Date.now(),cfg.stale_minutes||45);
      health.dataset.state=loadError?'error':state;
      const count=data.posts.filter(matched).length;
      health.textContent=(loadError?loadError+' · 保留已加载快照':STATUS[state])+` · 保留历史中 ${count} 条命中`;
      if(state==='unconfigured')meta.append(el('p','','配置 GitHub Secret CZ_X_COOKIES 后运行刷新工作流；也可配置已验证的 CZ_RSS_URL。'));
      const rows=(filter==='signals'?data.posts.filter(matched):data.posts).slice(0,30);
      for(const p of rows){
        const card=el('article','cz-card '+(matched(p)?'cz-signal':''));
        const top=el('div','cz-card-top');
        top.append(el('span','cz-badge',LEVELS[p.analysis.level]),el('span','cz-time',time(p.published_at)));
        card.append(top,el('p','cz-text',p.text),el('p','cz-summary',p.analysis.summary));
        const tags=el('div','cz-reasons');
        for(const reason of p.analysis.reasons.slice(0,8))tags.append(el('span','',reason));
        card.append(tags);
        const footer=el('div','cz-card-footer');
        footer.append(el('span','',`${p.source==='twscrape'?'X 时间线':'RSS 二手来源'} · 发现于 ${time(p.first_seen_at)}${p.backfill?' · 历史/补采':''}${p.edited?' · 已编辑':''}${p.text_complete!==true?' · 正文完整性待确认':''}${state!=='ok'?' · 历史快照':''}`));
        const link=el('a','','查看原帖 ↗');link.href='https://x.com/cz_binance/status/'+p.id;link.target='_blank';link.rel='noopener noreferrer';footer.append(link);card.append(footer);cards.append(card);
      }
      if(!rows.length)cards.append(el('div','cz-empty',filter==='signals'?(state==='ok'?'当前保留的原文中暂无规则命中，可切换「最近原文」检查。':'暂无可展示的命中；数据源未就绪或状态待确认，不能据此认定没有新信号。'):'尚无可展示的真实原文。'));
      meta.append(el('p','',`快照生成 ${time(data.generated_at)} · 最近成功读取 ${time(data.last_success_at)} · 时间 UTC+8`));
      for(const [name,s] of Object.entries(data.sources)){
        if(!['twscrape','rss'].includes(name))continue;
        const coverage={baseline:'仅建立初始窗口',overlap:'已与上次窗口衔接',gap:'未衔接上次窗口，可能漏帖',unknown:'无法验证上游完整性'}[s.coverage]||'尚无覆盖记录';
        meta.append(el('p','',`${name}：${CODES[s.code]||'待确认'} · ${coverage}${s.retry_after?' · 下次尝试不早于 '+time(s.retry_after):''}`));
      }
      meta.append(el('p','','手动刷新只读取已发布快照。页面关闭后不发送系统通知；“检查正常”也不保证上游零漏报。'));
    }
    async function refreshFeed(){
      if(pending)return;
      pending=true;render();
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
      try{
        const response=await fetch('data/cz.json',{cache:'no-store',signal:controller.signal});
        if(!response.ok)throw Error('HTTP '+response.status);
        const next=validate(await response.json());
        if(data&&validDate(data.generated_at)&&(!validDate(next.generated_at)||Date.parse(next.generated_at)<Date.parse(data.generated_at)))throw Error('收到较旧快照');
        const fresh=initialized&&status(next,Date.now(),cfg.stale_minutes||45)==='ok'?notices(next,known,started,Date.now(),cfg.alert_max_age_minutes||60):[];
        data=next;loadError='';initialized=true;
        for(const p of next.posts)known.add(p.id);
        if(known.size>2000)known=new Set(next.posts.map(p=>p.id));
        if(fresh.length){toast.textContent=`发现 ${fresh.length} 条新的 CZ 相关表达，请查看原文和命中依据。`;toast.hidden=false;}
      }catch(error){loadError=error.name==='AbortError'?'快照读取超时':'快照读取失败或格式无效';}
      finally{clearTimeout(timer);pending=false;render();}
    }
    refresh.onclick=refreshFeed;
    signals.onclick=()=>{filter='signals';render();};all.onclick=()=>{filter='all';render();};
    const tick=()=>{render();if(!document.hidden)refreshFeed();};
    let timer=setInterval(tick,refreshSeconds*1000);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshFeed();});
    window.addEventListener('pagehide',()=>{clearInterval(timer);timer=null;});
    window.addEventListener('pageshow',()=>{if(timer===null){timer=setInterval(tick,refreshSeconds*1000);refreshFeed();}});
    render();refreshFeed();
  }
  const api={mount,validate,status,notices};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.CZRadar=api;
})(typeof globalThis!=='undefined'?globalThis:this);
