import uuid
from dataclasses import replace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.partners.models import PartnerEmail
from app.partners.repository import PartnerRepository
from app.partners.service import (
    PartnerInput,
    PartnerNotFoundError,
    PartnerService,
    PartnerValidationError,
)
from tests.fakes import FakeFreeeClient

VALID_INPUT = PartnerInput(
    name="Aメディア",
    emails="billing@a-media.jp",
    freee_partner_id="101",
    freee_account_item_id="201",
    freee_tax_code="136",
    freee_approval_flow_route_id="301",
)


@pytest.fixture
def service(session: Session) -> PartnerService:
    return PartnerService(session, FakeFreeeClient())


def errors_of(service: PartnerService, partner_input: PartnerInput) -> list[str]:
    with pytest.raises(PartnerValidationError) as exc_info:
        service.create(partner_input)
    return exc_info.value.errors


# 登録・正規化


def test_取引先を登録できる(service: PartnerService, session: Session) -> None:
    partner = service.create(VALID_INPUT)

    found = PartnerRepository(session).get_including_deleted(partner.id)
    assert found is not None
    assert found.name == "Aメディア"
    assert [email.email for email in found.emails] == ["billing@a-media.jp"]
    assert (found.freee_partner_id, found.freee_account_item_id) == (101, 201)
    assert (found.freee_tax_code, found.freee_approval_flow_route_id) == (136, 301)


def test_取引先名の前後の空白を除く(service: PartnerService) -> None:
    partner = service.create(replace(VALID_INPUT, name="　 Aメディア 　"))

    assert partner.name == "Aメディア"


def test_全角と半角が違う取引先名は別の名前として登録できる(service: PartnerService) -> None:
    service.create(replace(VALID_INPUT, name="Aメディア"))

    service.create(replace(VALID_INPUT, name="Ａメディア", emails="other@a-media.jp"))


def test_送信元メールアドレスを正規化し空の行と重複をまとめる(service: PartnerService) -> None:
    partner = service.create(
        replace(
            VALID_INPUT, emails=" Billing@A-Media.jp \n\n  \nbilling@a-media.jp\nInfo@a-media.jp"
        )
    )

    assert [email.email for email in partner.emails] == ["billing@a-media.jp", "info@a-media.jp"]


# 入力チェック


def test_取引先名が空なら拒否する(service: PartnerService) -> None:
    assert errors_of(service, replace(VALID_INPUT, name=" 　 ")) == ["取引先名を入力してください"]


def test_送信元メールアドレスがなければ拒否する(service: PartnerService) -> None:
    assert errors_of(service, replace(VALID_INPUT, emails="\n  \n")) == [
        "送信元メールアドレスを 1 件以上入力してください"
    ]


@pytest.mark.parametrize(
    "email",
    ["billing", "billing@", "@a-media.jp", "a@b@a-media.jp", "billing@localhost", "bil ling@a.jp"],
)
def test_メールアドレスの形式でなければ拒否する(service: PartnerService, email: str) -> None:
    assert errors_of(service, replace(VALID_INPUT, emails=email)) == [
        f"「{email}」はメールアドレスの形式ではありません"
    ]


def test_他の取引先と同じ取引先名なら拒否する(service: PartnerService) -> None:
    service.create(VALID_INPUT)

    assert errors_of(service, replace(VALID_INPUT, emails="other@a-media.jp")) == [
        "取引先名「Aメディア」は他の取引先に登録されています"
    ]


def test_大文字小文字だけが違うアドレスは重複として拒否する(service: PartnerService) -> None:
    service.create(VALID_INPUT)

    assert errors_of(service, replace(VALID_INPUT, name="Cアド", emails="Billing@A-Media.jp")) == [
        "「billing@a-media.jp」は取引先「Aメディア」に登録されています"
    ]


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("freee_partner_id", "既定の freee 上の取引先を選択してください"),
        ("freee_account_item_id", "既定の勘定科目を選択してください"),
        ("freee_tax_code", "既定の税区分を選択してください"),
        ("freee_approval_flow_route_id", "既定の承認経路を選択してください"),
    ],
)
@pytest.mark.parametrize("value", ["", "999", "abc"], ids=["空", "選択肢にない", "数値でない"])
def test_freeeの既定値が空か選択肢になければ拒否する(
    service: PartnerService, field: str, message: str, value: str
) -> None:
    assert errors_of(service, replace(VALID_INPUT, **{field: value})) == [message]


