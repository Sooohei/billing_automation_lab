import hashlib
import logging
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.gmail.client import Attachment, GmailAuthError, GmailClient, GmailMessage
from app.invoices.ingest import ingest, ingest_start_of
from app.invoices.models import IngestedMessage, Invoice
from app.partners.models import Partner
from app.storage.local import LocalFileStorage
from tests.fakes import FakeGmailClient
from tests.test_partner_repository import add_partner

START_DATE = date(2026, 10, 1)
# 取込を実行する日時。60 日前の日（2026-08-13）は運用開始日より前なので、
# 取込の起点は運用開始日になる
NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)
PDF_A = Attachment("請求書A.pdf", "application/pdf", b"%PDF-A")
PDF_B = Attachment("請求書B.pdf", "application/pdf", b"%PDF-B")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_message(
    message_id: str = "msg-1",
    *,
    from_header: str = "請求担当 <billing@a-media.jp>",
    received_at: datetime = datetime(2026, 10, 5, 1, 0, tzinfo=UTC),
    attachments: list[Attachment] | None = None,
) -> GmailMessage:
    return GmailMessage(
        message_id=message_id,
        from_header=from_header,
        subject="10月分のご請求",
        received_at=received_at,
        attachments=[PDF_A] if attachments is None else attachments,
    )


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path)


@pytest.fixture(autouse=True)
def partner(session: Session) -> None:
    add_partner(session, "Aメディア", ["billing@a-media.jp"])
    session.commit()


def invoices(session: Session) -> list[Invoice]:
    return list(session.scalars(select(Invoice).order_by(Invoice.file_name)))


def ingested_ids(session: Session) -> list[str]:
    return list(session.scalars(select(IngestedMessage.gmail_message_id)))


def run(session: Session, gmail: FakeGmailClient, storage: LocalFileStorage) -> int:
    result = ingest(session, gmail, storage, START_DATE, NOW)
    return result.created_invoice_count


# 取込対象の判定


def test_条件をすべて満たすメールを取り込む(session: Session, storage: LocalFileStorage) -> None:
    gmail = FakeGmailClient([make_message()])

    result = ingest(session, gmail, storage, START_DATE, NOW)

    assert (result.created_invoice_count, result.ingested_message_count) == (1, 1)
    assert not result.has_errors
    [invoice] = invoices(session)
    assert invoice.file_key == f"invoices/{sha256(b'%PDF-A')}.pdf"
    assert invoice.file_sha256 == sha256(b"%PDF-A")
    assert invoice.file_name == "請求書A.pdf"
    assert invoice.sender_email == "billing@a-media.jp"
    assert invoice.subject == "10月分のご請求"
    assert invoice.received_at == datetime(2026, 10, 5, 1, 0, tzinfo=UTC)
    assert invoice.ingested_at is not None
    assert invoice.gmail_message_id == "msg-1"
    assert storage.load(invoice.file_key) == b"%PDF-A"
    assert ingested_ids(session) == ["msg-1"]


@pytest.mark.parametrize(
    ("received_at", "expected"),
    [
        (datetime(2026, 9, 30, 14, 59, 59, tzinfo=UTC), 0),  # 日本時間 9/30 23:59:59
        (datetime(2026, 9, 30, 15, 0, 0, tzinfo=UTC), 1),  # 日本時間 10/1 0:00:00
    ],
    ids=["運用開始日の前日", "運用開始日の0時"],
)
def test_受信日時は運用開始日の日本時間0時以降を取り込む(
    session: Session, storage: LocalFileStorage, received_at: datetime, expected: int
) -> None:
    gmail = FakeGmailClient([make_message(received_at=received_at)])

    assert run(session, gmail, storage) == expected


@pytest.mark.parametrize(
    ("received_at", "expected"),
    [
        (datetime(2026, 10, 10, 14, 59, 59, tzinfo=UTC), 0),  # 日本時間 10/10 23:59:59
        (datetime(2026, 10, 10, 15, 0, 0, tzinfo=UTC), 1),  # 日本時間 10/11 0:00:00
    ],
    ids=["60日前の日の前日", "60日前の日の0時"],
)
def test_受信日時は取込を実行する日の60日前の日の0時以降を取り込む(
    session: Session, storage: LocalFileStorage, received_at: datetime, expected: int
) -> None:
    gmail = FakeGmailClient([make_message(received_at=received_at)])
    # 日本時間 12/10 0:30 に実行する。60 日前の日は 10/11
    now = datetime(2026, 12, 9, 15, 30, tzinfo=UTC)

    result = ingest(session, gmail, storage, START_DATE, now)

    assert result.created_invoice_count == expected


