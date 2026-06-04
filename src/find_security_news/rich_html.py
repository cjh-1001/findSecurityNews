from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import html
import re


ALLOWED_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "code",
    "em",
    "figcaption",
    "figure",
    "h2",
    "h3",
    "h4",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}

VOID_TAGS = {"br", "hr", "img"}
SKIP_TAGS = {"script", "style", "noscript", "iframe", "object", "embed", "form", "svg"}
URL_ATTRS = {"href", "src"}
SAFE_CLASSES = re.compile(r"[^A-Za-z0-9_ -]")


class ArticleHTMLSanitizer(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth or tag not in ALLOWED_TAGS:
            return
        clean_attrs = self._clean_attrs(tag, attrs)
        if tag == "img" and not any(name == "src" for name, _ in clean_attrs):
            return
        rendered_attrs = "".join(
            f' {name}="{html.escape(value, quote=True)}"' for name, value in clean_attrs
        )
        self.parts.append(f"<{tag}{rendered_attrs}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth or tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        self.parts.append(html.escape(data))

    def _clean_attrs(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> list[tuple[str, str]]:
        clean: list[tuple[str, str]] = []
        image_src = ""
        for raw_name, raw_value in attrs:
            if not raw_name or raw_value is None:
                continue
            name = raw_name.lower()
            value = raw_value.strip()
            if tag == "img" and name in {"data-src", "data-original", "data-lazy-src"}:
                image_src = image_src or self._safe_url(value, allow_images=True)
                continue
            if name in URL_ATTRS:
                value = self._safe_url(value, allow_images=(tag == "img"))
                if value:
                    clean.append((name, value))
                    if tag == "img" and name == "src":
                        image_src = value
                continue
            if tag == "img" and name in {"alt", "title", "width", "height"}:
                clean.append((name, value))
                continue
            if tag == "a" and name == "title":
                clean.append((name, value))
                continue
            if tag in {"code", "pre"} and name == "class":
                class_value = SAFE_CLASSES.sub("", value).strip()
                if class_value:
                    clean.append((name, class_value[:80]))
        if tag == "img" and image_src and not any(name == "src" for name, _ in clean):
            clean.insert(0, ("src", image_src))
        if tag == "a":
            clean.extend([("target", "_blank"), ("rel", "noreferrer")])
        if tag == "img":
            clean.extend([("loading", "lazy"), ("decoding", "async")])
        return clean

    def _safe_url(self, value: str, allow_images: bool) -> str:
        if not value or value.startswith(("javascript:", "vbscript:")):
            return ""
        absolute = urljoin(self.base_url, value)
        parsed = urlparse(absolute)
        if parsed.scheme in {"http", "https"}:
            return absolute
        if not allow_images and parsed.scheme == "mailto":
            return absolute
        return ""

    def html(self) -> str:
        return "".join(self.parts).strip()


def sanitize_article_html(content_html: str, base_url: str) -> str:
    parser = ArticleHTMLSanitizer(base_url)
    parser.feed(content_html or "")
    return parser.html()
