from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
from typing import Iterator

from .dedup import find_duplicate
from .models import Article


SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    content_html TEXT NOT NULL DEFAULT '',
    content_text TEXT NOT NULL DEFAULT '',
    categories_json TEXT NOT NULL DEFAULT '[]',
    duplicate_of_article_id INTEGER,
    duplicate_score REAL NOT NULL DEFAULT 0,
    duplicate_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_name);
CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at);

CREATE TABLE IF NOT EXISTS ai_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL UNIQUE,
    model TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(article_id) REFERENCES articles(id)
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._ensure_article_columns(connection)

    def _ensure_article_columns(self, connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(articles)").fetchall()
        }
        if "duplicate_of_article_id" not in columns:
            connection.execute("ALTER TABLE articles ADD COLUMN duplicate_of_article_id INTEGER")
        if "duplicate_score" not in columns:
            connection.execute("ALTER TABLE articles ADD COLUMN duplicate_score REAL NOT NULL DEFAULT 0")
        if "duplicate_reason" not in columns:
            connection.execute("ALTER TABLE articles ADD COLUMN duplicate_reason TEXT NOT NULL DEFAULT ''")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_duplicate_of ON articles(duplicate_of_article_id)"
        )

    def upsert_article(self, article: Article) -> tuple[int, bool, bool]:
        now = utc_now()
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id, duplicate_of_article_id FROM articles WHERE url = ?",
                (article.url,),
            ).fetchone()
            if existing:
                article_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE articles
                    SET source_name = ?, title = ?, author = ?, published_at = ?, summary = ?,
                        content_html = ?, content_text = ?, categories_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        article.source_name,
                        article.title,
                        article.author,
                        article.published_at,
                        article.summary,
                        article.content_html,
                        article.content_text,
                        json.dumps(article.categories, ensure_ascii=False),
                        now,
                        article_id,
                    ),
                )
                return article_id, False, existing["duplicate_of_article_id"] is not None

            duplicate = self._find_duplicate(connection, article)
            duplicate_of = duplicate.article_id if duplicate else None
            duplicate_score = duplicate.score if duplicate else 0
            duplicate_reason = duplicate.reason if duplicate else ""

            cursor = connection.execute(
                """
                INSERT INTO articles (
                    source_name, url, title, author, published_at, summary, content_html,
                    content_text, categories_json, duplicate_of_article_id, duplicate_score,
                    duplicate_reason, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article.source_name,
                    article.url,
                    article.title,
                    article.author,
                    article.published_at,
                    article.summary,
                    article.content_html,
                    article.content_text,
                    json.dumps(article.categories, ensure_ascii=False),
                    duplicate_of,
                    duplicate_score,
                    duplicate_reason,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid), True, duplicate is not None

    def _find_duplicate(self, connection: sqlite3.Connection, article: Article):
        candidates = connection.execute(
            """
            SELECT id, title, summary, content_text
            FROM articles
            WHERE duplicate_of_article_id IS NULL
            ORDER BY COALESCE(NULLIF(published_at, ''), created_at) DESC
            LIMIT 500
            """
        ).fetchall()
        return find_duplicate(article, candidates)

    def mark_existing_duplicates(self, limit: int = 1000) -> tuple[int, int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, source_name, url, title, author, published_at, summary,
                       content_html, content_text, categories_json
                FROM articles
                WHERE duplicate_of_article_id IS NULL
                ORDER BY COALESCE(NULLIF(published_at, ''), created_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            canonical = []
            marked = 0
            for row in rows:
                article = Article(
                    source_name=row["source_name"],
                    url=row["url"],
                    title=row["title"],
                    author=row["author"],
                    published_at=row["published_at"],
                    summary=row["summary"],
                    content_html=row["content_html"],
                    content_text=row["content_text"],
                    categories=json.loads(row["categories_json"]),
                )
                duplicate = find_duplicate(article, canonical)
                if duplicate:
                    connection.execute(
                        """
                        UPDATE articles
                        SET duplicate_of_article_id = ?, duplicate_score = ?,
                            duplicate_reason = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            duplicate.article_id,
                            duplicate.score,
                            duplicate.reason,
                            utc_now(),
                            row["id"],
                        ),
                    )
                    marked += 1
                    continue
                canonical.append(row)
            return len(rows), marked

    def save_ai_result(self, article_id: int, model: str, result: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO ai_results(article_id, model, result_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(article_id) DO UPDATE SET
                    model = excluded.model,
                    result_json = excluded.result_json,
                    created_at = excluded.created_at
                """,
                (article_id, model, json.dumps(result, ensure_ascii=False), utc_now()),
            )

    def list_articles(self, limit: int = 20, include_duplicates: bool = False) -> list[sqlite3.Row]:
        duplicate_filter = "" if include_duplicates else "WHERE a.duplicate_of_article_id IS NULL"
        with self.connect() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT a.*, r.result_json AS ai_result_json, r.model AS ai_model
                    FROM articles a
                    LEFT JOIN ai_results r ON r.article_id = a.id
                    {duplicate_filter}
                    ORDER BY COALESCE(NULLIF(a.published_at, ''), a.created_at) DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def articles_without_ai(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT a.*
                    FROM articles a
                    LEFT JOIN ai_results r ON r.article_id = a.id
                    WHERE r.id IS NULL AND a.duplicate_of_article_id IS NULL
                    ORDER BY COALESCE(NULLIF(a.published_at, ''), a.created_at) DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def articles_for_ai(self, limit: int = 20, force: bool = False) -> list[sqlite3.Row]:
        if force:
            with self.connect() as connection:
                return list(
                    connection.execute(
                        """
                        SELECT a.*
                        FROM articles a
                        WHERE a.duplicate_of_article_id IS NULL
                        ORDER BY COALESCE(NULLIF(a.published_at, ''), a.created_at) DESC
                        LIMIT ?
                        """,
                        (limit,),
                    )
                )
        return self.articles_without_ai(limit=limit)
