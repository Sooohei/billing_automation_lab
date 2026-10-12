import json
from pathlib import Path

from app.freee.client import FreeeOption

DEFAULT_SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data" / "freee"


class SampleFreeeClient:
    """freee と通信せず、sample_data/freee/ の JSON を返す。"""

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

    def _load_options(self, file_name: str) -> list[FreeeOption]:
        with (self._sample_dir / file_name).open(encoding="utf-8") as f:
            items = json.load(f)
        return [FreeeOption(id=int(item["id"]), name=str(item["name"])) for item in items]
