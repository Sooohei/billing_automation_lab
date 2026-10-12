import email
import email.policy
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

DEFAULT_SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data" / "gmail"


@dataclass(frozen=True)
class Attachment:
    file_name: str
    mime_type: str
    data: bytes


@dataclass(frozen=True)
class GmailMessage:
    message_id: str
    from_header: str
    subject: str
    received_at: datetime
    attachments: list[Attachment]


class GmailClient:
    """Gmail とのやり取り。

    第 1 段階: sample_data/gmail/ の .eml ファイルをメールとして返す（現在の実装）。
    第 2 段階: Gmail API で実際の Gmail に接続する形に置き換える。メソッドの形は変えない。
    """

    def __init__(self, sample_dir: Path = DEFAULT_SAMPLE_DIR) -> None:
        self._sample_dir = sample_dir

    def list_message_ids(self, received_after: datetime, senders: list[str]) -> list[str]:
        """取込対象の候補のメールの ID。第 1 段階では絞り込まず、すべてのメールを返す。

        取込対象かどうかの最終的な判定は、取込処理が行う。
        """
        return sorted(path.stem for path in self._sample_dir.glob("*.eml"))

    def get_message(self, message_id: str) -> GmailMessage:
        path = self._sample_dir / f"{message_id}.eml"
        if path.parent != self._sample_dir or not path.is_file():
            raise ValueError(f"メールがありません: {message_id}")

        with path.open("rb") as f:
            message = email.message_from_binary_file(f, policy=email.policy.default)
        assert isinstance(message, EmailMessage)

        return GmailMessage(
            message_id=message_id,
            from_header=str(message.get("From", "")),
            subject=str(message.get("Subject", "")),
            received_at=parsedate_to_datetime(str(message["Date"])),
            attachments=_attachments(message),
        )


def _attachments(message: EmailMessage) -> list[Attachment]:
    """MIME パートを入れ子までたどり、ファイル名があるパートをすべて集める。"""
    attachments = []
    for part in message.walk():
        file_name = part.get_filename()
        if file_name is None:
            continue
        data = part.get_payload(decode=True)
        attachments.append(
            Attachment(
                file_name=file_name,
                mime_type=part.get_content_type(),
                data=data if isinstance(data, bytes) else b"",
            )
        )
    return attachments
