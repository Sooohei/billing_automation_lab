from app.freee.client import FreeeClient
from app.freee.sample_client import SampleFreeeClient


def get_freee_client() -> FreeeClient:
    """画面で使う FreeeClient（FastAPI の依存関係）。テストでは偽物に差し替える。"""
    return SampleFreeeClient()
