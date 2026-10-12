from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.extraction.models import ExtractionResult
from app.freee.client import FreeeNoResponseError
from app.invoices.models import Invoice
from app.payment_requests.models import PaymentRequestInput, PaymentRequestStatus
from app.payment_requests.repository import PaymentRequestRepository
from app.payment_requests.service import application_title, ensure_input
from app.storage.local import LocalFileStorage
from tests.fakes import FakeFreeeClient
from tests.test_invoice_list import Data
from tests.test_partner_repository import add_partner

NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)
FULL_EXTRACTION: dict[str, object] = {
    "invoice_number": "AM-2026-10-001",
    "qualified_invoice_issuer_number": "T1234567890123",
    "issue_date": date(2026, 10, 1),
    "due_date": date(2026, 10, 31),
    "amount_excluding_tax": 1_000_000,
    "tax_amount": 100_000,
    "amount_including_tax": 1_100_000,
}


@pytest.fixture
def data(session: Session) -> Data:
    return Data(session)


def input_of(session: Session, invoice: Invoice) -> PaymentRequestInput:
    session.expire_all()
    payment_input = PaymentRequestRepository(session).get(invoice.id)
    assert payment_input is not None
    return payment_input


# 支払い依頼インプットの作成


def test_抽出結果があれば抽出結果と取引先の既定値で作る(session: Session, data: Data) -> None:
    partner = add_partner(session, "Aメディア", ["billing@a-media.jp"])
    invoice = data.invoice(extraction={"partner_id": partner.id, **FULL_EXTRACTION})

    ensure_input(session, invoice.id, NOW)

    created = input_of(session, invoice)
    assert created.created_from_extraction is True
    assert created.status == PaymentRequestStatus.UNSUBMITTED
    assert created.partner_id == partner.id
    assert created.title == "202610_Aメディア_メディア費"
    for field, value in FULL_EXTRACTION.items():
        assert getattr(created, field) == value
    assert (created.freee_partner_id, created.freee_account_item_id) == (101, 201)
    assert (created.freee_tax_code, created.freee_approval_flow_route_id) == (136, 301)
    assert created.pre_application_id is None


def test_抽出結果の取引先が空なら取引先の既定値と申請タイトルも空(
    session: Session, data: Data
) -> None:
    invoice = data.invoice(extraction={"partner_id": None, "invoice_number": "X-1"})

    ensure_input(session, invoice.id, NOW)

    created = input_of(session, invoice)
    assert created.created_from_extraction is True
    assert created.invoice_number == "X-1"
    assert (created.partner_id, created.title, created.freee_partner_id) == (None, None, None)


def test_抽出結果がなければ空で作り後からできた抽出結果は反映しない(
    session: Session, data: Data
) -> None:
    invoice = data.invoice()

    ensure_input(session, invoice.id, NOW)
    session.add(ExtractionResult(invoice_id=invoice.id, **FULL_EXTRACTION))
    session.commit()
    ensure_input(session, invoice.id, NOW)

    created = input_of(session, invoice)
    assert created.created_from_extraction is False
    assert (created.partner_id, created.title, created.invoice_number) == (None, None, None)


def test_2回目以降に開いても作り直さない(session: Session, data: Data) -> None:
    partner = add_partner(session, "Aメディア", ["billing@a-media.jp"])
    invoice = data.invoice(extraction={"partner_id": partner.id, **FULL_EXTRACTION})
    ensure_input(session, invoice.id, NOW)
    created = input_of(session, invoice)
    created.title = "利用者が直したタイトル"
    partner.freee_account_item_id = 202
    session.commit()

    ensure_input(session, invoice.id, NOW)

    reopened = input_of(session, invoice)
    assert reopened.title == "利用者が直したタイトル"
    # 作成後に変えた取引先の既定値は反映しない
    assert reopened.freee_account_item_id == 201


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 31, 14, 59, tzinfo=UTC), "202610_Aメディア_メディア費"),
        (datetime(2026, 10, 31, 15, 0, tzinfo=UTC), "202611_Aメディア_メディア費"),
    ],
    ids=["日本時間10月31日23時59分", "日本時間11月1日0時"],
)
def test_申請月は作成した日の日本時間の年月(session: Session, now: datetime, expected: str) -> None:
    partner = add_partner(session, "Aメディア", [])

    assert application_title(partner, now) == expected


# 確認・修正画面


def test_開くと請求書ファイルと入力フォームを並べて表示する(
    client: TestClient, session: Session, data: Data
) -> None:
    partner = add_partner(session, "Aメディア", ["billing@a-media.jp"])
    invoice = data.invoice(extraction={"partner_id": partner.id, **FULL_EXTRACTION})

    response = client.get(f"/invoices/{invoice.id}")

    assert response.status_code == 200
    assert f'<iframe src="/invoices/{invoice.id}/file"' in response.text
    assert 'value="AM-2026-10-001"' in response.text
    assert 'value="2026-10-31"' in response.text
    assert f'<option value="{partner.id}" selected>Aメディア</option>' in response.text
    assert '<option value="201" selected>広告宣伝費</option>' in response.text
    assert ">保存</button>" in response.text
    assert ">申請</button>" in response.text
    assert input_of(session, invoice).title == f"{datetime.now(UTC):%Y%m}_Aメディア_メディア費"


