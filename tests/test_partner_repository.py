import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.partners.models import Partner, PartnerEmail
from app.partners.repository import PartnerRepository


def add_partner(
    session: Session, name: str, emails: list[str], *, deleted: bool = False
) -> Partner:
    partner = Partner(
        name=name,
        freee_partner_id=101,
        freee_account_item_id=201,
        freee_tax_code=136,
        freee_approval_flow_route_id=301,
        deleted_at=datetime.now(UTC) if deleted else None,
        emails=[PartnerEmail(email=email) for email in emails],
    )
    session.add(partner)
    session.flush()
    return partner


def test_find_active_by_emailは大文字を含むアドレスでも見つかる(session: Session) -> None:
    partner = add_partner(session, "Aメディア", ["billing@a-media.jp"])

    found = PartnerRepository(session).find_active_by_email(" Billing@A-Media.jp ")

    assert found is not None
    assert found.id == partner.id


def test_find_active_by_emailは登録のないアドレスならNoneを返す(session: Session) -> None:
    add_partner(session, "Aメディア", ["billing@a-media.jp"])

    assert PartnerRepository(session).find_active_by_email("other@a-media.jp") is None


def test_削除済みの取引先は有効な取引先の検索に出ない(session: Session) -> None:
    # 削除時はアドレスの行を物理削除する。ここでは deleted_at の条件だけを確かめる
    add_partner(session, "Bネットワークス", ["info@b-net.jp"], deleted=True)
    repository = PartnerRepository(session)

    assert repository.find_active_by_email("info@b-net.jp") is None
    assert repository.list_active_emails() == []
    assert repository.list_active() == []


def test_list_activeは有効な取引先を取引先名の順に返す(session: Session) -> None:
    add_partner(session, "Cアド", ["c@c-ad.jp"])
    add_partner(session, "Aメディア", ["a2@a-media.jp", "a1@a-media.jp"])

    partners = PartnerRepository(session).list_active()

    assert [partner.name for partner in partners] == ["Aメディア", "Cアド"]
    assert [email.email for email in partners[0].emails] == ["a2@a-media.jp", "a1@a-media.jp"]


def test_list_active_emailsは有効な取引先のアドレスをすべて返す(session: Session) -> None:
    add_partner(session, "Aメディア", ["a1@a-media.jp", "a2@a-media.jp"])
    add_partner(session, "Cアド", ["c@c-ad.jp"])

    emails = PartnerRepository(session).list_active_emails()

    assert emails == ["a1@a-media.jp", "a2@a-media.jp", "c@c-ad.jp"]


def test_get_including_deletedは削除済みの取引先も返す(session: Session) -> None:
    partner = add_partner(session, "Bネットワークス", [], deleted=True)
    repository = PartnerRepository(session)

    found = repository.get_including_deleted(partner.id)

    assert found is not None
    assert found.name == "Bネットワークス"
    assert repository.get_including_deleted(uuid.uuid4()) is None


def test_有効な取引先どうしで同じ取引先名は登録できない(session: Session) -> None:
    add_partner(session, "Aメディア", [])

    with pytest.raises(IntegrityError, match="uq_partners_name_active"):
        add_partner(session, "Aメディア", [])


def test_削除済みの取引先と同じ取引先名は登録できる(session: Session) -> None:
    add_partner(session, "Aメディア", [], deleted=True)

    add_partner(session, "Aメディア", [])


def test_同じ送信元メールアドレスは登録できない(session: Session) -> None:
    add_partner(session, "Aメディア", ["billing@a-media.jp"])

    with pytest.raises(IntegrityError, match="uq_partner_emails_email"):
        add_partner(session, "Cアド", ["billing@a-media.jp"])
