from email.utils import parsedate_to_datetime
from html import unescape
import xml.etree.ElementTree as ET

from .html_text import html_to_text
from .models import Article, Source


NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def _text(parent: ET.Element, path: str) -> str:
    node = parent.find(path, NS)
    if node is None or node.text is None:
        return ""
    return unescape(node.text.strip())


def _date_to_iso(value: str) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return value


def parse_rss(source: Source, xml_text: str, limit: int | None = None) -> list[Article]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        preview = html_to_text(xml_text)[:120]
        raise RuntimeError(
            f"Invalid RSS/Atom XML for {source.name}. Response preview: {preview}"
        ) from exc
    items = root.findall("./channel/item")
    if not items:
        return parse_atom(source, root, limit=limit)
    if limit is not None:
        items = items[:limit]

    articles: list[Article] = []
    for item in items:
        content_html = _text(item, "content:encoded")
        description = _text(item, "description")
        categories = [
            unescape(category.text.strip())
            for category in item.findall("category")
            if category.text and category.text.strip()
        ]
        articles.append(
            Article(
                source_name=source.name,
                url=_text(item, "link"),
                title=_text(item, "title"),
                author=_text(item, "dc:creator"),
                published_at=_date_to_iso(_text(item, "pubDate")),
                summary=html_to_text(description),
                content_html=content_html,
                content_text=html_to_text(content_html or description),
                categories=categories,
            )
        )
    return [article for article in articles if article.url and article.title]


def parse_atom(source: Source, root: ET.Element, limit: int | None = None) -> list[Article]:
    entries = root.findall("atom:entry", NS)
    if limit is not None:
        entries = entries[:limit]

    articles = []
    for entry in entries:
        link = ""
        link_node = entry.find("atom:link", NS)
        if link_node is not None:
            link = link_node.attrib.get("href", "")
        summary = _text(entry, "atom:summary")
        content_html = _text(entry, "atom:content")
        published = _text(entry, "atom:published") or _text(entry, "atom:updated")
        articles.append(
            Article(
                source_name=source.name,
                url=link,
                title=_text(entry, "atom:title"),
                author=_text(entry, "atom:author/atom:name"),
                published_at=_date_to_iso(published),
                summary=html_to_text(summary),
                content_html=content_html,
                content_text=html_to_text(content_html or summary),
                categories=[],
            )
        )
    return [article for article in articles if article.url and article.title]
