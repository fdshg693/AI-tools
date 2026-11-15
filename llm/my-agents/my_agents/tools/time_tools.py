"""現在時刻を返すツール。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import tool


@tool
def get_time(tz: str = "Asia/Tokyo") -> str:
    """指定したIANAタイムゾーン名(既定: Asia/Tokyo)の現在時刻をISO 8601形式で返す。"""
    try:
        zone = ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"不正なタイムゾーン: {tz}") from exc
    return datetime.now(zone).isoformat()
