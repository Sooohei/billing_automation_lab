from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

import pytest

from app.gmail.client import Attachment, GmailClient


def write_eml(directory: Path, message_id: str, message: EmailMessage) -> None:
    (directory / f"{message_id}.eml").write_bytes(message.as_bytes())


def make_message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "請求担当 <Billing@A-Media.jp>"
    message["Subject"] = "10月分のご請求"
    message["Date"] = "Mon, 05 Oct 2026 10:00:00 +0900"
    message.set_content("本文")
    return message


def test_emlファイルのファイル名をメールのIDとしてすべて返す(tmp_path: Path) -> None:
    write_eml(tmp_path, "b", make_message())
    write_eml(tmp_path, "a", make_message())
    (tmp_path / "memo.txt").write_text("対象外")

    ids = GmailClient(tmp_path).list_message_ids(datetime(2026, 10, 1, tzinfo=UTC), [])

    assert ids == ["a", "b"]


def test_メールの項目と添付ファイルを返す(tmp_path: Path) -> None:
    message = make_message()
    message.add_attachment(
        b"%PDF-1.4", maintype="application", subtype="pdf", filename="請求書_10月.pdf"
    )
    message.add_attachment(b"a,b", maintype="text", subtype="csv", filename="明細.csv")
    write_eml(tmp_path, "msg-1", message)

    gmail_message = GmailClient(tmp_path).get_message("msg-1")

    assert gmail_message.message_id == "msg-1"
    assert gmail_message.from_header == "請求担当 <Billing@A-Media.jp>"
    assert gmail_message.subject == "10月分のご請求"
    assert gmail_message.received_at == datetime(2026, 10, 5, 1, 0, tzinfo=UTC)
    assert gmail_message.attachments == [
        Attachment("請求書_10月.pdf", "application/pdf", b"%PDF-1.4"),
        Attachment("明細.csv", "text/csv", b"a,b"),
    ]


def test_入れ子のMIMEパートの添付ファイルも集める(tmp_path: Path) -> None:
    inner = EmailMessage()
    inner.set_content("転送された本文")
    inner.add_attachment(b"%PDF-inner", maintype="application", subtype="pdf", filename="in.pdf")
    message = make_message()
    message.add_attachment(inner)
    write_eml(tmp_path, "msg-1", message)

    gmail_message = GmailClient(tmp_path).get_message("msg-1")

    assert [a.file_name for a in gmail_message.attachments] == ["in.pdf"]


def test_件名がなければ空文字を返す(tmp_path: Path) -> None:
    message = make_message()
    del message["Subject"]
    write_eml(tmp_path, "msg-1", message)

    assert GmailClient(tmp_path).get_message("msg-1").subject == ""


@pytest.mark.parametrize("message_id", ["no-such-message", "../outside"])
def test_存在しないメールは取得できない(tmp_path: Path, message_id: str) -> None:
    with pytest.raises(ValueError):
        GmailClient(tmp_path).get_message(message_id)


def test_リポジトリのサンプルのメールを読み込める() -> None:
    client = GmailClient()

    ids = client.list_message_ids(datetime(2026, 10, 1, tzinfo=UTC), [])

    assert len(ids) == 8
    for message_id in ids:
        assert client.get_message(message_id).attachments
