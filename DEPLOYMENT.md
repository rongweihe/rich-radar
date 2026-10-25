# GitHub 发布与部署

适用现有仓库 `rongweihe/rich-radar`，默认分支 `main`。这里的实现不需要付费 X API 或 LLM。选择公开仓库和标准 GitHub 托管 runner；私有仓库的 Pages 可用性、Actions 配额取决于账户计划。免费采集依赖上游和登录会话，无法承诺每 15 分钟必达。

## 1. 推送代码

原仓库已有 `origin`，不需要重复 `git init` 或添加 remote。在终端执行：

```bash
cd /Users/soso/Desktop/rich-rader/rich-radar
git status --short
git diff --check
git add .github/workflows .gitignore README.md DEPLOYMENT.md THIRD_PARTY_NOTICES.md \
  config.json index.html requirements-cz.txt requirements-cz.lock \
  data/cz.json data/refresh-state.json docs/CZ_MONITOR.md \
  scripts/cz_sources.py scripts/cz_rules.py scripts/compute_cz.py scripts/cz-radar.js \
  scripts/refresh.py scripts/build_site.py scripts/verify_site.py \
  styles/cz-radar.css tests/test_cz.py tests/test_cz_frontend.cjs
git diff --cached --stat
git commit -m "feat: add CZ signals monitor and verified Pages deployment"
git push origin main
```

先检查暂存内容，确保没有其他任务的更改或凭据。若远端已有新提交，先同步并解决冲突，不要强推。推送代码仅发布已有快照，不会在每次推送时重复抓取数据。GitHub 尚未设置 Pages 时首次发布可能失败，完成下面设置后手动重跑即可。

## 2. 设置 GitHub Pages 和权限

1. 仓库 **Settings → Pages → Build and deployment → Source → GitHub Actions**。若之前选了 `Deploy from a branch`，需要切换。
2. **Settings → Actions → General → Workflow permissions → Read and write permissions**，保存。工作流需要把公开快照提交回 `main`。组织策略和分支保护仍然有效；若禁止机器人直接写入 `main`，需要仓库管理员先调整适用规则，本方案不会绕过保护。
3. 若 `github-pages` 环境配置了部署分支限制，允许 `main`。若配置了每次人工审批，自动更新会等待审批。
4. Actions 页面仅启用新的 **Radar refresh and Pages deploy**。旧 `weekly.yml`、`ema-daily.yml` 已删除，不要重新启用额外的定时写入任务。

本工作流直接部署 `_site`，不依赖机器人提交再触发第二次构建。[GitHub Pages 自定义工作流说明](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)、[GITHUB_TOKEN 触发限制](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)。

## 3. 配置免费 X 采集

在仓库 **Settings → Secrets and variables → Actions → New repository secret** 新增：

| Secret | 内容 | 必需性 |
|---|---|---|
| `CZ_X_COOKIES` | 自己授权使用的 X 账户会话，格式 `auth_token=实际值; ct0=实际值` | 主数据源需要 |
| `CZ_RSS_URL` | 自己验证过、可读到 CZ 原文的 HTTPS RSS 地址 | 可选降级源，不提供默认公共服务 |

获取会话：用自己的浏览器登录 `x.com`，开发者工具 → Application（或 Storage）→ Cookies → `https://x.com`，找到 `auth_token` 和 `ct0`，将两项组成上述字符串并直接存入 Secret。**不要把值发到聊天、写到 `config.json`、截图公开或提交到 Git。** 这些值代表已登录会话，失效时需要在浏览器重新登录并更新 Secret。无需提供账户密码，也不需要购买账号或 API Key。

RSS 只作为可选二手来源：地址本身可能含访问令牌，所以也放 Secret。不要填 `https://x.com/cz_binance`，那是网页，不是 RSS。没有已验证源就留空。RSSHub 的 X 路由也常需要登录态，不等于开箱即用的匿名稳定接口。

凭据只传给刷新步骤，临时 SQLite 位于系统临时目录，不进入仓库、缓存或发布产物。日志和公开 JSON 只记录受控错误码。

## 4. 首次运行与验收

