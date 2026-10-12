from pathlib import Path

import pytest

from app.config import Settings
from app.storage.dependencies import create_file_storage
from app.storage.local import LocalFileStorage


def test_保存したファイルを読み出せる(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)

    storage.save("invoices/abc.pdf", b"%PDF-1")

    assert storage.load("invoices/abc.pdf") == b"%PDF-1"
    assert (tmp_path / "invoices" / "abc.pdf").read_bytes() == b"%PDF-1"


def test_同じ保存先に保存すると上書きする(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    storage.save("invoices/abc.pdf", b"old")

    storage.save("invoices/abc.pdf", b"new")

    assert storage.load("invoices/abc.pdf") == b"new"
    assert [path.name for path in (tmp_path / "invoices").iterdir()] == ["abc.pdf"]


@pytest.mark.parametrize("key", ["", "/etc/passwd", "../outside.pdf", "invoices/../../x.pdf"])
def test_フォルダの外を指す保存先は拒否する(tmp_path: Path, key: str) -> None:
    storage = LocalFileStorage(tmp_path)

    with pytest.raises(ValueError):
        storage.save(key, b"data")
    with pytest.raises(ValueError):
        storage.load(key)


def test_STORAGE_BACKENDがlocalならLocalFileStorageを使う(tmp_path: Path) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://x", app_origin="http://x", local_storage_dir=tmp_path
    )

    storage = create_file_storage(settings)

    assert isinstance(storage, LocalFileStorage)
