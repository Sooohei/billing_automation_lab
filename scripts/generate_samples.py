"""サンプルデータを作り直す。

    uv run python scripts/generate_samples.py

- sample_data/gmail/: SR-01 のサンプルのメール（.eml）
- sample_data/extraction/: SR-02 のサンプルの読み取り結果（{PDF の SHA-256}.json）

添付する PDF は毎回同じバイト列になるように作る。読み取り結果は PDF の SHA-256 で探すため、
PDF の中身を変えたら、このスクリプトで両方を作り直す。
"""

import hashlib
import json
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

SAMPLE_DATA_DIR = Path(__file__).resolve().parents[1] / "sample_data"
GMAIL_DIR = SAMPLE_DATA_DIR / "gmail"
EXTRACTION_DIR = SAMPLE_DATA_DIR / "extraction"


@dataclass(frozen=True)
class InvoiceContent:
    issuer: str
    invoice_number: str
    registration_number: str
    issue_date: str
    due_date: str
    amount_excluding_tax: int
    tax_amount: int

    @property
    def amount_including_tax(self) -> int:
        return self.amount_excluding_tax + self.tax_amount


def build_pdf(content: InvoiceContent) -> bytes:
    """日本語の標準フォント（埋め込みなし）で、1 ページの請求書の PDF を作る。"""
    lines = [
        (24, "請求書"),
        (12, "株式会社サンプル広告 御中"),
        (12, f"発行元: {content.issuer}"),
        (12, f"登録番号: {content.registration_number}"),
        (12, f"請求書番号: {content.invoice_number}"),
        (12, f"発行日: {content.issue_date}"),
        (12, f"お支払期限: {content.due_date}"),
        (12, "品目: 広告掲載費"),
        (12, f"小計（税抜）: {content.amount_excluding_tax:,} 円"),
        (12, f"消費税（10%）: {content.tax_amount:,} 円"),
        (16, f"ご請求金額（税込）: {content.amount_including_tax:,} 円"),
    ]
    stream_lines = []
    y = 780
    for size, text in lines:
        stream_lines.append(f"BT /F1 {size} Tf 60 {y} Td <{text.encode('utf-16-be').hex()}> Tj ET")
        y -= size + 18
    stream = "\n".join(stream_lines).encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /HeiseiKakuGo-W5 "
        b"/Encoding /UniJIS-UCS2-HW-H /DescendantFonts [6 0 R] >>",
        b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /HeiseiKakuGo-W5 "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Japan1) /Supplement 2 >> "
        # 半角の英数字（CID 231〜325）の幅を半分にする
        b"/FontDescriptor 7 0 R /DW 1000 /W [231 325 500] >>",
        b"<< /Type /FontDescriptor /FontName /HeiseiKakuGo-W5 /Flags 4 "
        b"/FontBBox [-92 -250 1010 922] /ItalicAngle 0 /Ascent 752 /Descent -221 "
        b"/CapHeight 737 /StemV 114 >>",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n".encode()
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    pdf += f"startxref\n{xref_offset}\n%%EOF\n".encode()
    return bytes(pdf)


A_MEDIA_OCTOBER = build_pdf(
    InvoiceContent(
        "株式会社Aメディア",
        "AM-2026-10-001",
        "T1234567890123",
        "2026-10-01",
        "2026-10-31",
        1_000_000,
        100_000,
    )
)


@dataclass(frozen=True)
class SampleAttachment:
    file_name: str
    mime_type: str
    data: bytes
    # SR-02 のサンプルの読み取り結果。None なら JSON を作らない（すべて「読み取れず」になる）
    extraction: dict[str, str | None] | None = None


@dataclass(frozen=True)
class SampleEmail:
    message_id: str
    from_header: str
    subject: str
    date: str
    attachments: list[SampleAttachment]


def pdf(
    file_name: str,
    data: bytes,
    mime_type: str = "application/pdf",
    extraction: dict[str, str | None] | None = None,
) -> SampleAttachment:
    return SampleAttachment(file_name, mime_type, data, extraction)


