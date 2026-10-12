import json
from datetime import date
from pathlib import Path

import pytest

from app.auth import CurrentUser
from app.freee.client import ApprovalRequest, FreeeOption, PaymentRequestParams
from app.freee.sample_client import SampleFreeeClient


def test_サンプルデータの選択肢を返す(tmp_path: Path) -> None:
    for file_name, items in {
        "partners.json": [{"id": 101, "name": "株式会社Aメディア"}],
        "account_items.json": [{"id": 201, "name": "広告宣伝費"}],
        "taxes.json": [{"id": 136, "name": "課対仕入10%"}],
        "approval_flow_routes.json": [{"id": 301, "name": "媒体費（部長承認）"}],
    }.items():
        (tmp_path / file_name).write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")

    client = SampleFreeeClient(tmp_path)

    assert client.list_partners() == [FreeeOption(id=101, name="株式会社Aメディア")]
    assert client.list_account_items() == [FreeeOption(id=201, name="広告宣伝費")]
    assert client.list_taxes() == [FreeeOption(id=136, name="課対仕入10%")]
    assert client.list_approval_flow_routes() == [FreeeOption(id=301, name="媒体費（部長承認）")]


def test_リポジトリのサンプルデータを読み込める() -> None:
    client = SampleFreeeClient()

    for options in [
        client.list_partners(),
        client.list_account_items(),
        client.list_taxes(),
        client.list_approval_flow_routes(),
    ]:
        assert options
        assert len({option.id for option in options}) == len(options)


USER = CurrentUser(email="dev@example.com")


def approval_request(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": 5001,
        "application_number": "A-0001",
        "title": "2026年10月 媒体費 Aメディア",
        "amount": 1100000,
        "application_date": "2026-09-20",
        "status": "approved",
        "deal_created": False,
        "manual_journal_created": False,
        "child_request_count": 0,
    }
    item.update(overrides)
    return item


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),
        ({"child_request_count": 14}, True),
        ({"status": "in_progress"}, False),
        ({"title": "2026年10月 出張交通費"}, False),
        ({"deal_created": True}, False),
        ({"manual_journal_created": True}, False),
        ({"child_request_count": 15}, False),
    ],
    ids=[
        "条件を満たす",
        "作成した申請が14件",
        "承認済みでない",
        "件名に媒体費がない",
        "取引を作成済み",
        "振替伝票を作成済み",
        "作成した申請が15件",
    ],
)
def test_事前申請は取得条件をすべて満たすものだけを返す(
    tmp_path: Path, overrides: dict[str, object], expected: bool
) -> None:
    (tmp_path / "approval_requests.json").write_text(
        json.dumps([approval_request(**overrides)], ensure_ascii=False), encoding="utf-8"
    )

    requests = SampleFreeeClient(tmp_path).list_approval_requests(USER)

    if expected:
        assert requests == [
            ApprovalRequest(
                5001, "A-0001", "2026年10月 媒体費 Aメディア", 1100000, date(2026, 9, 20)
            )
        ]
    else:
        assert requests == []


def test_リポジトリの事前申請のサンプルを読み込める() -> None:
    requests = SampleFreeeClient().list_approval_requests(USER)

    assert [r.application_number for r in requests] == [
        "A-0001",
        "A-0002",
        "A-0003",
        "A-0004",
        "A-0010",
    ]


def test_アップロードと申請は常に成功し識別子を返す() -> None:
    client = SampleFreeeClient()
    receipt_id = client.upload_receipt(USER, b"%PDF", "請求書.pdf")

    payment_request_id = client.create_payment_request(
        USER,
        PaymentRequestParams(
            title="202610_Aメディア_メディア費",
            partner_id=101,
            document_code="AM-2026-10-001",
            issue_date=date(2026, 10, 1),
            payment_date=date(2026, 10, 31),
            amount=1100000,
            account_item_id=201,
            tax_code=136,
            approval_flow_route_id=301,
            parent_id=5001,
            receipt_ids=[receipt_id],
        ),
    )

    assert receipt_id > 0
    assert payment_request_id > 0
