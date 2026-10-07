# RICH Crypto \* Stock 带血筹码雷达

一个自托管的 Crypto / 美股「机会监测」看板。用公开的价格、成交量与情绪指数计算一个 **恐慌分数**，并给出「下一步观察价」。

> ⚠️ 仅供研究，**不是投资建议**。恐慌分数只用于触发进一步研究，不是买入信号；页面不编造目标价与概率。买卖决定与风险自负。

在线地址（启用 Pages 后）：**https://rongweihe.github.io/rich-radar/**

---

## 它做什么

- **三层分析**：市场（恐惧贪婪 / VIX / 大盘）→ 板块（同类均分与均回撤）→ 单资产（逐个研究卡）。
- **恐慌分数（0–100）** = 回撤(25) + 7 日价格冲击分位(25) + 成交量异常(25) + 情绪(25)。阈值：≥60 触发研究、≥40 关注。
- **每张研究卡**：质量 / 估值 / 催化 / 最强反方理由 / 上涨空间 / 下行风险 / 等待时间 / 波动性，并标注数据时间、来源与缺失项。
- **风险预算**：稳健档——单资产 ≤5%、加密总仓 ≤20%、单次分批 ≤1.5%（见 `config.json`，可改）。
- **加密实时**：网页打开时直接向 Gate.io / Alternative.me 拉最新价与情绪；**美股每周由 GitHub Actions 更新**。
- **第三层 · 均线指标雷达**：独立跟踪 BTC / SOL / LINK / AAVE / NEAR / ZEC / UNI / CRCL 的 EMA20、EMA200；EMA20 在上方时显示绿色提示、连续持续时间、上穿日期、两线差幅和最近 60 根均线走势。可筛选上方资产，也可单独刷新均线。

## 均线指标口径

- 仅使用**已收盘日 K 的收盘价**，排除盘中 K 线。EMA(N) 以首 N 根收盘价的简单平均初始化，随后按 `EMA = close × 2/(N+1) + 前一 EMA × (1−2/(N+1))` 递推；与原研究卡的 MA200（简单均线）是不同指标。
- 加密从 Gate.io 拉最多 1,000 根 UTC 日 K，在打开页面和点击「刷新均线」时更新。CRCL 为 **Circle 的美股**，使用 Yahoo 日 K（最多 5 年/可用上市历史），由每日 Actions 生成快照；浏览器刷新会读取最新快照。
- 只有 `EMA20 > EMA200` 才触发上方信号；相等不触发。最新一根由非上方变为上方时标注「最新收盘上穿」。加密持续时间按连续自然日统计；CRCL 按连续交易日统计，并同时展示自然日跨度，均包含起始日与最后收盘日。
- EMA200 至少需要 200 根历史；不足时展示已有 EMA20 和历史根数，不生成信号。如果在 EMA200 可计算窗口开始时就已处于上方，只能确认「至少 N 天」，不会把窗口起点当成实际上穿日期。
- 每张卡标注最后收盘日与来源。抓取失败保留原快照并显示错误；加密收盘日距今超过 2 日、美股超过 5 日会标注快照较旧，失败或过期的卡片不计入当前有效信号汇总。均线雷达名单不改变原有恐慌评分、分档和研究卡。
- [Gate API 文档](https://www.gate.com/docs/developers/apiv4/en/)、[EMA 计算说明](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/ema)、[Circle 投资者关系](https://investor.circle.com/)。

## 数据源（全部免费、无需 API Key）

| 类型 | 来源 | 说明 |
|---|---|---|
| 加密价格/量 | Gate.io 公开现货 1d K 线 | 浏览器可直接跨域读取 |
| 美股价格/量 | Yahoo Finance chart API 1d | 仅服务端(Actions)抓取；约 1 年历史 |
| 加密情绪 | Alternative.me Fear & Greed | 400 日历史 |
| 美股情绪 | CBOE VIX（Yahoo ^VIX） | 约 1 年历史 |

已知限制见页面「数据缺失与限制」与 `data/latest.json` 的 `missing` 字段（Stooq 不可用改用 Yahoo；美股仅 1 年历史；LINK 等单所成交量偏薄会标注「薄流动性」）。

---

## 目录结构

```
rich-radar/
├── index.html              # 单文件前端（内嵌一份数据作离线兜底）
├── config.json             # 观察名单、风险预算、评分口径、分档
├── data/
│   ├── latest.json         # 最新快照（Actions 每周覆盖）
│   ├── history.json        # 每次运行的分数/情绪历史（自动追加）
│   └── ema.json            # 独立均线快照（Actions 每日覆盖）
├── research/assets.json    # 16 张定性研究卡（人工维护）
├── scripts/compute.py      # 抓取+计算，生成 data/latest.json
├── scripts/compute_ema.py  # 已收盘日 K / EMA 计算，生成 data/ema.json
├── scripts/ema-radar.js    # 浏览器均线计算、卡片渲染与独立刷新
├── tests/test_ema.py       # EMA 边界和 Python / JS 一致性验证
├── .github/workflows/weekly.yml  # 每周一 09:00(北京) 自动刷新
├── .github/workflows/ema-daily.yml # 每天 09:15(北京) 自动刷新均线
└── .nojekyll
```

---

## 部署到 GitHub Pages（逐步）

> 我（Claude）无法替你登录 GitHub 或创建仓库（涉及账号凭证），请你自己执行下面命令。仓库名用 `rich-radar` 时，地址即 `https://rongweihe.github.io/rich-radar/`。

**1) 在 GitHub 网站上新建一个空仓库** `rich-radar`（不要勾选 README/License）。

