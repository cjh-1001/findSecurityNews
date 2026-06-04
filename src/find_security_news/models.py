from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    name: str
    type: str
    url: str
    homepage: str = ""
    language: str = "en"
    enabled: bool = True


@dataclass(frozen=True)
class Article:
    source_name: str
    url: str
    title: str
    author: str = ""
    published_at: str = ""
    summary: str = ""
    content_html: str = ""
    content_text: str = ""
    categories: list[str] = field(default_factory=list)
