from dataclasses import dataclass


@dataclass(frozen=True)
class RawExtraction:
    """請求書ファイルから読み取った抽出項目。形式チェック前の値で、読み取れなかった項目は None。"""

    invoice_number: str | None = None
    qualified_invoice_issuer_number: str | None = None
    issue_date: str | None = None
    due_date: str | None = None
    amount_excluding_tax: str | None = None
    tax_amount: str | None = None
    amount_including_tax: str | None = None
