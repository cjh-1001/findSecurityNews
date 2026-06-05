# findSecurityNews

安全资讯采集、AI 摘要、飞书推送、Web 仪表盘和定时清理工具。

## 功能概览

- 从 `config/sources.toml` 配置的 RSS / HTML / sitemap 来源采集安全资讯
- 写入 SQLite：`data/security_news.db`
- 自动去重，保留重复原因和相似度
- 可选 AI 分析：中文摘要、中文译文、风险优先级、CVE、标签、关键点
- 支持飞书机器人推送日报、早报、晚报
- 支持本地 Web 仪表盘查看、筛选、清理数据
- 支持导出静态 HTML 站点
- 支持 Linux cron 定时采集推送和周/月自动归档清理

## 最快启用：Linux 服务器

把项目复制到服务器后执行：

```bash
cd findSecurityNews
chmod +x scripts/*.sh
./scripts/setup_linux.sh
```

交互脚本会完成：

- 检查或安装 Python 3.10+、pip、cron/crontab
- 创建 `.venv`
- 安装依赖
- 创建 `.env`
- 初始化数据库
- 配置飞书 webhook 和可选签名 secret
- 配置是否启用 AI
- 配置采集数量、推送数量
- 配置是否安装 08:00 / 20:00 定时推送
- 配置是否安装周清或月清数据库任务
- 可选立即运行一次真实工作流测试

建议服务器使用北京时间，避免 cron 触发时间和工作流窗口不一致：

```bash
sudo timedatectl set-timezone Asia/Shanghai
```

## 部署后验证

查看定时任务：

```bash
crontab -l | grep findSecurityNews
```

手动跑一次最新采集和推送：

```bash
scripts/run_feishu.sh latest
```

按当天窗口采集和推送：

```bash
scripts/run_feishu.sh day
```

手动跑早报 / 晚报窗口：

```bash
scripts/run_feishu.sh morning
scripts/run_feishu.sh evening
```

查看日志：

```bash
tail -f logs/feishu.log
tail -f logs/cleanup.log
```

## 核心配置

部署脚本会生成 `.env`。也可以复制 `.env.example` 手动配置：

```bash
cp .env.example .env
nano .env
```

常用配置：

```bash
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/replace-me
FEISHU_SECRET=replace-me

COLLECT_LIMIT=30
PUSH_LIMIT=20
PYTHON_BIN=/path/to/findSecurityNews/.venv/bin/python

ENABLE_AI=false
AI_PROVIDER=openai
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=replace-me
OPENAI_MODEL=gpt-4.1-mini
AI_MAX_TOKENS=8192

CLEANUP_SCHEDULE=weekly
CLEANUP_RETENTION_DAYS=30
CLEANUP_VACUUM=false
```

配置说明：

| 配置 | 作用 |
| --- | --- |
| `FEISHU_WEBHOOK` | 飞书群机器人 webhook，推送功能必填 |
| `FEISHU_SECRET` | 飞书机器人签名密钥，开启签名校验时填写 |
| `COLLECT_LIMIT` | 每个来源每次采集数量 |
| `PUSH_LIMIT` | 每次推送最多发送多少篇 |
| `ENABLE_AI` | 定时工作流是否启用 AI 分析 |
| `OPENAI_BASE_URL` | OpenAI 或兼容网关地址 |
| `OPENAI_API_KEY` | AI API key |
| `OPENAI_MODEL` | AI 模型名 |
| `CLEANUP_SCHEDULE` | `weekly`、`monthly` 或 `none` |
| `CLEANUP_RETENTION_DAYS` | 保留最近多少天数据，旧数据归档后删除 |
| `CLEANUP_VACUUM` | 清理后是否执行 SQLite `VACUUM` |

## 手动运行

初始化数据库：

```bash
python3 run.py init-db
```

采集最新资讯：

```bash
python3 run.py collect --limit 30
```

采集并执行 AI 分析：

```bash
python3 run.py collect --limit 30 --ai
```

列出最新文章：

```bash
python3 run.py list --limit 10
```

生成 Markdown 简报：

```bash
python3 run.py digest --limit 20
```

## 飞书推送

只推送数据库里的最新文章：

```bash
python3 run.py push-feishu --limit 8
```

