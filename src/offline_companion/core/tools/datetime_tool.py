"""datetime_tool：返回当前时间的 builtin Tool。"""

from __future__ import annotations

from datetime import datetime, timezone


def datetime_now() -> dict[str, object]:
    """摘要：返回当前 UTC 时间与 Unix 时间戳。"""
    now = datetime.now(timezone.utc)
    return {
        "iso_utc": now.isoformat(),
        "timestamp": now.timestamp(),
    }
