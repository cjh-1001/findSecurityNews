from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, time, timezone
import json
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "security_news.db"
DEFAULT_ARCHIVE_DIR = ROOT / "outputs" / "archive"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive and clean old security news records.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--from-date", default="", help="Inclusive start date, YYYY-MM-DD.")
    parser.add_argument("--to-date", default="", help="Exclusive end date, YYYY-MM-DD.")
    parser.add_argument("--before", default="", help="Delete records before this date, YYYY-MM-DD.")
    parser.add_argument("--yes", action="store_true", help="Do not prompt for DELETE confirmation.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted only.")
    parser.add_argument("--vacuum", action="store_true", help="Run SQLite VACUUM after deletion.")
    return parser.parse_args()


def parse_record_time(row: sqlite3.Row) -> datetime:
    value = row["published_at"] or row["created_at"]
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    if len(value) == 10:
        return datetime.combine(date.fromisoformat(value), time.min, timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date_bound(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), time.min, timezone.utc)


def load_rows(db_path: Path) -> list[sqlite3.Row]:
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return list(
            connection.execute(
                """
                SELECT a.*, r.result_json AS ai_result_json, r.model AS ai_model
                FROM articles a
                LEFT JOIN ai_results r ON r.article_id = a.id
                ORDER BY COALESCE(NULLIF(a.published_at, ''), a.created_at) ASC
                """
            )
        )


def bucket_rows(rows: list[sqlite3.Row]) -> dict[str, list[sqlite3.Row]]:
    buckets: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        record_time = parse_record_time(row)
        key = f"{record_time:%Y-%m}"
        buckets[key].append(row)
    return dict(sorted(buckets.items()))


def print_buckets(buckets: dict[str, list[sqlite3.Row]]) -> None:
    print("Available article periods:")
    for index, (month, rows) in enumerate(buckets.items(), start=1):
        times = [parse_record_time(row) for row in rows]
        sources = sorted({row["source_name"] for row in rows})
        print(
            f"{index}. {month} | {len(rows)} articles | "
            f"{min(times):%Y-%m-%d} to {max(times):%Y-%m-%d} | "
            f"sources: {', '.join(sources)}"
        )


def select_interactive(rows: list[sqlite3.Row]) -> tuple[list[sqlite3.Row], str]:
    buckets = bucket_rows(rows)
    if not buckets:
        return [], ""
    print_buckets(buckets)
    print("")
    print("Choose cleanup mode:")
    print("1. Select month numbers, e.g. 1 or 1,2")
    print("2. Custom date range [from, to), e.g. 2026-05-01 to 2026-06-01")
    choice = input("Mode [1/2, default 1]: ").strip() or "1"

    if choice == "2":
        from_value = input("From date YYYY-MM-DD: ").strip()
        to_value = input("To date YYYY-MM-DD (exclusive): ").strip()
        since = parse_date_bound(from_value)
        until = parse_date_bound(to_value)
        selected = rows_in_range(rows, since, until)
        return selected, f"{from_value}_to_{to_value}"

    keys = list(buckets)
    selected_input = input("Month number(s): ").strip()
    selected_indexes = {
        int(part.strip())
        for part in selected_input.split(",")
        if part.strip().isdigit()
    }
    selected_rows = []
    selected_keys = []
    for index in selected_indexes:
        if 1 <= index <= len(keys):
            key = keys[index - 1]
            selected_keys.append(key)
            selected_rows.extend(buckets[key])
    return selected_rows, "_".join(selected_keys)


def rows_in_range(rows: list[sqlite3.Row], since: datetime | None, until: datetime) -> list[sqlite3.Row]:
    selected = []
    for row in rows:
        record_time = parse_record_time(row)
        if since is not None and record_time < since:
            continue
        if record_time < until:
            selected.append(row)
    return selected


def selected_from_args(args: argparse.Namespace, rows: list[sqlite3.Row]) -> tuple[list[sqlite3.Row], str]:
    if args.before:
        until = parse_date_bound(args.before)
        return rows_in_range(rows, None, until), f"before_{args.before}"
    if args.from_date and args.to_date:
        since = parse_date_bound(args.from_date)
        until = parse_date_bound(args.to_date)
        return rows_in_range(rows, since, until), f"{args.from_date}_to_{args.to_date}"
    return select_interactive(rows)


def row_to_archive(row: sqlite3.Row) -> dict:
    data = dict(row)
    if data.get("ai_result_json"):
        try:
            data["ai_result"] = json.loads(data["ai_result_json"])
        except json.JSONDecodeError:
            data["ai_result"] = data["ai_result_json"]
    return data


def archive_rows(rows: list[sqlite3.Row], archive_dir: Path, label: str) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = label or "selected"
    path = archive_dir / f"security_news_archive_{safe_label}_{timestamp}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row_to_archive(row), ensure_ascii=False) + "\n")
    return path


def delete_rows(db_path: Path, rows: list[sqlite3.Row], vacuum: bool) -> None:
    ids = [int(row["id"]) for row in rows]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"DELETE FROM ai_results WHERE article_id IN ({placeholders})", ids)
        connection.execute(f"DELETE FROM articles WHERE id IN ({placeholders})", ids)
        connection.commit()
        if vacuum:
            connection.execute("VACUUM")


def summarize_selection(rows: list[sqlite3.Row]) -> None:
    if not rows:
        print("No rows selected.")
        return
    times = [parse_record_time(row) for row in rows]
    sources = sorted({row["source_name"] for row in rows})
    with_ai = sum(1 for row in rows if row["ai_result_json"])
    print("")
    print("Selected cleanup range:")
    print(f"- Articles: {len(rows)}")
    print(f"- With AI results: {with_ai}")
    print(f"- Date range: {min(times):%Y-%m-%d} to {max(times):%Y-%m-%d}")
    print(f"- Sources: {', '.join(sources)}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    rows = load_rows(args.db)
    if not rows:
        print("No articles found.")
        return 0

    selected, label = selected_from_args(args, rows)
    summarize_selection(selected)
    if not selected:
        return 0

    if args.dry_run:
        print("Dry run only. No archive was written and database was not changed.")
        return 0

    archive_path = archive_rows(selected, args.archive_dir, label)
    print(f"Archive written: {archive_path}")
    print("Archive includes original HTML/text fields and AI result JSON.")

    if not args.yes:
        confirmation = input("Type DELETE to remove selected rows from SQLite: ").strip()
        if confirmation != "DELETE":
            print("Cancelled. Archive was kept; database was not changed.")
            return 1

    delete_rows(args.db, selected, vacuum=args.vacuum)
    print(f"Deleted {len(selected)} articles from SQLite.")
    if args.vacuum:
        print("VACUUM completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
