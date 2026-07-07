import re
from datetime import datetime


def parse_production_date(question: str):
    """
    질문에서 생산일을 YYYY-MM-DD 형태로 추출한다.

    지원:
    - 6월 8일
    - 2026년 6월 8일
    - 2026-06-08
    - 06/08
    """
    q = str(question).strip()
    now = datetime.now()

    # 2026-06-08
    m = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", q)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"

    # 2026년 6월 8일
    m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", q)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"

    # 6월 8일
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", q)
    if m:
        year = now.year
        month = int(m.group(1))
        day = int(m.group(2))
        return f"{year:04d}-{month:02d}-{day:02d}"

    # 06/08
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", q)
    if m:
        year = now.year
        month = int(m.group(1))
        day = int(m.group(2))
        return f"{year:04d}-{month:02d}-{day:02d}"

    return None


def remove_date_text(question: str):
    """
    ai_parser가 날짜를 제품명으로 착각하지 않도록 질문에서 날짜 표현 제거.
    """
    q = str(question)

    q = re.sub(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", " ", q)
    q = re.sub(r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일", " ", q)
    q = re.sub(r"\d{1,2}월\s*\d{1,2}일", " ", q)
    q = re.sub(r"\b\d{1,2}/\d{1,2}\b", " ", q)

    q = re.sub(r"\s+", " ", q).strip()

    return q