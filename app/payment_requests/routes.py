import uuid
from datetime import date
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.partners.repository import PartnerRepository
from app.payment_requests.models import PaymentRequestStatus
from app.payment_requests.repository import InvoiceFilters, PaymentRequestRepository
from app.templating import templates

router = APIRouter(prefix="/invoices")

SessionDep = Annotated[Session, Depends(get_session)]

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
