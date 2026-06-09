from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
import sys
import threading
from time import sleep

from .ai import AIProcessor
from .bianews import parse_bianews_index
from .config import load_sources
from .database import Database
from .digest import write_digest
from .feishu import send_text, truncate
from .http_client import fetch_text, post_text
from .rss import parse_rss
from .sitemap import article_from_html, parse_html_index, parse_sitemap
from .time_format import format_article_time


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "sources.toml"
DEFAULT_DB = ROOT / "data" / "security_news.db"
DEFAULT_DIGEST_DIR = ROOT / "outputs" / "daily"
DEFAULT_SITE_DIR = ROOT / "outputs" / "site"
LOCAL_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="findSecurityNews")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db")

    collect = subparsers.add_parser("collect")
    collect.add_argument("--source", default="")
    collect.add_argument("--limit", type=int, default=10)
    collect.add_argument("--ai", action="store_true")
    collect.add_argument("--digest", action="store_true")

    list_cmd = subparsers.add_parser("list")
    list_cmd.add_argument("--limit", type=int, default=20)
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.add_argument("--include-duplicates", action="store_true")

    ai_cmd = subparsers.add_parser("process-ai")
    ai_cmd.add_argument("--limit", type=int, default=10)
    ai_cmd.add_argument("--force", action="store_true")

    digest_cmd = subparsers.add_parser("digest")
    digest_cmd.add_argument("--limit", type=int, default=20)
    digest_cmd.add_argument("--output-dir", type=Path, default=DEFAULT_DIGEST_DIR)

    export_cmd = subparsers.add_parser("export-html")
    export_cmd.add_argument("--limit", type=int, default=300)
    export_cmd.add_argument("--output-dir", type=Path, default=DEFAULT_SITE_DIR)
    export_cmd.add_argument("--include-duplicates", action="store_true")
    export_cmd.add_argument("--title", default="安全资讯")

    dedup_cmd = subparsers.add_parser("dedup")
    dedup_cmd.add_argument("--limit", type=int, default=1000)

    dashboard_cmd = subparsers.add_parser("dashboard")
    dashboard_cmd.add_argument("--host", default="127.0.0.1")
    dashboard_cmd.add_argument("--port", type=int, default=8000)

    feishu_cmd = subparsers.add_parser("push-feishu")
    feishu_cmd.add_argument("--limit", type=int, default=8)
    feishu_cmd.add_argument("--batch-size", type=int, default=20)
    feishu_cmd.add_argument("--date", default="")
    feishu_cmd.add_argument(
        "--window",
        choices=["latest", "day", "morning", "evening"],
        default="latest",
    )
    feishu_cmd.add_argument("--no-empty-message", action="store_true")
    feishu_cmd.add_argument("--webhook-env", default="FEISHU_WEBHOOK")
    feishu_cmd.add_argument("--secret-env", default="FEISHU_SECRET")

    workflow_cmd = subparsers.add_parser("feishu-workflow")
    workflow_cmd.add_argument("--collect-limit", type=int, default=30)
    workflow_cmd.add_argument("--push-limit", type=int, default=20)
    workflow_cmd.add_argument("--batch-size", type=int, default=20)
    workflow_cmd.add_argument("--date", default="")
    workflow_cmd.add_argument("--ai", action="store_true")
    workflow_cmd.add_argument(
        "--window",
        choices=["latest", "day", "morning", "evening"],
        default="latest",
    )
    workflow_cmd.add_argument("--no-empty-message", action="store_true")
    workflow_cmd.add_argument("--webhook-env", default="FEISHU_WEBHOOK")
    workflow_cmd.add_argument("--secret-env", default="FEISHU_SECRET")
    return parser


