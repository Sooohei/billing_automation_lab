import json
import secrets
from datetime import date
from pathlib import Path
from typing import Any

from app.auth import CurrentUser
from app.freee.client import ApprovalRequest, FreeeOption, PaymentRequestParams

DEFAULT_SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data" / "freee"

# 事前申請から作成した経費精算・支払い依頼・各種申請の上限（この件数に達したら紐付けできない）
MAX_CHILD_REQUESTS = 15


class SampleFreeeClient:
    """freee と通信せず、sample_data/freee/ の JSON を返す。申請は常に成功する。"""

    def __init__(self, sample_dir: Path = DEFAULT_SAMPLE_DIR) -> None:
        self._sample_dir = sample_dir

    def list_partners(self) -> list[FreeeOption]:
        return self._load_options("partners.json")

    def list_account_items(self) -> list[FreeeOption]:
        return self._load_options("account_items.json")

    def list_taxes(self) -> list[FreeeOption]:
        return self._load_options("taxes.json")

    def list_approval_flow_routes(self) -> list[FreeeOption]:
        return self._load_options("approval_flow_routes.json")

    def list_approval_requests(self, user: CurrentUser) -> list[ApprovalRequest]:
        """取得条件で絞り込む。利用者による違いはない。"""
        return [
            ApprovalRequest(
                id=int(item["id"]),
                application_number=str(item["application_number"]),
                title=str(item["title"]),
                amount=int(item["amount"]),
                application_date=date.fromisoformat(item["application_date"]),
            )
            for item in self._load("approval_requests.json")
            if _is_linkable(item)
        ]

    def upload_receipt(self, user: CurrentUser, pdf: bytes, file_name: str) -> int:
        # 何も保存せず、新しい識別子を返す
        return _new_id()

    def create_payment_request(self, user: CurrentUser, params: PaymentRequestParams) -> int:
        # 何も保存せず、新しい識別子を返す。事前申請の child_request_count も増やさない
        return _new_id()

    def _load_options(self, file_name: str) -> list[FreeeOption]:
        return [
            FreeeOption(id=int(item["id"]), name=str(item["name"]))
            for item in self._load(file_name)
        ]

    def _load(self, file_name: str) -> list[dict[str, Any]]:
        with (self._sample_dir / file_name).open(encoding="utf-8") as f:
            items: list[dict[str, Any]] = json.load(f)
        return items


def _is_linkable(item: dict[str, Any]) -> bool:
    """SR-03 の要件 1 の取得条件。"""
    return (
        item["status"] == "approved"
        and "媒体費" in item["title"]
        and not item["deal_created"]
        and not item["manual_journal_created"]
        and item["child_request_count"] < MAX_CHILD_REQUESTS
    )


def _new_id() -> int:
    return secrets.randbelow(900_000_000) + 100_000_000