@pytest.mark.parametrize("path_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_存在しない請求書は404を表示する(client: TestClient, path_id: str) -> None:
    assert client.get(f"/invoices/{path_id}").status_code == 404
    assert client.get(f"/invoices/{path_id}/file").status_code == 404


def test_請求書ファイルをPDFとしてブラウザで表示できる形で返す(
    client: TestClient, data: Data, file_storage: LocalFileStorage
) -> None:
    invoice = data.invoice()
    file_storage.save(invoice.file_key, b"%PDF-1.4 test")

    response = client.get(f"/invoices/{invoice.id}/file")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 test"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")


def test_事前申請を申請番号と件名と金額と申請日とともに表示し検索欄を置く(
    client: TestClient, data: Data
) -> None:
    invoice = data.invoice()

    response = client.get(f"/invoices/{invoice.id}")

    assert 'name="pre_application_id" value="5001"' in response.text
    assert "A-0001" in response.text
    assert "2026年10月 媒体費 Aメディア" in response.text
    assert "1,100,000 円" in response.text
    assert "2026-09-20" in response.text
    assert 'id="pre-application-search"' in response.text


def test_事前申請を取得できなければその旨を表示し選べなくする(
    client: TestClient, session: Session, data: Data, freee_client: FakeFreeeClient
) -> None:
    invoice = data.invoice(
        payment_input={
            "pre_application_id": 5001,
            "pre_application_number": "A-0001",
            "pre_application_title": "2026年10月 媒体費 Aメディア",
        }
    )
    freee_client.list_approval_requests_error = FreeeNoResponseError("timeout")

    response = client.get(f"/invoices/{invoice.id}")

    assert response.status_code == 200
    assert "事前申請を取得できませんでした" in response.text
    assert 'name="pre_application_id"' not in response.text
    # 紐付けている事前申請は、控えで表示する
    assert "紐付けている事前申請: A-0001 2026年10月 媒体費 Aメディア" in response.text
    assert ">保存</button>" in response.text


def test_抽出結果で読み取れなかった項目を強調表示する(client: TestClient, data: Data) -> None:
    invoice = data.invoice(extraction={"invoice_number": "INV-1", "due_date": None})

    response = client.get(f"/invoices/{invoice.id}")

    assert response.text.count('class="unreadable-note">読み取れず') == 6
    assert '<div class="field unreadable">\n      <label for="due_date">' in response.text
    assert '<div class="field">\n      <label for="invoice_number">' in response.text


def test_抽出結果なしで作ったインプットは読み取れずを表示しない(
    client: TestClient, data: Data
) -> None:
    invoice = data.invoice()

    response = client.get(f"/invoices/{invoice.id}")

    assert "読み取れず" not in response.text


def test_freeeの選択肢にない保存済みの値は未選択にして選び直しを促す(
    client: TestClient, data: Data
) -> None:
    invoice = data.invoice(payment_input={"freee_tax_code": 999, "freee_account_item_id": 201})

    response = client.get(f"/invoices/{invoice.id}")

    assert (
        "保存済みの値（識別子: 999）は freee の選択肢にありません。選び直してください"
        in response.text
    )
    assert '<option value="136">課対仕入10%</option>' in response.text


def test_削除済みの取引先も現在の取引先なら選択肢に残す(
    client: TestClient, session: Session, data: Data
) -> None:
    deleted = add_partner(session, "旧メディア", [], deleted=True)
    invoice = data.invoice(payment_input={"partner_id": deleted.id})

    response = client.get(f"/invoices/{invoice.id}")

    assert f'<option value="{deleted.id}" selected>旧メディア（削除済み）</option>' in response.text


def test_申請済は読み取り専用で表示し申請の記録を出す(
    client: TestClient, session: Session, data: Data
) -> None:
    partner = add_partner(session, "Aメディア", [])
    invoice = data.invoice(
        payment_input={
            "partner_id": partner.id,
            "amount_including_tax": 1_100_000,
            "freee_account_item_id": 201,
            "freee_tax_code": 999,
            "pre_application_number": "A-0001",
            "pre_application_title": "2026年10月 媒体費 Aメディア",
            "status": PaymentRequestStatus.SUBMITTED,
            "freee_payment_request_id": 9001,
            "applicant_email": "dev@example.com",
            "applied_at": datetime(2026, 10, 12, 3, 0, tzinfo=UTC),
        }
    )

    response = client.get(f"/invoices/{invoice.id}")

    assert "申請済" in response.text
    assert "<form" not in response.text.split('<div class="input">')[1]
    assert ">保存</button>" not in response.text
    assert ">申請</button>" not in response.text
    assert "1,100,000 円" in response.text
    assert "広告宣伝費" in response.text
    assert "（freee に存在しない値: 999）" in response.text
    assert "9001" in response.text
    assert "2026-10-12 12:00" in response.text
