from typing import Protocol


class FileStorage(Protocol):
    """ファイルの保存先。請求書データの保持の要件のため、削除のメソッドは設けない。"""

    def save(self, key: str, data: bytes) -> None:
        """key（保存先のパス）にファイルを保存する。同じ key があれば上書きする。"""
        ...

    def load(self, key: str) -> bytes:
        """key のファイルを読み出す。"""
        ...
