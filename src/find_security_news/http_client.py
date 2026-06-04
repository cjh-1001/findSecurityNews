from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from time import sleep


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def fetch_text(url: str, timeout: int = 60, retries: int = 2) -> str:
    try:
        import requests
    except ImportError:
        requests = None

    if requests is not None:
        for attempt in range(retries + 1):
            try:
                response = requests.get(
                    url,
                    headers=DEFAULT_HEADERS,
                    timeout=timeout,
                )
                response.raise_for_status()
                response.encoding = response.encoding or response.apparent_encoding or "utf-8"
                return response.text
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else "unknown"
                raise RuntimeError(f"HTTP {status} while fetching {url}") from exc
            except requests.RequestException as exc:
                if attempt >= retries:
                    raise RuntimeError(f"Network error while fetching {url}: {exc}") from exc
                sleep(1 + attempt)

    request = Request(
        url,
        headers=DEFAULT_HEADERS,
    )
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} while fetching {url}") from exc
        except (TimeoutError, URLError) as exc:
            if attempt >= retries:
                reason = getattr(exc, "reason", exc)
                raise RuntimeError(f"Network error while fetching {url}: {reason}") from exc
            sleep(1 + attempt)
    raise RuntimeError(f"Unable to fetch {url}")


def post_text(
    url: str,
    data: dict[str, object] | None = None,
    timeout: int = 60,
    retries: int = 2,
    referer: str = "",
) -> str:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("POST fetching requires requests.") from exc

    headers = dict(DEFAULT_HEADERS)
    headers["X-Requested-With"] = "XMLHttpRequest"
    if referer:
        headers["Referer"] = referer

    for attempt in range(retries + 1):
        try:
            response = requests.post(url, data=data or {}, headers=headers, timeout=timeout)
            response.raise_for_status()
            response.encoding = response.encoding or response.apparent_encoding or "utf-8"
            return response.text
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            raise RuntimeError(f"HTTP {status} while fetching {url}") from exc
        except requests.RequestException as exc:
            if attempt >= retries:
                raise RuntimeError(f"Network error while fetching {url}: {exc}") from exc
            sleep(1 + attempt)
    raise RuntimeError(f"Unable to fetch {url}")
