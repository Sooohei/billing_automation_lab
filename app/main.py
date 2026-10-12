from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.auth import install_auth
from app.config import get_settings
from app.csrf import install_csrf
from app.errors import install_error_handlers
from app.partners.routes import router as partners_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="billing_automation_lab")

    install_error_handlers(app)
    # ミドルウェアは後に登録したものが先に動く。認証 → CSRF の順にする
    install_csrf(app, settings.app_origin)
    install_auth(app, settings)

    app.include_router(partners_router)

    @app.get("/")
    def index() -> RedirectResponse:
        # 請求書一覧（SR-03）ができるまでは、取引先管理を最初の画面にする
        return RedirectResponse("/partners")

    return app


app = create_app()
