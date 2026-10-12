from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FreeeOption:
    """freee の選択肢 1 件。税区分は freee 上の code を id に入れる。"""

    id: int
    name: str


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