@pytest.mark.parametrize(
    ("start_date", "now", "expected"),
    [
        (date(2026, 10, 1), datetime(2026, 10, 12, 3, 0, tzinfo=UTC), "2026-10-01T00:00:00+09:00"),
        (date(2026, 10, 1), datetime(2026, 12, 10, 3, 0, tzinfo=UTC), "2026-10-11T00:00:00+09:00"),
        # UTC では 12/9 だが、日本時間では 12/10
        (date(2026, 10, 1), datetime(2026, 12, 9, 15, 0, tzinfo=UTC), "2026-10-11T00:00:00+09:00"),
    ],
    ids=["運用開始日の方が遅い", "60日前の日の方が遅い", "実行日は日本時間で決める"],
)
def test_取込の起点は運用開始日と60日前の日の遅い方(
    start_date: date, now: datetime, expected: str
) -> None:
    assert ingest_start_of(start_date, now).isoformat() == expected


def test_登録されていない送信元のメールは取り込まない(
    session: Session, storage: LocalFileStorage
) -> None:
    gmail = FakeGmailClient([make_message(from_header="unknown@example.com")])

    assert run(session, gmail, storage) == 0
    assert ingested_ids(session) == []


def test_表示名付きで大文字を含む送信元も照合する(
    session: Session, storage: LocalFileStorage
) -> None:
    gmail = FakeGmailClient([make_message(from_header='"請求担当" <Billing@A-Media.JP>')])

    assert run(session, gmail, storage) == 1
    assert invoices(session)[0].sender_email == "billing@a-media.jp"


def test_削除した取引先のアドレスからのメールは取り込まない(
    session: Session, storage: LocalFileStorage
) -> None:
    add_partner(session, "削除済み", [], deleted=True)
    gmail = FakeGmailClient([make_message(from_header="old@deleted.jp")])

    assert run(session, gmail, storage) == 0


@pytest.mark.parametrize(
    ("attachment", "expected"),
    [
        (Attachment("invoice.pdf", "application/pdf", b"1"), 1),
        (Attachment("請求書", "application/pdf", b"2"), 1),
        (Attachment("invoice.pdf", "application/octet-stream", b"3"), 1),
        (Attachment("INVOICE.PDF", "application/octet-stream", b"4"), 1),
        (Attachment("明細.csv", "text/csv", b"5"), 0),
        (Attachment("invoice.pdf.zip", "application/zip", b"6"), 0),
    ],
    ids=["種類がPDF", "種類がPDFで拡張子なし", "拡張子pdf", "拡張子PDF", "CSV", "ZIP"],
)
def test_種類か拡張子でPDFを判定する(
    session: Session, storage: LocalFileStorage, attachment: Attachment, expected: int
) -> None:
    gmail = FakeGmailClient([make_message(attachments=[attachment])])

    assert run(session, gmail, storage) == expected


def test_PDF以外の添付ファイルは請求書データにしない(
    session: Session, storage: LocalFileStorage
) -> None:
    csv = Attachment("明細.csv", "text/csv", b"a,b")
    gmail = FakeGmailClient([make_message(attachments=[PDF_A, csv])])

    assert run(session, gmail, storage) == 1
    assert [invoice.file_name for invoice in invoices(session)] == ["請求書A.pdf"]


def test_取込対象でないメールは記録せず後から取引先を登録すれば取り込む(
    session: Session, storage: LocalFileStorage
) -> None:
    gmail = FakeGmailClient([make_message(from_header="billing@c-ad.jp")])
    assert run(session, gmail, storage) == 0

    add_partner(session, "Cアド", ["billing@c-ad.jp"])
    session.commit()

    assert run(session, gmail, storage) == 1


def test_取引先が登録されていなければGmailに問い合わせない(
    session: Session, storage: LocalFileStorage
) -> None:
    session.execute(update(Partner).values(deleted_at=func.now()))
    session.commit()
    gmail = FakeGmailClient([make_message()])
    gmail.list_error = AssertionError("呼ばれてはいけない")

    result = ingest(session, gmail, storage, START_DATE, NOW)

    assert not result.has_errors


# 請求書データの作成・重複


def test_PDF1件ごとに請求書データを作る(session: Session, storage: LocalFileStorage) -> None:
    gmail = FakeGmailClient([make_message(attachments=[PDF_A, PDF_B])])

    assert run(session, gmail, storage) == 2
    assert [invoice.file_name for invoice in invoices(session)] == ["請求書A.pdf", "請求書B.pdf"]


def test_同じメールの中の同じ中身のPDFは1件にする(
    session: Session, storage: LocalFileStorage
) -> None:
    copy = Attachment("請求書A（コピー）.pdf", "application/pdf", PDF_A.data)
    gmail = FakeGmailClient([make_message(attachments=[PDF_A, copy])])

    assert run(session, gmail, storage) == 1


