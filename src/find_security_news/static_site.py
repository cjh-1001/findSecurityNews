from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import html
import json
import sqlite3

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
        "critical": "关键",
        "high": "高",
        "medium": "中",
        "low": "低",
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


def shared_css() -> str:
    return """
:root {
  color-scheme: light;
  --bg: #f6f7f9;
  --surface: #ffffff;
  --surface-2: #fbfcfe;
  --border: #d9e0ea;
  --text: #151d2a;
  --muted: #667386;
  --blue: #1f6feb;
  --blue-dark: #174ea6;
  --red: #bf2c20;
  --green: #137a4c;
  --yellow: #8a5b00;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
a { color: var(--blue); text-decoration: none; }
a:hover { color: var(--blue-dark); text-decoration: underline; }
header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 4;
}
.topbar {
  max-width: 1320px;
  margin: 0 auto;
  padding: 14px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.brand { font-size: 18px; font-weight: 750; white-space: nowrap; }
.timestamp { color: var(--muted); font-size: 12px; }
main { max-width: 1320px; margin: 0 auto; padding: 18px 20px 34px; }
.stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 14px;
}
.metric { padding: 13px 14px; border-right: 1px solid var(--border); }
.metric:last-child { border-right: 0; }
.metric strong { display: block; font-size: 22px; line-height: 1.2; }
.metric span { color: var(--muted); font-size: 12px; }
.toolbar {
  display: grid;
  grid-template-columns: minmax(220px, 1.7fr) minmax(160px, .7fr) minmax(140px, .6fr) minmax(140px, .6fr);
  gap: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 14px;
}
label { display: grid; gap: 4px; color: var(--muted); font-size: 12px; font-weight: 650; }
input, select {
  width: 100%;
  min-height: 36px;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 7px 9px;
  background: #fff;
  color: var(--text);
  font: inherit;
}
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border);
}
h1, h2 { margin: 0; font-size: 16px; line-height: 1.35; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td { padding: 11px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { text-align: left; color: var(--muted); background: var(--surface-2); font-size: 12px; }
.title-col { width: 42%; }
.source-col { width: 160px; }
.date-col { width: 170px; }
.type-col { width: 150px; }
.priority-col { width: 110px; }
.article-title { color: var(--text); font-weight: 750; }
.summary { margin-top: 4px; color: var(--muted); overflow-wrap: anywhere; }
.pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  max-width: 100%;
  border-radius: 999px;
  padding: 2px 8px;
  background: #edf1f7;
  color: #344054;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pill.critical { background: #fcebea; color: var(--red); }
.pill.high { background: #fff2d6; color: var(--yellow); }
.pill.medium { background: #eaf1ff; color: var(--blue-dark); }
.pill.low { background: #e8f5ee; color: var(--green); }
.empty { padding: 18px; color: var(--muted); }
.article-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 14px;
}
.content, .side { display: grid; gap: 14px; align-content: start; }
.section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.section-body { padding: 14px; }
.meta-grid { display: grid; gap: 10px; }
.meta-row { display: grid; gap: 2px; }
.meta-row span { color: var(--muted); font-size: 12px; font-weight: 650; }
pre {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--text);
  font: inherit;
}
.json {
  max-height: 520px;
  overflow: auto;
  background: #f2f4f7;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
}
.back { font-weight: 700; }
@media (max-width: 920px) {
  .stats, .toolbar, .article-layout { grid-template-columns: 1fr; }
  .metric { border-right: 0; border-bottom: 1px solid var(--border); }
  .metric:last-child { border-bottom: 0; }
  .source-col, .type-col { display: none; }
  .title-col { width: auto; }
  .date-col { width: 130px; }
  .priority-col { width: 90px; }
  .topbar { align-items: flex-start; flex-direction: column; }
}
"""


