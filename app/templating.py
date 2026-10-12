from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates


def _current_user(request: Request) -> dict[str, Any]:
    """共通レイアウトでログイン中の利用者を表示するため、すべてのテンプレートに渡す。"""
    return {"current_user": getattr(request.state, "user", None)}


def _jst(value: datetime | None) -> str:
    """日時を日本時間の YYYY-MM-DD HH:MM で表示する。"""
    if value is None:
        return ""
    return value.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M")


def _yen(value: int | None) -> str:
    """金額をカンマ区切りで表示する。"""
    return "" if value is None else f"{value:,} 円"


templates = Jinja2Templates(
    directory=Path(__file__).parent / "templates",
    context_processors=[_current_user],
)
templates.env.filters["jst"] = _jst
templates.env.filters["yen"] = _yen
