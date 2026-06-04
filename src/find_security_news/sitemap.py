from dataclasses import dataclass
from html import unescape
import json
import re
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

from .html_text import html_to_text
from .models import Article, Source


VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

EXCLUDED_ARTICLE_PATHS = {
    "/articles/16751/",
}


@dataclass(frozen=True)
class SitemapEntry:
    url: str
    lastmod: str = ""


def parse_sitemap(source: Source, xml_text: str, limit: int | None = None) -> list[SitemapEntry]:
    root = ET.fromstring(xml_text)
    entries = []
    homepage = source.homepage.rstrip("/")

    for url_node in root.findall(".//{*}url"):
        loc_node = url_node.find("{*}loc")
        if loc_node is None or not loc_node.text:
            continue
        url = loc_node.text.strip()
        if homepage and not url.startswith(homepage + "/"):
            continue
        lastmod_node = url_node.find("{*}lastmod")
        lastmod = lastmod_node.text.strip() if lastmod_node is not None and lastmod_node.text else ""
        entries.append(SitemapEntry(url=url, lastmod=lastmod))

    entries.sort(key=lambda entry: entry.lastmod, reverse=True)
    if limit is not None:
        return entries[:limit]
    return entries


def parse_html_index(source: Source, html: str, limit: int | None = None) -> list[SitemapEntry]:
    entries = []
    seen = set()
    base_url = source.homepage or source.url
    base_host = urlparse(base_url).netloc

    blocks = re.findall(
        r"<article\b[^>]*>.*?</article>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not blocks:
        blocks = [html]

    for block in blocks:
        url = _article_url_from_block(block, base_url, base_host)
        if not url or url in seen:
            continue
        seen.add(url)
        date_match = re.search(r"日期:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", html_to_text(block))
        entries.append(SitemapEntry(url=url, lastmod=date_match.group(1) if date_match else ""))
        if limit is not None and len(entries) >= limit:
            break

    if limit is None or len(entries) < limit:
        for match in re.finditer(
            r"href\s*=\s*['\"]([^'\"]*(?:/post/id/\d+|/(?:post|articles)/\d+|articles-\d+\.html)[^'\"]*)['\"]",
            html,
        ):
            url = urljoin(base_url, match.group(1))
            parsed = urlparse(url)
            if url in seen or parsed.netloc != base_host or _excluded_article_path(parsed.path):
                continue
            seen.add(url)
            entries.append(SitemapEntry(url=url))
            if limit is not None and len(entries) >= limit:
                break

    return entries


def _article_url_from_block(block: str, base_url: str, base_host: str) -> str:
    for preferred in re.finditer(
        r"href\s*=\s*['\"]([^'\"]*(?:/post/id/\d+|/(?:post|articles)/\d+|articles-\d+\.html)[^'\"]*)['\"]",
        block,
    ):
        url = urljoin(base_url, preferred.group(1))
        if not _excluded_article_path(urlparse(url).path):
            return url

    for match in re.finditer(r"href\s*=\s*['\"]([^'\"]+)['\"]", block):
        url = urljoin(base_url, match.group(1))
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != base_host:
            continue
        path = parsed.path.rstrip("/") + "/"
        if _excluded_article_path(path):
            continue
        if path in {"/", "/feed/"}:
            continue
        if path.endswith((".png/", ".jpg/", ".jpeg/", ".gif/", ".webp/", ".ico/", ".css/", ".js/")):
            continue
        if path.startswith(("/page/", "/category/", "/author/", "/tag/", "/wp-", "/search/")):
            continue
        if path in {"/cve-watchtower/", "/submit-press-release/", "/privacy-policy/", "/about-us/"}:
            continue
        return url
    return ""


def _excluded_article_path(path: str) -> bool:
    normalized = path.rstrip("/") + "/"
    return normalized in EXCLUDED_ARTICLE_PATHS


def article_from_html(
    source: Source,
    url: str,
    html: str,
    published_at: str = "",
) -> Article:
    jsonld = _jsonld_metadata(html, url)
    title = (
        _meta_content(html, "og:title")
        or _meta_content(html, "twitter:title")
        or _jsonld_value(jsonld, "headline")
        or _jsonld_value(jsonld, "name")
        or _id_text_value(html, "title")
        or _first_heading(html)
    )
    summary = (
        _meta_content(html, "description")
        or _meta_content(html, "og:description")
        or _jsonld_value(jsonld, "description")
    )
    author = (
        _jsonld_author(jsonld)
        or _meta_content(html, "author")
        or _class_text_value(html, "display-name")
        or _class_text_value(html, "author")
    )
    published = (
        _jsonld_value(jsonld, "datePublished")
        or _meta_content(html, "article:published_time")
        or _meta_content(html, "article:modified_time")
        or _class_text_value(html, "meta_date")
        or _class_text_value(html, "time")
        or published_at
        or _label_value(html, "发布时间")
        or _label_value(html, "日期")
    )
    content_html = (
        _element_by_id(html, "blog-post-content")
        or _element_by_id(html, "js-article")
        or _element_by_class_within(html, "article_wrap", "body")
        or _element_by_class(html, "blog-post-content")
        or _element_by_class(html, "post-content")
        or _element_by_class(html, "entry-content")
        or _largest_element_by_class(html, "entry_content")
        or _largest_element_by_class(html, "item_content")
        or _element_by_class(html, "elementor-widget-theme-post-content")
        or _element_by_class(html, "blog_content")
        or _element_by_class(html, "wp-block-post-content")
        or _element_by_class(html, "rich_pages")
        or _element_by_class(html, "body-text")
        or _element_by_class(html, "paywall_body")
        or _element_by_class(html, "article-body")
        or _element_by_class(html, "article-content")
        or _first_element(html, "article")
        or _first_element(html, "main")
        or html
    )
    content_html = _strip_non_article_blocks(content_html)
    content_text = _clean_article_text(html_to_text(content_html))
    if not author:
        author = _label_value(html, "作者")
    categories = [category] if (category := _label_value(html, "分类")) else []
    if not summary:
        summary = content_text[:500]

    return Article(
        source_name=source.name,
        url=url,
        title=unescape(title).strip(),
        author=unescape(author).strip(),
        published_at=published.strip(),
        summary=html_to_text(summary),
        content_html=content_html,
        content_text=content_text,
        categories=categories,
    )


def _meta_content(html: str, key: str) -> str:
    for match in re.finditer(r"<meta\b([^>]*)>", html, re.IGNORECASE | re.DOTALL):
        attrs = _attrs(match.group(1))
        if attrs.get("property") == key or attrs.get("name") == key:
            return unescape(attrs.get("content", "")).strip()
    return ""


def _attrs(tag_text: str) -> dict[str, str]:
    attrs = {}
    pattern = r"""([A-Za-z_:.-]+)\s*=\s*(['"])(.*?)\2"""
    for name, _, value in re.findall(pattern, tag_text, re.DOTALL):
        attrs[name.lower()] = value
    return attrs


def _jsonld_metadata(html: str, url: str) -> dict:
    for match in re.finditer(
        r"<script\b[^>]*type\s*=\s*['\"]application/ld\+json['\"][^>]*>(.*?)</script>",
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        raw = unescape(match.group(1).strip())
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidate = _find_jsonld_item(data, url)
        if candidate:
            return candidate
    return {}


def _find_jsonld_item(data, url: str) -> dict:
    items = []
    if isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            items.extend(item for item in graph if isinstance(item, dict))
        items.append(data)
    elif isinstance(data, list):
        items.extend(item for item in data if isinstance(item, dict))

    preferred_types = {"article", "blogposting", "newarticle", "webpage"}
    for item in items:
        item_type = item.get("@type", "")
        if isinstance(item_type, list):
            item_types = {str(value).lower() for value in item_type}
        else:
            item_types = {str(item_type).lower()}
        item_url = str(item.get("url") or item.get("@id") or "")
        if item_types & preferred_types and (not item_url or url.rstrip("/") in item_url.rstrip("/")):
            return item
    return {}


def _jsonld_value(data: dict, key: str) -> str:
    value = data.get(key, "")
    if isinstance(value, str):
        return value.strip()
    return ""


def _jsonld_author(data: dict) -> str:
    author = data.get("author")
    if isinstance(author, dict):
        return str(author.get("name", "")).strip()
    if isinstance(author, list):
        names = [str(item.get("name", "")).strip() for item in author if isinstance(item, dict)]
        return ", ".join(name for name in names if name)
    if isinstance(author, str):
        return author.strip()
    return ""


def _first_heading(html: str) -> str:
    match = re.search(r"<h1\b[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return html_to_text(match.group(1))


def _class_text_value(html: str, class_name: str) -> str:
    content = _element_by_class(html, class_name)
    return html_to_text(content) if content else ""


def _id_text_value(html: str, element_id: str) -> str:
    content = _element_by_id(html, element_id)
    return html_to_text(content) if content else ""


def _label_value(html: str, label: str) -> str:
    text = html_to_text(html)
    if label == "发布时间":
        match = re.search(r"发布时间\s*[:：]\s*(20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)", text)
        return match.group(1).strip() if match else ""
    if label == "日期":
        match = re.search(r"日期:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text)
        return match.group(1).strip() if match else ""
    match = re.search(rf"{re.escape(label)}:\s*([^\n]+)", text)
    if not match:
        return ""
    value = re.split(r"\s+(?:作者|日期|分类|浏览次数|喜欢|分享到):?", match.group(1), maxsplit=1)[0]
    return value.strip()


def _clean_article_text(text: str) -> str:
    cleaned = text
    preferred = re.search(r"Add as a preferred\s+source on Google\s+", cleaned, re.IGNORECASE)
    if preferred and preferred.start() < 300:
        cleaned = cleaned[preferred.end() :]
    for marker in [
        "\nRelated posts:",
        "\nTags:",
        "\nShare this article",
        "\nWant the full threat landscape breakdown?",
        "\nSubscribe to Cyble",
    ]:
        index = cleaned.find(marker)
        if index >= 0:
            cleaned = cleaned[:index]
    return cleaned.strip()


def _element_by_id(html: str, element_id: str) -> str:
    pattern = rf"<([A-Za-z0-9]+)\b[^>]*\bid\s*=\s*['\"]{re.escape(element_id)}['\"][^>]*>"
    return _element_from_start(html, pattern)


def _element_by_class(html: str, class_name: str) -> str:
    pattern = _class_start_pattern(class_name)
    return _element_from_start(html, pattern)


def _element_by_class_within(html: str, outer_class: str, inner_class: str) -> str:
    outer = _element_by_class(html, outer_class)
    if not outer:
        return ""
    return _element_by_class(outer, inner_class)


def _largest_element_by_class(html: str, class_name: str) -> str:
    pattern = _class_start_pattern(class_name)
    largest = ""
    search_from = 0
    while search_from < len(html):
        match = re.search(pattern, html[search_from:], re.IGNORECASE | re.DOTALL)
        if not match:
            break
        span = _element_span_from_start(html[search_from + match.start() :], pattern)
        if not span:
            break
        start, end = span
        candidate = html[search_from + match.start() + start : search_from + match.start() + end]
        if len(html_to_text(candidate)) > len(html_to_text(largest)):
            largest = candidate
        search_from = search_from + match.start() + max(end, 1)
    return largest


def _first_element(html: str, tag_name: str) -> str:
    pattern = rf"<({re.escape(tag_name)})\b[^>]*>"
    return _element_from_start(html, pattern)


def _element_from_start(html: str, start_pattern: str) -> str:
    span = _element_span_from_start(html, start_pattern)
    if not span:
        return ""
    start, end = span
    return html[start:end]


def _strip_non_article_blocks(html: str) -> str:
    class_names = [
        "share",
        "share-widget",
        "share__wrapper",
        "new-share-icons",
        "share-url",
        "blog-post__sidebar",
        "sidebar",
        "article-tags",
        "more-posts",
        "card-post",
        "card-focus-taxonomy__content",
        "popup-content",
        "socialshare__text",
        "taxonomies__personaggi-title",
        "wpd-secondary-forms-social-content",
        "ratemypostextra-container",
        "post-card",
        "right-subscribe",
        "footer__section-subscribe",
        "footer__widget",
    ]
    cleaned = html
    for class_name in class_names:
        cleaned = _remove_elements_by_class(cleaned, class_name)
    return cleaned


def _remove_elements_by_class(html: str, class_name: str) -> str:
    pattern = _class_start_pattern(class_name)
    cleaned = html
    while True:
        span = _element_span_from_start(cleaned, pattern)
        if not span:
            return cleaned
        start, end = span
        cleaned = cleaned[:start] + cleaned[end:]


def _class_start_pattern(class_name: str) -> str:
    class_token = re.escape(class_name)
    return (
        r"<([A-Za-z0-9]+)\b[^>]*\bclass\s*=\s*['\"]"
        rf"[^'\"]*(?<![A-Za-z0-9_-]){class_token}(?![A-Za-z0-9_-])[^'\"]*"
        r"['\"][^>]*>"
    )


def _element_span_from_start(html: str, start_pattern: str) -> tuple[int, int] | None:
    start_match = re.search(start_pattern, html, re.IGNORECASE | re.DOTALL)
    if not start_match:
        return None
    target_tag = start_match.group(1).lower()
    start = start_match.start()
    depth = 0

    for match in re.finditer(r"</?([A-Za-z0-9]+)\b[^>]*>", html[start:], re.DOTALL):
        tag_text = match.group(0)
        tag_name = match.group(1).lower()
        if tag_name != target_tag:
            continue
        is_end = tag_text.startswith("</")
        is_self_closing = tag_text.endswith("/>") or tag_name in VOID_TAGS
        if is_end:
            depth -= 1
            if depth == 0:
                return start, start + match.end()
        elif not is_self_closing:
            depth += 1
    return None
