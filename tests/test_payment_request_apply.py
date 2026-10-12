from datetime import UTC, date, datetime

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.freee.client import FreeeApiError, FreeeNoResponseError, PaymentRequestParams
from app.invoices.models import Invoice
from app.partners.models import Partner
from app.payment_requests.models import PaymentRequestStatus
from app.storage.local import LocalFileStorage
from tests.fakes import FakeFreeeClient
from tests.test_invoice_list import Data
from tests.test_partner_repository import add_partner
from tests.test_payment_request_save import ORIGIN, form, input_of


@pytest.fixture
def data(session: Session) -> Data:
    return Data(session)


@pytest.fixture
def partner(session: Session) -> Partner:
    partner = add_partner(session, "Aメディア", [])
    session.commit()
    return partner


@pytest.fixture
def invoice(data: Data, file_storage: LocalFileStorage) -> Invoice:
    invoice = data.invoice(payment_input={})
    file_storage.save(invoice.file_key, b"%PDF-1.4 invoice")
    return invoice


def apply(client: TestClient, invoice: Invoice, values: dict[str, str]) -> httpx2.Response:
    return client.post(
        f"/invoices/{invoice.id}/apply", data=values, headers=ORIGIN, follow_redirects=False
    )


def complete_form(partner: Partner, **overrides: str) -> dict[str, str]:
    return form(partner_id=str(partner.id), pre_application_id="5001", **overrides)


def test_申請に成功したら申請済にして識別子と申請者と申請日時を記録する(
    client: TestClient,
    session: Session,
    invoice: Invoice,
    partner: Partner,
    freee_client: FakeFreeeClient,
) -> None:
    response = apply(client, invoice, complete_form(partner))

    assert response.status_code == 303
    assert response.headers["location"] == f"/invoices/{invoice.id}?applied=1"
    applied = input_of(session, invoice)
    assert applied.status == PaymentRequestStatus.SUBMITTED
    assert applied.freee_payment_request_id == 9001
    assert applied.applicant_email == "dev@example.com"
    assert applied.applied_at is not None
    assert "freee に支払い依頼を申請しました" in client.get(response.headers["location"]).text


def test_freeeに送る項目は対応表のとおり(
    client: TestClient, invoice: Invoice, partner: Partner, freee_client: FakeFreeeClient
) -> None:
    apply(client, invoice, complete_form(partner))

    user = CurrentUser(email="dev@example.com")
    assert freee_client.uploaded == [(user, b"%PDF-1.4 invoice", invoice.file_name)]
    assert freee_client.created == [
        (
            user,
            PaymentRequestParams(
                title="202610_Aメディア_メディア費",
                partner_id=101,
                document_code="AM-2026-10-001",
                issue_date=date(2026, 10, 1),
                payment_date=date(2026, 10, 31),
                amount=1_100_000,
                account_item_id=201,
                tax_code=136,
                approval_flow_route_id=301,
                parent_id=5001,
                receipt_ids=[7001],
            ),
        )
    ]


def test_入力チェックに当てはまれば保存も申請もしない(
    client: TestClient,
    session: Session,
    invoice: Invoice,
    partner: Partner,
    freee_client: FakeFreeeClient,
) -> None:
    response = apply(client, invoice, complete_form(partner, issue_date="2026-02-30"))

    assert response.status_code == 422
    assert "請求書発行日は実在する日付を入力してください" in response.text
    assert input_of(session, invoice).title is None
    assert freee_client.created == []


def test_必須の項目が空か事前申請がなければすべて表示して申請しないが保存はする(
    client: TestClient, session: Session, invoice: Invoice, freee_client: FakeFreeeClient
) -> None:
    empty = {key: "" for key in form()}

    response = apply(client, invoice, {**empty, "invoice_number": "保存される番号"})

    assert response.status_code == 422
    for message in [
        "取引先を選択してください",
        "申請タイトルを入力してください",
        "請求書発行日を入力してください",
        "支払期日を入力してください",
        "税込金額を入力してください",
        "freee 上の取引先を選択してください",
        "勘定科目を選択してください",
        "税区分を選択してください",
        "承認経路を選択してください",
        "紐付ける事前申請を選択してください",
    ]:
        assert message in response.text
    saved = input_of(session, invoice)
    assert saved.status == PaymentRequestStatus.UNSUBMITTED
    assert saved.invoice_number == "保存される番号"
    assert freee_client.uploaded == []


