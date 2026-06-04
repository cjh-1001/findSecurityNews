from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import html
import json
import sqlite3

from .rich_html import sanitize_article_html
from .time_format import format_article_time


DEFAULT_SITE_DIR = Path(__file__).resolve().parents[2] / "outputs" / "site"


def h(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def row_ai(row: sqlite3.Row) -> dict:
    value = row["ai_result_json"]
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_categories(row: sqlite3.Row) -> list[str]:
    try:
        parsed = json.loads(row["categories_json"] or "[]")
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed if item]
    return []


def normalize_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


def compact(value: str, limit: int = 180) -> str:
    value = " ".join((value or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def priority_label(value: str) -> str:
    labels = {
        "critical": "严重",
        "high": "高危",
        "medium": "中危",
        "low": "低危",
    }
    return labels.get((value or "").lower(), value or "未标注")


def type_label(value: str) -> str:
    labels = {
        "security_news": "安全资讯",
        "vulnerability": "漏洞",
        "network device vulnerability": "网络设备漏洞",
        "threat_intelligence": "威胁情报",
        "ransomware": "勒索软件",
        "malware": "恶意软件",
        "incident": "安全事件",
    }
    return labels.get((value or "").lower(), value or "安全资讯")


def article_filename(row: sqlite3.Row) -> str:
    return f"article-{int(row['id']):06d}.html"


def load_rows(db_path: Path, limit: int, include_duplicates: bool) -> list[sqlite3.Row]:
    if not db_path.exists():
        return []
    duplicate_filter = "" if include_duplicates else "WHERE a.duplicate_of_article_id IS NULL"
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return list(
            connection.execute(
                f"""
                SELECT a.*, r.result_json AS ai_result_json, r.model AS ai_model
                FROM articles a
                LEFT JOIN ai_results r ON r.article_id = a.id
                {duplicate_filter}
                ORDER BY COALESCE(NULLIF(a.published_at, ''), a.created_at) DESC
                LIMIT ?
                """,
                (limit,),
            )
        )


# ---------------------------------------------------------------------------
# CSS — design system, components, layout
# ---------------------------------------------------------------------------

SHARED_CSS = r"""
/* ============================================================
   Design Tokens & Theme
   ============================================================ */
:root {
  color-scheme: light dark;

  /* Light palette (default) */
  --bg: #f3f4f6;
  --surface: #ffffff;
  --surface-2: #f9fafb;
  --surface-3: #f3f4f6;
  --border: #e5e7eb;
  --border-light: #f0f1f3;
  --text: #111827;
  --text-secondary: #4b5563;
  --muted: #9ca3af;
  --shadow-sm: 0 1px 2px rgba(0,0,0,.04);
  --shadow: 0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04);
  --shadow-md: 0 4px 6px rgba(0,0,0,.04), 0 2px 4px rgba(0,0,0,.04);
  --radius-sm: 6px;
  --radius: 10px;
  --radius-lg: 14px;

  /* Brand */
  --accent: #2563eb;
  --accent-light: #eff6ff;
  --accent-dark: #1d4ed8;

  /* Semantic */
  --critical: #dc2626;
  --critical-bg: #fef2f2;
  --critical-border: #fecaca;
  --high: #ea580c;
  --high-bg: #fff7ed;
  --high-border: #fed7aa;
  --medium: #ca8a04;
  --medium-bg: #fefce8;
  --medium-border: #fde68a;
  --low: #059669;
  --low-bg: #ecfdf5;
  --low-border: #a7f3d0;
  --info: #7c3aed;
  --info-bg: #f5f3ff;
  --info-border: #ddd6fe;

  /* Stats card accent colors */
  --stat-1: #2563eb;
  --stat-2: #7c3aed;
  --stat-3: #059669;
  --stat-4: #ea580c;
  --stat-5: #dc2626;
}

/* Dark palette */
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --surface-2: #1c2128;
    --surface-3: #21262d;
    --border: #30363d;
    --border-light: #262c34;
    --text: #e6edf3;
    --text-secondary: #8b949e;
    --muted: #8b949e;
    --shadow-sm: 0 1px 2px rgba(0,0,0,.2);
    --shadow: 0 1px 3px rgba(0,0,0,.3), 0 1px 2px rgba(0,0,0,.2);
    --shadow-md: 0 4px 6px rgba(0,0,0,.3), 0 2px 4px rgba(0,0,0,.2);

    --accent: #58a6ff;
    --accent-light: #0d2847;
    --accent-dark: #79b8ff;

    --critical: #f85149;
    --critical-bg: #2d1114;
    --critical-border: #5c1d20;
    --high: #f0883e;
    --high-bg: #2d1a0e;
    --high-border: #5c3a1a;
    --medium: #d29922;
    --medium-bg: #2d240a;
    --medium-border: #5c4a14;
    --low: #3fb950;
    --low-bg: #0d2d17;
    --low-border: #1a5c2e;
    --info: #a371f7;
    --info-bg: #1a1030;
    --info-border: #3d2a6e;

    --stat-1: #58a6ff;
    --stat-2: #a371f7;
    --stat-3: #3fb950;
    --stat-4: #f0883e;
    --stat-5: #f85149;
  }
}

/* ============================================================
   Reset & Base
   ============================================================ */
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI",
        "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
a { color: var(--accent); text-decoration: none; transition: color .15s; }
a:hover { color: var(--accent-dark); }

/* ============================================================
   Header
   ============================================================ */
header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 10;
}
@supports (backdrop-filter: blur(12px)) {
  header {
    background: color-mix(in srgb, var(--surface) 88%, transparent);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
  }
}
.topbar {
  max-width: 1340px;
  margin: 0 auto;
  padding: 14px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.brand-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-icon {
  width: 34px; height: 34px;
  border-radius: var(--radius-sm);
  background: linear-gradient(135deg, var(--accent) 0%, #60a5fa 100%);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: 16px; font-weight: 800;
  flex-shrink: 0;
}
.brand {
  font-size: 18px; font-weight: 750; letter-spacing: -.01em; white-space: nowrap;
}
.brand-sub {
  color: var(--muted); font-size: 12px; font-weight: 500;
}
.timestamp {
  color: var(--muted); font-size: 12px;
  display: flex; align-items: center; gap: 6px;
}
.timestamp::before {
  content: ""; display: inline-block;
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--low); flex-shrink: 0;
}

/* ============================================================
   Layout
   ============================================================ */
main { max-width: 1340px; margin: 0 auto; padding: 24px 24px 48px; }

/* ============================================================
   Stats — Bento Grid cards
   ============================================================ */
.stats {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.metric {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 18px;
  position: relative; overflow: hidden;
  transition: transform .15s, box-shadow .15s;
  box-shadow: var(--shadow-sm);
}
.metric:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}
.metric::before {
  content: ""; position: absolute; top: 0; left: 0; right: 0; height: 3px;
}
.metric:nth-child(1)::before { background: var(--stat-1); }
.metric:nth-child(2)::before { background: var(--stat-2); }
.metric:nth-child(3)::before { background: var(--stat-3); }
.metric:nth-child(4)::before { background: var(--stat-4); }
.metric:nth-child(5)::before { background: var(--stat-5); }
.metric-icon { font-size: 18px; margin-bottom: 6px; opacity: .7; }
.metric strong {
  display: block; font-size: 26px; font-weight: 750;
  line-height: 1.15; letter-spacing: -.02em; color: var(--text);
}
.metric span {
  display: block; color: var(--text-secondary);
  font-size: 12.5px; font-weight: 500; margin-top: 2px;
}

/* ============================================================
   Toolbar
   ============================================================ */
.toolbar {
  display: grid;
  grid-template-columns: minmax(240px, 1.8fr) minmax(150px, .65fr) minmax(140px, .6fr) minmax(100px, .4fr);
  gap: 10px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 14px 16px; margin-bottom: 16px;
  box-shadow: var(--shadow-sm); align-items: end;
}
.toolbar label { display: grid; gap: 5px; color: var(--text-secondary); font-size: 12px; font-weight: 650; }
.toolbar input, .toolbar select {
  width: 100%; min-height: 38px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 7px 10px; background: var(--surface); color: var(--text);
  font: inherit; font-size: 13px;
  transition: border-color .15s, box-shadow .15s; outline: none;
}
.toolbar input:focus, .toolbar select:focus {
  border-color: var(--accent);
  outline: 2px solid var(--accent);
  outline-offset: -1px;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent);
}
.match-badge {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 38px; height: 30px; border-radius: 999px;
  background: var(--accent-light); color: var(--accent);
  font-size: 13px; font-weight: 700; padding: 0 10px;
}

/* ============================================================
   Panel & Table
   ============================================================ */
.panel {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.panel-head {
  display: flex; justify-content: space-between; align-items: center; gap: 14px;
  padding: 14px 18px; background: var(--surface-2); border-bottom: 1px solid var(--border);
}
.panel-head h1, .panel-head h2 {
  margin: 0; font-size: 15px; font-weight: 700; letter-spacing: -.01em;
}
.panel-head .count { color: var(--muted); font-size: 12.5px; }

table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td { padding: 12px 14px; border-bottom: 1px solid var(--border-light); vertical-align: top; }
th {
  text-align: left; color: var(--muted); background: var(--surface-2);
  font-size: 11.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em;
}
tbody tr { transition: background .1s; }
tbody tr:hover td { background: var(--surface-3); }
tbody tr:last-child td { border-bottom: none; }

/* Priority left-accent on rows */
tr.priority-critical { box-shadow: inset 3px 0 0 var(--critical); }
tr.priority-high     { box-shadow: inset 3px 0 0 var(--high); }
tr.priority-medium   { box-shadow: inset 3px 0 0 var(--medium); }
tr.priority-low      { box-shadow: inset 3px 0 0 var(--low); }

.title-col { width: 44%; }
.source-col { width: 140px; }
.date-col { width: 165px; }
.type-col { width: 130px; }
.priority-col { width: 95px; }

.article-title {
  color: var(--text); font-weight: 650; font-size: 13.5px;
  line-height: 1.4; transition: color .15s;
}
.article-title:hover { color: var(--accent); }
.summary {
  margin-top: 5px; color: var(--text-secondary); font-size: 12.5px;
  line-height: 1.5; overflow-wrap: anywhere;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}

/* ============================================================
   Pills / Badges
   ============================================================ */
.pill {
  display: inline-flex; align-items: center; min-height: 24px; max-width: 100%;
  border-radius: 999px; padding: 3px 9px; font-size: 11.5px; font-weight: 600;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  transition: opacity .15s;
}
.pill.source-pill {
  background: var(--surface-3); color: var(--text-secondary); border: 1px solid var(--border);
}
.pill.critical { background: var(--critical-bg); color: var(--critical); border: 1px solid var(--critical-border); }
.pill.high     { background: var(--high-bg);     color: var(--high);     border: 1px solid var(--high-border); }
.pill.medium   { background: var(--medium-bg);   color: var(--medium);   border: 1px solid var(--medium-border); }
.pill.low      { background: var(--low-bg);      color: var(--low);      border: 1px solid var(--low-border); }
.pill.info     { background: var(--info-bg);     color: var(--info);     border: 1px solid var(--info-border); }
.pill.ghost    { background: transparent;        color: var(--muted);    border: 1px solid var(--border); }

.empty { padding: 48px 18px; text-align: center; color: var(--muted); font-size: 14px; }

/* ============================================================
   Article Detail Layout
   ============================================================ */
.article-layout {
  display: grid; grid-template-columns: minmax(0, 1fr) 340px;
  gap: 16px; align-items: start;
}
.content, .side { display: grid; gap: 16px; align-content: start; }
.side { position: sticky; top: 80px; }

.section {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow-sm);
}
.section-body { padding: 18px; }
.section-body p { margin: 0 0 10px; line-height: 1.7; }
.section-body p:last-child { margin-bottom: 0; }

.meta-grid {
  display: grid; gap: 1px; background: var(--border-light);
  border-radius: var(--radius-sm); overflow: hidden;
}
.meta-row {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 12px; padding: 10px 14px; background: var(--surface);
}
.meta-row span {
  color: var(--muted); font-size: 12px; font-weight: 600; white-space: nowrap; flex-shrink: 0;
}
.meta-row strong {
  text-align: right; font-size: 13px; font-weight: 600; line-height: 1.5; word-break: break-all;
}

.key-points { margin: 0; padding-left: 20px; }
.key-points li { margin-bottom: 8px; line-height: 1.7; color: var(--text-secondary); }
.key-points li:last-child { margin-bottom: 0; }

pre {
  margin: 0; white-space: pre-wrap; overflow-wrap: anywhere;
  color: var(--text); font: inherit; font-size: 14px; line-height: 1.8;
}
.article-rich {
  line-height: 1.78;
  overflow-wrap: anywhere;
}
.article-rich > *:first-child { margin-top: 0; }
.article-rich > *:last-child { margin-bottom: 0; }
.article-rich p,
.article-rich ul,
.article-rich ol,
.article-rich blockquote,
.article-rich figure,
.article-rich table,
.article-rich pre { margin: 0 0 14px; }
.article-rich ul,
.article-rich ol { padding-left: 22px; }
.article-rich li { margin: 4px 0; }
.article-rich img {
  display: block;
  max-width: 100%;
  height: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  margin: 12px auto;
  background: var(--surface-2);
}
.article-rich figure { max-width: 100%; }
.article-rich figcaption {
  color: var(--muted);
  font-size: 12px;
  text-align: center;
  margin-top: -6px;
}
.article-rich blockquote {
  border-left: 3px solid var(--accent);
  background: var(--surface-2);
  padding: 10px 14px;
  color: var(--text-secondary);
}
.article-rich pre {
  overflow: auto;
  background: var(--surface-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 14px;
  line-height: 1.55;
}
.article-rich code {
  font-family: ui-monospace, SFMono-Regular, "Cascadia Code", Consolas, monospace;
  font-size: 12.5px;
}
.article-rich :not(pre) > code {
  background: var(--surface-3);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 5px;
}
.article-rich table {
  width: 100%;
  border-collapse: collapse;
  display: block;
  overflow-x: auto;
}
.article-rich th,
.article-rich td {
  border: 1px solid var(--border);
  padding: 8px 10px;
  text-align: left;
}
.article-rich th { background: var(--surface-2); }
.json-block {
  max-height: 520px; overflow: auto; background: var(--surface-3);
  border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 14px;
  font-family: ui-monospace, SFMono-Regular, "Cascadia Code", Consolas, monospace;
  font-size: 12.5px; line-height: 1.6;
}

/* ============================================================
   Buttons & Links
   ============================================================ */
.back-link {
  display: inline-flex; align-items: center; gap: 5px; font-weight: 650;
  font-size: 13px; padding: 7px 14px; border-radius: var(--radius-sm);
  background: var(--surface-3); border: 1px solid var(--border);
  color: var(--text-secondary); transition: all .15s;
}
.back-link:hover {
  background: var(--accent-light); color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 25%, transparent); text-decoration: none;
}
.external-link {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 8px 16px; border-radius: var(--radius-sm);
  background: var(--accent); color: #fff !important;
  font-weight: 650; font-size: 13px; transition: background .15s, transform .15s;
}
.external-link:hover { background: var(--accent-dark); transform: translateY(-1px); text-decoration: none; }
.view-toggle {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  background: var(--surface-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.view-toggle button {
  border: 0;
  border-radius: 4px;
  padding: 6px 12px;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}
.view-toggle button.active {
  background: var(--surface);
  color: var(--accent);
  box-shadow: var(--shadow-sm);
}
.article-panel[hidden] { display: none; }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }

/* ============================================================
   Responsive
   ============================================================ */
@media (max-width: 960px) {
  .stats { grid-template-columns: repeat(3, 1fr); }
  .stats .metric:last-child { grid-column: span 2; }
  .toolbar { grid-template-columns: 1fr 1fr; }
  .article-layout { grid-template-columns: 1fr; }
  .side { position: static; }
}
@media (max-width: 680px) {
  .stats { grid-template-columns: 1fr 1fr; }
  .stats .metric:last-child { grid-column: span 1; }
  .toolbar { grid-template-columns: 1fr; }
  .topbar { flex-direction: column; align-items: flex-start; gap: 10px; }
  .source-col, .type-col { display: none; }
  .title-col { width: auto; }
  .date-col { width: 120px; }
  .priority-col { width: 80px; }
  th, td { padding: 10px 10px; }
  main { padding: 16px 12px 36px; }
  .topbar { padding: 12px 16px; }
}
"""


# ---------------------------------------------------------------------------
# HTML rendering helpers
# ---------------------------------------------------------------------------

def base_html(title: str, body: str, extra_head: str = "") -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>{h(title)}</title>
  <style>{SHARED_CSS}</style>
  {extra_head}
</head>
<body>
{body}
</body>
</html>"""


def priority_class(value: str) -> str:
    normalized = (value or "").lower()
    if normalized in {"critical", "high", "medium", "low"}:
        return normalized
    return ""


def _stat_icon(index: int) -> str:
    icons = ["📰", "📡", "🤖", "🎯", "🔄"]
    return icons[index] if index < len(icons) else ""


def render_stats(rows: list[sqlite3.Row]) -> str:
    source_count = len({row["source_name"] for row in rows})
    ai_count = sum(1 for row in rows if row["ai_result_json"])
    duplicate_count = sum(1 for row in rows if row["duplicate_of_article_id"])
    cve_count = 0
    for row in rows:
        cve_count += len(normalize_list(row_ai(row).get("cves")))
    metrics = [
        ("文章", len(rows)),
        ("来源", source_count),
        ("AI 分析", ai_count),
        ("CVE", cve_count),
        ("重复", duplicate_count),
    ]
    cards = []
    for i, (label, value) in enumerate(metrics):
        cards.append(
            f'<div class="metric">'
            f'<div class="metric-icon">{_stat_icon(i)}</div>'
            f'<strong>{h(value)}</strong>'
            f'<span>{h(label)}</span>'
            f'</div>'
        )
    return '<section class="stats">' + "".join(cards) + "</section>"


def render_index(rows: list[sqlite3.Row], title: str) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sources = Counter(row["source_name"] for row in rows)
    priorities = Counter((row_ai(row).get("priority") or "unknown").lower() for row in rows)

    source_options = ['<option value="">全部来源</option>'] + [
        f'<option value="{h(source)}">{h(source)} ({count})</option>'
        for source, count in sorted(sources.items())
    ]
    priority_options = ['<option value="">全部优先级</option>'] + [
        f'<option value="{h(priority)}">{h(priority_label(priority))} ({count})</option>'
        for priority, count in sorted(priorities.items())
    ]

    rows_html = []
    for row in rows:
        ai = row_ai(row)
        priority = ai.get("priority") or "unknown"
        security_type = ai.get("security_type") or "security_news"
        brief = (
            ai.get("summary_zh")
            or ai.get("brief_zh")
            or row["summary"]
            or row["content_text"]
            or row["title"]
        )
        search_blob = " ".join(
            [
                row["title"] or "",
                row["summary"] or "",
                row["content_text"] or "",
                row["source_name"] or "",
                " ".join(normalize_list(ai.get("tags_zh"))),
                " ".join(normalize_list(ai.get("cves"))),
            ]
        ).lower()

        row_cls = f"priority-{priority_class(priority)}" if priority_class(priority) else ""

        rows_html.append(
            f'<tr class="{row_cls}" '
            f'data-source="{h(row["source_name"])}" '
            f'data-priority="{h(priority.lower())}" '
            f'data-search="{h(search_blob)}">'
            f'<td class="title-col"><a class="article-title" href="articles/{h(article_filename(row))}">'
            f'{h(row["title"])}</a><div class="summary">{h(compact(brief, 170))}</div></td>'
            f'<td class="source-col"><span class="pill source-pill">{h(row["source_name"])}</span></td>'
            f'<td class="date-col">{h(format_article_time(row["published_at"]))}</td>'
            f'<td class="type-col"><span class="pill ghost">{h(type_label(security_type))}</span></td>'
            f'<td class="priority-col"><span class="pill {h(priority_class(priority))}">'
            f'{h(priority_label(priority))}</span></td>'
            "</tr>"
        )

    table = (
        '<div class="empty">📭 暂无文章</div>'
        if not rows_html
        else (
            '<table id="articleTable"><thead><tr><th class="title-col">文章</th>'
            '<th class="source-col">来源</th><th class="date-col">时间</th>'
            '<th class="type-col">类型</th><th class="priority-col">优先级</th>'
            "</tr></thead><tbody>"
            + "".join(rows_html)
            + "</tbody></table>"
        )
    )

    body = f"""
<header>
  <div class="topbar">
    <div class="brand-group">
      <div class="brand-icon">S</div>
      <div>
        <div class="brand">{h(title)}</div>
        <div class="brand-sub">安全资讯聚合 · Security News Aggregator</div>
      </div>
    </div>
    <div class="timestamp">{h(generated_at)}</div>
  </div>
</header>
<main>
  {render_stats(rows)}
  <section class="toolbar">
    <label>🔍 搜索<input id="searchInput" type="search" placeholder="标题、摘要、标签、CVE 编号…"></label>
    <label>📡 来源<select id="sourceFilter">{"".join(source_options)}</select></label>
    <label>🚨 优先级<select id="priorityFilter">{"".join(priority_options)}</select></label>
    <label>匹配<span id="matchCount" class="match-badge">{len(rows)}</span></label>
  </section>
  <section class="panel">
    <div class="panel-head"><h1>📋 安全资讯</h1><span class="count">{len(rows)} 条</span></div>
    {table}
  </section>
</main>
<script>
const searchInput = document.getElementById('searchInput');
const sourceFilter = document.getElementById('sourceFilter');
const priorityFilter = document.getElementById('priorityFilter');
const matchCount = document.getElementById('matchCount');
const rows = Array.from(document.querySelectorAll('#articleTable tbody tr'));
function applyFilters() {{
  const query = (searchInput?.value || '').trim().toLowerCase();
  const source = sourceFilter?.value || '';
  const priority = priorityFilter?.value || '';
  let visible = 0;
  for (const row of rows) {{
    const okQuery = !query || row.dataset.search.includes(query);
    const okSource = !source || row.dataset.source === source;
    const okPriority = !priority || row.dataset.priority === priority;
    const show = okQuery && okSource && okPriority;
    row.style.display = show ? '' : 'none';
    if (show) visible += 1;
  }}
  if (matchCount) matchCount.textContent = String(visible);
}}
searchInput?.addEventListener('input', applyFilters);
sourceFilter?.addEventListener('change', applyFilters);
priorityFilter?.addEventListener('change', applyFilters);
</script>
"""
    return base_html(title, body)


def render_article(row: sqlite3.Row, title: str) -> str:
    ai = row_ai(row)
    categories = parse_categories(row)
    tags = normalize_list(ai.get("tags_zh"))
    cves = normalize_list(ai.get("cves"))
    priority = ai.get("priority") or "unknown"
    security_type = ai.get("security_type") or "security_news"
    brief = ai.get("summary_zh") or ai.get("brief_zh") or row["summary"] or ""
    translation = ai.get("translation_zh") or ""
    key_points = normalize_list(ai.get("key_points"))
    ai_json = json.dumps(ai, ensure_ascii=False, indent=2) if ai else "无"
    rich_content = sanitize_article_html(row["content_html"] or "", row["url"])
    if not rich_content:
        rich_content = f"<pre>{h(row['content_text'] or '无')}</pre>"
    view_toggle = ""
    translation_panel = ""
    view_script = ""
    if translation:
        view_toggle = """
        <div class="view-toggle">
          <button type="button" class="active" data-view="source">原文</button>
          <button type="button" data-view="translation">中文译文</button>
        </div>"""
        translation_panel = f"""
      <div id="translationPanel" class="article-panel" hidden>
        <pre>{h(translation)}</pre>
      </div>"""
        view_script = """
<script>
const viewButtons = Array.from(document.querySelectorAll('[data-view]'));
const sourcePanel = document.getElementById('sourcePanel');
const translationPanel = document.getElementById('translationPanel');
for (const button of viewButtons) {
  button.addEventListener('click', () => {
    const view = button.dataset.view;
    for (const item of viewButtons) item.classList.toggle('active', item === button);
    if (sourcePanel) sourcePanel.hidden = view !== 'source';
    if (translationPanel) translationPanel.hidden = view !== 'translation';
  });
}
</script>"""

    if key_points:
        points_html = '<ul class="key-points">' + "".join(
            f"<li>{h(point)}</li>" for point in key_points
        ) + "</ul>"
    else:
        points_html = '<span style="color:var(--muted);font-size:13px;">无</span>'

    tags_html = ""
    if tags:
        tags_html = '<div class="tag-list">' + "".join(
            f'<span class="pill info">{h(tag)}</span>' for tag in tags[:12]
        ) + "</div>"

    body = f"""
<header>
  <div class="topbar">
    <div class="brand-group">
      <div class="brand-icon">S</div>
      <div>
        <div class="brand">{h(title)}</div>
        <div class="brand-sub">安全资讯聚合</div>
      </div>
    </div>
    <a class="back-link" href="../index.html">← 返回列表</a>
  </div>
</header>
<main class="article-layout">
  <div class="content">
    <section class="section">
      <div class="panel-head"><h1>{h(row["title"])}</h1></div>
      <div class="section-body" style="line-height:1.8;">
        <p>{h(brief or compact(row["content_text"], 260))}</p>
        <a class="external-link" href="{h(row["url"])}" target="_blank" rel="noreferrer">🔗 查看原文</a>
      </div>
    </section>
    <section class="section">
      <div class="panel-head"><h2>🎯 重点摘要</h2></div>
      <div class="section-body">{points_html}</div>
    </section>
    <section class="section">
      <div class="panel-head"><h2>正文内容</h2>{view_toggle}</div>
      <div class="section-body">
        <div id="sourcePanel" class="article-panel article-rich">{rich_content}</div>
        {translation_panel}
      </div>
    </section>
    <section class="section">
      <div class="panel-head"><h2>🤖 AI 分析结果</h2></div>
      <div class="section-body"><pre class="json-block">{h(ai_json)}</pre></div>
    </section>
  </div>
  <aside class="side">
    <section class="section">
      <div class="panel-head"><h2>📋 元数据</h2></div>
      <div class="section-body" style="padding:0;">
        <div class="meta-grid">
          <div class="meta-row"><span>来源</span><strong>{h(row["source_name"])}</strong></div>
          <div class="meta-row"><span>发布时间</span><strong>{h(format_article_time(row["published_at"]))}</strong></div>
          <div class="meta-row"><span>作者</span><strong>{h(row["author"] or "无")}</strong></div>
          <div class="meta-row"><span>类型</span><strong>{h(type_label(security_type))}</strong></div>
          <div class="meta-row"><span>优先级</span><strong><span class="pill {h(priority_class(priority))}">{h(priority_label(priority))}</span></strong></div>
          <div class="meta-row"><span>CVE</span><strong>{h("、".join(cves) or "无")}</strong></div>
          <div class="meta-row"><span>分类</span><strong>{h("、".join(categories) or "无")}</strong></div>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="panel-head"><h2>🏷️ 标签</h2></div>
      <div class="section-body">
        {tags_html or '<span style="color:var(--muted);font-size:13px;">无</span>'}
      </div>
    </section>
  </aside>
</main>
{view_script}
"""
    return base_html(row["title"], body)


def write_static_site(
    db_path: Path,
    output_dir: Path = DEFAULT_SITE_DIR,
    limit: int = 300,
    include_duplicates: bool = False,
    title: str = "安全资讯",
) -> Path:
    rows = load_rows(db_path, limit=limit, include_duplicates=include_duplicates)
    articles_dir = output_dir / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)
    for old_page in articles_dir.glob("article-*.html"):
        old_page.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(render_index(rows, title), encoding="utf-8")
    for row in rows:
        (articles_dir / article_filename(row)).write_text(render_article(row, title), encoding="utf-8")
    return output_dir / "index.html"
