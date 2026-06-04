from dataclasses import dataclass, field
from html import unescape
import re
from urllib.parse import urljoin

from .html_text import html_to_text
from .models import Source


@dataclass(frozen=True)
class BianewsEntry:
    url: str
    title: str = ""
    lastmod: str = ""
    summary: str = ""
    categories: list[str] = field(default_factory=list)


def parse_bianews_index(source: Source, html: str, limit: int | None = None) -> list[BianewsEntry]:
    entries: list[BianewsEntry] = []
    base_url = source.homepage or "https://www.bianews.com/"

    for block in re.findall(
        r"<li\b[^>]*class\s*=\s*['\"][^'\"]*js_news_item[^'\"]*['\"][^>]*>.*?</li>",
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        item_id = _attr_value(block, "id")
        if not item_id:
            continue
        title = _title_from_block(block)
        published = _date_value(_class_text(block, "country-name"))
        summary = _class_text(block, "prview_wrap")
        categories = _tag_values(block)
        entries.append(
            BianewsEntry(
                url=urljoin(base_url, f"/news/details?id={item_id}"),
                title=title,
                lastmod=published,
                summary=summary,
                categories=categories,
            )
        )
        if limit is not None and len(entries) >= limit:
            break
    return entries


def _attr_value(html: str, attr: str) -> str:
    match = re.search(rf"\b{re.escape(attr)}\s*=\s*['\"]([^'\"]+)['\"]", html, re.IGNORECASE)
    return unescape(match.group(1)).strip() if match else ""


def _title_from_block(html: str) -> str:
    match = re.search(
        r"<a\b[^>]*class\s*=\s*['\"][^'\"]*title[^'\"]*js_title[^'\"]*['\"][^>]*>(.*?)</a>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return html_to_text(match.group(1))
    return _attr_value(html, "title")


def _class_text(html: str, class_name: str) -> str:
    pattern = (
        r"<([A-Za-z0-9]+)\b[^>]*\bclass\s*=\s*['\"]"
        rf"[^'\"]*(?<![A-Za-z0-9_-]){re.escape(class_name)}(?![A-Za-z0-9_-])[^'\"]*"
        r"['\"][^>]*>(.*?)</\1>"
    )
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    return html_to_text(match.group(2)) if match else ""


def _tag_values(html: str) -> list[str]:
    tags = []
    for match in re.finditer(
        r"<a\b[^>]*class\s*=\s*['\"][^'\"]*js_tags[^'\"]*['\"][^>]*>(.*?)</a>",
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        tag = html_to_text(match.group(1)).strip()
        if tag:
            tags.append(tag)
    return tags


def _date_value(text: str) -> str:
    match = re.search(r"20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?", text)
    return match.group(0) if match else text
