import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.freee.client import FreeeClient, FreeeOption
from app.partners.models import Partner, PartnerEmail
from app.partners.normalize import normalize_email, normalize_partner_name
from app.partners.repository import PartnerRepository


@dataclass(frozen=True)
class PartnerInput:
    """入力フォームの値（正規化前）。送信元メールアドレスは 1 行に 1 件。"""

    name: str
    emails: str
    freee_partner_id: str
    freee_account_item_id: str
    freee_tax_code: str
    freee_approval_flow_route_id: str


class PartnerValidationError(Exception):
    """入力チェックに当てはまった。当てはまったメッセージをすべて持つ。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


class PartnerNotFoundError(Exception):
    """取引先が削除済みまたは存在しない。"""


@dataclass(frozen=True)
class _NormalizedInput:
    name: str
    emails: list[str]
    freee_ids: dict[str, int | None]


# freee 申請用の既定値の項目名と表示名
_FREEE_FIELDS = {
    "freee_partner_id": "既定の freee 上の取引先",
    "freee_account_item_id": "既定の勘定科目",
    "freee_tax_code": "既定の税区分",
    "freee_approval_flow_route_id": "既定の承認経路",
}


def is_email_format(email: str) -> bool:
    """@ がちょうど 1 つあり、前後が空でなく、@ の後ろに . を含み、空白を含まない。"""
    if any(char.isspace() for char in email) or email.count("@") != 1:
        return False
    local, domain = email.split("@")
    return bool(local) and bool(domain) and "." in domain


class PartnerService:
    """取引先の登録・変更・削除。"""

    def __init__(self, session: Session, freee_client: FreeeClient) -> None:
        self._session = session
        self._freee_client = freee_client
        self._repository = PartnerRepository(session)

    def create(self, partner_input: PartnerInput) -> Partner:
        values = self._normalize(partner_input)
        self._raise_if_invalid(values, exclude_id=None)

        partner = Partner(
            name=values.name,
            **self._freee_values(values),
            emails=[PartnerEmail(email=email) for email in values.emails],
        )
        self._session.add(partner)
        self._commit(values, exclude_id=None)
        return partner

    def update(self, partner_id: uuid.UUID, partner_input: PartnerInput) -> Partner:
        partner = self._repository.get_active_for_update(partner_id)
        if partner is None:
            self._session.rollback()
            raise PartnerNotFoundError
        values = self._normalize(partner_input)
        self._raise_if_invalid(values, exclude_id=partner_id)

        partner.name = values.name
        for field, value in self._freee_values(values).items():
            setattr(partner, field, value)
        partner.updated_at = datetime.now(UTC)
        # アドレスは全件削除してから追加し直す。同じアドレスを残す場合に一意制約に
        # 当たらないよう、削除を先に DB に反映する
        partner.emails.clear()
        self._session.flush()
        partner.emails.extend(PartnerEmail(email=email) for email in values.emails)
        self._commit(values, exclude_id=partner_id)
        return partner

    def delete(self, partner_id: uuid.UUID) -> None:
        """論理削除する。アドレスの行は物理削除し、SR-01〜03 のデータには触れない。"""
        partner = self._repository.get_active_for_update(partner_id)
        if partner is None:
            self._session.rollback()
            raise PartnerNotFoundError
        partner.deleted_at = datetime.now(UTC)
        partner.emails.clear()
        self._session.commit()

    def _normalize(self, partner_input: PartnerInput) -> _NormalizedInput:
        emails: list[str] = []
        for line in partner_input.emails.splitlines():
            email = normalize_email(line)
            # 空の行は無視し、同じアドレスが複数行あれば 1 件にまとめる
            if email and email not in emails:
                emails.append(email)
        return _NormalizedInput(
            name=normalize_partner_name(partner_input.name),
            emails=emails,
            freee_ids={field: _parse_id(getattr(partner_input, field)) for field in _FREEE_FIELDS},
        )

    def _raise_if_invalid(self, values: _NormalizedInput, exclude_id: uuid.UUID | None) -> None:
        errors = self._validate(values, exclude_id)
        if errors:
            self._session.rollback()
            raise PartnerValidationError(errors)

    def _validate(self, values: _NormalizedInput, exclude_id: uuid.UUID | None) -> list[str]:
        """入力チェック 1〜6 をすべて行い、当てはまったメッセージを順に返す。"""
        errors: list[str] = []
        if not values.name:
            errors.append("取引先名を入力してください")
        if not values.emails:
            errors.append("送信元メールアドレスを 1 件以上入力してください")
        errors.extend(
            f"「{email}」はメールアドレスの形式ではありません"
            for email in values.emails
            if not is_email_format(email)
        )
        errors.extend(self._duplicate_name_errors(values, exclude_id))
        errors.extend(self._duplicate_email_errors(values, exclude_id))
        errors.extend(self._freee_errors(values))
        return errors

    def _duplicate_name_errors(
        self, values: _NormalizedInput, exclude_id: uuid.UUID | None
    ) -> list[str]:
        if values.name and self._repository.exists_other_active_name(values.name, exclude_id):
            return [f"取引先名「{values.name}」は他の取引先に登録されています"]
        return []

    def _duplicate_email_errors(
        self, values: _NormalizedInput, exclude_id: uuid.UUID | None
    ) -> list[str]:
        owners = self._repository.find_other_active_owners(values.emails, exclude_id)
        return [
            f"「{email}」は取引先「{owners[email]}」に登録されています"
            for email in values.emails
            if email in owners
        ]

    def _freee_errors(self, values: _NormalizedInput) -> list[str]:
        options: dict[str, list[FreeeOption]] = {
            "freee_partner_id": self._freee_client.list_partners(),
            "freee_account_item_id": self._freee_client.list_account_items(),
            "freee_tax_code": self._freee_client.list_taxes(),
            "freee_approval_flow_route_id": self._freee_client.list_approval_flow_routes(),
        }
        errors: list[str] = []
        for field, label in _FREEE_FIELDS.items():
            value = values.freee_ids[field]
            if value is None or value not in {option.id for option in options[field]}:
                errors.append(f"{label}を選択してください")
        return errors

    def _freee_values(self, values: _NormalizedInput) -> dict[str, int]:
        # 入力チェックを通った後なので、すべて値がある
        return {field: value for field, value in values.freee_ids.items() if value is not None}

    def _commit(self, values: _NormalizedInput, exclude_id: uuid.UUID | None) -> None:
        """チェックの後に他の利用者が同じ名前・アドレスを登録していた場合も、重複として表示する。"""
        try:
            self._session.commit()
        except IntegrityError as e:
            self._session.rollback()
            constraint = (
                e.orig.diag.constraint_name if isinstance(e.orig, UniqueViolation) else None
            )
            if constraint == "uq_partners_name_active":
                raise PartnerValidationError(
                    [f"取引先名「{values.name}」は他の取引先に登録されています"]
                ) from e
            if constraint == "uq_partner_emails_email":
                errors = self._duplicate_email_errors(values, exclude_id)
                raise PartnerValidationError(
                    errors or ["送信元メールアドレスが他の取引先に登録されています"]
                ) from e
            raise


def _parse_id(value: str) -> int | None:
    try:
        return int(value.strip())
    except ValueError:
        return None
