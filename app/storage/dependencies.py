from app.config import Settings, get_settings
from app.storage.local import LocalFileStorage
from app.storage.storage import FileStorage


def create_file_storage(settings: Settings) -> FileStorage:
    """STORAGE_BACKEND に応じた FileStorage を作る。"""
    if settings.storage_backend == "local":
        return LocalFileStorage(settings.local_storage_dir)
    # GcsFileStorage は、Google Cloud にデプロイする場合の想定。本リポジトリでは実装しない
    raise RuntimeError(f"STORAGE_BACKEND={settings.storage_backend} は未実装です")


def get_file_storage() -> FileStorage:
    """画面で使う FileStorage（FastAPI の依存関係）。テストでは一時フォルダのものに差し替える。"""
    return create_file_storage(get_settings())