def _fetch_source(source, limit: int) -> tuple[object, list]:
    """Fetch articles from one source. Returns (source, articles)."""
    articles: list = []
    if source.type == "rss":
        xml_text = fetch_text(source.url)
        rss_articles = parse_rss(source, xml_text, limit=limit)
        articles = fetch_full_articles(source, rss_articles)
    elif source.type == "rss_html":
        xml_text = fetch_text(source.url)
        rss_articles = parse_rss(source, xml_text, limit=limit)
        articles = fetch_full_articles(source, rss_articles)
    elif source.type == "rsshub":
        xml_text = fetch_text(source.url)
        articles = parse_rss(source, xml_text, limit=limit)
    elif source.type == "sitemap":
        xml_text = fetch_text(source.url)
        entries = parse_sitemap(source, xml_text, limit=limit)
        for index, entry in enumerate(entries, start=1):
            print(f"  [{source.name}] Fetching article {index}/{len(entries)}: {entry.url}", flush=True)
            try:
                html = fetch_text(entry.url, timeout=30, retries=1)
            except RuntimeError as exc:
                print(f"  [{source.name}] Skipping: {entry.url} ({exc})", file=sys.stderr, flush=True)
                continue
            article = article_from_html(source, entry.url, html, published_at=entry.lastmod)
            if article.url and article.title:
                articles.append(article)
            if index < len(entries):
                sleep(1)
    elif source.type == "html_index":
        html = fetch_text(source.url)
        entries = parse_html_index(source, html, limit=limit)
        for index, entry in enumerate(entries, start=1):
            print(f"  [{source.name}] Fetching article {index}/{len(entries)}: {entry.url}", flush=True)
            try:
                article_html = fetch_text(entry.url, timeout=30, retries=1)
            except RuntimeError as exc:
                print(f"  [{source.name}] Skipping: {entry.url} ({exc})", file=sys.stderr, flush=True)
                continue
            article = article_from_html(source, entry.url, article_html, published_at=entry.lastmod)
            if article.url and article.title:
                articles.append(article)
            if index < len(entries):
                sleep(1)
    elif source.type == "bianews_ai":
        list_html = post_text(
            source.url,
            data={"page_no": 1, "page_size": limit},
            referer=source.homepage,
        )
        entries = parse_bianews_index(source, list_html, limit=limit)
        for index, entry in enumerate(entries, start=1):
            print(f"  [{source.name}] Fetching article {index}/{len(entries)}: {entry.url}", flush=True)
            try:
                article_html = fetch_text(entry.url, timeout=30, retries=1)
            except RuntimeError as exc:
                print(f"  [{source.name}] Skipping: {entry.url} ({exc})", file=sys.stderr, flush=True)
                continue
            article = article_from_html(source, entry.url, article_html, published_at=entry.lastmod)
            article = article.__class__(
                **{
                    **article.__dict__,
                    "title": article.title or entry.title,
                    "summary": article.summary or entry.summary,
                    "categories": article.categories or entry.categories,
                }
            )
            if article.url and article.title:
                articles.append(article)
            if index < len(entries):
                sleep(1)
    else:
        print(f"[{source.name}] Skipping unsupported source type: {source.type}", file=sys.stderr, flush=True)
    return source, articles


def collect(args: argparse.Namespace, db: Database) -> int:
    sources = load_sources(args.config)
    if args.source:
        sources = [source for source in sources if source.name == args.source]
    if not sources:
        print("No enabled sources matched.", file=sys.stderr)
        return 1

    ai = AIProcessor()

    # ── Phase 1: Fetch all sources concurrently ──
    print(f"Fetching {len(sources)} sources in parallel (max 5) ...", flush=True)
    all_articles: list[tuple] = []  # (source, article)
    failed_sources = 0

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_source, s, args.limit): s for s in sources}
        for future in as_completed(futures):
            source = futures[future]
            try:
                src, articles = future.result()
                all_articles.extend((src, a) for a in articles)
                print(f"[{src.name}] Done: {len(articles)} articles", flush=True)
            except RuntimeError as exc:
                failed_sources += 1
                print(f"[{source.name}] Skipping source fetch failure: {exc}", file=sys.stderr, flush=True)

    # ── Phase 2: Store in DB ──
    print(f"\nStoring {len(all_articles)} articles ...", flush=True)
    collected = 0
    inserted = 0
    duplicates = 0
    articles_for_ai: list[tuple[int, object]] = []  # (article_id, article)

    for src, article in all_articles:
        article_id, is_new, is_duplicate = db.upsert_article(article)
        collected += 1
        inserted += int(is_new and not is_duplicate)
        duplicates += int(is_duplicate)
        if args.ai and is_new and not is_duplicate:
            articles_for_ai.append((article_id, article))

    print(
        f"Stored {collected} articles, {inserted} new unique, {duplicates} duplicates.",
        flush=True,
    )

    # ── Phase 3: AI analyze concurrently ──
    if articles_for_ai:
        print(f"\nAI analyzing {len(articles_for_ai)} articles in parallel (max 3) ...", flush=True)
        ai_total = len(articles_for_ai)
        ai_done = [0]
        ai_lock = threading.Lock()

        def analyze_one(article_id, article):
            print(f"  AI: {article.title[:60]}...", flush=True)
            result = ai.analyze(article.title, article.content_text, article.categories)
            db.save_ai_result(article_id, ai.model if ai.enabled else "heuristic", result)
            with ai_lock:
                ai_done[0] += 1
            print(f"  AI done ({ai_done[0]}/{ai_total}): {article.title[:50]}", flush=True)
            return result

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(analyze_one, aid, a) for aid, a in articles_for_ai
            ]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    print(f"  AI error: {exc}", file=sys.stderr, flush=True)

    print(
        f"\nDone: {len(sources)} sources, {collected} articles, "
        f"{inserted} new, {duplicates} duplicates.",
        flush=True,
    )
    if args.digest:
        path = write_digest(db.list_articles(limit=args.limit), DEFAULT_DIGEST_DIR)
        print(f"Digest written: {path}")
    if failed_sources and collected == 0:
        return 1
    return 0


