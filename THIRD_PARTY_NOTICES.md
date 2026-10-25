# 第三方依赖与设计来源

本次 CZ 模块接入以下库的公开 API，没有直接复制这些项目的实现代码。这里记录来源，不能替代各依赖发行包随附的完整许可证。

| 直接依赖 | 固定版本 | 许可证与来源 |
|---|---|---|
| twscrape | 0.20.1 | [MIT / 项目与 LICENSE](https://github.com/vladkens/twscrape) |
| feedparser | 6.0.14 | [BSD-2-Clause / 项目与 LICENSE](https://github.com/kurtmckee/feedparser) |

`requirements-cz.lock` 为本地验证环境的完整版本约束清单；安装方式为 `pip install -r requirements-cz.txt -c requirements-cz.lock`。间接依赖以各发行包元数据与许可证为准；本项目不把 Python 库源码或环境发布到 Pages。

调研但未引入：RSSHub（AGPL-3.0）、Nitter（AGPL-3.0）、Twikit（MIT）、changedetection.io（Apache-2.0）。仅比较架构、维护状态与已知限制，未复制代码；具体链接与决策见 [CZ_MONITOR.md](docs/CZ_MONITOR.md)。

GitHub Actions 使用 actions/checkout、setup-python、setup-node、configure-pages、upload-pages-artifact、deploy-pages 官方 action；许可证与更新记录以其各自 GitHub 仓库为准。
