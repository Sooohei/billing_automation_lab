from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from app.errors import FORBIDDEN_MESSAGE, error_response

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def install_csrf(app: FastAPI, app_origin: str) -> None:
    """状態を変えるリクエストで、Origin ヘッダーが APP_ORIGIN と一致しなければ 403 で拒否する。"""

    @app.middleware("http")
    async def check_origin(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in SAFE_METHODS and request.headers.get("origin") != app_origin:
            return error_response(request, 403, FORBIDDEN_MESSAGE)
        return await call_next(request)