def test_任意の項目は空でも申請できる(
    client: TestClient, session: Session, invoice: Invoice, partner: Partner
) -> None:
    optional = {
        "invoice_number": "",
        "qualified_invoice_issuer_number": "",
        "amount_excluding_tax": "",
        "tax_amount": "",
    }

    assert apply(client, invoice, complete_form(partner, **optional)).status_code == 303
    assert input_of(session, invoice).status == PaymentRequestStatus.SUBMITTED


def test_freeeがエラーを返したら未申請のままエラー内容を表示する(
    client: TestClient,
    session: Session,
    invoice: Invoice,
    partner: Partner,
    freee_client: FakeFreeeClient,
) -> None:
    freee_client.create_payment_request_error = FreeeApiError("承認経路が無効です")

    response = apply(client, invoice, complete_form(partner))

    assert response.status_code == 502
    assert "freee への申請に失敗しました: 承認経路が無効です" in response.text
    failed = input_of(session, invoice)
    assert failed.status == PaymentRequestStatus.UNSUBMITTED
    assert failed.freee_payment_request_id is None
    # 画面の入力値は保存されている
    assert failed.title == "202610_Aメディア_メディア費"


def test_freeeから応答がなければ未申請のまま確認を促す(
    client: TestClient,
    session: Session,
    invoice: Invoice,
    partner: Partner,
    freee_client: FakeFreeeClient,
) -> None:
    freee_client.upload_receipt_error = FreeeNoResponseError("timeout")

    response = apply(client, invoice, complete_form(partner))

    assert response.status_code == 504
    assert "freee から応答を受け取れませんでした。freee 上で申請されている可能性があります。" in (
        response.text
    )
    assert "申請されていないことを確認してください" in response.text
    assert input_of(session, invoice).status == PaymentRequestStatus.UNSUBMITTED


def test_失敗した請求書は再度申請できる(
    client: TestClient,
    session: Session,
    invoice: Invoice,
    partner: Partner,
    freee_client: FakeFreeeClient,
) -> None:
    freee_client.create_payment_request_error = FreeeApiError("一時的なエラー")
    apply(client, invoice, complete_form(partner))
    freee_client.create_payment_request_error = None

    assert apply(client, invoice, complete_form(partner)).status_code == 303
    assert input_of(session, invoice).status == PaymentRequestStatus.SUBMITTED


def test_申請済の請求書の申請は受け付けない(
    client: TestClient,
    session: Session,
    invoice: Invoice,
    partner: Partner,
    freee_client: FakeFreeeClient,
) -> None:
    apply(client, invoice, complete_form(partner))

    response = apply(client, invoice, complete_form(partner, title="別のタイトル"))

    assert response.status_code == 409
    assert "申請済です" in response.text
    assert len(freee_client.created) == 1
    assert input_of(session, invoice).title == "202610_Aメディア_メディア費"


def test_申請すると一覧の申請状態が申請済になる(
    client: TestClient, invoice: Invoice, partner: Partner
) -> None:
    apply(client, invoice, complete_form(partner))

    response = client.get("/invoices?status=submitted")

    assert f'href="/invoices/{invoice.id}"' in response.text


def test_申請日時と申請者は申請済の画面に表示する(
    client: TestClient, session: Session, invoice: Invoice, partner: Partner
) -> None:
    apply(client, invoice, complete_form(partner))
    applied_at = input_of(session, invoice).applied_at
    assert applied_at is not None

    response = client.get(f"/invoices/{invoice.id}")

    assert "dev@example.com" in response.text
    assert ">申請</button>" not in response.text
    assert applied_at.astimezone(UTC) <= datetime.now(UTC)