**2) 在本机把本文件夹推上去**（在 `rich-radar/` 目录内执行）：

```bash
cd rich-radar
git init
git add .
git commit -m "init: RICH 带血筹码雷达"
git branch -M main
git remote add origin https://github.com/rongweihe/rich-radar.git
git push -u origin main
```

**3) 开启 Pages**：仓库 → Settings → Pages → Build and deployment →
Source 选 **Deploy from a branch**，Branch 选 **main / (root)**，Save。
约 1 分钟后访问 `https://rongweihe.github.io/rich-radar/`。

**4) 开启每周自动更新**：仓库 → Settings → Actions → General →
Workflow permissions 选 **Read and write permissions**，Save。
然后 Actions 标签页 → 选 “Weekly data refresh” → **Run workflow** 手动跑一次验证；之后每周一 09:00（北京时间）自动刷新美股数据并提交。
均线快照通过 “Daily EMA radar refresh” 每天 09:15（北京时间）单独更新；也可手动运行。两项任务使用同一并发组，避免同时提交产生推送冲突。

> 想改频率：编辑 `.github/workflows/weekly.yml` 里的 `cron`。
> `0 1 * * 1` = 每周一 01:00 UTC = 北京时间周一 09:00。

---

## 本地预览

`index.html` 内嵌了一份数据兜底，**直接双击即可打开**看到完整页面；加密实时价会尝试联网刷新。
若想让它读取 `data/latest.json` 最新文件（而非内嵌兜底），用本地服务器打开：

```bash
cd rich-radar
python3 -m http.server 8000
# 浏览器打开 http://localhost:8000/
```

## 手动更新数据

```bash
cd rich-radar
python3 scripts/compute.py      # 需要能联网（Actions 环境即可）
# 会覆盖 data/latest.json 并追加 data/history.json
python3 scripts/compute_ema.py  # 单独更新 data/ema.json，不依赖情绪指数
```

验证均线算法（Python 3.9+，跨端一致性测试需 Node.js）：

```bash
python3 -m unittest discover -s tests -v
node --check scripts/ema-radar.js
```

页面内嵌一份均线快照供离线兜底；在线始终优先读取 `data/ema.json`。自动更新只写快照文件，直接双击离线展示的内嵌快照可能较旧，卡片会显示实际收盘日期。

## 维护研究卡

`research/assets.json` 是人工维护的定性判断，请定期复核（改 `_meta.reviewed` 日期）。
新增/删除资产：改 `config.json` 的 `watchlist` 与分档 `tiers`，脚本与页面会自动跟随。

---

生成于 2026-09-15 · 评分口径 v1（未经充分历史检验，仅作观察提醒）