def fetch_full_articles(source, rss_articles):
    articles = []
    for index, rss_article in enumerate(rss_articles, start=1):
        print(f"  [{source.name}] article {index}/{len(rss_articles)}: {rss_article.url}", flush=True)
        try:
            article_html = fetch_text(rss_article.url, timeout=30, retries=1)
        except RuntimeError as exc:
            print(
                f"Skipping article fetch failure: {rss_article.url} ({exc})",
                file=sys.stderr,
            )
            articles.append(rss_article)
            continue
        page_article = article_from_html(
            source,
            rss_article.url,
            article_html,
            published_at=rss_article.published_at,
        )
        article = merge_article(rss_article, page_article)
        if article.url and article.title:
            articles.append(article)
        if index < len(rss_articles):
            sleep(1)
    return articles


def merge_article(rss_article, page_article):
    page_text = page_article.content_text or ""
    rss_text = rss_article.content_text or ""
    use_page_content = len(page_text) >= max(200, int(len(rss_text) * 0.8))
    return page_article.__class__(
        source_name=page_article.source_name or rss_article.source_name,
        url=page_article.url or rss_article.url,
        title=page_article.title or rss_article.title,
        author=page_article.author or rss_article.author,
        published_at=page_article.published_at or rss_article.published_at,
        summary=page_article.summary or rss_article.summary,
        content_html=(
            page_article.content_html
            if use_page_content
            else (rss_article.content_html or page_article.content_html)
        ),
        content_text=page_text if use_page_content else (rss_text or page_text),
        categories=page_article.categories or rss_article.categories,
    )


def list_articles(args: argparse.Namespace, db: Database) -> int:
    rows = db.list_articles(limit=args.limit, include_duplicates=args.include_duplicates)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": row["id"],
                        "source_name": row["source_name"],
                        "title": row["title"],
                        "url": row["url"],
                        "published_at": row["published_at"],
                        "duplicate_of_article_id": row["duplicate_of_article_id"],
                        "duplicate_score": row["duplicate_score"],
                    }
                    for row in rows
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    for row in rows:
        duplicate = ""
        if row["duplicate_of_article_id"]:
            duplicate = f" duplicate_of={row['duplicate_of_article_id']} score={row['duplicate_score']:.2f}"
        print(f"[{row['published_at']}] {row['title']}")
        print(f"  {row['url']}{duplicate}")
    return 0


def process_ai(args: argparse.Namespace, db: Database) -> int:
    ai = AIProcessor()
    rows = db.articles_for_ai(limit=args.limit, force=args.force)
    fallback_count = 0
    for row in rows:
        categories = json.loads(row["categories_json"])
        result = ai.analyze(row["title"], row["content_text"], categories)
        if result.get("ai_error"):
            fallback_count += 1
        db.save_ai_result(row["id"], ai.model if ai.enabled else "heuristic", result)
    engine = ai.model if ai.enabled else "heuristic"
    print(f"Processed AI for {len(rows)} articles using {engine}.")
    if fallback_count:
        print(f"Fallback heuristic used for {fallback_count} articles because the API call failed.")
    return 0


def digest(args: argparse.Namespace, db: Database) -> int:
    path = write_digest(db.list_articles(limit=args.limit), args.output_dir)
    print(f"Digest written: {path}")
    return 0


def dedup(args: argparse.Namespace, db: Database) -> int:
    scanned, marked = db.mark_existing_duplicates(limit=args.limit)
    print(f"Dedup scanned {scanned} articles, marked {marked} duplicates.")
    return 0


