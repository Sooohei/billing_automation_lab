from datetime import date, datetime

from app.auth import CurrentUser
from app.extraction.extractor import InvoiceExtractor, RawExtraction
from app.freee.client import ApprovalRequest, FreeeError, FreeeOption, PaymentRequestParams
from app.gmail.client import GmailClient, GmailMessage


class FakeFreeeClient:
    """テスト用の FreeeClient。"""

    def __init__(self) -> None:
        self.approval_requests = [
            ApprovalRequest(
                5001, "A-0001", "2026年10月 媒体費 Aメディア", 1_100_000, date(2026, 9, 20)
            ),
            ApprovalRequest(
                5002, "A-0002", "2026年10月 媒体費 Bネット", 682_000, date(2026, 9, 21)
            ),
        ]
        # 各メソッドで起こすエラー
        self.list_approval_requests_error: FreeeError | None = None
        self.upload_receipt_error: FreeeError | None = None
        self.create_payment_request_error: FreeeError | None = None
        # 呼び出しの記録
        self.uploaded: list[tuple[CurrentUser, bytes, str]] = []
        self.created: list[tuple[CurrentUser, PaymentRequestParams]] = []

    def list_partners(self) -> list[FreeeOption]:
        return [FreeeOption(101, "株式会社Aメディア"), FreeeOption(102, "株式会社Bネットワークス")]

    def list_account_items(self) -> list[FreeeOption]:
        return [FreeeOption(201, "広告宣伝費"), FreeeOption(202, "販売促進費")]

    def list_taxes(self) -> list[FreeeOption]:
        return [FreeeOption(136, "課対仕入10%"), FreeeOption(2, "対象外")]

    def list_approval_flow_routes(self) -> list[FreeeOption]:
        return [FreeeOption(301, "媒体費（部長承認）"), FreeeOption(302, "媒体費（役員承認）")]

    def list_approval_requests(self, user: CurrentUser) -> list[ApprovalRequest]:
        if self.list_approval_requests_error is not None:
            raise self.list_approval_requests_error
        return self.approval_requests

    def upload_receipt(self, user: CurrentUser, pdf: bytes, file_name: str) -> int:
        if self.upload_receipt_error is not None:
            raise self.upload_receipt_error
        self.uploaded.append((user, pdf, file_name))
        return 7000 + len(self.uploaded)

    def create_payment_request(self, user: CurrentUser, params: PaymentRequestParams) -> int:
        if self.create_payment_request_error is not None:
            raise self.create_payment_request_error
        self.created.append((user, params))
        return 9000 + len(self.created)


class FakeGmailClient(GmailClient):
    """テスト用の GmailClient。テストごとに渡したメールを返す。"""

    def __init__(self, messages: list[GmailMessage]) -> None:
        self.messages = {message.message_id: message for message in messages}
        # メールの ID ごとに、get_message で起こすエラー
        self.errors: dict[str, Exception] = {}
        self.list_error: Exception | None = None
        self.fetched_ids: list[str] = []

    def list_message_ids(self, received_after: datetime, senders: list[str]) -> list[str]:
        if self.list_error is not None:
            raise self.list_error
        return list(self.messages)

    def get_message(self, message_id: str) -> GmailMessage:
        self.fetched_ids.append(message_id)
        if message_id in self.errors:
            raise self.errors.pop(message_id)
        return self.messages[message_id]


class FakeInvoiceExtractor(InvoiceExtractor):
    """テスト用の InvoiceExtractor。PDF の中身ごとに渡した読み取り結果を返す。"""

    def __init__(self, results: dict[bytes, RawExtraction] | None = None) -> None:
        self.results = results or {}
        # PDF の中身ごとに、extract で起こすエラー
        self.errors: dict[bytes, Exception] = {}

    def extract(self, pdf: bytes, file_name: str) -> RawExtraction:
        if pdf in self.errors:
            raise self.errors.pop(pdf)
        return self.results.get(pdf, RawExtraction())
