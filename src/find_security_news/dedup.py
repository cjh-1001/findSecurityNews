from dataclasses import dataclass
from difflib import SequenceMatcher
import re

from .models import Article


@dataclass(frozen=True)
class DuplicateMatch:
    article_id: int
    score: float
    reason: str


CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
WORD_RE = re.compile(r"[a-z0-9][a-z0-9_.+-]{1,}", re.IGNORECASE)
HAN_RE = re.compile(r"[\u4e00-\u9fff]+")


def find_duplicate(article: Article, candidates) -> DuplicateMatch | None:
    best: DuplicateMatch | None = None
    for row in candidates:
        score, reason = similarity(article, row)
        if score < 0.86:
            continue
        if best is None or score > best.score:
            best = DuplicateMatch(article_id=int(row["id"]), score=score, reason=reason)
    return best


def similarity(article: Article, row) -> tuple[float, str]:
    title_score = text_similarity(article.title, row["title"])
    current_text = comparable_text(article.title, article.summary, article.content_text)
    existing_text = comparable_text(row["title"], row["summary"], row["content_text"])
    content_score = text_similarity(current_text, existing_text)

    score = max(title_score, content_score)
    reason = f"title={title_score:.2f},content={content_score:.2f}"

    current_cves = cves(current_text)
    existing_cves = cves(existing_text)
    if current_cves and current_cves == existing_cves and title_score >= 0.45:
        score = max(score, 0.9)
        reason += ",same_cves"

    if title_score >= 0.92:
        score = max(score, title_score)
    return score, reason


def comparable_text(title: str, summary: str, content_text: str) -> str:
    body = content_text or summary
    return f"{title}\n{summary}\n{body[:1800]}"


def text_similarity(left: str, right: str) -> float:
    left_norm = normalize(left)
    right_norm = normalize(right)
    if not left_norm or not right_norm:
        return 0.0

    seq_score = SequenceMatcher(None, left_norm[:2200], right_norm[:2200]).ratio()
    left_tokens = token_set(left_norm)
    right_tokens = token_set(right_norm)
    token_score = jaccard(left_tokens, right_tokens)
    return max(seq_score, token_score)


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def token_set(text: str) -> set[str]:
    tokens = {match.group(0) for match in WORD_RE.finditer(text)}
    for match in HAN_RE.finditer(text):
        value = match.group(0)
        if len(value) == 1:
            tokens.add(value)
        else:
            tokens.update(value[index : index + 2] for index in range(len(value) - 1))
    return tokens


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def cves(text: str) -> set[str]:
    return {match.group(0).upper() for match in CVE_RE.finditer(text)}
