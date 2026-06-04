from datetime import datetime
from pathlib import Path
import json
import sqlite3

from .time_format import format_article_time


def _ai(row: sqlite3.Row) -> dict:
    if not row["ai_result_json"]:
        return {}
    try:
        return json.loads(row["ai_result_json"])
    except json.JSONDecodeError:
        return {}


def _list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


def write_digest(rows: list[sqlite3.Row], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    path = output_dir / f"{today}.md"

    lines = [f"# Security News Digest - {today}", ""]
    for index, row in enumerate(rows, start=1):
        ai = _ai(row)
        brief = ai.get("brief_zh") or ai.get("summary_zh") or f"待 AI 优化：{row['title']}"
        priority = ai.get("priority", "unknown")
        security_type = ai.get("security_type", "security_news")
        cves = ", ".join(ai.get("cves", [])) or "None"
        tags = "、".join(_list(ai.get("tags_zh"))) or "None"
        lines.extend(
            [
                f"## {index}. {row['title']}",
                "",
                f"- Source: {row['source_name']}",
                f"- Published: {format_article_time(row['published_at'])}",
                f"- Priority: {priority}",
                f"- Type: {security_type}",
                f"- Tags: {tags}",
                f"- CVEs: {cves}",
                f"- URL: {row['url']}",
                "",
                brief.strip(),
                "",
            ]
        )

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
