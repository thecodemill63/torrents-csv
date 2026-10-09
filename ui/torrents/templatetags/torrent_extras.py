"""Custom template filters for the torrents UI."""
import time
from datetime import datetime, timezone

from django import template

register = template.Library()


@register.filter
def rel_time(unix_ts):
    """Render a unix epoch as a short relative time ('3d ago', '2w ago', etc.).

    Returns an empty string for None or values that look like sentinels.
    """
    if not unix_ts or unix_ts < 946684800:  # before 2000-01-01: sentinel/garbage
        return ""
    now = time.time()
    delta = now - unix_ts
    if delta < 0:
        delta = 0
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    if delta < 604800:
        return f"{int(delta // 86400)}d ago"
    if delta < 2592000:
        return f"{int(delta // 604800)}w ago"
    if delta < 31536000:
        return f"{int(delta // 2592000)}mo ago"
    return f"{int(delta // 31536000)}y ago"


@register.filter
def short_date(unix_ts):
    """Render a unix epoch as YYYY-MM-DD."""
    if not unix_ts or unix_ts < 946684800:
        return ""
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%d")
