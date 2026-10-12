"""SR-02 の抽出処理。1 時間ごとのバッチで、SR-01 の取込のあとに呼ばれる。"""

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.extraction.extractor import InvoiceExtractor
from app.extraction.models import ExtractionResult
from app.extraction.repository import ExtractionRepository
from app.extraction.validation import validate
from app.partners.repository import PartnerRepository
from app.storage.storage import FileStorage

logger = logging.getLogger(__name__)


@dataclass
class ExtractResult:
    created_count: int = 0
    failed_invoice_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.failed_invoice_ids)


@dataclass(frozen=True)
class _Target:
    invoice_id: uuid.UUID
    file_key: str
    file_name: str
    sender_email: str


def extract(session: Session, extractor: InvoiceExtractor, storage: FileStorage) -> ExtractResult:
    """抽出結果がない請求書データをすべて、受信日時の古い順に処理する。

    このバッチで取り込んだものに限らないので、前回までにエラーになったものも再度抽出する。
    """
    result = ExtractResult()
    # エラー時のロールバックで ORM のオブジェクトが期限切れになるため、必要な値を先に取り出す
    targets = [
        _Target(invoice.id, invoice.file_key, invoice.file_name, invoice.sender_email)
        for invoice in ExtractionRepository(session).list_invoices_without_result()
    ]

    for target in targets:
        try:
            _extract_one(session, extractor, storage, target)
        except Exception:
            # 抽出結果を作らないので、次回のバッチで再度抽出する
            session.rollback()
            logger.exception("抽出できませんでした: invoice_id=%s", target.invoice_id)
            result.failed_invoice_ids.append(target.invoice_id)
            continue
        result.created_count += 1

    logger.info(
        "抽出が終わりました: 作成した抽出結果=%d 件、失敗=%d 件",
        result.created_count,
        len(result.failed_invoice_ids),
    )
    return result


def _extract_one(
    session: Session, extractor: InvoiceExtractor, storage: FileStorage, target: _Target
) -> None:
    # 取込のあとに SR-00 で取引先を削除した、またはアドレスを外した場合は、取引先を空にする
    partner = PartnerRepository(session).find_active_by_email(target.sender_email)
    pdf = storage.load(target.file_key)
    values = validate(extractor.extract(pdf, target.file_name))

    ExtractionRepository(session).add(
        ExtractionResult(
            invoice_id=target.invoice_id,
            partner_id=partner.id if partner is not None else None,
            invoice_number=values.invoice_number,
            qualified_invoice_issuer_number=values.qualified_invoice_issuer_number,
            issue_date=values.issue_date,
            due_date=values.due_date,
            amount_excluding_tax=values.amount_excluding_tax,
            tax_amount=values.tax_amount,
            amount_including_tax=values.amount_including_tax,
        )
    )
    session.commit()