def test_当てはまる入力チェックをすべて順に表示する(service: PartnerService) -> None:
    service.create(VALID_INPUT)

    errors = errors_of(
        service,
        PartnerInput(
            name="Aメディア",
            emails="invalid\nBILLING@a-media.jp",
            freee_partner_id="",
            freee_account_item_id="201",
            freee_tax_code="136",
            freee_approval_flow_route_id="999",
        ),
    )

    assert errors == [
        "「invalid」はメールアドレスの形式ではありません",
        "取引先名「Aメディア」は他の取引先に登録されています",
        "「billing@a-media.jp」は取引先「Aメディア」に登録されています",
        "既定の freee 上の取引先を選択してください",
        "既定の承認経路を選択してください",
    ]


def test_チェックの後に重複が登録されていても重複として表示する(
    service: PartnerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service.create(VALID_INPUT)
    # チェックを通った後に、他の利用者が同じ名前・アドレスを登録した状態を再現する
    monkeypatch.setattr(service, "_validate", lambda values, exclude_id: [])

    assert errors_of(service, replace(VALID_INPUT, emails="other@a-media.jp")) == [
        "取引先名「Aメディア」は他の取引先に登録されています"
    ]
    assert errors_of(service, replace(VALID_INPUT, name="Cアド")) == [
        "「billing@a-media.jp」は取引先「Aメディア」に登録されています"
    ]


# 変更


def test_自分自身の名前とアドレスのままなら変更できる(service: PartnerService) -> None:
    partner = service.create(VALID_INPUT)

    updated = service.update(partner.id, replace(VALID_INPUT, freee_account_item_id="202"))

    assert updated.freee_account_item_id == 202


def test_変更でアドレスの追加と削除を反映する(service: PartnerService, session: Session) -> None:
    partner = service.create(replace(VALID_INPUT, emails="a1@a-media.jp\na2@a-media.jp"))

    service.update(
        partner.id, replace(VALID_INPUT, name="Aメディア2", emails="a2@a-media.jp\na3@a-media.jp")
    )

    repository = PartnerRepository(session)
    assert repository.list_active_emails() == ["a2@a-media.jp", "a3@a-media.jp"]
    found = repository.find_active_by_email("a3@a-media.jp")
    assert found is not None
    assert found.name == "Aメディア2"


def test_変更で他の取引先と重複すれば拒否する(service: PartnerService) -> None:
    service.create(VALID_INPUT)
    partner = service.create(replace(VALID_INPUT, name="Cアド", emails="c@c-ad.jp"))

    with pytest.raises(PartnerValidationError) as exc_info:
        service.update(partner.id, replace(VALID_INPUT, emails="c@c-ad.jp"))

    assert exc_info.value.errors == ["取引先名「Aメディア」は他の取引先に登録されています"]


def test_削除済みか存在しない取引先は変更できない(service: PartnerService) -> None:
    partner = service.create(VALID_INPUT)
    service.delete(partner.id)

    with pytest.raises(PartnerNotFoundError):
        service.update(partner.id, VALID_INPUT)
    with pytest.raises(PartnerNotFoundError):
        service.update(uuid.uuid4(), VALID_INPUT)


# 削除


def test_削除した取引先は有効な取引先の検索に出ない(
    service: PartnerService, session: Session
) -> None:
    partner = service.create(VALID_INPUT)

    service.delete(partner.id)

    repository = PartnerRepository(session)
    assert repository.list_active() == []
    assert repository.list_active_emails() == []
    assert repository.find_active_by_email("billing@a-media.jp") is None
    found = repository.get_including_deleted(partner.id)
    assert found is not None
    assert found.name == "Aメディア"
    assert found.deleted_at is not None
    assert session.scalar(select(func.count()).select_from(PartnerEmail)) == 0


def test_削除した取引先と同じ名前とアドレスで登録し直せる(service: PartnerService) -> None:
    partner = service.create(VALID_INPUT)
    service.delete(partner.id)

    service.create(VALID_INPUT)


def test_削除済みか存在しない取引先は削除できない(service: PartnerService) -> None:
    partner = service.create(VALID_INPUT)
    service.delete(partner.id)

    with pytest.raises(PartnerNotFoundError):
        service.delete(partner.id)
    with pytest.raises(PartnerNotFoundError):
        service.delete(uuid.uuid4())