def parse_local_date(value: str) -> date:
    if value:
        return date.fromisoformat(value)
    return datetime.now(LOCAL_TZ).date()


def window_bounds(window: str, value: str = "") -> tuple[datetime | None, datetime | None, str]:
    target = parse_local_date(value)
    if window == "latest":
        return None, None, "最新文章"
    if window == "day":
        since = datetime.combine(target, time(0, 0), LOCAL_TZ)
        until = since + timedelta(days=1)
        return since, until, f"{target.isoformat()} 全天"
    if window == "morning":
        since = datetime.combine(target - timedelta(days=1), time(20, 0), LOCAL_TZ)
        until = datetime.combine(target, time(8, 0), LOCAL_TZ)
        return since, until, f"{since:%Y-%m-%d %H:%M} - {until:%Y-%m-%d %H:%M}"
    if window == "evening":
        since = datetime.combine(target, time(8, 0), LOCAL_TZ)
        until = datetime.combine(target, time(20, 0), LOCAL_TZ)
        return since, until, f"{since:%Y-%m-%d %H:%M} - {until:%Y-%m-%d %H:%M}"
    raise ValueError(f"Unknown window: {window}")


def parse_article_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL_TZ)


def filter_rows_by_window(rows, window: str, value: str = ""):
    since, until, label = window_bounds(window, value)
    if since is None or until is None:
        return rows, label
    filtered = []
    for row in rows:
        published = parse_article_time(row["published_at"])
        if published and since <= published < until:
            filtered.append(row)
    return filtered, label


def normalize_text_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


