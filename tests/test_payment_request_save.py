import uuid
from datetime import UTC, date, datetime

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.extraction.repository import ExtractionRepository
from app.freee.client import FreeeNoResponseError
from app.invoices.models import Invoice
from app.payment_requests.models import PaymentRequestInput, PaymentRequestStatus
from app.payment_requests.repository import PaymentRequestRepository
from tests.fakes import FakeFreeeClient
from tests.test_invoice_list import Data
from tests.test_partner_repository import add_partner

ORIGIN = {"Origin": "http://localhost:8000"}


@pytest.fixture
def data(session: Session) -> Data:
    return Data(session)


def form(**overrides: str) -> dict[str, str]:
    values = {
        "partner_id": "",
        "title": "202610_Aメディア_メディア費",
        "invoice_number": "AM-2026-10-001",
        "qualified_invoice_issuer_number": "T1234567890123",
        "issue_date": "2026-10-01",
        "due_date": "2026-10-31",
        "amount_excluding_tax": "1000000",
        "tax_amount": "100000",
        "amount_including_tax": "1100000",
        "freee_partner_id": "101",
        "freee_account_item_id": "201",
        "freee_tax_code": "136",
        "freee_approval_flow_route_id": "301",
    }
    values.update(overrides)
    return values


def input_of(session: Session, invoice: Invoice) -> PaymentRequestInput:
    session.expire_all()
    payment_input = PaymentRequestRepository(session).get(invoice.id)
    assert payment_input is not None
    return payment_input


def save(client: TestClient, invoice: Invoice, values: dict[str, str]) -> httpx2.Response:
    return client.post(
        f"/invoices/{invoice.id}/save", data=values, headers=ORIGIN, follow_redirects=False
    )


def test_入力値で保存して確認修正画面を表示し直す(
    client: TestClient, session: Session, data: Data
) -> None:
    partner = add_partner(session, "Aメディア", [])
    invoice = data.invoice(payment_input={})

    response = save(client, invoice, form(partner_id=str(partner.id), pre_application_id="5001"))

    assert response.status_code == 303
    assert response.headers["location"] == f"/invoices/{invoice.id}?saved=1"
    saved = input_of(session, invoice)
    assert saved.partner_id == partner.id
    assert saved.title == "202610_Aメディア_メディア費"
    assert saved.qualified_invoice_issuer_number == "T1234567890123"
    assert (saved.issue_date, saved.due_date) == (date(2026, 10, 1), date(2026, 10, 31))
    assert (saved.amount_excluding_tax, saved.tax_amount) == (1_000_000, 100_000)
    assert saved.amount_including_tax == 1_100_000
    assert (saved.freee_partner_id, saved.freee_tax_code) == (101, 136)
    # 事前申請は、申請番号と件名の控えも保存する
    assert saved.pre_application_id == 5001
    assert saved.pre_application_number == "A-0001"
    assert saved.pre_application_title == "2026年10月 媒体費 Aメディア"
    assert "保存しました" in client.get(response.headers["location"]).text


def test_空の項目はそのまま空で保存できる(client: TestClient, session: Session, data: Data) -> None:
    invoice = data.invoice(payment_input={"title": "元のタイトル", "amount_including_tax": 1})
    empty = {key: "" for key in form()}

    assert save(client, invoice, empty).status_code == 303

    saved = input_of(session, invoice)
    assert (saved.title, saved.amount_including_tax, saved.freee_partner_id) == (None, None, None)


