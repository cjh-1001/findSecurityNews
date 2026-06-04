from datetime import datetime, timedelta, timezone
import re


LOCAL_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def format_article_time(value: str) -> str:
    if not value:
        return "未知"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return f"{value}（无具体时间）"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone(LOCAL_TZ)
    return f"{local:%Y-%m-%d %H:%M} UTC+8"
