# findSecurityNews

安全资讯采集、AI 全文摘要、飞书/钉钉推送、微信公众号爬取（RSSHub）、Web 仪表盘。

## 功能概览

- 从 `config/sources.toml` 爬取 18 个来源（RSS / HTML / sitemap / RSSHub 微信）
- SQLite 存储，自动 URL 去重
- AI 读全文生成中文摘要（支持 OpenAI / Anthropic 兼容 API）
- 飞书机器人推送（**精简 4 字段**：标题、日期、摘要、链接）
- 内置 RSSHub（Docker Compose）抓取微信公众号文章
- Web 仪表盘（默认关闭，`ENABLE_DASHBOARD=true` 启用）
- 静态 HTML 站点导出
- Linux cron 早晚定时采集推送 + 自动归档清理

## 环境要求

- Python >= 3.10
- Docker（微信 RSSHub 需要）
- cron（定时推送需要，可选）

## 最快启用

```bash
git clone https://github.com/cjh-1001/findSecurityNews.git
cd findSecurityNews
chmod +x scripts/*.sh
./scripts/setup_linux.sh
```

交互式脚本会引导你完成全部配置。完成后：

```bash
# 启动 RSSHub（如果用微信源的话）
docker compose up -d

# 手动跑一次
scripts/run_feishu.sh latest

# 查看定时任务
crontab -l | grep findSecurityNews
```

## 项目结构

```
findSecurityNews/
├── config/sources.toml          # 18 个资讯源配置
├── docker-compose.yml           # RSSHub 服务
├── Makefile                     # 常用命令
├── run.py                       # 入口
├── src/find_security_news/      # Python 包
│   ├── cli.py                   # 命令行 + 工作流编排
│   ├── ai.py                    # AI 分析（读全文 24,000 字）
│   ├── rss.py                   # RSS/Atom 解析
│   ├── sitemap.py               # sitemap + HTML 正文提取
│   ├── database.py              # SQLite 存储 + 去重
│   ├── dashboard.py             # Web 仪表盘
│   ├── feishu.py                # 飞书 webhook
│   ├── dedup.py                 # 近重复检测
│   ├── dedup.py                 # Markdown 简报
│   └── static_site.py           # 静态站点导出
├── scripts/
│   ├── setup_linux.sh           # 交互式 Linux 部署
│   ├── deploy.sh                # 一键更新部署
│   ├── run_feishu.sh            # 飞书工作流（cron 用）
│   ├── install_cron.sh          # 安装 cron 定时
│   └── cleanup_data.py          # 数据归档清理
├── data/security_news.db        # SQLite 数据
├── outputs/                     # 归档/简报/静态站点
└── logs/                        # 运行日志
```

## 配置

`.env` 所有配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `FEISHU_WEBHOOK` | 飞书机器人 webhook | 必填 |
| `FEISHU_SECRET` | 飞书签名密钥 | 可选 |
| `COLLECT_LIMIT` | 每源每次采集数 | `30` |
| `PUSH_LIMIT` | 每次推送数 | `20` |
| `PUSH_BATCH_SIZE` | 每条飞书消息最多包含条数 | `20` |
| `PUSH_SUMMARY_LIMIT` | 飞书梗概最大字数 | `30` |
| `ENABLE_AI` | 启用 AI 分析 | `false` |
| `AI_PROVIDER` | `openai` / `anthropic` | `openai` |
| `OPENAI_BASE_URL` | API 地址 | `https://api.openai.com/v1` |
| `OPENAI_API_KEY` | API key | 必填（AI 开启时） |
| `OPENAI_MODEL` | 模型名 | `gpt-4.1-mini` |
| `AI_MAX_TOKENS` | 最大输出 token | `8192` |
| `ENABLE_DASHBOARD` | 启用 Web 仪表盘 | `false` |
| `ENABLE_RSSHUB` | 工作流前检查 RSSHub 健康 | `false` |
| `CLEANUP_SCHEDULE` | `weekly` / `monthly` / `none` | `weekly` |
| `CLEANUP_RETENTION_DAYS` | 保留天数 | `30` |
| `CLEANUP_VACUUM` | 清理后 VACUUM | `false` |

## 微信公众号爬取

通过内置 RSSHub 抓取。当前配置了两个安全公众号：

