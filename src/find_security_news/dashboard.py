from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
import html
import json
import sqlite3

from .database import Database
from .time_format import format_article_time


DEFAULT_ARCHIVE_DIR = Path(__file__).resolve().parents[2] / "outputs" / "archive"
PAGE_SIZE_OPTIONS = (20, 50, 100, 200)


def h(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def parse_int(value: str, default: int, minimum: int = 1, maximum: int = 500) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def parse_record_time(row: sqlite3.Row) -> datetime:
    value = row["published_at"] or row["created_at"]
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    if len(value) == 10:
        return datetime.combine(date.fromisoformat(value), time.min, timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date_bound(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), time.min, timezone.utc)


def next_month(value: str) -> str:
    year, month = [int(part) for part in value.split("-", 1)]
    if month == 12:
        return f"{year + 1}-01"
    return f"{year}-{month + 1:02d}"


def row_ai(row: sqlite3.Row) -> dict:
    value = row["ai_result_json"]
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def truncate(value: str, limit: int = 180) -> str:
    value = " ".join((value or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


class DashboardStore:
    def __init__(self, db_path: Path, archive_dir: Path = DEFAULT_ARCHIVE_DIR) -> None:
        self.db_path = db_path
        self.archive_dir = archive_dir
        Database(db_path).init()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def stats(self) -> dict:
        with self.connect() as connection:
            article = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN duplicate_of_article_id IS NULL THEN 1 ELSE 0 END) AS unique_total,
                    SUM(CASE WHEN duplicate_of_article_id IS NOT NULL THEN 1 ELSE 0 END) AS duplicate_total,
                    MIN(COALESCE(NULLIF(published_at, ''), created_at)) AS oldest_at,
                    MAX(COALESCE(NULLIF(published_at, ''), created_at)) AS latest_at
                FROM articles
                """
            ).fetchone()
            ai_total = connection.execute("SELECT COUNT(*) AS total FROM ai_results").fetchone()
            source_total = connection.execute(
                "SELECT COUNT(DISTINCT source_name) AS total FROM articles"
            ).fetchone()
            return {
                "total": int(article["total"] or 0),
                "unique_total": int(article["unique_total"] or 0),
                "duplicate_total": int(article["duplicate_total"] or 0),
                "ai_total": int(ai_total["total"] or 0),
                "source_total": int(source_total["total"] or 0),
                "oldest_at": article["oldest_at"] or "",
                "latest_at": article["latest_at"] or "",
            }

    def source_counts(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT source_name, COUNT(*) AS total
                    FROM articles
                    GROUP BY source_name
                    ORDER BY total DESC, source_name ASC
                    """
                )
            )

    def list_articles(self, params: dict[str, str]) -> tuple[list[sqlite3.Row], int]:
        q = params.get("q", "").strip()
        source = params.get("source", "").strip()
        from_date = params.get("from", "").strip()
        to_date = params.get("to", "").strip()
        include_duplicates = params.get("duplicates") == "1"
        page = parse_int(params.get("page", "1"), 1, 1, 99999)
        limit = parse_int(params.get("limit", "50"), 50, 1, 500)
        offset = (page - 1) * limit

        where = []
        values: list[object] = []
        if not include_duplicates:
            where.append("a.duplicate_of_article_id IS NULL")
        if q:
            where.append("(a.title LIKE ? OR a.summary LIKE ? OR a.content_text LIKE ? OR a.url LIKE ?)")
            needle = f"%{q}%"
            values.extend([needle, needle, needle, needle])
        if source:
            where.append("a.source_name = ?")
            values.append(source)
        if from_date:
            where.append("substr(COALESCE(NULLIF(a.published_at, ''), a.created_at), 1, 10) >= ?")
            values.append(from_date)
        if to_date:
            where.append("substr(COALESCE(NULLIF(a.published_at, ''), a.created_at), 1, 10) < ?")
            values.append(to_date)
        clause = f"WHERE {' AND '.join(where)}" if where else ""

        with self.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) AS total FROM articles a {clause}",
                values,
            ).fetchone()["total"]
            rows = list(
                connection.execute(
                    f"""
                    SELECT a.*, r.result_json AS ai_result_json, r.model AS ai_model
                    FROM articles a
                    LEFT JOIN ai_results r ON r.article_id = a.id
                    {clause}
                    ORDER BY COALESCE(NULLIF(a.published_at, ''), a.created_at) DESC
                    LIMIT ? OFFSET ?
                    """,
                    [*values, limit, offset],
                )
            )
        return rows, int(total)

    def article(self, article_id: int) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT a.*, r.result_json AS ai_result_json, r.model AS ai_model
                FROM articles a
                LEFT JOIN ai_results r ON r.article_id = a.id
                WHERE a.id = ?
                """,
                (article_id,),
            ).fetchone()

    def all_rows(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT a.*, r.result_json AS ai_result_json, r.model AS ai_model
                    FROM articles a
                    LEFT JOIN ai_results r ON r.article_id = a.id
                    ORDER BY COALESCE(NULLIF(a.published_at, ''), a.created_at) ASC
                    """
                )
            )

    def month_buckets(self) -> dict[str, list[sqlite3.Row]]:
        buckets: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in self.all_rows():
            buckets[f"{parse_record_time(row):%Y-%m}"].append(row)
        return dict(sorted(buckets.items(), reverse=True))

    def select_cleanup_rows(self, form: dict[str, str]) -> tuple[list[sqlite3.Row], str]:
        mode = form.get("mode", "before")
        rows = self.all_rows()
        if mode == "month":
            month = form.get("month", "").strip()
            if not month:
                return [], ""
            since = parse_date_bound(f"{month}-01")
            until = parse_date_bound(f"{next_month(month)}-01")
            return rows_in_range(rows, since, until), month
        if mode == "range":
            from_value = form.get("from_date", "").strip()
            to_value = form.get("to_date", "").strip()
            if not from_value or not to_value:
                return [], ""
            since = parse_date_bound(from_value)
            until = parse_date_bound(to_value)
            return rows_in_range(rows, since, until), f"{from_value}_to_{to_value}"
        before = form.get("before", "").strip()
        if not before:
            return [], ""
        until = parse_date_bound(before)
        return rows_in_range(rows, None, until), f"before_{before}"

    def archive_rows(self, rows: list[sqlite3.Row], label: str) -> Path:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)
        path = self.archive_dir / f"security_news_archive_{safe_label}_{timestamp}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                data = dict(row)
                if data.get("ai_result_json"):
                    try:
                        data["ai_result"] = json.loads(data["ai_result_json"])
                    except json.JSONDecodeError:
                        data["ai_result"] = data["ai_result_json"]
                handle.write(json.dumps(data, ensure_ascii=False) + "\n")
        return path

    def delete_rows(self, rows: list[sqlite3.Row], vacuum: bool) -> None:
        ids = [int(row["id"]) for row in rows]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as connection:
            connection.execute(f"DELETE FROM ai_results WHERE article_id IN ({placeholders})", ids)
            connection.execute(f"DELETE FROM articles WHERE id IN ({placeholders})", ids)
            connection.commit()
            if vacuum:
                connection.execute("VACUUM")


