import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.extraction.models import ExtractionResult
from app.invoices.models import Invoice
from app.payment_requests.models import PaymentRequestInput, PaymentRequestStatus
from app.payment_requests.repository import InvoiceFilters, PaymentRequestRepository
from tests.test_partner_repository import add_partner


class Data:
    """テスト用の請求書データ・抽出結果・支払い依頼インプットを作る。"""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.count = 0

    def invoice(
        self,
        received_at: datetime = datetime(2026, 10, 5, 1, 0, tzinfo=UTC),
        *,
        extraction: dict[str, object] | None = None,
        payment_input: dict[str, object] | None = None,
    ) -> Invoice:
        self.count += 1
        sha256 = f"{self.count:064x}"
        invoice = Invoice(
            file_key=f"invoices/{sha256}.pdf",
            file_sha256=sha256,
            file_name=f"請求書{self.count}.pdf",
            sender_email="billing@a-media.jp",
            subject="ご請求",
            received_at=received_at,
            gmail_message_id=f"msg-{self.count}",
        )
        self.session.add(invoice)
        self.session.flush()
        if extraction is not None:
            self.session.add(ExtractionResult(invoice_id=invoice.id, **extraction))
        if payment_input is not None:
            self.session.add(
                PaymentRequestInput(
                    invoice_id=invoice.id, created_from_extraction=False, **payment_input
                )
            )
        # 画面の処理がエラーでロールバックしても消えないように、確定しておく
        self.session.commit()
        return invoice


@pytest.fixture
def data(session: Session) -> Data:
    return Data(session)


def search(
    session: Session, filters: InvoiceFilters | None = None, offset: int = 0, limit: int = 100
) -> list[uuid.UUID]:
    rows = PaymentRequestRepository(session).search(filters or InvoiceFilters(), offset, limit)
    return [row.invoice_id for row in rows]


# 表示する行と値


def test_抽出結果も支払い依頼インプットもない請求書データも表示する(
    session: Session, data: Data
) -> None:
    invoice = data.invoice()

    [row] = PaymentRequestRepository(session).search(InvoiceFilters(), 0, 10)

    assert row.invoice_id == invoice.id
    assert row.received_at == datetime(2026, 10, 5, 1, 0, tzinfo=UTC)
    assert (row.partner_name, row.amount_including_tax, row.due_date) == (None, None, None)
    assert row.status == PaymentRequestStatus.UNSUBMITTED


def test_インプットがなければ抽出結果の値を表示する(session: Session, data: Data) -> None:
    partner = add_partner(session, "Aメディア", [])
    data.invoice(
        extraction={
            "partner_id": partner.id,
            "amount_including_tax": 1_100_000,
            "due_date": date(2026, 10, 31),
        }
    )

    [row] = PaymentRequestRepository(session).search(InvoiceFilters(), 0, 10)

    assert (row.partner_name, row.amount_including_tax, row.due_date) == (
        "Aメディア",
        1_100_000,
        date(2026, 10, 31),
    )


def test_インプットがあればインプットの値を表示し消した値は空で表示する(
    session: Session, data: Data
) -> None:
    a = add_partner(session, "Aメディア", [])
    b = add_partner(session, "Bネットワークス", [])
    data.invoice(
        extraction={"partner_id": a.id, "amount_including_tax": 1, "due_date": date(2026, 10, 1)},
        payment_input={
            "partner_id": b.id,
            "amount_including_tax": None,
            "due_date": date(2026, 11, 30),
            "status": PaymentRequestStatus.SUBMITTED,
            "freee_payment_request_id": 9001,
            "applicant_email": "dev@example.com",
            "applied_at": datetime(2026, 10, 12, tzinfo=UTC),
        },
    )

    [row] = PaymentRequestRepository(session).search(InvoiceFilters(), 0, 10)

    assert (row.partner_name, row.amount_including_tax, row.due_date) == (
        "Bネットワークス",
        None,
        date(2026, 11, 30),
    )
    assert row.status == PaymentRequestStatus.SUBMITTED


def test_削除済みの取引先も取引先名を表示する(session: Session, data: Data) -> None:
    partner = add_partner(session, "削除済みメディア", [], deleted=True)
    data.invoice(extraction={"partner_id": partner.id})

    [row] = PaymentRequestRepository(session).search(InvoiceFilters(), 0, 10)

    assert row.partner_name == "削除済みメディア"


# 並び順


def test_支払期日の古い順で空は末尾に並べ同じなら受信日時の順(session: Session, data: Data) -> None:
    no_due = data.invoice(datetime(2026, 10, 1, tzinfo=UTC))
    late = data.invoice(extraction={"due_date": date(2026, 11, 30)})
    early_received_later = data.invoice(
        datetime(2026, 10, 9, tzinfo=UTC), extraction={"due_date": date(2026, 10, 31)}
    )
    early_received_earlier = data.invoice(
        datetime(2026, 10, 8, tzinfo=UTC), payment_input={"due_date": date(2026, 10, 31)}
    )

    assert search(session) == [
        early_received_earlier.id,
        early_received_later.id,
        late.id,
        no_due.id,
    ]


def test_ページをまたいでも重複も抜けもない(session: Session, data: Data) -> None:
    # 支払期日と受信日時が同じ請求書が多くても、請求書 ID の順で決まる
    invoices = [data.invoice(extraction={"due_date": date(2026, 10, 31)}) for _ in range(25)]

    pages = search(session, offset=0, limit=10) + search(session, offset=10, limit=10)
    pages += search(session, offset=20, limit=10)

    assert len(pages) == 25
    assert set(pages) == {invoice.id for invoice in invoices}


# 絞り込み


