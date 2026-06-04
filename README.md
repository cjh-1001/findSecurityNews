# findSecurityNews

Security news collection workflow for crawling source feeds, storing articles, and generating Chinese security briefings.

## Current MVP

- Reads configured sources from `config/sources.toml`
- Collects Security Affairs articles from the category RSS feed
- Extracts title, URL, author, published time, categories, summary, and full article text
- Stores data in SQLite at `data/security_news.db`
- Optionally calls an OpenAI-compatible Chat Completions API for Chinese summary, translation, and structured security extraction
- Generates Markdown digests under `outputs/daily/`

## Run

```powershell
py .\run.py init-db
py .\run.py collect --limit 10 --digest
py .\run.py list --limit 10
py .\run.py dashboard
py .\run.py export-html
```

## One-Command Setup

Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

Linux:

```bash
chmod +x scripts/setup_linux.sh
./scripts/setup_linux.sh
```

The Linux setup script checks Python 3.10+, pip, cron/crontab, creates a local `.venv`,
installs project dependencies, creates or updates `.env`, initializes the database, and can
optionally install scheduled Feishu pushes. On a fresh server it may ask for `sudo` to install
system packages through `apt`, `dnf`, `yum`, `zypper`, or `pacman`.

Set `ENABLE_AI=true` in `.env` to make scheduled pushes use AI summaries.

AI processing is optional. Without an API key the crawler still works.

## Web Dashboard

Start the local dashboard:

```powershell
py .\run.py dashboard --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000`.

For a Linux server, bind to an internal address or put it behind an authenticated reverse proxy:

```bash
python3 run.py dashboard --host 127.0.0.1 --port 8000
```

The dashboard includes article statistics, source filters, keyword/date search, article detail pages,
cleanup month buckets, cleanup preview, archive-and-delete, and optional SQLite `VACUUM`.
Cleanup archives are written to `outputs/archive/` before rows are deleted.

## Static HTML Site

Generate a directly accessible HTML site from collected articles:

```powershell
py .\run.py collect --limit 30 --ai
py .\run.py export-html --limit 300 --output-dir .\outputs\site --title "安全资讯"
```

Open `outputs/site/index.html` in a browser, or deploy the whole `outputs/site/` directory as static files.
Each article gets its own HTML page under `outputs/site/articles/`.

Linux:

```bash
python3 run.py collect --limit 30 --ai
python3 run.py export-html --limit 300 --output-dir outputs/site --title "安全资讯"
```

```powershell
$env:OPENAI_API_KEY = "your_api_key"
$env:OPENAI_MODEL = "gpt-4.1-mini"
py .\run.py collect --limit 5 --ai --digest
```

For OpenAI-compatible gateways, override the base URL:

```powershell
$env:OPENAI_BASE_URL = "https://api.openai.com/v1"
```

## Push To Feishu

Create a Feishu group custom bot and copy its webhook URL. Then run:

```powershell
$env:FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/..."
py .\run.py collect --limit 10
py .\run.py push-feishu --limit 8
```

If the bot enables signature verification, also set:

```powershell
$env:FEISHU_SECRET = "bot_signing_secret"
```

Date windows are supported for twice-daily pushes:

```powershell
# Previous day 20:00 through today 08:00, Asia/Shanghai time
py .\run.py feishu-workflow --window morning --collect-limit 30 --push-limit 20

# Today 08:00 through today 20:00, Asia/Shanghai time
py .\run.py feishu-workflow --window evening --collect-limit 30 --push-limit 20

# Collect, process with AI, then push the optimized briefing
py .\run.py feishu-workflow --window evening --collect-limit 30 --push-limit 20 --ai

# Specific date windows
py .\run.py push-feishu --window day --date 2026-06-04
py .\run.py push-feishu --window morning --date 2026-06-04
py .\run.py push-feishu --window evening --date 2026-06-04
```

## Data Cleanup

When the database grows, use the cleanup helper to inspect available time periods and archive old rows before deleting them.

Interactive mode:

```powershell
py .\scripts\cleanup_data.py
```

Preview a cleanup without changing the database:

```powershell
py .\scripts\cleanup_data.py --before 2026-06-01 --dry-run
```

Archive and delete a specific range:

```powershell
py .\scripts\cleanup_data.py --from-date 2026-05-01 --to-date 2026-06-01
```

The script writes JSONL archives under `outputs/archive/` before deleting rows. Archives include original article HTML/text, extracted metadata, and AI result JSON.

## Linux Scheduled Deployment

Recommended one-command deployment on a Linux server:

```bash
chmod +x scripts/setup_linux.sh
./scripts/setup_linux.sh
```

The script will prompt for Feishu webhook, optional AI settings, collection limits, and whether
to install cron jobs for 08:00 and 20:00 server time. After setup, test manually with:

```bash
scripts/run_feishu.sh latest
scripts/feishu_morning.sh
scripts/feishu_evening.sh
```

Manual cron installation is still available:

```bash
./scripts/install_cron.sh
```

Cron logs are written to `logs/feishu.log`.
The workflow filters article windows in UTC+8. Set the Linux server timezone to Asia/Shanghai, or adjust the cron hours if the server runs in another timezone.

## Windows Scheduled Deployment

Create `.env` from `.env.example`, then run:

```powershell
Copy-Item .env.example .env
notepad .env
.\scripts\feishu_morning.ps1
.\scripts\feishu_evening.ps1
```

Install Windows scheduled tasks for 08:00 and 20:00:

```powershell
.\scripts\install_windows_tasks.ps1
```

If PowerShell blocks script execution, run the scripts with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\feishu_morning.ps1
```

## Add Sources

Edit `config/sources.toml`:

```toml
[[sources]]
name = "security_affairs_security"
type = "rss"
url = "https://securityaffairs.com/category/security/feed"
homepage = "https://securityaffairs.com/category/security"
language = "en"
enabled = true
```

The first version supports RSS sources. Category-page scraping can be added as a fallback when a source has no RSS feed.