def base_html(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title)}</title>
  <style>{shared_css()}</style>
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
        ("AI 结果", ai_count),
        ("CVE", cve_count),
        ("重复", duplicate_count),
    ]
    return '<section class="stats">' + "".join(
        f"<div class=\"metric\"><strong>{h(value)}</strong><span>{h(label)}</span></div>"
        for label, value in metrics
    ) + "</section>"


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
            ai.get("brief_zh")
            or ai.get("summary_zh")
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
        rows_html.append(
            "<tr "
            f'data-source="{h(row["source_name"])}" '
            f'data-priority="{h(priority.lower())}" '
            f'data-search="{h(search_blob)}">'
            f'<td class="title-col"><a class="article-title" href="articles/{h(article_filename(row))}">'
            f'{h(row["title"])}</a><div class="summary">{h(compact(brief, 170))}</div></td>'
            f'<td class="source-col"><span class="pill">{h(row["source_name"])}</span></td>'
            f'<td class="date-col">{h(format_article_time(row["published_at"]))}</td>'
            f'<td class="type-col"><span class="pill">{h(type_label(security_type))}</span></td>'
            f'<td class="priority-col"><span class="pill {h(priority_class(priority))}">'
            f'{h(priority_label(priority))}</span></td>'
            "</tr>"
        )
    table = (
        '<div class="empty">暂无文章。</div>'
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
<header><div class="topbar"><div class="brand">{h(title)}</div><div class="timestamp">生成时间 {h(generated_at)}</div></div></header>
<main>
  {render_stats(rows)}
  <section class="toolbar">
    <label>搜索<input id="searchInput" type="search" placeholder="标题、摘要、标签、CVE"></label>
    <label>来源<select id="sourceFilter">{"".join(source_options)}</select></label>
    <label>优先级<select id="priorityFilter">{"".join(priority_options)}</select></label>
    <label>匹配<span id="matchCount" class="pill">{len(rows)}</span></label>
  </section>
  <section class="panel">
    <div class="panel-head"><h1>安全资讯</h1><span class="timestamp">{len(rows)} 条</span></div>
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
    brief = ai.get("brief_zh") or ai.get("summary_zh") or row["summary"] or ""
    translation = ai.get("translation_zh") or ""
    key_points = normalize_list(ai.get("key_points"))
    ai_json = json.dumps(ai, ensure_ascii=False, indent=2) if ai else "无"
    points_html = (
        "<ul>" + "".join(f"<li>{h(point)}</li>" for point in key_points) + "</ul>"
        if key_points
        else '<span class="timestamp">无</span>'
    )
    body = f"""
<header><div class="topbar"><div class="brand">{h(title)}</div><a class="back" href="../index.html">返回列表</a></div></header>
<main class="article-layout">
  <div class="content">
    <section class="section">
      <div class="panel-head"><h1>{h(row["title"])}</h1></div>
      <div class="section-body">
        <p>{h(brief or compact(row["content_text"], 260))}</p>
        <p><a href="{h(row["url"])}" target="_blank" rel="noreferrer">原文链接</a></p>
      </div>
    </section>
    <section class="section">
      <div class="panel-head"><h2>重点</h2></div>
      <div class="section-body">{points_html}</div>
    </section>
    <section class="section">
      <div class="panel-head"><h2>正文</h2></div>
      <div class="section-body"><pre>{h(translation or row["content_text"] or "无")}</pre></div>
    </section>
    <section class="section">
      <div class="panel-head"><h2>AI 结果</h2></div>
      <div class="section-body"><pre class="json">{h(ai_json)}</pre></div>
    </section>
  </div>
  <aside class="side">
    <section class="section">
      <div class="panel-head"><h2>元数据</h2></div>
      <div class="section-body meta-grid">
        <div class="meta-row"><span>来源</span><strong>{h(row["source_name"])}</strong></div>
        <div class="meta-row"><span>发布时间</span><strong>{h(format_article_time(row["published_at"]))}</strong></div>
        <div class="meta-row"><span>作者</span><strong>{h(row["author"] or "无")}</strong></div>
        <div class="meta-row"><span>类型</span><strong>{h(type_label(security_type))}</strong></div>
        <div class="meta-row"><span>优先级</span><strong>{h(priority_label(priority))}</strong></div>
        <div class="meta-row"><span>CVE</span><strong>{h("、".join(cves) or "无")}</strong></div>
        <div class="meta-row"><span>标签</span><strong>{h("、".join(tags) or "无")}</strong></div>
        <div class="meta-row"><span>分类</span><strong>{h("、".join(categories) or "无")}</strong></div>
      </div>
    </section>
  </aside>
</main>
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
