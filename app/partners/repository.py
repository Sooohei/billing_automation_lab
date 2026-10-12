import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.partners.models import Partner, PartnerEmail
from app.partners.normalize import normalize_email


class PartnerRepository:
    """取引先の読み出し。SR-01〜03 にも提供する。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_active_by_email(self, email: str) -> Partner | None:
        """送信元メールアドレス（正規化して照合）に対応する有効な取引先。なければ None。"""
        statement = (
            select(Partner)
            .join(PartnerEmail)
            .where(PartnerEmail.email == normalize_email(email), Partner.deleted_at.is_(None))
        )
        return self._session.scalars(statement).one_or_none()

    def list_active_emails(self) -> list[str]:
        """有効な取引先の送信元メールアドレスの一覧。"""
        statement = (
            select(PartnerEmail.email)
            .join(Partner)
            .where(Partner.deleted_at.is_(None))
            .order_by(PartnerEmail.email)
        )
        return list(self._session.scalars(statement))

    def list_active(self) -> list[Partner]:
        """有効な取引先を取引先名の順に返す。"""
        statement = (
            select(Partner)
            .where(Partner.deleted_at.is_(None))
            .options(selectinload(Partner.emails))
            .order_by(Partner.name)
        )
        return list(self._session.scalars(statement))

    def get_active(self, partner_id: uuid.UUID) -> Partner | None:
        """有効な取引先を返す。削除済みか存在しなければ None。"""
        statement = select(Partner).where(Partner.id == partner_id, Partner.deleted_at.is_(None))
        return self._session.scalars(statement).one_or_none()

    def get_including_deleted(self, partner_id: uuid.UUID) -> Partner | None:
        """削除済みも含めて取引先を返す。"""
        return self._session.get(Partner, partner_id)

    # 以下は SR-00 の登録・変更・削除の処理で使う

    def get_active_for_update(self, partner_id: uuid.UUID) -> Partner | None:
        """有効な取引先を SELECT ... FOR UPDATE でロックして返す。"""
        statement = (
            select(Partner)
            .where(Partner.id == partner_id, Partner.deleted_at.is_(None))
            .with_for_update()
        )
        return self._session.scalars(statement).one_or_none()

    def exists_other_active_name(self, name: str, exclude_id: uuid.UUID | None) -> bool:
        """自分自身（exclude_id）以外の有効な取引先に、同じ取引先名があるか。"""
        statement = select(Partner.id).where(Partner.name == name, Partner.deleted_at.is_(None))
        if exclude_id is not None:
            statement = statement.where(Partner.id != exclude_id)
        return self._session.scalars(statement).first() is not None

    def find_other_active_owners(
        self, emails: list[str], exclude_id: uuid.UUID | None
    ) -> dict[str, str]:
        """自分自身（exclude_id）以外の有効な取引先に登録済みのアドレスと、その取引先名。"""
        statement = (
            select(PartnerEmail.email, Partner.name)
            .join(Partner)
            .where(PartnerEmail.email.in_(emails), Partner.deleted_at.is_(None))
        )
        if exclude_id is not None:
            statement = statement.where(Partner.id != exclude_id)
        return {email: name for email, name in self._session.execute(statement)}
