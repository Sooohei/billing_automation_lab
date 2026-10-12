import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.extraction.repository import ExtractionRepository
from app.freee.client import ApprovalRequest, FreeeClient
from app.partners.models import Partner
from app.partners.repository import PartnerRepository
from app.payment_requests.models import PaymentRequestInput
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


# 保存


@dataclass(frozen=True)
class PaymentInputForm:
    """確認・修正画面の入力値（文字列のまま）。

    pre_application_id が None のときは、事前申請を選ぶ欄がなかった（取得に失敗した、
    または紐付けている事前申請が一覧にない）ので、紐付けを変えない。
    """

    partner_id: str = ""
    title: str = ""
    invoice_number: str = ""
    qualified_invoice_issuer_number: str = ""
    issue_date: str = ""
    due_date: str = ""
    amount_excluding_tax: str = ""
    tax_amount: str = ""
    amount_including_tax: str = ""
    freee_partner_id: str = ""
    freee_account_item_id: str = ""
    freee_tax_code: str = ""
    freee_approval_flow_route_id: str = ""
    pre_application_id: str | None = None


class SaveValidationError(Exception):
    """入力チェックに当てはまった。当てはまったメッセージをすべて持つ。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


class AlreadySubmittedError(Exception):
    """申請済のため、修正・申請できない。"""


class InputNotFoundError(Exception):
    """支払い依頼インプットがない。"""


_REGISTRATION_NUMBER = re.compile(r"T[0-9]{13}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_INTEGER = re.compile(r"-?[0-9]+")
_BIGINT_MAX = 2**63 - 1

_DATE_FIELDS = {"issue_date": "請求書発行日", "due_date": "支払期日"}
_AMOUNT_FIELDS = {
    "amount_excluding_tax": "税抜金額",
    "tax_amount": "消費税額",
    "amount_including_tax": "税込金額",
}
_FREEE_FIELDS = {
    "freee_partner_id": ("freee 上の取引先", "list_partners"),
    "freee_account_item_id": ("勘定科目", "list_account_items"),
    "freee_tax_code": ("税区分", "list_taxes"),
    "freee_approval_flow_route_id": ("承認経路", "list_approval_flow_routes"),
}


def save_input(
    session: Session,
    freee_client: FreeeClient,
    invoice_id: uuid.UUID,
    form: PaymentInputForm,
    approval_requests: list[ApprovalRequest] | None,
) -> None:
    """入力値で支払い依頼インプットを更新する。approval_requests は取得に失敗したら None。

    同じ請求書を同時に修正した場合は、後から保存した値で上書きする（競合は検出しない）。
    """
    payment_input = PaymentRequestRepository(session).get_for_update(invoice_id)
    if payment_input is None:
        session.rollback()
        raise InputNotFoundError
    if payment_input.is_submitted:
        session.rollback()
        raise AlreadySubmittedError

    errors: list[str] = []
    values: dict[str, Any] = {}

    partner_id = _parse_uuid(form.partner_id)
    if form.partner_id.strip() and not _is_selectable_partner(session, partner_id, payment_input):
        errors.append("取引先は登録されている取引先から選択してください")
    values["partner_id"] = partner_id

    values["title"] = form.title.strip() or None
    values["invoice_number"] = form.invoice_number.strip() or None

    registration_number = form.qualified_invoice_issuer_number.strip()
    if registration_number and not _REGISTRATION_NUMBER.fullmatch(registration_number):
        errors.append("適格請求書発行事業者登録番号は「T」と 13 桁の数字で入力してください")
    values["qualified_invoice_issuer_number"] = registration_number or None

    for field, label in _DATE_FIELDS.items():
        text = getattr(form, field).strip()
        parsed_date = _parse_date(text)
        if text and parsed_date is None:
            errors.append(f"{label}は実在する日付を入力してください")
        values[field] = parsed_date

    for field, label in _AMOUNT_FIELDS.items():
        text = getattr(form, field).strip()
        amount = _parse_int(text)
        if text and amount is None:
            errors.append(f"{label}は整数で入力してください")
        values[field] = amount

    for field, (label, method) in _FREEE_FIELDS.items():
        text = getattr(form, field).strip()
        freee_id = _parse_int(text)
        option_ids = {option.id for option in getattr(freee_client, method)()}
        if text and freee_id not in option_ids:
            errors.append(f"{label}は freee の選択肢から選択してください")
        values[field] = freee_id

    errors.extend(_apply_pre_application(form, payment_input, approval_requests, values))

    if errors:
        session.rollback()
        raise SaveValidationError(errors)

    for field, value in values.items():
        setattr(payment_input, field, value)
    payment_input.updated_at = datetime.now(UTC)
    session.commit()


def _is_selectable_partner(
    session: Session, partner_id: uuid.UUID | None, payment_input: PaymentRequestInput
) -> bool:
    """SR-00 の有効な取引先、または現在の取引先（削除済みでもよい）。"""
    if partner_id is None:
        return False
    if partner_id == payment_input.partner_id:
        return True
    return PartnerRepository(session).get_active(partner_id) is not None


def _apply_pre_application(
    form: PaymentInputForm,
    payment_input: PaymentRequestInput,
    approval_requests: list[ApprovalRequest] | None,
    values: dict[str, Any],
) -> list[str]:
    """紐付ける事前申請を values に入れ、エラーがあれば返す。"""
    if form.pre_application_id is None:
        return []
    selected = _parse_int(form.pre_application_id.strip())
    if selected == payment_input.pre_application_id:
        return []
    if approval_requests is None:
        return ["事前申請を取得できなかったため、紐付ける事前申請を変更できません"]
    request = next((r for r in approval_requests if r.id == selected), None)
    if request is None:
        return ["紐付ける事前申請は一覧から選択してください"]
    # 申請番号と件名は、表示用の控えとして持つ
    values["pre_application_id"] = request.id
    values["pre_application_number"] = request.application_number
    values["pre_application_title"] = request.title
    return []


def _parse_uuid(text: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(text.strip()) if text.strip() else None
    except ValueError:
        return None


def _parse_date(text: str) -> date | None:
    if not _DATE.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_int(text: str) -> int | None:
    if not _INTEGER.fullmatch(text):
        return None
    value = int(text)
    return value if abs(value) <= _BIGINT_MAX else None
