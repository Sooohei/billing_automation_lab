import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.extraction.extractor import InvoiceExtractor, RawExtraction
from app.extraction.validation import validate
from app.gmail.client import GmailClient


def write_sample(directory: Path, pdf: bytes, values: dict[str, object]) -> None:
    path = directory / f"{hashlib.sha256(pdf).hexdigest()}.json"
    path.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")


def test_PDFのSHA256に対応するサンプルを返す(tmp_path: Path) -> None:
    write_sample(
        tmp_path,
        b"%PDF-A",
        {
            "invoice_number": "INV-2026-0001",
            "qualified_invoice_issuer_number": "T1234567890123",
            "issue_date": "2026-10-01",
            "due_date": "2026-10-31",
            "amount_excluding_tax": "100000",
            "tax_amount": "10000",
            "amount_including_tax": "110000",
        },
    )

    raw = InvoiceExtractor(tmp_path).extract(b"%PDF-A", "請求書.pdf")

    assert raw == RawExtraction(
        invoice_number="INV-2026-0001",
        qualified_invoice_issuer_number="T1234567890123",
        issue_date="2026-10-01",
        due_date="2026-10-31",
        amount_excluding_tax="100000",
        tax_amount="10000",
        amount_including_tax="110000",
    )


def test_ファイル名ではなく中身で探す(tmp_path: Path) -> None:
    write_sample(tmp_path, b"%PDF-A", {"invoice_number": "A"})
    write_sample(tmp_path, b"%PDF-B", {"invoice_number": "B"})
    extractor = InvoiceExtractor(tmp_path)

    assert extractor.extract(b"%PDF-A", "請求書.pdf").invoice_number == "A"
    assert extractor.extract(b"%PDF-B", "請求書.pdf").invoice_number == "B"


def test_nullとない項目はNoneで数値は文字列にする(tmp_path: Path) -> None:
    write_sample(tmp_path, b"%PDF-A", {"invoice_number": None, "tax_amount": 10000})

    raw = InvoiceExtractor(tmp_path).extract(b"%PDF-A", "請求書.pdf")

    assert raw == RawExtraction(tax_amount="10000")


def test_サンプルがなければすべての項目をNoneにする(tmp_path: Path) -> None:
    assert InvoiceExtractor(tmp_path).extract(b"%PDF-X", "請求書.pdf") == RawExtraction()


def test_リポジトリのサンプルで設計書の表の場合を確かめられる() -> None:
    client = GmailClient()
    pdfs = {
        attachment.file_name: attachment.data
        for message_id in client.list_message_ids(datetime(2026, 10, 1, tzinfo=UTC), [])
        for attachment in client.get_message(message_id).attachments
    }
    extractor = InvoiceExtractor()

    def validated(file_name: str) -> dict[str, object]:
        return vars(validate(extractor.extract(pdfs[file_name], file_name)))

    # すべての項目がある
    assert None not in validated("請求書_AM-2026-10-001.pdf").values()
    # 一部の項目が null
    partial = validated("BN-1001.pdf")
    assert partial["amount_excluding_tax"] is None
    assert partial["tax_amount"] is None
    assert partial["amount_including_tax"] == 550_000
    # 登録番号がハイフン付き・全角
    assert validated("INVOICE_202610.PDF")["qualified_invoice_issuer_number"] == "T3456789012345"
    # 日付が実在しない、金額が数字でない
    invalid = validated("DP_請求書_202610.pdf")
    assert invalid["due_date"] is None
    assert invalid["amount_including_tax"] is None
    assert invalid["issue_date"] is not None
    # JSON ファイルがない
    assert set(validated("BN-1002.pdf").values()) == {None}
