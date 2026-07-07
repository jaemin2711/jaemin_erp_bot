from bot_config import *


def is_allowed_user(user_id: int) -> bool:
    """
    .env의 ALLOWED_USER_IDS로 사용자를 제한합니다.

    ALLOWED_USER_IDS가 비어 있으면 기본 차단합니다.
    예:
    ALLOWED_USER_IDS=
    ALLOWED_USER_IDS=123456789
    ALLOWED_USER_IDS=123456789,987654321
    """
    if not ALLOWED_USER_IDS.strip():
        return False

    allowed = [x.strip() for x in ALLOWED_USER_IDS.split(",") if x.strip()]
    return str(user_id) in allowed


def is_admin_user(user_id: int) -> bool:
    """
    OCR 기억값 관리 같은 위험한 기능은 관리자만 사용합니다.
    .env에 ADMIN_USER_IDS=123456789,987654321 형식으로 넣으세요.
    """
    admin_raw = os.getenv("ADMIN_USER_IDS", "").strip()

    if not admin_raw:
        return False

    admins = [x.strip() for x in admin_raw.split(",") if x.strip()]
    return str(user_id) in admins
