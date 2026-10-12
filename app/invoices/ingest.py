"""SR-01 の取込処理。1 時間ごとのバッチから、advisory lock を取ったうえで呼ばれる。"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from email.utils import parseaddr
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.gmail.client import Attachment, GmailClient, GmailMessage
from app.invoices.models import Invoice
from app.invoices.repository import InvoiceRepository
from app.partners.normalize import normalize_email
from app.partners.repository import PartnerRepository
from app.storage.storage import FileStorage

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")
# 取込を実行する日の何日前の日以降に受信したメールを取り込むか
LOOKBACK_DAYS = 60


@dataclass
class IngestResult:
    created_invoice_count: int = 0
    ingested_message_count: int = 0
    failed_message_ids: list[str] = field(default_factory=list)
    # 取込全体を止めた（メールの一覧の取得の失敗）
    aborted: bool = False

    @property
    def has_errors(self) -> bool:
        return self.aborted or bool(self.failed_message_ids)


@dataclass(frozen=True)
class _Pdf:
    attachment: Attachment
    sha256: str


def ingest(
    session: Session,
    gmail_client: GmailClient,
    storage: FileStorage,
    start_date: date,
    now: datetime,
) -> IngestResult:
    """取込の起点以降に、登録済みの送信元から届いた PDF 付きのメールを取り込む。

    now は取込を実行する日時。取込の起点は ingest_start_of を参照。
    """
    result = IngestResult()

    senders = PartnerRepository(session).list_active_emails()
    if not senders:
        logger.info("送信元メールアドレスが登録されていないため、取込を行いません")
        return result
    received_after = ingest_start_of(start_date, now)

    try:
        message_ids = gmail_client.list_message_ids(received_after, senders)
    except Exception:
        logger.exception("メールの一覧を取得できなかったため、取込を止めます")
        result.aborted = True
        return result

    repository = InvoiceRepository(session)
    ingested = repository.find_ingested_message_ids(message_ids)
    # 一覧の取得のあとに SR-00 で変更されても、この取込の中では同じ判定にする
    sender_set = set(senders)

    for message_id in message_ids:
        if message_id in ingested:
            continue
        try:
            created = _ingest_message(
                session, gmail_client, storage, message_id, received_after, sender_set
            )
        except Exception:
            # このメールは取込済みとして記録しないので、次回の取込で再度取り込む
            session.rollback()
            logger.exception("メールを取り込めませんでした: gmail_message_id=%s", message_id)
            result.failed_message_ids.append(message_id)
            continue
        if created is not None:
            result.ingested_message_count += 1
            result.created_invoice_count += created

    logger.info(
        "取込が終わりました: 取り込んだメール=%d 件、作成した請求書データ=%d 件、失敗=%d 件",
        result.ingested_message_count,
        result.created_invoice_count,
        len(result.failed_message_ids),
    )
    return result


def ingest_start_of(start_date: date, now: datetime) -> datetime:
    """取込の起点。運用開始日と、取込を実行する日の 60 日前の日の遅い方の日本時間 0 時。"""
    lookback_date = now.astimezone(JST).date() - timedelta(days=LOOKBACK_DAYS)
    return datetime.combine(max(start_date, lookback_date), time(0), tzinfo=JST)


def _ingest_message(
    session: Session,
    gmail_client: GmailClient,
    storage: FileStorage,
    message_id: str,
    received_after: datetime,
    senders: set[str],
) -> int | None:
    """1 通のメールを取り込み、作成した請求書データの件数を返す。取込対象でなければ None。"""
    message = gmail_client.get_message(message_id)
    sender_email = sender_email_of(message)
    pdfs = [attachment for attachment in message.attachments if is_pdf(attachment)]
    if message.received_at < received_after or sender_email not in senders or not pdfs:
        return None

    repository = InvoiceRepository(session)
    new_pdfs = _new_pdfs(repository, pdfs)
    for pdf in new_pdfs:
        storage.save(file_key(pdf.sha256), pdf.attachment.data)

    for pdf in new_pdfs:
        repository.add_invoice(
            Invoice(
                file_key=file_key(pdf.sha256),
                file_sha256=pdf.sha256,
                file_name=pdf.attachment.file_name,
                sender_email=sender_email,
                subject=message.subject,
                received_at=message.received_at,
                gmail_message_id=message.message_id,
            )
        )
    # PDF がすべて重複していて請求書データを作らなかったメールも、取込済みとして記録する
    repository.add_ingested_message(message.message_id)
    session.commit()
    return len(new_pdfs)


def _new_pdfs(repository: InvoiceRepository, pdfs: list[Attachment]) -> list[_Pdf]:
    """同じメールの中で同じ中身のものは 1 件にまとめ、請求書データがすでにあるものは除く。"""
    unique: dict[str, _Pdf] = {}
    for attachment in pdfs:
        sha256 = hashlib.sha256(attachment.data).hexdigest()
        unique.setdefault(sha256, _Pdf(attachment, sha256))
    existing = repository.find_existing_sha256s(list(unique))
    return [pdf for sha256, pdf in unique.items() if sha256 not in existing]


def sender_email_of(message: GmailMessage) -> str:
    """From ヘッダーからメールアドレスを取り出し、正規化する。"""
    return normalize_email(parseaddr(message.from_header)[1])


def is_pdf(attachment: Attachment) -> bool:
    return attachment.mime_type == "application/pdf" or attachment.file_name.lower().endswith(
        ".pdf"
    )


def file_key(sha256: str) -> str:
    return f"invoices/{sha256}.pdf"
