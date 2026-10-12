from fastapi import FastAPI

from app.auth import install_auth
from app.config import get_settings
from app.csrf import install_csrf
from app.errors import install_error_handlers


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="billing_automation_lab")

    install_error_handlers(app)
    # ミドルウェアは後に登録したものが先に動く。認証 → CSRF の順にする
    install_csrf(app, settings.app_origin)
    install_auth(app, settings)

    return app


app = create_app()