def rows_in_range(
    rows: list[sqlite3.Row],
    since: datetime | None,
    until: datetime,
) -> list[sqlite3.Row]:
    selected = []
    for row in rows:
        record_time = parse_record_time(row)
        if since is not None and record_time < since:
            continue
        if record_time < until:
            selected.append(row)
    return selected


def base_html(title: str, active: str, body: str) -> str:
    nav_items = [
        ("articles", "/", "文章"),
        ("cleanup", "/cleanup", "清理"),
    ]
    nav = "".join(
        f'<a class="nav-link {"active" if key == active else ""}" href="{url}">{label}</a>'
        for key, url, label in nav_items
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --surface: #ffffff;
      --border: #d8dee7;
      --text: #18202b;
      --muted: #657184;
      --blue: #1f6feb;
      --blue-dark: #1858bd;
      --red: #c42b1c;
      --red-soft: #fcebea;
      --green: #16794c;
      --row: #fbfcfe;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      z-index: 5;
    }}
    .bar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      max-width: 1360px;
      margin: 0 auto;
      padding: 12px 20px;
    }}
    .brand {{ font-size: 17px; font-weight: 700; white-space: nowrap; }}
    nav {{ display: flex; align-items: center; gap: 4px; }}
    .nav-link {{
      color: var(--muted);
      text-decoration: none;
      padding: 7px 10px;
      border-radius: 6px;
      font-weight: 600;
    }}
    .nav-link.active {{ background: #eaf1ff; color: var(--blue-dark); }}
    main {{ max-width: 1360px; margin: 0 auto; padding: 18px 20px 32px; }}
    .toolbar, .panel, .stats {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    .toolbar {{
      display: grid;
      grid-template-columns: minmax(220px, 1.6fr) repeat(3, minmax(130px, .7fr)) auto;
      gap: 10px;
      align-items: end;
      padding: 12px;
      margin-bottom: 14px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(5, minmax(120px, 1fr));
      gap: 0;
      margin-bottom: 14px;
      overflow: hidden;
    }}
    .metric {{ padding: 12px 14px; border-right: 1px solid var(--border); }}
    .metric:last-child {{ border-right: 0; }}
    .metric-value {{ display: block; font-size: 22px; font-weight: 750; }}
    .metric-label {{ color: var(--muted); font-size: 12px; }}
    label {{ display: grid; gap: 4px; color: var(--muted); font-size: 12px; font-weight: 650; }}
    input, select {{
      width: 100%;
      min-height: 36px;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 7px 9px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }}
    .checkbox {{
      display: flex;
      align-items: center;
      gap: 7px;
      min-height: 36px;
      color: var(--text);
      font-size: 13px;
    }}
    .checkbox input {{ width: 16px; min-height: 16px; }}
    button, .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 36px;
      border: 1px solid var(--blue);
      border-radius: 6px;
      padding: 7px 12px;
      background: var(--blue);
      color: #fff;
      text-decoration: none;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }}
    button:hover, .button:hover {{ background: var(--blue-dark); }}
    button.secondary, .button.secondary {{ background: #fff; color: var(--blue); }}
    button.danger {{ background: var(--red); border-color: var(--red); }}
    .panel {{ margin-bottom: 14px; overflow: hidden; }}
    .panel-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      background: #fbfcfe;
    }}
    h1, h2 {{ margin: 0; font-size: 16px; line-height: 1.3; }}
    .muted {{ color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }}
    th {{ color: var(--muted); text-align: left; font-size: 12px; background: #fbfcfe; }}
    tr:nth-child(even) td {{ background: var(--row); }}
    .title-cell {{ width: 38%; }}
    .source-cell {{ width: 150px; }}
    .date-cell {{ width: 170px; }}
    .status-cell {{ width: 150px; }}
    .action-cell {{ width: 90px; text-align: right; }}
    .title-link {{ color: var(--text); font-weight: 700; text-decoration: none; }}
    .title-link:hover {{ color: var(--blue); }}
    .pill {{
      display: inline-flex;
      align-items: center;
      max-width: 100%;
      min-height: 24px;
      padding: 2px 7px;
      border-radius: 999px;
      background: #eef2f7;
      color: #344054;
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .pill.green {{ background: #e8f5ee; color: var(--green); }}
    .pill.red {{ background: var(--red-soft); color: var(--red); }}
    .grid-two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .form-grid {{ display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 10px; padding: 14px; }}
    .form-actions {{ display: flex; gap: 10px; align-items: end; }}
    .content {{ padding: 14px; }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: #f2f4f7;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      max-height: 520px;
      overflow: auto;
    }}
    .message {{ padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; background: #fff; margin-bottom: 14px; }}
    .message.error {{ border-color: #f0b8b2; background: var(--red-soft); color: #7d1a11; }}
    .pager {{ display: flex; justify-content: flex-end; gap: 8px; padding: 12px; }}
    @media (max-width: 900px) {{
      .toolbar, .form-grid, .grid-two, .stats {{ grid-template-columns: 1fr; }}
      .metric {{ border-right: 0; border-bottom: 1px solid var(--border); }}
      .metric:last-child {{ border-bottom: 0; }}
      th.source-cell, td.source-cell, th.status-cell, td.status-cell {{ display: none; }}
      .title-cell {{ width: auto; }}
      .date-cell {{ width: 120px; }}
      .bar {{ align-items: flex-start; flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <header><div class="bar"><div class="brand">findSecurityNews</div><nav>{nav}</nav></div></header>
  <main>{body}</main>
</body>
</html>"""


def query_link(path: str, params: dict[str, object]) -> str:
    clean = {key: value for key, value in params.items() if value not in ("", None, False)}
    return f"{path}?{urlencode(clean)}" if clean else path


def render_stats(store: DashboardStore) -> str:
    stats = store.stats()
    items = [
        ("文章总数", stats["total"]),
        ("唯一文章", stats["unique_total"]),
        ("重复记录", stats["duplicate_total"]),
        ("AI 结果", stats["ai_total"]),
        ("来源数", stats["source_total"]),
    ]
    return '<section class="stats">' + "".join(
        f'<div class="metric"><span class="metric-value">{h(value)}</span>'
        f'<span class="metric-label">{h(label)}</span></div>'
        for label, value in items
    ) + "</section>"


def render_articles(store: DashboardStore, params: dict[str, str]) -> str:
    rows, total = store.list_articles(params)
    page = parse_int(params.get("page", "1"), 1, 1, 99999)
    limit = parse_int(params.get("limit", "50"), 50, 1, 500)
    source = params.get("source", "")
    sources = store.source_counts()
    pages = max(1, (total + limit - 1) // limit)
    options = ['<option value="">全部来源</option>']
    for row in sources:
        selected = " selected" if source == row["source_name"] else ""
        options.append(
            f'<option value="{h(row["source_name"])}"{selected}>'
            f'{h(row["source_name"])} ({h(row["total"])})</option>'
        )
    limit_options = "".join(
        f'<option value="{size}"{" selected" if size == limit else ""}>{size}</option>'
        for size in PAGE_SIZE_OPTIONS
    )
    duplicates_checked = " checked" if params.get("duplicates") == "1" else ""
    body = f"""
{render_stats(store)}
<form class="toolbar" method="get" action="/">
  <label>搜索<input name="q" value="{h(params.get("q", ""))}" placeholder="标题、摘要、正文、链接"></label>
  <label>来源<select name="source">{"".join(options)}</select></label>
  <label>起始日期<input type="date" name="from" value="{h(params.get("from", ""))}"></label>
  <label>结束日期<input type="date" name="to" value="{h(params.get("to", ""))}"></label>
  <div class="form-actions">
    <label>每页<select name="limit">{limit_options}</select></label>
    <label class="checkbox"><input type="checkbox" name="duplicates" value="1"{duplicates_checked}>含重复</label>
    <button type="submit">筛选</button>
  </div>
</form>
<section class="panel">
  <div class="panel-head"><h1>文章列表</h1><span class="muted">{total} 条，当前第 {page}/{pages} 页</span></div>
  {render_article_table(rows)}
  {render_pager("/", params, page, pages)}
</section>
"""
    return base_html("文章 - findSecurityNews", "articles", body)


def render_article_table(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return '<div class="content muted">没有匹配记录。</div>'
    table_rows = []
    for row in rows:
        ai = row_ai(row)
        status = []
        if row["duplicate_of_article_id"]:
            status.append('<span class="pill red">重复</span>')
        else:
            status.append('<span class="pill green">唯一</span>')
        if ai:
            priority = ai.get("priority") or "AI"
            status.append(f'<span class="pill">{h(priority)}</span>')
        table_rows.append(
            "<tr>"
            f'<td class="title-cell"><a class="title-link" href="/article?id={h(row["id"])}">'
            f'{h(row["title"])}</a><div class="muted">{h(truncate(row["summary"] or row["content_text"], 150))}</div></td>'
            f'<td class="source-cell"><span class="pill">{h(row["source_name"])}</span></td>'
            f'<td class="date-cell">{h(format_article_time(row["published_at"]))}</td>'
            f'<td class="status-cell">{" ".join(status)}</td>'
            f'<td class="action-cell"><a class="button secondary" href="/article?id={h(row["id"])}">查看</a></td>'
            "</tr>"
        )
    return (
        '<table><thead><tr><th class="title-cell">标题</th><th class="source-cell">来源</th>'
        '<th class="date-cell">时间</th><th class="status-cell">状态</th>'
        '<th class="action-cell"></th></tr></thead><tbody>'
        + "".join(table_rows)
        + "</tbody></table>"
    )


def render_pager(path: str, params: dict[str, str], page: int, pages: int) -> str:
    if pages <= 1:
        return ""
    prev_params = {**params, "page": max(1, page - 1)}
    next_params = {**params, "page": min(pages, page + 1)}
    prev_class = "button secondary" if page > 1 else "button secondary muted"
    next_class = "button secondary" if page < pages else "button secondary muted"
    return (
        '<div class="pager">'
        f'<a class="{prev_class}" href="{h(query_link(path, prev_params))}">上一页</a>'
        f'<a class="{next_class}" href="{h(query_link(path, next_params))}">下一页</a>'
        "</div>"
    )


def render_article_detail(store: DashboardStore, article_id: int) -> str:
    row = store.article(article_id)
    if not row:
        return base_html("未找到 - findSecurityNews", "articles", '<div class="message error">文章不存在。</div>')
    categories = []
    try:
        categories = json.loads(row["categories_json"] or "[]")
    except json.JSONDecodeError:
        categories = []
    ai = row_ai(row)
    ai_text = json.dumps(ai, ensure_ascii=False, indent=2) if ai else "无"
    body = f"""
<section class="panel">
  <div class="panel-head"><h1>{h(row["title"])}</h1><a class="button secondary" href="/">返回</a></div>
  <div class="content grid-two">
    <div>
      <p><strong>来源：</strong>{h(row["source_name"])}</p>
      <p><strong>作者：</strong>{h(row["author"])}</p>
      <p><strong>发布时间：</strong>{h(format_article_time(row["published_at"]))}</p>
      <p><strong>链接：</strong><a href="{h(row["url"])}" target="_blank" rel="noreferrer">{h(row["url"])}</a></p>
      <p><strong>分类：</strong>{h("、".join(str(item) for item in categories))}</p>
      <p><strong>重复：</strong>{h(row["duplicate_of_article_id"] or "否")}</p>
    </div>
    <div>
      <p><strong>AI 模型：</strong>{h(row["ai_model"] or "无")}</p>
      <p><strong>重复分数：</strong>{h(row["duplicate_score"])}</p>
      <p><strong>重复原因：</strong>{h(row["duplicate_reason"])}</p>
    </div>
  </div>
</section>
<section class="panel">
  <div class="panel-head"><h2>摘要</h2></div>
  <div class="content"><pre>{h(row["summary"] or "无")}</pre></div>
</section>
<section class="panel">
  <div class="panel-head"><h2>正文</h2></div>
  <div class="content"><pre>{h(row["content_text"] or "无")}</pre></div>
</section>
<section class="panel">
  <div class="panel-head"><h2>AI 结果</h2></div>
  <div class="content"><pre>{h(ai_text)}</pre></div>
</section>
"""
    return base_html(row["title"], "articles", body)


def render_cleanup(store: DashboardStore, message: str = "", error: bool = False, preview: str = "") -> str:
    buckets = store.month_buckets()
    month_options = ['<option value="">选择月份</option>']
    for month, rows in buckets.items():
        month_options.append(f'<option value="{h(month)}">{h(month)} ({len(rows)})</option>')
    message_html = ""
    if message:
        message_html = f'<div class="message {"error" if error else ""}">{h(message)}</div>'
    body = f"""
{message_html}
{render_stats(store)}
<section class="panel">
  <div class="panel-head"><h1>数据清理</h1><span class="muted">归档目录：{h(store.archive_dir)}</span></div>
  <form method="post" action="/cleanup">
    <div class="form-grid">
      <label>模式
        <select name="mode">
          <option value="before">早于日期</option>
          <option value="range">日期范围</option>
          <option value="month">整月</option>
        </select>
      </label>
      <label>早于<input type="date" name="before"></label>
      <label>起始<input type="date" name="from_date"></label>
      <label>结束<input type="date" name="to_date"></label>
      <label>月份<select name="month">{"".join(month_options)}</select></label>
      <label>确认删除<input name="confirm" placeholder="DELETE"></label>
      <label class="checkbox"><input type="checkbox" name="vacuum" value="1">VACUUM</label>
      <div class="form-actions">
        <button type="submit" name="action" value="preview" class="secondary">预览</button>
        <button type="submit" name="action" value="delete" class="danger">归档并删除</button>
      </div>
    </div>
  </form>
</section>
<section class="panel">
  <div class="panel-head"><h2>可清理月份</h2></div>
  {render_bucket_table(buckets)}
</section>
{preview}
"""
    return base_html("清理 - findSecurityNews", "cleanup", body)


def render_bucket_table(buckets: dict[str, list[sqlite3.Row]]) -> str:
    if not buckets:
        return '<div class="content muted">暂无数据。</div>'
    rows = []
    for month, items in buckets.items():
        times = [parse_record_time(row) for row in items]
        sources = sorted({row["source_name"] for row in items})
        rows.append(
            "<tr>"
            f"<td>{h(month)}</td><td>{len(items)}</td>"
            f"<td>{h(min(times).strftime('%Y-%m-%d'))} 至 {h(max(times).strftime('%Y-%m-%d'))}</td>"
            f"<td>{h('、'.join(sources[:8]))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>月份</th><th>文章</th><th>范围</th><th>来源</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_cleanup_preview(rows: list[sqlite3.Row], label: str) -> str:
    if not rows:
        return '<section class="panel"><div class="content muted">没有匹配清理记录。</div></section>'
    times = [parse_record_time(row) for row in rows]
    with_ai = sum(1 for row in rows if row["ai_result_json"])
    summary = (
        f"{len(rows)} 条；AI 结果 {with_ai} 条；"
        f"{min(times):%Y-%m-%d} 至 {max(times):%Y-%m-%d}；标签 {label}"
    )
    return (
        '<section class="panel"><div class="panel-head">'
        f"<h2>清理预览</h2><span class=\"muted\">{h(summary)}</span></div>"
        f"{render_article_table(rows[:100])}</section>"
    )


def handle_cleanup_post(store: DashboardStore, form: dict[str, str]) -> str:
    try:
        rows, label = store.select_cleanup_rows(form)
    except ValueError as exc:
        return render_cleanup(store, f"日期格式无效：{exc}", error=True)
    action = form.get("action", "preview")
    preview = render_cleanup_preview(rows, label)
    if action == "preview":
        return render_cleanup(store, preview=preview)
    if not rows:
        return render_cleanup(store, "没有匹配清理记录。", error=True)
    if form.get("confirm", "").strip() != "DELETE":
        return render_cleanup(store, "确认删除需要输入 DELETE。", error=True, preview=preview)
    archive_path = store.archive_rows(rows, label or "selected")
    store.delete_rows(rows, vacuum=form.get("vacuum") == "1")
    return render_cleanup(store, f"已归档并删除 {len(rows)} 条记录：{archive_path}")


def parse_params(query: str) -> dict[str, str]:
    parsed = parse_qs(query, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def make_handler(store: DashboardStore):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_params(parsed.query)
            if parsed.path == "/":
                self.respond_html(render_articles(store, params))
                return
            if parsed.path == "/article":
                article_id = parse_int(params.get("id", "0"), 0, 0, 999999999)
                self.respond_html(render_article_detail(store, article_id))
                return
            if parsed.path == "/cleanup":
                self.respond_html(render_cleanup(store))
                return
            self.respond_html(base_html("未找到", "articles", '<div class="message error">页面不存在。</div>'), HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            length = parse_int(self.headers.get("Content-Length", "0"), 0, 0, 2_000_000)
            payload = self.rfile.read(length).decode("utf-8", errors="replace")
            form = parse_params(payload)
            if parsed.path == "/cleanup":
                self.respond_html(handle_cleanup_post(store, form))
                return
            self.respond_html(base_html("未找到", "articles", '<div class="message error">页面不存在。</div>'), HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            print(f"{self.address_string()} - {format % args}")

        def respond_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = body.encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return DashboardHandler


def run_dashboard(db_path: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    store = DashboardStore(db_path)
    server = ThreadingHTTPServer((host, port), make_handler(store))
    print(f"Dashboard running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("")
    finally:
        server.server_close()
    return 0
