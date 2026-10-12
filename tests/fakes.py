from app.freee.client import FreeeOption


class FakeFreeeClient:
    """テスト用の FreeeClient。"""

    def list_partners(self) -> list[FreeeOption]:
        return [FreeeOption(101, "株式会社Aメディア"), FreeeOption(102, "株式会社Bネットワークス")]

    def list_account_items(self) -> list[FreeeOption]:
        return [FreeeOption(201, "広告宣伝費"), FreeeOption(202, "販売促進費")]

    def list_taxes(self) -> list[FreeeOption]:
        return [FreeeOption(136, "課対仕入10%"), FreeeOption(2, "対象外")]

    def list_approval_flow_routes(self) -> list[FreeeOption]:
        return [FreeeOption(301, "媒体費（部長承認）"), FreeeOption(302, "媒体費（役員承認）")]
