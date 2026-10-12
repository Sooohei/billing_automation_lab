import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated, Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.db import get_session
from app.extraction.repository import ExtractionRepository
from app.freee.client import ApprovalRequest, FreeeClient, FreeeError, FreeeOption
from app.freee.dependencies import get_freee_client
from app.invoices.models import Invoice
from app.partners.repository import PartnerRepository
from app.payment_requests.models import PaymentRequestInput, PaymentRequestStatus
from app.payment_requests.repository import InvoiceFilters, PaymentRequestRepository
from app.payment_requests.service import ensure_input
from app.storage.dependencies import get_file_storage
from app.storage.storage import FileStorage
from app.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invoices")

SessionDep = Annotated[Session, Depends(get_session)]
FreeeClientDep = Annotated[FreeeClient, Depends(get_freee_client)]
FileStorageDep = Annotated[FileStorage, Depends(get_file_storage)]
UserDep = Annotated[CurrentUser, Depends(get_current_user)]

PAGE_SIZE = 10
STATUS_LABELS = {
    PaymentRequestStatus.UNSUBMITTED: "未申請",
    PaymentRequestStatus.SUBMITTED: "申請済",
}


def parse_filters(
    received_from: str = "", received_to: str = "", partner_id: str = "", status: str = ""
) -> InvoiceFilters:
    """クエリ文字列の絞り込み条件。形式の正しくない値は、指定なしとして扱う。"""
    return InvoiceFilters(
        received_from=_parse_date(received_from),
        received_to=_parse_date(received_to),
        partner_id=_parse_uuid(partner_id),
        status=PaymentRequestStatus(status) if status in PaymentRequestStatus else None,
    )


FiltersDep = Annotated[InvoiceFilters, Depends(parse_filters)]


def filter_query(filters: InvoiceFilters) -> dict[str, str]:
    """絞り込み条件をクエリ文字列の値に戻す（フォームの表示と、次の 10 件の URL に使う）。"""
    return {
        "received_from": filters.received_from.isoformat() if filters.received_from else "",
        "received_to": filters.received_to.isoformat() if filters.received_to else "",
        "partner_id": str(filters.partner_id) if filters.partner_id else "",
        "status": filters.status.value if filters.status else "",
    }


def rows_context(session: Session, filters: InvoiceFilters, offset: int) -> dict[str, object]:
    # 11 件目があるかで、次の 10 件のボタンを出すかを決める
    rows = PaymentRequestRepository(session).search(filters, offset, PAGE_SIZE + 1)
    has_more = len(rows) > PAGE_SIZE
    next_url = "/invoices/rows?" + urlencode(
        {"offset": offset + PAGE_SIZE, **filter_query(filters)}
    )
    return {
        "rows": rows[:PAGE_SIZE],
        "has_more": has_more,
        "next_url": next_url,
        "status_labels": STATUS_LABELS,
    }


@router.get("")
def list_invoices(request: Request, session: SessionDep, filters: FiltersDep) -> Response:
    return templates.TemplateResponse(
        request,
        "invoices/list.html",
        {
            "filters": filter_query(filters),
            "partners": PartnerRepository(session).list_active(),
            "status_labels": STATUS_LABELS,
            **rows_context(session, filters, 0),
        },
    )


@router.get("/rows")
def list_more_rows(
    request: Request, session: SessionDep, filters: FiltersDep, offset: int = 0
) -> Response:
    """次の 10 件の行（htmx で一覧の末尾に追加する）。"""
    return templates.TemplateResponse(
        request, "invoices/_rows.html", rows_context(session, filters, max(offset, 0))
    )


# 確認・修正画面


@dataclass(frozen=True)
class InputField:
    name: str
    label: str
    input_type: str
    # SR-02 の抽出項目か（「読み取れず」の強調表示の対象）
    extracted: bool = True


INPUT_FIELDS = [
    InputField("title", "申請タイトル", "text", extracted=False),
    InputField("invoice_number", "請求書番号", "text"),
    InputField("qualified_invoice_issuer_number", "適格請求書発行事業者登録番号", "text"),
    InputField("issue_date", "請求書発行日", "date"),
    InputField("due_date", "支払期日", "date"),
    InputField("amount_excluding_tax", "税抜金額", "number"),
    InputField("tax_amount", "消費税額", "number"),
    InputField("amount_including_tax", "税込金額", "number"),
]

# freee の申請用の項目と、選択肢の取り方
FREEE_FIELDS = [
    ("freee_partner_id", "freee 上の取引先", "list_partners"),
    ("freee_account_item_id", "勘定科目", "list_account_items"),
    ("freee_tax_code", "税区分", "list_taxes"),
    ("freee_approval_flow_route_id", "承認経路", "list_approval_flow_routes"),
]