| 源名 | 公众号 | 微信号 |
|------|--------|--------|
| `wechat_qianxin_ti` | 奇安信威胁情报中心 | `gh_166784eae33e` |
| `wechat_blackorbird` | 黑鸟 | `blackorbird` |

### 添加更多公众号

1. 找到公众号的微信号（搜狗微信搜索 `weixin.sogou.com`）
2. 在 `config/sources.toml` 添加：

```toml
[[sources]]
name = "wechat_你的名字"
type = "rsshub"
url = "http://127.0.0.1:1200/wechat/mp/profile/微信号"
homepage = "https://mp.weixin.qq.com/"
language = "zh-CN"
enabled = true
```

3. 重启 RSSHub：`docker compose restart rsshub`

> **注意**：微信源用 `type = "rsshub"`，不会去爬 `mp.weixin.qq.com`（有反爬），
> 而是直接用 RSSHub 提供的全文内容。

## 推送格式

飞书推送每条消息 4 个字段：

```
安全资讯简报
时间窗口: 2026-06-05 08:00 - 2026-06-05 20:00

1. CVE-2026-XXXX 漏洞分析报告
日期: 2026-06-05 14:30
梗概: 主流防火墙存在远程代码执行漏洞
链接: https://example.com/article
```

## 手动运行

```bash
# 采集
python3 run.py collect --limit 30 --ai

# 推送
python3 run.py push-feishu --window morning --limit 20 --batch-size 20 --summary-limit 30

# 采集+推送（推荐）
python3 run.py feishu-workflow --window day --ai

# AI 补处理未分析文章
python3 run.py process-ai --limit 100

# 仪表盘
ENABLE_DASHBOARD=true python3 run.py dashboard --port 8000

# 静态站点
python3 run.py export-html --limit 300
```

时间窗口（Asia/Shanghai）：

| 窗口 | 范围 |
|------|------|
| `morning` | 前一天 20:00 ~ 当天 08:00 |
| `evening` | 当天 08:00 ~ 20:00 |
| `day` | 当天 00:00 ~ 24:00 |
| `latest` | 全部 |

## Makefile 常用命令

```bash
make deploy      # 一键部署
make start       # 启动 RSSHub
make stop        # 停止 RSSHub
make status      # 查看服务状态
make collect     # 采集（含 AI）
make push-am     # 推送早报
make push-pm     # 推送晚报
make dashboard   # 启动仪表盘
make clean       # 清理 outputs/
```

## 定时任务

```bash
# 安装早晚推送 (08:00 + 20:00)
scripts/install_cron.sh

# 安装清理
scripts/install_cleanup_cron.sh weekly  # 周清
scripts/install_cleanup_cron.sh monthly # 月清
```

## 国内服务器部署

国内服务器访问国外安全站点可能很慢。建议在 `config/sources.toml` 中禁用：

```bash
sed -i \
  -e '/name = "group_ib_blog"/{n;s/enabled = true/enabled = false/}' \
  -e '/name = "security_affairs_security"/{n;s/enabled = true/enabled = false/}' \
  -e '/name = "securityonline_info"/{n;s/enabled = true/enabled = false/}' \
  -e '/name = "malwarebytes_blog"/{n;s/enabled = true/enabled = false/}' \
  -e '/name = "cyble_blog"/{n;s/enabled = true/enabled = false/}' \
  -e '/name = "cybersecurity360_news"/{n;s/enabled = true/enabled = false/}' \
  -e '/name = "krebs_on_security"/{n;s/enabled = true/enabled = false/}' \
  config/sources.toml
```

## 常见问题

### 飞书没收到消息

```bash
tail -100 logs/feishu.log
python3 run.py push-feishu --limit 3
```

### cron 没执行

```bash
crontab -l | grep findSecurityNews       # 确认任务存在
systemctl status cron                    # 确认 cron 在跑
sudo timedatectl set-timezone Asia/Shanghai  # 设对时区
```

### Python SyntaxError

说明 Python < 3.10。重建虚拟环境：

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e .
echo "PYTHON_BIN=$(pwd)/.venv/bin/python" >> .env
```

### 采集卡住

通常是国外源网络不通。Ctrl+C 后禁用对应源即可。

### 微信源没数据

```bash
# 确认 RSSHub 在跑
docker compose ps
curl http://127.0.0.1:1200/healthz

# 手动测一下微信源
curl http://127.0.0.1:1200/wechat/mp/profile/blackorbird
```
