from pathlib import Path

from .models import Source


def _parse_simple_toml_sources(text: str) -> dict:
    sources: list[dict] = []
    current: dict | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "[[sources]]":
            current = {}
            sources.append(current)
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.lower() in {"true", "false"}:
            current[key] = value.lower() == "true"
        elif value.startswith('"') and value.endswith('"'):
            current[key] = value[1:-1]
        else:
            current[key] = value
    return {"sources": sources}


def _load_toml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib  # type: ignore
    except ModuleNotFoundError:
        return _parse_simple_toml_sources(text)
    return tomllib.loads(text)


def load_sources(path: Path) -> list[Source]:
    data = _load_toml(path)
    sources = []
    for item in data.get("sources", []):
        source = Source(
            name=item["name"],
            type=item["type"],
            url=item["url"],
            homepage=item.get("homepage", ""),
            language=item.get("language", "en"),
            enabled=bool(item.get("enabled", True)),
        )
        if source.enabled:
            sources.append(source)
    return sources
