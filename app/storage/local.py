import os
import tempfile
from pathlib import Path, PurePosixPath


class LocalFileStorage:
    """ローカルのフォルダに保存する。"""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 途中で失敗しても書きかけのファイルが残らないよう、一時ファイルに書いてから置き換える
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
            f.write(data)
        os.replace(f.name, path)

    def load(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def _path(self, key: str) -> Path:
        parts = PurePosixPath(key).parts
        if not parts or key.startswith("/") or ".." in parts:
            raise ValueError(f"保存先のパスが正しくありません: {key}")
        return self._base_dir.joinpath(*parts)
