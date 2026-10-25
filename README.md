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
- **CZ 言论雷达**：每 15 分钟尝试采集 `@cz_binance`，识别中英文买入、逆向机会和长期叙述，展示原文、命中依据、发现时间与监控健康状态。免费方案需要自己的 X 登录会话，不能保证实时或零漏报。
- **加密实时**：网页打开时直接向 Gate.io / Alternative.me 拉最新价与情绪；**美股每周由 GitHub Actions 更新**。
- **第三层 · 均线指标雷达**：独立跟踪 BTC / SOL / LINK / AAVE / NEAR / ZEC / UNI / CRCL 的 EMA20、EMA200；EMA20 在上方时显示绿色提示、连续持续时间、上穿日期、两线差幅和最近 60 根均线走势。可筛选上方资产，也可单独刷新均线。

## 均线指标口径

- 仅使用**已收盘日 K 的收盘价**，排除盘中 K 线。EMA(N) 以首 N 根收盘价的简单平均初始化，随后按 `EMA = close × 2/(N+1) + 前一 EMA × (1−2/(N+1))` 递推；与原研究卡的 MA200（简单均线）是不同指标。
- 加密从 Gate.io 拉最多 1,000 根 UTC 日 K，在打开页面和点击「刷新均线」时更新。CRCL 为 **Circle 的美股**，使用 Yahoo 日 K（最多 5 年/可用上市历史），由每日 Actions 生成快照；浏览器刷新会读取最新快照。
- 只有 `EMA20 > EMA200` 才触发上方信号；相等不触发。最新一根由非上方变为上方时标注「最新收盘上穿」。加密持续时间按连续自然日统计；CRCL 按连续交易日统计，并同时展示自然日跨度，均包含起始日与最后收盘日。
- EMA200 至少需要 200 根历史；不足时展示已有 EMA20 和历史根数，不生成信号。如果在 EMA200 可计算窗口开始时就已处于上方，只能确认「至少 N 天」，不会把窗口起点当成实际上穿日期。
- 每张卡标注最后收盘日与来源。抓取失败保留原快照并显示错误；加密收盘日距今超过 2 日、美股超过 5 日会标注快照较旧，失败或过期的卡片不计入当前有效信号汇总。均线雷达名单不改变原有恐慌评分、分档和研究卡。
- [Gate API 文档](https://www.gate.com/docs/developers/apiv4/en/)、[EMA 计算说明](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/ema)、[Circle 投资者关系](https://investor.circle.com/)。

## 行情数据源（公开接口，无需 API Key）

| 类型 | 来源 | 说明 |
|---|---|---|
| 加密价格/量 | Gate.io 公开现货 1d K 线 | 浏览器可直接跨域读取 |
| 美股价格/量 | Yahoo Finance chart API 1d | 仅服务端(Actions)抓取；约 1 年历史 |
| 加密情绪 | Alternative.me Fear & Greed | 400 日历史 |
| 美股情绪 | CBOE VIX（Yahoo ^VIX） | 约 1 年历史 |

已知限制见页面「数据缺失与限制」与 `data/latest.json` 的 `missing` 字段（Stooq 不可用改用 Yahoo；美股仅 1 年历史；LINK 等单所成交量偏薄会标注「薄流动性」）。

---

## CZ 模块与发布流程

`CZRadar` 独立读取 `data/cz.json`，不参与恐慌评分。后台使用固定版本的 twscrape 和可选 RSS，前端只读取公开快照，不持有登录凭据。

| 文件 | 职责 |
|---|---|
| `scripts/cz_sources.py` | X / RSS 适配、作者校验、限时采集 |
| `scripts/cz_rules.py` | 可解释的中英文规则及反例排除 |
| `scripts/compute_cz.py` | 去重、编辑修订、覆盖检查、退避、保留历史 |
| `scripts/cz-radar.js` / `styles/cz-radar.css` | 独立卡片、筛选、健康状态、页面内新信号提示 |
| `scripts/refresh.py` | CZ / 每日 EMA / 每周市场数据的单写者调度 |
| `data/refresh-state.json` | 记录完成周期，延迟调度可补跑 |
| `scripts/build_site.py` / `scripts/verify_site.py` | 静态文件白名单打包、部署后验证线上哈希 |
| `.github/workflows/radar.yml` | 唯一的刷新和 Pages 发布工作流 |

**部署按 [DEPLOYMENT.md](DEPLOYMENT.md) 操作**。Pages Source 必须选择 **GitHub Actions**；旧的每周/每日工作流已合并，不能继续照旧选择分支发布。推送代码只部署现有快照；首次运行选择 `all`，以后定时 `auto`。

实现边界与开源选型见 [docs/CZ_MONITOR.md](docs/CZ_MONITOR.md)，依赖来源与许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 本地预览与验证

需要 Python 3.12 和 Node.js 22+：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-cz.txt -c requirements-cz.lock
.venv/bin/python -m unittest discover -s tests -v
node --test tests/test_cz_frontend.cjs
.venv/bin/python scripts/build_site.py
.venv/bin/python -m http.server 8000 --bind 127.0.0.1 --directory _site
```

打开 `http://127.0.0.1:8000/`。`_site` 只包含可公开的静态文件。每次修改后重新构建再刷新浏览器。直接双击 HTML 只能看到内嵌行情兜底，CZ 在线快照需要 HTTP 服务。

手动更新使用 `.venv/bin/python scripts/refresh.py --scope all`；可选 `cz`、`market`、`ema`。`auto` 根据已完成周期补跑；`publish` 不采集。CZ 未设置环境变量时正常显示「未配置」，不会写入演示推文。配置凭据方法见部署文档，不要把会话写入仓库。

页面显示的加密实时价格与每周评分快照分别计时，价格刷新不会重算恐慌评分；失败不推进价格时间。均线仅使用已收盘日 K，实际收盘日期见卡片。

## 维护研究卡

`research/assets.json` 是人工维护的定性判断，请定期复核（改 `_meta.reviewed` 日期）。
新增/删除资产：改 `config.json` 的 `watchlist` 与分档 `tiers`，脚本与页面会自动跟随。

---

生成于 2026-09-15 · 评分口径 v1（未经充分历史检验，仅作观察提醒）