@pytest.fixture
def received(data: Data) -> dict[str, Invoice]:
    """日本時間の日付の境目の前後に受信した請求書。"""
    return {
        "9/30 23:59": data.invoice(datetime(2026, 9, 30, 14, 59, tzinfo=UTC)),
        "10/1 0:00": data.invoice(datetime(2026, 9, 30, 15, 0, tzinfo=UTC)),
        "10/31 23:59": data.invoice(datetime(2026, 10, 31, 14, 59, tzinfo=UTC)),
        "11/1 0:00": data.invoice(datetime(2026, 10, 31, 15, 0, tzinfo=UTC)),
    }


@pytest.mark.parametrize(
    ("received_from", "received_to", "expected"),
    [
        (date(2026, 10, 1), None, ["10/1 0:00", "10/31 23:59", "11/1 0:00"]),
        (None, date(2026, 10, 31), ["9/30 23:59", "10/1 0:00", "10/31 23:59"]),
        (date(2026, 10, 1), date(2026, 10, 31), ["10/1 0:00", "10/31 23:59"]),
    ],
    ids=["開始日のみ", "終了日のみ", "両方"],
)
def test_受信日時を日本時間の日付で絞り込む(
    session: Session,
    received: dict[str, Invoice],
    received_from: date | None,
    received_to: date | None,
    expected: list[str],
) -> None:
    filters = InvoiceFilters(received_from=received_from, received_to=received_to)

    assert set(search(session, filters)) == {received[key].id for key in expected}


def test_取引先と申請状態で絞り込み組み合わせはすべてを満たすものにする(
    session: Session, data: Data
) -> None:
    a = add_partner(session, "Aメディア", [])
    b = add_partner(session, "Bネットワークス", [])
    submitted = {
        "status": PaymentRequestStatus.SUBMITTED,
        "freee_payment_request_id": 9001,
        "applicant_email": "dev@example.com",
        "applied_at": datetime(2026, 10, 12, tzinfo=UTC),
    }
    a_unsubmitted = data.invoice(extraction={"partner_id": a.id})
    a_submitted = data.invoice(payment_input={"partner_id": a.id, **submitted})
    b_unsubmitted = data.invoice(extraction={"partner_id": b.id})
    # インプットで取引先を A から B に変えた請求書は、B として絞り込む
    changed_to_b = data.invoice(extraction={"partner_id": a.id}, payment_input={"partner_id": b.id})

    def ids(filters: InvoiceFilters) -> set[uuid.UUID]:
        return set(search(session, filters))

    unsubmitted = PaymentRequestStatus.UNSUBMITTED
    assert ids(InvoiceFilters(partner_id=a.id)) == {a_unsubmitted.id, a_submitted.id}
    assert ids(InvoiceFilters(partner_id=b.id)) == {b_unsubmitted.id, changed_to_b.id}
    assert ids(InvoiceFilters(status=PaymentRequestStatus.SUBMITTED)) == {a_submitted.id}
    assert ids(InvoiceFilters(status=unsubmitted)) == {
        a_unsubmitted.id,
        b_unsubmitted.id,
        changed_to_b.id,
    }
    assert ids(InvoiceFilters(partner_id=a.id, status=unsubmitted)) == {a_unsubmitted.id}


# 画面


def test_一覧画面に行と絞り込みのフォームを表示する(
    client: TestClient, session: Session, data: Data
) -> None:
    partner = add_partner(session, "Aメディア", [])
    invoice = data.invoice(
        extraction={
            "partner_id": partner.id,
            "amount_including_tax": 1_100_000,
            "due_date": date(2026, 10, 31),
        }
    )

    response = client.get("/invoices")

    assert response.status_code == 200
    assert "2026-10-05 10:00" in response.text  # 日本時間で表示する
    assert "1,100,000 円" in response.text
    assert "2026-10-31" in response.text
    assert "未申請" in response.text
    assert f'href="/invoices/{invoice.id}"' in response.text
    assert f'<option value="{partner.id}">Aメディア</option>' in response.text
    assert "次の 10 件を表示" not in response.text


def test_11件目があるときだけ次の10件のボタンを出し押すと次の行を返す(
    client: TestClient, data: Data
) -> None:
    for day in range(1, 12):
        data.invoice(extraction={"due_date": date(2026, 10, day)})

    first = client.get("/invoices")
    assert first.text.count("確認・修正") == 10
    assert 'hx-get="/invoices/rows?offset=10&amp;' in first.text

    more = client.get("/invoices/rows?offset=10")
    assert more.text.count("確認・修正") == 1
    assert "2026-10-11" in more.text
    assert "次の 10 件を表示" not in more.text


def test_次の10件のURLに絞り込み条件を引き継ぐ(
    client: TestClient, session: Session, data: Data
) -> None:
    partner = add_partner(session, "Aメディア", [])
    for _ in range(11):
        data.invoice(extraction={"partner_id": partner.id})

    response = client.get(f"/invoices?partner_id={partner.id}&status=unsubmitted")

    assert f"partner_id={partner.id}&amp;status=unsubmitted" in response.text
    assert f'<option value="{partner.id}" selected>' in response.text
    assert '<option value="unsubmitted" selected>' in response.text


def test_形式の正しくない絞り込み条件は指定なしとして扱う(client: TestClient, data: Data) -> None:
    data.invoice()

    response = client.get("/invoices?received_from=abc&partner_id=x&status=y")

    assert response.status_code == 200
    assert response.text.count("確認・修正") == 1


def test_共通レイアウトでhtmxを読み込む(client: TestClient) -> None:
    response = client.get("/invoices")

    assert '<script src="/static/htmx.min.js"></script>' in response.text
    assert client.get("/static/htmx.min.js").status_code == 200


def test_該当する請求書がなければその旨を表示する(client: TestClient) -> None:
    assert "該当する請求書はありません" in client.get("/invoices").text
