from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response

from app.config import Settings

DEV_USER_EMAIL = "dev@example.com"


@dataclass(frozen=True)
class CurrentUser:
    email: str


def install_auth(app: FastAPI, settings: Settings) -> None:
    """すべてのリクエストで利用者を特定し、request.state.user に入れる。"""
    if settings.auth_mode != "dev":
        # IAP の JWT の検証は、Google Cloud に載せる段階で実装する
        raise RuntimeError(f"AUTH_MODE={settings.auth_mode} は未実装です")

    @app.middleware("http")
    async def authenticate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.user = CurrentUser(email=DEV_USER_EMAIL)
        return await call_next(request)


def get_current_user(request: Request) -> CurrentUser:
    """ルーティングで利用者を使うときの依存関係。"""
    user: CurrentUser = request.state.user
    return user
