from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates


def _current_user(request: Request) -> dict[str, Any]:
    """共通レイアウトでログイン中の利用者を表示するため、すべてのテンプレートに渡す。"""
    return {"current_user": getattr(request.state, "user", None)}


templates = Jinja2Templates(
    directory=Path(__file__).parent / "templates",
    context_processors=[_current_user],
)
