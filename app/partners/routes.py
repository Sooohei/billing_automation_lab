import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.freee.client import FreeeClient, FreeeOption
from app.freee.dependencies import get_freee_client
from app.partners.models import Partner
from app.partners.repository import PartnerRepository
from app.partners.service import (
    PartnerInput,
    PartnerNotFoundError,
    PartnerService,
    PartnerValidationError,
)
from app.templating import templates

router = APIRouter(prefix="/partners")

SessionDep = Annotated[Session, Depends(get_session)]
FreeeClientDep = Annotated[FreeeClient, Depends(get_freee_client)]
FormField = Annotated[str, Form()]

# freee 申請用の既定値の項目と、選択肢の取り方
FREEE_FIELDS = [
    ("freee_partner_id", "既定の freee 上の取引先", "list_partners"),
    ("freee_account_item_id", "既定の勘定科目", "list_account_items"),
    ("freee_tax_code", "既定の税区分", "list_taxes"),
    ("freee_approval_flow_route_id", "既定の承認経路", "list_approval_flow_routes"),
]


def freee_options(freee_client: FreeeClient) -> dict[str, list[FreeeOption]]:
    return {field: getattr(freee_client, method)() for field, _, method in FREEE_FIELDS}


def missing_value_label(freee_id: int) -> str:
    return f"（freee に存在しない値: {freee_id}）"


def parse_partner_id(partner_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(partner_id)
    except ValueError:
        raise HTTPException(status_code=404) from None


def render_form(
    request: Request,
    *,
    action: str,
    title: str,
    values: dict[str, str],
    options: dict[str, list[FreeeOption]],
    missing: dict[str, str] | None = None,
    errors: list[str] | None = None,
    status_code: int = 200,
) -> Response:
    return templates.TemplateResponse(
        request,
        "partners/form.html",
        {
            "action": action,
            "title": title,
            "values": values,
            "fields": FREEE_FIELDS,
            "options": options,
            "missing": missing or {},
            "errors": errors or [],
        },
        status_code=status_code,
    )


def form_values(partner_input: PartnerInput) -> dict[str, str]:
    return {
        "name": partner_input.name,
        "emails": partner_input.emails,
        **{field: getattr(partner_input, field) for field, _, _ in FREEE_FIELDS},
    }


def partner_input_from_form(
    name: FormField = "",
    emails: FormField = "",
    freee_partner_id: FormField = "",
    freee_account_item_id: FormField = "",
    freee_tax_code: FormField = "",
    freee_approval_flow_route_id: FormField = "",
) -> PartnerInput:
    return PartnerInput(
        name=name,
        emails=emails,
        freee_partner_id=freee_partner_id,
        freee_account_item_id=freee_account_item_id,
        freee_tax_code=freee_tax_code,
        freee_approval_flow_route_id=freee_approval_flow_route_id,
    )


PartnerInputDep = Annotated[PartnerInput, Depends(partner_input_from_form)]


@router.get("")
def list_partners(request: Request, session: SessionDep, freee_client: FreeeClientDep) -> Response:
    options = freee_options(freee_client)
    names = {
        field: {option.id: option.name for option in field_options}
        for field, field_options in options.items()
    }

    def freee_name(field: str, freee_id: int) -> str:
        return names[field].get(freee_id, missing_value_label(freee_id))

    return templates.TemplateResponse(
        request,
        "partners/list.html",
        {
            "partners": PartnerRepository(session).list_active(),
            "fields": FREEE_FIELDS,
            "freee_name": freee_name,
        },
    )


@router.get("/new")
def new_partner_form(request: Request, freee_client: FreeeClientDep) -> Response:
    values = {"name": "", "emails": "", **{field: "" for field, _, _ in FREEE_FIELDS}}
    return render_form(
        request,
        action="/partners/new",
        title="取引先登録",
        values=values,
        options=freee_options(freee_client),
    )


@router.post("/new")
def create_partner(
    request: Request,
    session: SessionDep,
    freee_client: FreeeClientDep,
    partner_input: PartnerInputDep,
) -> Response:
    try:
        PartnerService(session, freee_client).create(partner_input)
    except PartnerValidationError as e:
        return render_form(
            request,
            action="/partners/new",
            title="取引先登録",
            values=form_values(partner_input),
            options=freee_options(freee_client),
            errors=e.errors,
            status_code=422,
        )
    return RedirectResponse("/partners", status_code=303)


@router.get("/{partner_id}/edit")
def edit_partner_form(
    request: Request, partner_id: str, session: SessionDep, freee_client: FreeeClientDep
) -> Response:
    partner = PartnerRepository(session).get_active(parse_partner_id(partner_id))
    if partner is None:
        raise HTTPException(status_code=404)

    options = freee_options(freee_client)
    values, missing = current_values(partner, options)
    return render_form(
        request,
        action=f"/partners/{partner.id}/edit",
        title="取引先変更",
        values=values,
        options=options,
        missing=missing,
    )


def current_values(
    partner: Partner, options: dict[str, list[FreeeOption]]
) -> tuple[dict[str, str], dict[str, str]]:
    """変更画面の初期値。freee の選択肢にない保存済みの値は未選択にし、その旨を返す。"""
    values = {"name": partner.name, "emails": "\n".join(email.email for email in partner.emails)}
    missing: dict[str, str] = {}
    for field, _, _ in FREEE_FIELDS:
        freee_id: int = getattr(partner, field)
        if freee_id in {option.id for option in options[field]}:
            values[field] = str(freee_id)
        else:
            values[field] = ""
            missing[field] = missing_value_label(freee_id)
    return values, missing


@router.post("/{partner_id}/edit")
def update_partner(
    request: Request,
    partner_id: str,
    session: SessionDep,
    freee_client: FreeeClientDep,
    partner_input: PartnerInputDep,
) -> Response:
    parsed_id = parse_partner_id(partner_id)
    try:
        PartnerService(session, freee_client).update(parsed_id, partner_input)
    except PartnerNotFoundError:
        raise HTTPException(status_code=404) from None
    except PartnerValidationError as e:
        return render_form(
            request,
            action=f"/partners/{parsed_id}/edit",
            title="取引先変更",
            values=form_values(partner_input),
            options=freee_options(freee_client),
            errors=e.errors,
            status_code=422,
        )
    return RedirectResponse("/partners", status_code=303)


@router.post("/{partner_id}/delete")
def delete_partner(partner_id: str, session: SessionDep, freee_client: FreeeClientDep) -> Response:
    try:
        PartnerService(session, freee_client).delete(parse_partner_id(partner_id))
    except PartnerNotFoundError:
        raise HTTPException(status_code=404) from None
    return RedirectResponse("/partners", status_code=303)