采集、可选 AI、再推送，推荐用于定时任务：

```bash
python3 run.py feishu-workflow --window latest --collect-limit 30 --push-limit 20
python3 run.py feishu-workflow --window day --collect-limit 30 --push-limit 20
python3 run.py feishu-workflow --window morning --collect-limit 30 --push-limit 20
python3 run.py feishu-workflow --window evening --collect-limit 30 --push-limit 20 --ai
```

时间窗口按 `Asia/Shanghai` 计算：

- `latest`：最新文章，不按日期过滤
- `day`：当天 00:00 到 24:00
- `morning`：前一天 20:00 到当天 08:00
- `evening`：当天 08:00 到当天 20:00

指定日期：

```bash
python3 run.py push-feishu --window day --date 2026-06-05
python3 run.py feishu-workflow --window evening --date 2026-06-05 --ai
```

## 定时任务

安装早晚两次飞书工作流：

```bash
scripts/install_cron.sh
```

默认 cron：

```cron
0 8 * * *  scripts/feishu_morning.sh
0 20 * * * scripts/feishu_evening.sh
```

手动安装数据库自动清理：

```bash
# 每周日 03:30 清理
scripts/install_cleanup_cron.sh weekly

# 每月 1 日 03:30 清理
scripts/install_cleanup_cron.sh monthly

# 移除自动清理
scripts/install_cleanup_cron.sh none
```

## Web 仪表盘

启动仪表盘：

```bash
python3 run.py dashboard --host 127.0.0.1 --port 8000
```

打开：

```text
http://127.0.0.1:8000
```

仪表盘支持：

- 文章总览、今日/近 7 天统计、AI 覆盖率、风险分布、来源分布
- 关键词、来源、日期、重复记录筛选
- 文章详情、原文 HTML 渲染、AI 结果查看
- 数据清理预览、归档、删除、可选 `VACUUM`

如果部署到公网服务器，建议绑定内网地址或放在带认证的反向代理后面。

## 静态 HTML 站点

生成可直接部署的静态站点：

```bash
python3 run.py collect --limit 30 --ai
python3 run.py export-html --limit 300 --output-dir outputs/site --title "安全资讯"
```

打开：

```text
outputs/site/index.html
```

每篇文章会生成到：

```text
outputs/site/articles/
```

## 数据清理

交互式清理：

```bash
python3 scripts/cleanup_data.py
```

预览清理，不改数据库：

```bash
python3 scripts/cleanup_data.py --before 2026-06-01 --dry-run
```

归档并删除指定日期之前的数据：

```bash
python3 scripts/cleanup_data.py --before 2026-06-01 --yes
```

归档并删除指定范围：

```bash
python3 scripts/cleanup_data.py --from-date 2026-05-01 --to-date 2026-06-01 --yes
```

自动清理脚本：

```bash
scripts/run_cleanup.sh
```

清理前会写 JSONL 归档到：

```text
outputs/archive/
```

## Windows 快速运行

PowerShell：

```powershell
py .\run.py init-db
py .\run.py collect --limit 30
py .\run.py list --limit 10
py .\run.py dashboard
```

Windows 一键初始化：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

创建 `.env`：

```powershell
Copy-Item .env.example .env
notepad .env
```

安装 Windows 定时任务：

```powershell
.\scripts\install_windows_tasks.ps1
```

## 添加来源

编辑 `config/sources.toml`：

```toml
[[sources]]
name = "security_affairs_security"
type = "rss"
url = "https://securityaffairs.com/category/security/feed"
homepage = "https://securityaffairs.com/category/security"
language = "en"
enabled = true
```

支持的来源类型取决于采集器实现，目前项目里已经包含 RSS、HTML 索引、sitemap 和部分站点专用解析逻辑。

## 常见问题

如果飞书没有收到消息：

```bash
tail -n 100 logs/feishu.log
python3 run.py push-feishu --limit 3
```

如果 cron 时间不符合预期：

```bash
date
timedatectl
sudo timedatectl set-timezone Asia/Shanghai
```

如果清理任务没有执行：

```bash
crontab -l | grep cleanup
tail -n 100 logs/cleanup.log
scripts/run_cleanup.sh
```
