from sqlalchemy import text
from sqlalchemy.orm import Session


def test_テスト用のDBに接続できる(session: Session) -> None:
    database = session.execute(text("SELECT current_database()")).scalar_one()
    assert database == "billing_test"