def test_保存しても抽出結果は変わらない(client: TestClient, session: Session, data: Data) -> None:
    invoice = data.invoice(extraction={"invoice_number": "抽出した番号"}, payment_input={})

    save(client, invoice, form(invoice_number="直した番号"))

    session.expire_all()
    extraction = ExtractionRepository(session).get(invoice.id)
    assert extraction is not None
    assert extraction.invoice_number == "抽出した番号"
    assert input_of(session, invoice).invoice_number == "直した番号"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"partner_id": str(uuid.uuid4())}, "取引先は登録されている取引先から選択してください"),
        ({"partner_id": "abc"}, "取引先は登録されている取引先から選択してください"),
        (
            {"qualified_invoice_issuer_number": "T123"},
            "適格請求書発行事業者登録番号は「T」と 13 桁の数字で入力してください",
        ),
        ({"issue_date": "2026-02-30"}, "請求書発行日は実在する日付を入力してください"),
        ({"due_date": "2026/10/31"}, "支払期日は実在する日付を入力してください"),
        ({"amount_excluding_tax": "1.5"}, "税抜金額は整数で入力してください"),
        ({"tax_amount": "十万"}, "消費税額は整数で入力してください"),
        ({"amount_including_tax": "1,100,000"}, "税込金額は整数で入力してください"),
        ({"freee_partner_id": "999"}, "freee 上の取引先は freee の選択肢から選択してください"),
        ({"freee_account_item_id": "x"}, "勘定科目は freee の選択肢から選択してください"),
        ({"freee_tax_code": "999"}, "税区分は freee の選択肢から選択してください"),
        ({"freee_approval_flow_route_id": "999"}, "承認経路は freee の選択肢から選択してください"),
        ({"pre_application_id": "5999"}, "紐付ける事前申請は一覧から選択してください"),
    ],
)
def test_入力チェックに当てはまれば保存しない(
    client: TestClient,
    session: Session,
    data: Data,
    overrides: dict[str, str],
    message: str,
) -> None:
    invoice = data.invoice(payment_input={"title": "元のタイトル"})

    response = save(client, invoice, form(**overrides))

    assert response.status_code == 422
    assert message in response.text
    assert input_of(session, invoice).title == "元のタイトル"


def test_当てはまる入力チェックをすべて表示し入力値を残す(client: TestClient, data: Data) -> None:
    invoice = data.invoice(payment_input={})

    response = save(
        client, invoice, form(title="直したタイトル", issue_date="2026-02-30", tax_amount="x")
    )

    assert "請求書発行日は実在する日付を入力してください" in response.text
    assert "消費税額は整数で入力してください" in response.text
    assert 'value="直したタイトル"' in response.text
    assert 'value="x"' in response.text


def test_削除済みの取引先も現在の取引先なら保存できる(
    client: TestClient, session: Session, data: Data
) -> None:
    deleted = add_partner(session, "旧メディア", [], deleted=True)
    other_deleted = add_partner(session, "別の旧メディア", [], deleted=True)
    invoice = data.invoice(payment_input={"partner_id": deleted.id})

    assert save(client, invoice, form(partner_id=str(deleted.id))).status_code == 303
    assert save(client, invoice, form(partner_id=str(other_deleted.id))).status_code == 422


def test_事前申請を選ぶ欄がなければ紐付けを変えない(
    client: TestClient, session: Session, data: Data
) -> None:
    invoice = data.invoice(
        payment_input={
            "pre_application_id": 5009,
            "pre_application_number": "A-0009",
            "pre_application_title": "15 件に達した事前申請",
        }
    )

    # pre_application_id を送らない（一覧に現在の事前申請がなく、何も選ばなかった）
    assert save(client, invoice, form()).status_code == 303

    assert input_of(session, invoice).pre_application_id == 5009


def test_事前申請を取得できなかったときは変更できないが他の項目は保存できる(
    client: TestClient, session: Session, data: Data, freee_client: FakeFreeeClient
) -> None:
    invoice = data.invoice(payment_input={"pre_application_id": 5001})
    freee_client.list_approval_requests_error = FreeeNoResponseError("timeout")

    changed = save(client, invoice, form(pre_application_id="5002"))
    unchanged = save(client, invoice, form(title="直したタイトル"))

    assert changed.status_code == 422
    assert "事前申請を取得できなかったため、紐付ける事前申請を変更できません" in changed.text
    assert unchanged.status_code == 303
    saved = input_of(session, invoice)
    assert (saved.title, saved.pre_application_id) == ("直したタイトル", 5001)


def test_申請済は保存できない(client: TestClient, session: Session, data: Data) -> None:
    invoice = data.invoice(
        payment_input={
            "title": "申請したタイトル",
            "status": PaymentRequestStatus.SUBMITTED,
            "freee_payment_request_id": 9001,
            "applicant_email": "dev@example.com",
            "applied_at": datetime(2026, 10, 12, tzinfo=UTC),
        }
    )

    response = save(client, invoice, form(title="直したタイトル"))

    assert response.status_code == 409
    assert "申請済のため修正できません" in response.text
    assert input_of(session, invoice).title == "申請したタイトル"


def test_存在しない請求書は404を表示する(client: TestClient) -> None:
    response = client.post(f"/invoices/{uuid.uuid4()}/save", data=form(), headers=ORIGIN)

    assert response.status_code == 404
