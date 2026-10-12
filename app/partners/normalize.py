def normalize_partner_name(name: str) -> str:
    """前後の空白（全角空白を含む）を除く。全角・半角の変換はしない。"""
    return name.strip()


def normalize_email(email: str) -> str:
    """前後の空白を除いて、小文字にする。"""
    return email.strip().lower()
