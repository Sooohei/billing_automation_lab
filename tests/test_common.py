from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app

ORIGIN = "http://localhost:8000"


@pytest.fixture
def app() -> FastAPI:
    app = create_app()

    @app.post("/test/post")
    def post() -> dict[str, str]:
        return {"result": "ok"}

    @app.get("/test/error")
    def error() -> None:
        raise RuntimeError("テスト用のエラー")

    return app


@pytest.fixture
def test_client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_存在しないページは404の画面を表示する(test_client: TestClient) -> None:
    response = test_client.get("/no-such-page")

    assert response.status_code == 404
    assert "お探しのページは見つかりません" in response.text
    assert 'href="/invoices"' in response.text


def test_共通レイアウトにメニューとログイン中の利用者を表示する(test_client: TestClient) -> None:
    response = test_client.get("/no-such-page")

    assert 'href="/partners"' in response.text
    assert "dev@example.com" in response.text


def test_想定外のエラーは500の画面を表示し詳細を出さない(test_client: TestClient) -> None:
    response = test_client.get("/test/error")

    assert response.status_code == 500
    assert "エラーが発生しました" in response.text
    assert "テスト用のエラー" not in response.text


def test_OriginヘッダーがAPP_ORIGINと一致するPOSTは受け付ける(test_client: TestClient) -> None:
    response = test_client.post("/test/post", headers={"Origin": ORIGIN})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [{}, {"Origin": "https://evil.example.com"}],
    ids=["Originヘッダーなし", "別のオリジン"],
)
def test_OriginヘッダーがAPP_ORIGINと一致しないPOSTは403で拒否する(
    test_client: TestClient, headers: dict[str, str]
) -> None:
    response = test_client.post("/test/post", headers=headers)

    assert response.status_code == 403
    assert "この操作は受け付けられません" in response.text


def test_トップを開くと取引先管理へ移る(test_client: TestClient) -> None:
    response = test_client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/partners"