SAMPLES = [
    # 登録済みの送信元から、PDF 1 件 → 請求書データが 1 件できる
    SampleEmail(
        "sample-01-single-pdf",
        "株式会社Aメディア 請求担当 <billing@a-media.jp>",
        "【株式会社Aメディア】2026年10月分 ご請求書の送付",
        "Mon, 05 Oct 2026 10:00:00 +0900",
        [
            pdf(
                "請求書_AM-2026-10-001.pdf",
                A_MEDIA_OCTOBER,
                # すべての項目がある → すべて「読み取り済」になる
                extraction={
                    "invoice_number": "AM-2026-10-001",
                    "qualified_invoice_issuer_number": "T1234567890123",
                    "issue_date": "2026-10-01",
                    "due_date": "2026-10-31",
                    "amount_excluding_tax": "1000000",
                    "tax_amount": "100000",
                    "amount_including_tax": "1100000",
                },
            )
        ],
    ),
    # 登録済みの送信元から、PDF 2 件 → 請求書データが 2 件できる
    SampleEmail(
        "sample-02-two-pdfs",
        "株式会社Bネットワークス <invoice@b-networks.jp>",
        "2026年10月分 請求書（2 件）",
        "Tue, 06 Oct 2026 09:30:00 +0900",
        [
            pdf(
                "BN-1001.pdf",
                build_pdf(
                    InvoiceContent(
                        "株式会社Bネットワークス",
                        "BN-1001",
                        "T2345678901234",
                        "2026-10-01",
                        "2026-11-30",
                        500_000,
                        50_000,
                    )
                ),
                # 一部の項目が null → その項目だけ「読み取れず」になる
                extraction={
                    "invoice_number": "BN-1001",
                    "qualified_invoice_issuer_number": "T2345678901234",
                    "issue_date": "2026-10-01",
                    "due_date": "2026-11-30",
                    "amount_excluding_tax": None,
                    "tax_amount": None,
                    "amount_including_tax": "550000",
                },
            ),
            pdf(
                "BN-1002.pdf",
                build_pdf(
                    InvoiceContent(
                        "株式会社Bネットワークス",
                        "BN-1002",
                        "T2345678901234",
                        "2026-10-01",
                        "2026-11-30",
                        120_000,
                        12_000,
                    )
                ),
                # 読み取り結果の JSON がない → すべて「読み取れず」になる
            ),
        ],
    ),
    # 種類が application/octet-stream でファイル名が .PDF → PDF として取り込まれる
    SampleEmail(
        "sample-03-octet-stream-pdf",
        "Cアド合同会社 <info@c-ad.jp>",
        "請求書送付のご案内",
        "Wed, 07 Oct 2026 15:00:00 +0900",
        [
            pdf(
                "INVOICE_202610.PDF",
                build_pdf(
                    InvoiceContent(
                        "Cアド合同会社",
                        "C-202610",
                        "T3456789012345",
                        "2026-10-05",
                        "2026-10-31",
                        300_000,
                        30_000,
                    )
                ),
                "application/octet-stream",
                # 登録番号がハイフン付き・全角、金額がカンマ付き → そろえて保存される
                extraction={
                    "invoice_number": "C-202610",
                    "qualified_invoice_issuer_number": "Ｔ３４５６-７８９０-１２３４５",
                    "issue_date": "2026-10-05",
                    "due_date": "2026-10-31",
                    "amount_excluding_tax": "300,000",
                    "tax_amount": "30,000",
                    "amount_including_tax": "330,000",
                },
            )
        ],
    ),
    # PDF 以外の添付だけ → 取り込まれない
    SampleEmail(
        "sample-04-non-pdf-only",
        "株式会社Aメディア 請求担当 <billing@a-media.jp>",
        "2026年10月分 掲載明細",
        "Thu, 08 Oct 2026 11:00:00 +0900",
        [
            SampleAttachment(
                "掲載明細_202610.csv", "text/csv", "媒体,金額\nバナー,1000000\n".encode()
            )
        ],
    ),
    # 登録されていない送信元から、PDF 1 件 → 取り込まれない
    SampleEmail(
        "sample-05-unregistered-sender",
        "不明な送信元 <unknown@example.com>",
        "請求書",
        "Fri, 09 Oct 2026 10:00:00 +0900",
        [
            pdf(
                "invoice.pdf",
                build_pdf(
                    InvoiceContent(
                        "不明な会社",
                        "X-0001",
                        "T9999999999999",
                        "2026-10-01",
                        "2026-10-31",
                        10_000,
                        1_000,
                    )
                ),
            )
        ],
    ),
    # 送信元のアドレスに大文字を含む → 取り込まれる
    SampleEmail(
        "sample-06-uppercase-sender",
        "株式会社Dパブリッシング <Billing@D-Publishing.JP>",
        "ご請求書（2026年10月）",
        "Sat, 10 Oct 2026 08:00:00 +0900",
        [
            pdf(
                "DP_請求書_202610.pdf",
                build_pdf(
                    InvoiceContent(
                        "株式会社Dパブリッシング",
                        "DP-26-0101",
                        "T4567890123456",
                        "2026-10-09",
                        "2026-11-15",
                        800_000,
                        80_000,
                    )
                ),
                # 日付が実在しない、金額が数字でない → その項目が「読み取れず」になる
                extraction={
                    "invoice_number": "DP-26-0101",
                    "qualified_invoice_issuer_number": "T4567890123456",
                    "issue_date": "2026-10-09",
                    "due_date": "2026-02-30",
                    "amount_excluding_tax": "800000",
                    "tax_amount": "80000",
                    "amount_including_tax": "八十八万円",
                },
            )
        ],
    ),
    # 運用開始日（2026-10-01）より前の受信 → 取り込まれない
    SampleEmail(
        "sample-07-before-start-date",
        "株式会社Aメディア 請求担当 <billing@a-media.jp>",
        "【株式会社Aメディア】2026年9月分 ご請求書の送付",
        "Wed, 30 Sep 2026 23:30:00 +0900",
        [
            pdf(
                "請求書_AM-2026-09-001.pdf",
                build_pdf(
                    InvoiceContent(
                        "株式会社Aメディア",
                        "AM-2026-09-001",
                        "T1234567890123",
                        "2026-09-01",
                        "2026-09-30",
                        900_000,
                        90_000,
                    )
                ),
            )
        ],
    ),
    # 他のメール（sample-01）と同じ中身の PDF → 請求書データができない
    SampleEmail(
        "sample-08-duplicate-pdf",
        "株式会社Aメディア 請求担当 <billing@a-media.jp>",
        "【再送】【株式会社Aメディア】2026年10月分 ご請求書の送付",
        "Mon, 12 Oct 2026 10:00:00 +0900",
        [pdf("請求書_AM-2026-10-001（再送）.pdf", A_MEDIA_OCTOBER)],
    ),
]


