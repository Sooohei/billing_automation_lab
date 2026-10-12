from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.auth import install_auth
from app.config import get_settings
from app.csrf import install_csrf
from app.errors import install_error_handlers
from app.partners.routes import router as partners_router
from app.payment_requests.routes import router as payment_requests_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="billing_automation_lab")

    install_error_handlers(app)
    # ミドルウェアは後に登録したものが先に動く。認証 → CSRF の順にする
    install_csrf(app, settings.app_origin)
    install_auth(app, settings)

    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    app.include_router(partners_router)
    app.include_router(payment_requests_router)

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse("/invoices")

    return app


app = create_app()
