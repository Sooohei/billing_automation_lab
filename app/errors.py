import logging

from fastapi import FastAPI, Request, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.templating import templates

logger = logging.getLogger(__name__)

NOT_FOUND_MESSAGE = "お探しのページは見つかりません"
FORBIDDEN_MESSAGE = "この操作は受け付けられません。画面を開き直してください"
SERVER_ERROR_MESSAGE = "エラーが発生しました"


def error_response(request: Request, status_code: int, message: str) -> Response:
    return templates.TemplateResponse(
        request,
        "errors/error.html",
        {"message": message, "status_code": status_code, "show_home_link": status_code == 404},
        status_code=status_code,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code == 404:
            return error_response(request, 404, NOT_FOUND_MESSAGE)
        if exc.status_code == 403:
            return error_response(request, 403, FORBIDDEN_MESSAGE)
        return Response(status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def handle_exception(request: Request, exc: Exception) -> Response:
        # エラーの詳細は画面に出さず、ログに出す
        logger.exception("想定外のエラー: %s %s", request.method, request.url.path)
        return error_response(request, 500, SERVER_ERROR_MESSAGE)