1. **Actions → Radar refresh and Pages deploy → Run workflow → Branch: main → scope: all**。
2. 检查采集步骤摘要，以及 `Commit public snapshots only`、`Deploy Pages explicitly`、`Verify live content` 三步是否通过。最后一步比对线上 HTML、CZ 脚本和快照哈希，确认不是旧站点。
3. 打开 [线上看板](https://rongweihe.github.io/rich-radar/)。未配置 Cookie 时应显示「尚未配置数据源」；有数据时应显示原文、规则依据、原帖链接、快照生成与成功读取时间。
4. 首次成功采集只建立窗口，显示「监控降级 · 覆盖待确认」，初始帖子标记历史/补采；这是预期行为。再运行一次 `scope: cz`，若时间线与上次窗口衔接，才能显示「最近检查正常」。
5. 页面打开时每 60 秒读取已发布快照；只有打开页面之后新发现、足够新且来自正常主源的命中，才显示页内提示。首次打开不会弹一堆历史提醒。可以切换「最近原文」核对误报和漏报。

**工作流绿色代表执行和发布链路通过，不代表 X 来源健康。** 采集故障也会发布降级状态，避免旧页面一直显示正常。真实来源状态以页面及 `data/cz.json` 为准；底层进程异常可在 `data/refresh-state.json` 查看。

## 5. 自动周期与故障处理

- 定时计划为每小时 UTC 第 2、17、32、47 分钟。GitHub 调度可能延迟、跳过或合并；页面 45 分钟没有新快照会标记过期。
- `auto` 同时负责周期补跑：市场评分每周一 09:00（UTC+8）起，EMA 每天 09:15 起，在随后一次可执行的调度完成。失败每小时重试；CZ 自己维护失败退避。
- CZ 请求最长 90 秒、默认读取最近 200 条，失败退避 15/30/60/120/240/360 分钟。手动 `cz` 仍遵守退避，不会无限重试。
- 数据默认保留最近 90 天、最多 300 条。页面展示筛选后最新 30 条；仓库 Git 历史中的旧记录不会因这一保留策略自动删除。

| 现象 | 处理 |
|---|---|
| 未配置数据源 | 确认 Secret 名称与所在仓库，手动运行 `cz` |
| 空响应 / 会话可能失效 | 在自己的浏览器确认账户能正常读取 CZ，更新 Cookie，等待退避后重跑；不要把空结果当无新帖 |
| 仅建立初始窗口 | 再执行一次 `cz`，验证窗口重叠 |
| 未衔接上次窗口 | 可能有漏帖，也可能是锚点被删除；可适度增加 `max_posts` 后重跑，仍保留时间预算。不自动假装恢复连续覆盖 |
| 锚点长期无法恢复 | 明确接受丢失区间后，在 `data/cz.json` 仅移除 `sources.twscrape.anchor_id`，提交并再运行两次建立新基线；此操作不能恢复漏帖 |
| 手动运行仍在退避 | 默认等到页面的下次尝试时间。更换 Cookie 后如需立即验证，可只移除该来源的 `retry_after`、将 `failures` 设 0，保留推文和其他状态，再提交并运行 `cz` |
| 依赖安装失败 | 本轮仍可发布 `dependency_missing`；查看 Install collectors 日志，网络恢复后重跑。不要随意取消版本约束 |
| 推送冲突 / 403 | 检查写权限、分支保护和其他写入者；工作流不会强推。下一次使用最新 `main` 重跑 |
| 部署成功但核验失败 | 检查 Pages 地址、CDN 和 Actions 日志；可运行 `publish` 重发已保存快照，不必重新采集 |
| 长期没有定时运行 | 检查 Actions 是否被禁用、默认分支是否为 `main`，以及 GitHub 的计划任务停用规则；必要时手动恢复工作流 |

暂停 CZ 采集：将 `config.json` 的 `cz_monitor.enabled` 改为 `false`，提交后手动运行 `cz`。暂停所有定时更新：在 Actions 页面禁用该工作流。修改 CZ 周期需改工作流 cron；`refresh_seconds` 只影响浏览器读快照频率。

本次本地验证覆盖规则、异常恢复、去重、页面交互和部署哈希逻辑；尚未使用真实 X 凭据验证，也未替你推送 GitHub 或执行线上部署。
