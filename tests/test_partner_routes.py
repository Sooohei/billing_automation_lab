import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.partners.repository import PartnerRepository
from tests.test_partner_repository import add_partner

ORIGIN = {"Origin": "http://localhost:8000"}

VALID_FORM = {
    "name": "Aメディア",
    "emails": "billing@a-media.jp\ninfo@a-media.jp",
    "freee_partner_id": "101",
    "freee_account_item_id": "201",
    "freee_tax_code": "136",
    "freee_approval_flow_route_id": "301",
}


def test_一覧に有効な取引先とfreeeの表示名を表示する(client: TestClient, session: Session) -> None:
    add_partner(session, "Aメディア", ["billing@a-media.jp"])
    add_partner(session, "削除済みメディア", [], deleted=True)

    response = client.get("/partners")

    assert response.status_code == 200
    assert "Aメディア" in response.text
    assert "billing@a-media.jp" in response.text
    assert "株式会社Aメディア" in response.text
    assert "広告宣伝費" in response.text
    assert "削除済みメディア" not in response.text


def test_一覧でfreeeの選択肢にない値はその旨を表示する(
    client: TestClient, session: Session
) -> None:
    partner = add_partner(session, "Aメディア", ["billing@a-media.jp"])
    partner.freee_account_item_id = 999
    session.flush()

    response = client.get("/partners")

    assert "（freee に存在しない値: 999）" in response.text


def test_登録画面にfreeeの選択肢を表示する(client: TestClient) -> None:
    response = client.get("/partners/new")

    assert response.status_code == 200
    assert '<option value="201">広告宣伝費</option>' in response.text


def test_登録に成功したら一覧へ戻る(client: TestClient, session: Session) -> None:
    response = client.post("/partners/new", data=VALID_FORM, headers=ORIGIN, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/partners"
    [partner] = PartnerRepository(session).list_active()
    assert [email.email for email in partner.emails] == ["billing@a-media.jp", "info@a-media.jp"]


def test_登録に失敗したら入力値を残してエラーを表示する(client: TestClient) -> None:
    form = {**VALID_FORM, "emails": "invalid", "freee_tax_code": ""}

    response = client.post("/partners/new", data=form, headers=ORIGIN)

    assert response.status_code == 422
    assert "「invalid」はメールアドレスの形式ではありません" in response.text
    assert "既定の税区分を選択してください" in response.text
    assert 'value="Aメディア"' in response.text
    assert '<option value="201" selected>広告宣伝費</option>' in response.text


def test_変更画面に現在の値を表示する(client: TestClient, session: Session) -> None:
    partner = add_partner(session, "Aメディア", ["a1@a-media.jp", "a2@a-media.jp"])

    response = client.get(f"/partners/{partner.id}/edit")

    assert response.status_code == 200
    assert 'value="Aメディア"' in response.text
    assert "a1@a-media.jp\na2@a-media.jp</textarea>" in response.text
    assert '<option value="136" selected>課対仕入10%</option>' in response.text


def test_変更画面でfreeeの選択肢にない値は未選択にする(
    client: TestClient, session: Session
) -> None:
    partner = add_partner(session, "Aメディア", ["billing@a-media.jp"])
    partner.freee_tax_code = 999
    session.flush()

    response = client.get(f"/partners/{partner.id}/edit")

    assert "（freee に存在しない値: 999）。選び直してください" in response.text
    assert '<option value="136">課対仕入10%</option>' in response.text


def test_変更に成功したら一覧へ戻る(client: TestClient, session: Session) -> None:
    partner = add_partner(session, "Aメディア", ["billing@a-media.jp"])
    form = {**VALID_FORM, "name": "Aメディア2"}

    response = client.post(
        f"/partners/{partner.id}/edit", data=form, headers=ORIGIN, follow_redirects=False
    )

    assert response.status_code == 303
    [updated] = PartnerRepository(session).list_active()
    assert updated.name == "Aメディア2"


def test_変更に失敗したらエラーを表示する(client: TestClient, session: Session) -> None:
    partner = add_partner(session, "Aメディア", ["billing@a-media.jp"])

    response = client.post(
        f"/partners/{partner.id}/edit", data={**VALID_FORM, "name": ""}, headers=ORIGIN
    )

    assert response.status_code == 422
    assert "取引先名を入力してください" in response.text


def test_削除したら一覧へ戻り一覧に出ない(client: TestClient, session: Session) -> None:
    partner = add_partner(session, "Aメディア", ["billing@a-media.jp"])

    response = client.post(f"/partners/{partner.id}/delete", headers=ORIGIN, follow_redirects=False)

    assert response.status_code == 303
    assert "Aメディア" not in client.get("/partners").text


def test_一覧の削除ボタンは確認ダイアログを経て送信する(
    client: TestClient, session: Session
) -> None:
    add_partner(session, "Aメディア", ["billing@a-media.jp"])

    response = client.get("/partners")

    assert 'data-confirm="取引先「Aメディア」を削除しますか？"' in response.text
    assert 'onsubmit="return confirm(this.dataset.confirm)"' in response.text


@pytest.mark.parametrize("path_id", ["not-a-uuid", str(uuid.uuid4())])
def test_存在しない取引先は404を表示する(client: TestClient, path_id: str) -> None:
    assert client.get(f"/partners/{path_id}/edit").status_code == 404
    assert (
        client.post(f"/partners/{path_id}/edit", data=VALID_FORM, headers=ORIGIN).status_code == 404
    )
    assert client.post(f"/partners/{path_id}/delete", headers=ORIGIN).status_code == 404


def test_削除済みの取引先は変更画面を開けない(client: TestClient, session: Session) -> None:
    partner = add_partner(session, "Aメディア", [], deleted=True)

    assert client.get(f"/partners/{partner.id}/edit").status_code == 404


def test_取引先名はHTMLとしてエスケープして表示する(client: TestClient, session: Session) -> None:
    add_partner(session, "<script>alert(1)</script>", ["x@x.jp"])

    response = client.get("/partners")

    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text