def parse_categories(row) -> list[str]:
    try:
        categories = json.loads(row["categories_json"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return []
    return normalize_text_list(categories)


SECURITY_TYPE_SCORES = {
    "vulnerability": 80,
    "ransomware": 55,
    "malware": 45,
    "threat_intelligence": 40,
    "incident": 30,
    "security_news": 15,
}

SECURITY_KEYWORD_SCORES = {
    "cve-": 70,
    "漏洞": 65,
    "vulnerability": 65,
    "vulnerabilities": 65,
    "zero-day": 60,
    "0day": 60,
    "rce": 60,
    "remote code execution": 60,
    "在野利用": 55,
    "exploited in the wild": 55,
    "actively exploited": 55,
    "kev": 50,
    "cisa": 45,
    "poc": 45,
    "exploit": 45,
    "patch": 35,
    "补丁": 35,
    "critical": 35,
    "严重": 35,
    "高危": 35,
    "cvss": 30,
    "ransomware": 25,
    "勒索": 25,
    "malware": 20,
    "恶意软件": 20,
    "apt": 20,
}

LOW_PRIORITY_KEYWORDS = {
    "funding": 20,
    "融资": 20,
    "appointment": 15,
    "partnership": 15,
    "webinar": 15,
    "conference": 15,
}


def feishu_priority_score(row) -> int:
    ai = row_ai(row)
    score = SECURITY_TYPE_SCORES.get(str(ai.get("security_type", "")).lower(), 0)

    cves = normalize_text_list(ai.get("cves"))
    if cves:
        score += 80 + min(len(cves), 3) * 10

    priority = str(ai.get("priority", "")).lower()
    if priority in {"critical", "high"}:
        score += 35
    elif priority == "medium":
        score += 15

    text_parts = [
        row["title"] or "",
        row["summary"] or "",
        (row["content_text"] or "")[:3000],
        " ".join(parse_categories(row)),
        str(ai.get("brief_zh", "")),
        str(ai.get("summary_zh", "")),
        " ".join(normalize_text_list(ai.get("tags_zh"))),
    ]
    searchable = " ".join(part for part in text_parts if part).lower()
    for keyword, value in SECURITY_KEYWORD_SCORES.items():
        if keyword in searchable:
            score += value
    for keyword, value in LOW_PRIORITY_KEYWORDS.items():
        if keyword in searchable:
            score -= value
    return score


def prioritize_feishu_rows(rows):
    indexed_rows = list(enumerate(rows))
    indexed_rows.sort(key=lambda item: (-feishu_priority_score(item[1]), item[0]))
    return [row for _, row in indexed_rows]


def chunk_rows(rows, batch_size: int):
    batch_size = max(batch_size, 1)
    for start in range(0, len(rows), batch_size):
        yield start, rows[start : start + batch_size]


def build_feishu_text(
    rows,
    range_label: str = "",
    batch_label: str = "",
    start_index: int = 1,
) -> str:
    lines = ["安全资讯简报"]
    if range_label:
        lines.extend([f"时间窗口: {range_label}"])
    if batch_label:
        lines.append(f"批次: {batch_label}")
    lines.append("")
    if not rows:
        lines.append("本时段暂无新增安全资讯。")
        return "\n".join(lines).strip()

    for index, row in enumerate(rows, start=start_index):
        ai = row_ai(row)
        synopsis = ai.get("summary_zh") or ai.get("brief_zh") or fallback_brief(row)
        lines.extend(
            [
                f"{index}. {row['title']}",
                f"日期: {format_article_time(row['published_at'])}",
                f"梗概: {truncate(synopsis, 360)}",
                f"链接: {row['url']}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def row_ai(row) -> dict:
    if not row["ai_result_json"]:
        return {}
    try:
        result = json.loads(row["ai_result_json"])
    except json.JSONDecodeError:
        return {}
    return result if isinstance(result, dict) else {}


def fallback_brief(row) -> str:
    return f"待 AI 优化：{row['title']}"


def push_feishu(args: argparse.Namespace, db: Database) -> int:
    webhook = os.getenv(args.webhook_env, "")
    secret = os.getenv(args.secret_env, "")
    if not webhook:
        print(f"Missing Feishu webhook. Set ${args.webhook_env} first.", file=sys.stderr)
        return 1

    rows, range_label = filter_rows_by_window(
        db.list_articles(limit=max(args.limit, 200)),
        args.window,
        args.date,
    )
    rows = prioritize_feishu_rows(rows)[: args.limit]
    if not rows:
        if not args.no_empty_message:
            response = send_text(webhook, build_feishu_text(rows, range_label), secret=secret)
            print(json.dumps(response, ensure_ascii=False))
            return 0
        print("No articles to push.", file=sys.stderr)
        return 1
    batches = list(chunk_rows(rows, args.batch_size))
    for batch_number, (start, batch_rows) in enumerate(batches, start=1):
        batch_label = ""
        if len(batches) > 1:
            batch_label = f"{batch_number}/{len(batches)}"
        response = send_text(
            webhook,
            build_feishu_text(
                batch_rows,
                range_label,
                batch_label=batch_label,
                start_index=start + 1,
            ),
            secret=secret,
        )
        print(json.dumps(response, ensure_ascii=False))
        if batch_number < len(batches):
            sleep(3)
    return 0


def feishu_workflow(args: argparse.Namespace, db: Database) -> int:
    collect_args = argparse.Namespace(
        config=args.config,
        source="",
        limit=args.collect_limit,
        ai=args.ai,
        digest=False,
    )
    collect_status = collect(collect_args, db)
    if collect_status != 0:
        return collect_status

    push_args = argparse.Namespace(
        limit=args.push_limit,
        batch_size=args.batch_size,
        date=args.date,
        window=args.window,
        no_empty_message=args.no_empty_message,
        webhook_env=args.webhook_env,
        secret_env=args.secret_env,
    )
    return push_feishu(push_args, db)


def main(argv: list[str] | None = None) -> int:
    load_env_file(ROOT / ".env")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)
    db = Database(args.db)
    db.init()

    if args.command == "init-db":
        print(f"Database initialized: {args.db}")
        return 0
    if args.command == "collect":
        return collect(args, db)
    if args.command == "list":
        return list_articles(args, db)
    if args.command == "process-ai":
        return process_ai(args, db)
    if args.command == "digest":
        return digest(args, db)
    if args.command == "export-html":
        from .static_site import write_static_site

        path = write_static_site(
            args.db,
            output_dir=args.output_dir,
            limit=args.limit,
            include_duplicates=args.include_duplicates,
            title=args.title,
        )
        print(f"HTML site written: {path}")
        return 0
    if args.command == "dedup":
        return dedup(args, db)
    if args.command == "dashboard":
        enable_dashboard = os.getenv("ENABLE_DASHBOARD", "false").strip().lower()
        if enable_dashboard not in ("1", "true", "yes"):
            print(
                "Dashboard is disabled. Set ENABLE_DASHBOARD=true in .env to enable.",
                file=sys.stderr,
            )
            return 1
        from .dashboard import run_dashboard

        return run_dashboard(args.db, host=args.host, port=args.port)
    if args.command == "push-feishu":
        return push_feishu(args, db)
    if args.command == "feishu-workflow":
        return feishu_workflow(args, db)
    parser.error(f"Unknown command: {args.command}")
    return 2
