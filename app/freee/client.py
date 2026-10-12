from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.auth import CurrentUser


@dataclass(frozen=True)
class FreeeOption:
    """freee の選択肢 1 件。税区分は freee 上の code を id に入れる。"""

    id: int
    name: str


@dataclass(frozen=True)
class ApprovalRequest:
    """紐付けできる事前申請（freee の各種申請）。"""

    id: int
    application_number: str
    title: str
    amount: int
    application_date: date


@dataclass(frozen=True)
class PaymentRequestParams:
    """freee の支払依頼として送る項目。"""

    title: str
    partner_id: int
    document_code: str | None
    issue_date: date
    payment_date: date
    amount: int
    account_item_id: int
    tax_code: int
    approval_flow_route_id: int
    parent_id: int
    receipt_ids: list[int]


class FreeeError(Exception):
    """freee とのやり取りの失敗。"""


class FreeeApiError(FreeeError):
    """freee がエラーを返した。メッセージは freee が返したエラー内容。"""


class FreeeNoResponseError(FreeeError):
    """freee から応答を受け取れなかった（タイムアウト、接続失敗）。"""


class FreeeClient(Protocol):
    """freee とのやり取り。本リポジトリでは SampleFreeeClient だけを実装する。"""

    def list_partners(self) -> list[FreeeOption]:
        """freee 上の取引先の一覧。"""
        ...

    def list_account_items(self) -> list[FreeeOption]:
        """勘定科目の一覧。"""
        ...

    def list_taxes(self) -> list[FreeeOption]:
        """税区分の一覧。"""
        ...

    def list_approval_flow_routes(self) -> list[FreeeOption]:
        """承認経路（申請経路）の一覧。"""
        ...

    def list_approval_requests(self, user: CurrentUser) -> list[ApprovalRequest]:
        """利用者が閲覧できる事前申請のうち、SR-03 の要件 1 の取得条件をすべて満たすもの。

        取得に失敗したら FreeeError を送出する。
        """
        ...

    def upload_receipt(self, user: CurrentUser, pdf: bytes, file_name: str) -> int:
        """請求書ファイルを freee のファイルボックスにアップロードし、その識別子を返す。"""
        ...

    def create_payment_request(self, user: CurrentUser, params: PaymentRequestParams) -> int:
        """支払依頼を申請中で作成し、その識別子を返す。"""
        ...
