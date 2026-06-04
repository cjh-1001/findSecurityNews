from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_MODEL = "gpt-4.1-mini"


def heuristic_security_extract(title: str, text: str, categories: list[str]) -> dict:
    cves = sorted(set(__import__("re").findall(r"CVE-\d{4}-\d{4,7}", text, flags=__import__("re").I)))
    lower = f"{title}\n{text}".lower()
    priority = "medium"
    if cves or "exploited" in lower or "ransomware" in lower or "zero-day" in lower:
        priority = "high"
    elif "research" in lower or "report" in lower:
        priority = "medium"

    security_type = infer_type(lower, categories)
    return {
        "brief_zh": "",
        "summary_zh": "",
        "translation_zh": "",
        "security_type": security_type,
        "priority": priority,
        "tags_zh": heuristic_tags(security_type, lower, cves),
        "cves": cves,
        "vendors": [],
        "products": [],
        "threat_actors": [],
        "malware": [],
        "iocs": [],
        "key_points": [],
    }


def infer_type(lower_text: str, categories: list[str]) -> str:
    category_text = " ".join(categories).lower()
    leading_text = lower_text[:2500]
    title_and_categories = f"{category_text} {lower_text.splitlines()[0] if lower_text else ''}"
    if "ransomware" in title_and_categories or "ransomware" in leading_text:
        return "ransomware"
    if "espionage" in leading_text or "apt" in title_and_categories:
        return "threat_intelligence"
    if "malware" in category_text:
        return "malware"
    if (
        "cve-" in title_and_categories
        or "known exploited vulnerabilities" in leading_text
        or "vulnerab" in leading_text
        or "flaw" in leading_text
        or "patch" in leading_text
    ):
        return "vulnerability"
    if "malware" in leading_text:
        return "malware"
    if "breach" in leading_text or "data leak" in leading_text:
        return "incident"
    return "security_news"


def heuristic_tags(security_type: str, lower_text: str, cves: list[str]) -> list[str]:
    tags = []
    type_tags = {
        "vulnerability": "漏洞",
        "ransomware": "勒索软件",
        "threat_intelligence": "威胁情报",
        "malware": "恶意软件",
        "incident": "安全事件",
        "security_news": "安全资讯",
    }
    tags.append(type_tags.get(security_type, "安全资讯"))
    if cves:
        tags.append("CVE")
    if "exploited" in lower_text or "in the wild" in lower_text:
        tags.append("在野利用")
    if "phishing" in lower_text or "smishing" in lower_text:
        tags.append("钓鱼攻击")
    if "ransomware" in lower_text:
        tags.append("勒索软件")
    return list(dict.fromkeys(tags))[:5]


