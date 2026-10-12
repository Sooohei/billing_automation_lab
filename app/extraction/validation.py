"""読み取った値の形式チェック。

前処理は表記をそろえるだけで、値の中身は変えない。チェックに通らない値は、推測した値が
混ざった可能性があるものとみなして None（読み取れず）にする。
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from app.extraction.extractor import RawExtraction

_REGISTRATION_NUMBER = re.compile(r"T[0-9]{13}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_INTEGER = re.compile(r"-?[0-9]+")
# 登録番号から除くハイフン（NFKC で "-" にならないものを含む）
_HYPHENS = "-‐‑‒–—―−"
# DB の bigint に入る範囲
_BIGINT_MIN = -(2**63)
_BIGINT_MAX = 2**63 - 1


@dataclass(frozen=True)
class ValidatedExtraction:
    """形式チェックを通った抽出項目。None は「読み取れず」。"""

    invoice_number: str | None
    qualified_invoice_issuer_number: str | None
    issue_date: date | None
    due_date: date | None
    amount_excluding_tax: int | None
    tax_amount: int | None
    amount_including_tax: int | None


def validate(raw: RawExtraction) -> ValidatedExtraction:
    return ValidatedExtraction(
        invoice_number=validate_invoice_number(raw.invoice_number),
        qualified_invoice_issuer_number=validate_registration_number(
            raw.qualified_invoice_issuer_number
        ),
        issue_date=validate_date(raw.issue_date),
        due_date=validate_date(raw.due_date),
        amount_excluding_tax=validate_amount(raw.amount_excluding_tax),
        tax_amount=validate_amount(raw.tax_amount),
        amount_including_tax=validate_amount(raw.amount_including_tax),
    )


def validate_invoice_number(value: str | None) -> str | None:
    """前後の空白を除き、空でなければ通す。"""
    if value is None:
        return None
    value = value.strip()
    return value or None


def validate_registration_number(value: str | None) -> str | None:
    """全角を半角にし、ハイフンと空白を除き、先頭の t を大文字にする。T + 13 桁なら通す。"""
    if value is None:
        return None
    value = unicodedata.normalize("NFKC", value)
    value = "".join(char for char in value if char not in _HYPHENS and not char.isspace())
    if value.startswith("t"):
        value = "T" + value[1:]
    return value if _REGISTRATION_NUMBER.fullmatch(value) else None


def validate_date(value: str | None) -> date | None:
    """前後の空白を除き、YYYY-MM-DD で実在する日付なら通す。"""
    if value is None:
        return None
    value = value.strip()
    if not _DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_amount(value: str | None) -> int | None:
    """全角を半角にし、カンマと空白を除く。整数（負の数も可）なら通す。"""
    if value is None:
        return None
    value = unicodedata.normalize("NFKC", value)
    value = "".join(char for char in value if char != "," and not char.isspace())
    if not _INTEGER.fullmatch(value):
        return None
    amount = int(value)
    return amount if _BIGINT_MIN <= amount <= _BIGINT_MAX else None