def build_email(sample: SampleEmail) -> bytes:
    message = EmailMessage()
    message["From"] = sample.from_header
    message["To"] = "invoices@example.com"
    message["Subject"] = sample.subject
    message["Date"] = sample.date
    message["Message-ID"] = f"<{sample.message_id}@example.com>"
    message.set_content("請求書を添付いたします。ご確認のほどよろしくお願いいたします。\n")
    for attachment in sample.attachments:
        maintype, subtype = attachment.mime_type.split("/")
        message.add_attachment(
            attachment.data, maintype=maintype, subtype=subtype, filename=attachment.file_name
        )
    # 毎回同じ内容になるように、区切り文字を固定する
    message.set_boundary(f"sample-boundary-{sample.message_id}")
    return message.as_bytes()


def main() -> None:
    GMAIL_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACTION_DIR.mkdir(parents=True, exist_ok=True)
    for old in [*GMAIL_DIR.glob("*.eml"), *EXTRACTION_DIR.glob("*.json")]:
        old.unlink()

    for sample in SAMPLES:
        (GMAIL_DIR / f"{sample.message_id}.eml").write_bytes(build_email(sample))
        print(f"gmail/{sample.message_id}.eml")
        for attachment in sample.attachments:
            if attachment.extraction is None:
                continue
            sha256 = hashlib.sha256(attachment.data).hexdigest()
            content = json.dumps(attachment.extraction, ensure_ascii=False, indent=2) + "\n"
            (EXTRACTION_DIR / f"{sha256}.json").write_text(content, encoding="utf-8")
            print(f"extraction/{sha256}.json（{attachment.file_name}）")


if __name__ == "__main__":
    main()
