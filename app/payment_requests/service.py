import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.extraction.repository import ExtractionRepository
from app.partners.models import Partner
from app.partners.repository import PartnerRepository
from app.payment_requests.repository import PaymentRequestRepository

JST = ZoneInfo("Asia/Tokyo")


def application_title(partner: Partner | None, now: datetime) -> str | None:
    """申請タイトルの初期値 `{申請月}_{媒体名}_メディア費`。媒体名（取引先名）が空なら空。"""
    if partner is None:
        return None
    return f"{now.astimezone(JST):%Y%m}_{partner.name}_メディア費"


def ensure_input(session: Session, invoice_id: uuid.UUID, now: datetime) -> None:
    """支払い依頼インプットがなければ、初期値で作る（SR-03 の要件 14）。

    抽出結果がない状態で作った場合、その後に抽出結果ができても反映しない。
    """
    repository = PaymentRequestRepository(session)
    if repository.get(invoice_id) is not None:
        return

    extraction = ExtractionRepository(session).get(invoice_id)
    if extraction is None:
        repository.create_if_absent(invoice_id, created_from_extraction=False)
    else:
        # 取引先の既定値は、作成した時点の値をコピーする。作成後に取引先の既定値を変えても変わらない
        partner = (
            PartnerRepository(session).get_including_deleted(extraction.partner_id)
            if extraction.partner_id is not None
            else None
        )
        repository.create_if_absent(
            invoice_id,
            created_from_extraction=True,
            partner_id=extraction.partner_id,
            title=application_title(partner, now),
            invoice_number=extraction.invoice_number,
            qualified_invoice_issuer_number=extraction.qualified_invoice_issuer_number,
            issue_date=extraction.issue_date,
            due_date=extraction.due_date,
            amount_excluding_tax=extraction.amount_excluding_tax,
            tax_amount=extraction.tax_amount,
            amount_including_tax=extraction.amount_including_tax,
            freee_partner_id=partner.freee_partner_id if partner else None,
            freee_account_item_id=partner.freee_account_item_id if partner else None,
            freee_tax_code=partner.freee_tax_code if partner else None,
            freee_approval_flow_route_id=partner.freee_approval_flow_route_id if partner else None,
        )
    session.commit()
