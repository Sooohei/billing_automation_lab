import hashlib
import json
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data" / "extraction"


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


class InvoiceExtractor:
    """請求書ファイルからの抽出項目の読み取り。sample_data/extraction/{PDF の SHA-256}.json を返す。

    Gemini で読み取る場合は、このクラスの中身を置き換える（メソッドの形は変えない）。
    """

    def __init__(self, sample_dir: Path = DEFAULT_SAMPLE_DIR) -> None:
        self._sample_dir = sample_dir

    def extract(self, pdf: bytes, file_name: str) -> RawExtraction:
        """読み取れなかった項目は None にする。

        別々の請求書が同じファイル名で届くことがあるため、ファイル名ではなく中身の SHA-256 で探す。
        サンプルがなければ、すべての項目を None で返す。
        """
        path = self._sample_dir / f"{hashlib.sha256(pdf).hexdigest()}.json"
        if not path.is_file():
            return RawExtraction()

        with path.open(encoding="utf-8") as f:
            values = json.load(f)
        return RawExtraction(
            **{
                field.name: None if values.get(field.name) is None else str(values[field.name])
                for field in fields(RawExtraction)
            }
        )