class AIProcessor:
    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self.max_tokens = int(os.getenv("AI_MAX_TOKENS", "8192"))
        self.provider = os.getenv("AI_PROVIDER", "").strip().lower()
        if not self.provider and "anthropic" in self.base_url.lower():
            self.provider = "anthropic"
        if not self.provider:
            self.provider = "openai"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def analyze(self, title: str, text: str, categories: list[str]) -> dict:
        fallback = heuristic_security_extract(title, text, categories)
        if not self.enabled:
            return fallback

        if self.provider == "anthropic":
            return self._analyze_anthropic(title, text, categories, fallback)

        prompt = {
            "title": title,
            "categories": categories,
            "text": text[:24000],
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a cyber threat intelligence analyst. Return compact JSON only. "
                    "Read the full article content, verify the synopsis against the full text, "
                    "translate English articles into Chinese, extract useful entities, and avoid "
                    "unsupported claims. Preserve company, vendor, product, service, "
                    "malware family, threat actor, vulnerability, protocol, and CVE names in their "
                    "original English form unless the source itself uses Chinese. Use Chinese prose "
                    "for summary_zh, translation_zh, brief_zh, and key_points, but do not translate "
                    "proper nouns. summary_zh must be a verified synopsis based on the full article, "
                    "not the RSS description. translation_zh must be a full Chinese translation when "
                    "the source article is primarily English; if the source is already Chinese, return "
                    "an empty string for translation_zh."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Analyze this article. Return JSON with keys: summary_zh, translation_zh, "
                    "security_type, priority, cves, vendors, products, threat_actors, malware, "
                    "iocs, key_points, brief_zh, tags_zh. summary_zh is 2-4 Chinese sentences that "
                    "summarize the full article after checking the whole text. translation_zh is the "
                    "full Chinese translation for English articles. brief_zh is one concise Chinese "
                    "sentence derived from summary_zh. tags_zh is 3-6 short "
                    "Chinese security tags. security_type must be one of: vulnerability, malware, "
                    "ransomware, threat_intelligence, incident, security_news. priority must be one "
                    "of: critical, high, medium, low. "
                    "Chinese fields must be Chinese prose while preserving "
                    "English proper nouns exactly as they appear in the source.\n\n"
                    + json.dumps(prompt, ensure_ascii=False)
                ),
            },
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_tokens,
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            result = parse_json_object(content)
            return {**fallback, **result}
        except (HTTPError, URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            fallback["ai_error"] = str(exc)
            return fallback

    def _analyze_anthropic(
        self,
        title: str,
        text: str,
        categories: list[str],
        fallback: dict,
    ) -> dict:
        prompt = {
            "title": title,
            "categories": categories,
            "text": text[:24000],
        }
        system = (
            "You are a cyber threat intelligence analyst. Return compact JSON only. "
            "Read the full article content, verify the synopsis against the full text, "
            "translate English articles into Chinese, extract useful entities, and avoid "
            "unsupported claims. Preserve company, vendor, product, service, "
            "malware family, threat actor, vulnerability, protocol, and CVE names in their "
            "original English form unless the source itself uses Chinese. Use Chinese prose "
            "for summary_zh, translation_zh, brief_zh, and key_points, but do not translate "
            "proper nouns. summary_zh must be a verified synopsis based on the full article, "
            "not the RSS description. translation_zh must be a full Chinese translation when "
            "the source article is primarily English; if the source is already Chinese, return "
            "an empty string for translation_zh."
        )
        user = (
            "Analyze this article. Return JSON with keys: summary_zh, translation_zh, "
            "security_type, priority, cves, vendors, products, threat_actors, malware, "
            "iocs, key_points, brief_zh, tags_zh. summary_zh is 2-4 Chinese sentences that "
            "summarize the full article after checking the whole text. translation_zh is the "
            "full Chinese translation for English articles. brief_zh is one concise Chinese "
            "sentence derived from summary_zh. tags_zh is 3-6 short "
            "Chinese security tags. security_type must be one of: vulnerability, malware, "
            "ransomware, threat_intelligence, incident, security_news. priority must be one "
            "of: critical, high, medium, low. "
            "Chinese fields must be Chinese prose while preserving "
            "English proper nouns exactly as they appear in the source.\n\n"
            + json.dumps(prompt, ensure_ascii=False)
        )
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        endpoint = (
            f"{self.base_url}/messages"
            if self.base_url.endswith("/v1")
            else f"{self.base_url}/v1/messages"
        )
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = "\n".join(
                block.get("text", "")
                for block in data.get("content", [])
                if isinstance(block, dict) and block.get("type") == "text"
            )
            result = parse_json_object(content)
            return {**fallback, **result}
        except (HTTPError, URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
            fallback["ai_error"] = str(exc)
            return fallback


def parse_json_object(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = __import__("re").sub(r"^```(?:json)?\s*", "", text, flags=__import__("re").I)
        text = __import__("re").sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        result = json.loads(text[start : end + 1])
    if not isinstance(result, dict):
        raise json.JSONDecodeError("AI response is not a JSON object", text, 0)
    return result