def get_invoice(session: Session, invoice_id: str) -> Invoice:
    try:
        parsed_id = uuid.UUID(invoice_id)
    except ValueError:
        raise HTTPException(status_code=404) from None
    invoice = session.get(Invoice, parsed_id)
    if invoice is None:
        raise HTTPException(status_code=404)
    return invoice


def input_values(payment_input: PaymentRequestInput) -> dict[str, str]:
    """支払い依頼インプットの値を、入力フォームに入れる文字列にする。"""
    names = ["partner_id", *(f.name for f in INPUT_FIELDS), *(f[0] for f in FREEE_FIELDS)]
    values = {}
    for name in names:
        value = getattr(payment_input, name)
        values[name] = "" if value is None else str(value)
    values["pre_application_id"] = (
        "" if payment_input.pre_application_id is None else str(payment_input.pre_application_id)
    )
    return values


def fetch_approval_requests(
    freee_client: FreeeClient, user: CurrentUser
) -> list[ApprovalRequest] | None:
    """紐付けできる事前申請。取得に失敗したら None。"""
    try:
        return freee_client.list_approval_requests(user)
    except FreeeError:
        logger.exception("事前申請を取得できませんでした")
        return None


def detail_context(
    session: Session,
    freee_client: FreeeClient,
    invoice: Invoice,
    payment_input: PaymentRequestInput,
    approval_requests: list[ApprovalRequest] | None,
    *,
    values: dict[str, str] | None = None,
    errors: list[str] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """確認・修正画面の表示に使う値。values は入力フォームの値（省略時は保存済みの値）。"""
    partner_repository = PartnerRepository(session)
    partners = [(str(p.id), p.name) for p in partner_repository.list_active()]
    current_partner = (
        partner_repository.get_including_deleted(payment_input.partner_id)
        if payment_input.partner_id is not None
        else None
    )
    if current_partner is not None and current_partner.deleted_at is not None:
        # 削除済みの取引先も、現在の取引先なら選択肢に残す
        partners.append((str(current_partner.id), f"{current_partner.name}（削除済み）"))

    options: dict[str, list[FreeeOption]] = {
        field: getattr(freee_client, method)() for field, _, method in FREEE_FIELDS
    }
    # 保存済みの値のうち、freee の選択肢にないもの
    missing = {
        field: value
        for field, _, _ in FREEE_FIELDS
        if (value := getattr(payment_input, field)) is not None
        and value not in {option.id for option in options[field]}
    }

    extraction = ExtractionRepository(session).get(invoice.id)
    unreadable = {
        field.name
        for field in INPUT_FIELDS
        if field.extracted
        and payment_input.created_from_extraction
        and extraction is not None
        and getattr(extraction, field.name) is None
    }

    return {
        "invoice": invoice,
        "payment_input": payment_input,
        "values": values if values is not None else input_values(payment_input),
        "input_fields": INPUT_FIELDS,
        "freee_fields": FREEE_FIELDS,
        "partners": partners,
        "current_partner": current_partner,
        "options": options,
        "option_names": {
            field: {option.id: option.name for option in field_options}
            for field, field_options in options.items()
        },
        "missing": missing,
        "unreadable": unreadable,
        "approval_requests": approval_requests,
        "status_labels": STATUS_LABELS,
        "errors": errors or [],
        "message": message,
    }


@router.get("/{invoice_id}")
def show_invoice(
    request: Request,
    invoice_id: str,
    session: SessionDep,
    freee_client: FreeeClientDep,
    user: UserDep,
) -> Response:
    invoice = get_invoice(session, invoice_id)
    # 初めて開いたときに、支払い依頼インプットを作る
    ensure_input(session, invoice.id, datetime.now(UTC))
    payment_input = PaymentRequestRepository(session).get(invoice.id)
    assert payment_input is not None

    approval_requests = fetch_approval_requests(freee_client, user)
    return templates.TemplateResponse(
        request,
        "invoices/detail.html",
        detail_context(session, freee_client, invoice, payment_input, approval_requests),
    )


@router.get("/{invoice_id}/file")
def invoice_file(invoice_id: str, session: SessionDep, storage: FileStorageDep) -> Response:
    """請求書ファイル。ブラウザの PDF 表示で見られるように inline で返す。"""
    invoice = get_invoice(session, invoice_id)
    return Response(
        content=storage.load(invoice.file_key),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(invoice.file_name)}"},
    )


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None
