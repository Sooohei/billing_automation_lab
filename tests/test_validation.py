from datetime import date

import pytest

from app.extraction.extractor import RawExtraction
from app.extraction.validation import (
    ValidatedExtraction,
    validate,
    validate_amount,
    validate_date,
    validate_invoice_number,
    validate_registration_number,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("INV-2026-0001", "INV-2026-0001"),
        ("  INV-2026-0001　", "INV-2026-0001"),
        ("ＩＮＶ－０１", "ＩＮＶ－０１"),  # 書かれている通りに保存する（全角のまま）
        ("   ", None),
        ("", None),
        (None, None),
    ],
)
def test_請求書番号(value: str | None, expected: str | None) -> None:
    assert validate_invoice_number(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("T1234567890123", "T1234567890123"),
        ("t1234567890123", "T1234567890123"),
        ("Ｔ１２３４５６７８９０１２３", "T1234567890123"),
        ("T1234-5678-90123", "T1234567890123"),
        ("T 1234 5678 90123", "T1234567890123"),
        ("T1234−5678‐90123", "T1234567890123"),
        ("T123456789012", None),  # 12 桁
        ("T12345678901234", None),  # 14 桁
        ("1234567890123", None),  # T がない
        ("X1234567890123", None),
        ("T12345678901２A", None),
        (None, None),
    ],
)
def test_適格請求書発行事業者登録番号(value: str | None, expected: str | None) -> None:
    assert validate_registration_number(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-01", date(2026, 10, 1)),
        (" 2026-10-31 ", date(2026, 10, 31)),
        ("2028-02-29", date(2028, 2, 29)),
        ("2026-02-30", None),  # 実在しない
        ("2026-13-01", None),
        ("2026/10/01", None),
        ("20261001", None),
        ("2026-1-1", None),
        ("2026年10月1日", None),
        ("２０２６-１０-０１", None),
        (None, None),
    ],
)
def test_日付(value: str | None, expected: date | None) -> None:
    assert validate_date(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("110000", 110000),
        ("1,100,000", 1100000),
        ("１，１００，０００", 1100000),
        (" 1 100 000 ", 1100000),
        ("0", 0),
        ("-5000", -5000),
        ("¥110000", None),
        ("110000円", None),
        ("110000.5", None),
        ("一万円", None),
        ("", None),
        ("9223372036854775808", None),  # bigint に入らない
        (None, None),
    ],
)
def test_金額(value: str | None, expected: int | None) -> None:
    assert validate_amount(value) == expected


def test_項目ごとにチェックし通らない項目だけを読み取れずにする() -> None:
    raw = RawExtraction(
        invoice_number="AM-2026-10-001",
        qualified_invoice_issuer_number="T1234-5678-90123",
        issue_date="2026-10-01",
        due_date="2026-02-30",
        amount_excluding_tax="1,000,000",
        tax_amount=None,
        amount_including_tax="不明",
    )

    assert validate(raw) == ValidatedExtraction(
        invoice_number="AM-2026-10-001",
        qualified_invoice_issuer_number="T1234567890123",
        issue_date=date(2026, 10, 1),
        due_date=None,
        amount_excluding_tax=1_000_000,
        tax_amount=None,
        amount_including_tax=None,
    )