def test_別のメールの同じ中身のPDFは請求書データを作らず取込済みにする(
    session: Session, storage: LocalFileStorage
) -> None:
    resent = Attachment("請求書A（再送）.pdf", "application/pdf", PDF_A.data)
    gmail = FakeGmailClient([make_message("msg-1"), make_message("msg-2", attachments=[resent])])

    result = ingest(session, gmail, storage, START_DATE, NOW)

    assert (result.created_invoice_count, result.ingested_message_count) == (1, 2)
    assert sorted(ingested_ids(session)) == ["msg-1", "msg-2"]


# 再取込・エラー


def test_取込済みのメールは再度取り込まない(session: Session, storage: LocalFileStorage) -> None:
    gmail = FakeGmailClient([make_message()])
    run(session, gmail, storage)
    gmail.fetched_ids.clear()

    assert run(session, gmail, storage) == 0
    assert gmail.fetched_ids == []


class FailingStorage(LocalFileStorage):
    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir)
        self.fail = True

    def save(self, key: str, data: bytes) -> None:
        if self.fail:
            raise OSError("保存に失敗")
        super().save(key, data)


def test_エラーになったメールは記録せず次回取り込む(
    session: Session, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    storage = FailingStorage(tmp_path)
    gmail = FakeGmailClient([make_message()])

    result = ingest(session, gmail, storage, START_DATE, NOW)

    assert result.failed_message_ids == ["msg-1"]
    assert result.has_errors
    assert invoices(session) == []
    assert ingested_ids(session) == []
    assert "gmail_message_id=msg-1" in caplog.text

    storage.fail = False
    assert run(session, gmail, storage) == 1


def test_1通のエラーで他のメールの取込を止めない(
    session: Session, storage: LocalFileStorage
) -> None:
    gmail = FakeGmailClient([make_message("msg-1"), make_message("msg-2", attachments=[PDF_B])])
    gmail.errors["msg-1"] = RuntimeError("添付ファイルを取得できない")

    result = ingest(session, gmail, storage, START_DATE, NOW)

    assert result.failed_message_ids == ["msg-1"]
    assert ingested_ids(session) == ["msg-2"]


def test_Gmailの認証エラーで取込全体を止める(
    session: Session, storage: LocalFileStorage, caplog: pytest.LogCaptureFixture
) -> None:
    gmail = FakeGmailClient([make_message("msg-1"), make_message("msg-2", attachments=[PDF_B])])
    gmail.errors["msg-1"] = GmailAuthError("invalid_grant")

    with caplog.at_level(logging.ERROR):
        result = ingest(session, gmail, storage, START_DATE, NOW)

    assert result.aborted
    assert result.has_errors
    assert gmail.fetched_ids == ["msg-1"]
    assert "Gmail の接続許可が切れています。接続許可を取り直してください" in caplog.text


@pytest.mark.parametrize(
    "error", [GmailAuthError("invalid_grant"), RuntimeError("一覧を取得できない")]
)
def test_メールの一覧を取得できなければ取込全体を止める(
    session: Session, storage: LocalFileStorage, error: Exception
) -> None:
    gmail = FakeGmailClient([make_message()])
    gmail.list_error = error

    result = ingest(session, gmail, storage, START_DATE, NOW)

    assert result.aborted
    assert gmail.fetched_ids == []


def test_リポジトリのサンプルのメールを設計書の表のとおりに取り込む(
    session: Session, storage: LocalFileStorage
) -> None:
    add_partner(session, "Bネットワークス", ["invoice@b-networks.jp"])
    add_partner(session, "Cアド", ["info@c-ad.jp"])
    add_partner(session, "Dパブリッシング", ["billing@d-publishing.jp"])
    session.commit()

    result = ingest(session, GmailClient(), storage, START_DATE, NOW)

    assert not result.has_errors
    assert sorted(
        (invoice.gmail_message_id, invoice.file_name) for invoice in invoices(session)
    ) == [
        ("sample-01-single-pdf", "請求書_AM-2026-10-001.pdf"),
        ("sample-02-two-pdfs", "BN-1001.pdf"),
        ("sample-02-two-pdfs", "BN-1002.pdf"),
        ("sample-03-octet-stream-pdf", "INVOICE_202610.PDF"),
        ("sample-06-uppercase-sender", "DP_請求書_202610.pdf"),
    ]
    # sample-08 は PDF が sample-01 と同じなので、請求書データを作らずに取込済みにする
    assert sorted(ingested_ids(session)) == [
        "sample-01-single-pdf",
        "sample-02-two-pdfs",
        "sample-03-octet-stream-pdf",
        "sample-06-uppercase-sender",
        "sample-08-duplicate-pdf",
    ]
