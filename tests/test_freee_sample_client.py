import json
from pathlib import Path

from app.freee.client import FreeeOption
from app.freee.sample_client import SampleFreeeClient


def test_サンプルデータの選択肢を返す(tmp_path: Path) -> None:
    for file_name, items in {
        "partners.json": [{"id": 101, "name": "株式会社Aメディア"}],
        "account_items.json": [{"id": 201, "name": "広告宣伝費"}],
        "taxes.json": [{"id": 136, "name": "課対仕入10%"}],
        "approval_flow_routes.json": [{"id": 301, "name": "媒体費（部長承認）"}],
    }.items():
        (tmp_path / file_name).write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")

    client = SampleFreeeClient(tmp_path)

    assert client.list_partners() == [FreeeOption(id=101, name="株式会社Aメディア")]
    assert client.list_account_items() == [FreeeOption(id=201, name="広告宣伝費")]
    assert client.list_taxes() == [FreeeOption(id=136, name="課対仕入10%")]
    assert client.list_approval_flow_routes() == [FreeeOption(id=301, name="媒体費（部長承認）")]


def test_リポジトリのサンプルデータを読み込める() -> None:
    client = SampleFreeeClient()

    for options in [
        client.list_partners(),
        client.list_account_items(),
        client.list_taxes(),
        client.list_approval_flow_routes(),
    ]:
        assert options
        assert len({option.id for option in options}) == len(options)
