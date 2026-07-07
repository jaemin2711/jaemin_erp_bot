from __future__ import annotations

import os
import re
from datetime import datetime, date
from pathlib import Path

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from inventory_engine import build_result

try:
    from inventory_engine import fmt_num
except ImportError:
    def fmt_num(value):
        try:
            num = float(value)
        except Exception:
            return str(value)
        if abs(num - int(num)) < 0.000001:
            return f"{int(num):,}"
        return f"{num:,.2f}".rstrip("0").rstrip(".")


DATA_DIR = Path("data")
RESERVED_PLAN_FILE = DATA_DIR / "reserved_production_plan.xlsx"


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_reserved_plan_user_ids() -> set[str]:
    raw = os.getenv("RESERVED_PLAN_USER_IDS", "").strip()
    if not raw:
        return set()
    return {x.strip() for x in raw.split(",") if x.strip()}


def is_reserved_plan_user(user_id) -> bool:
    return str(user_id) in get_reserved_plan_user_ids()


def normalize_text(value) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", text)


def parse_date_text(text: str) -> str | None:
    raw = str(text or "").strip()
    today = datetime.now().date()

    if "오늘" in raw:
        return today.strftime("%Y-%m-%d")
    if "내일" in raw:
        return date.fromordinal(today.toordinal() + 1).strftime("%Y-%m-%d")
    if "모레" in raw:
        return date.fromordinal(today.toordinal() + 2).strftime("%Y-%m-%d")

    patterns = [
        (r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", True),
        (r"(\d{1,2})[-./](\d{1,2})", False),
        (r"(?:(\d{4})년)?\s*(\d{1,2})월\s*(\d{1,2})일?", "korean"),
    ]

    for pattern, mode in patterns:
        m = re.search(pattern, raw)
        if not m:
            continue
        try:
            if mode is True:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif mode is False:
                y, mo, d = today.year, int(m.group(1)), int(m.group(2))
            else:
                y = int(m.group(1)) if m.group(1) else today.year
                mo, d = int(m.group(2)), int(m.group(3))
            return date(y, mo, d).strftime("%Y-%m-%d")
        except Exception:
            return None

    return None


def parse_quantity_kg(text: str) -> float | None:
    raw = str(text or "").lower().replace(",", "")
    matches = list(re.finditer(r"(\d+(?:\.\d+)?)\s*(톤|t|kg|키로|킬로)", raw, flags=re.IGNORECASE))
    if not matches:
        return None

    m = matches[-1]
    qty = float(m.group(1))
    unit = m.group(2).lower()
    if unit in ["톤", "t"]:
        qty *= 1000
    return qty


def has_register_intent(text: str) -> bool:
    compact = str(text or "").replace(" ", "").lower()
    return (
        "등록" in compact
        or "저장" in compact
        or "정정" in compact
        or "수정" in compact
        or "변경" in compact
    )


def is_reserved_plan_explicit_text(text: str) -> bool:
    compact = str(text or "").replace(" ", "").lower()
    return (
        compact.startswith("/reserveplan")
        or compact.startswith("/reservedplan")
        or compact.startswith("/reservedplans")
        or compact.startswith("/reserveactual")
        or compact.startswith("/reservedactual")
        or compact.startswith("/reserveddelete")
        or compact.startswith("/reservedel")
        or "예약등록" in compact
        or "가예약" in compact
        or "예정등록" in compact
        or "계획예약" in compact
    )


def is_reserved_register_text(text: str, user_id=None) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False

    has_date = parse_date_text(raw) is not None
    has_qty = parse_quantity_kg(raw) is not None

    # 목록/삭제/전환 명령은 번호만 있어도 reserved_plan_command로 보내야 함
    if is_reserved_plan_explicit_text(raw) and (
        raw.replace(" ", "").lower().startswith("/reservedplans")
        or raw.replace(" ", "").lower().startswith("/reservedel")
        or raw.replace(" ", "").lower().startswith("/reserveddelete")
        or raw.replace(" ", "").lower().startswith("/reserveactual")
        or raw.replace(" ", "").lower().startswith("/reservedactual")
    ):
        return True

    if not has_date or not has_qty:
        return False

    if is_reserved_plan_explicit_text(raw):
        return True

    if user_id is not None and is_reserved_plan_user(user_id) and has_register_intent(raw):
        return True

    return False


def parse_reserved_plan_text(text: str):
    raw = str(text or "").strip()
    production_date = parse_date_text(raw)
    qty_kg = parse_quantity_kg(raw)

    if not production_date:
        return None, None, None, "생산일을 인식하지 못했습니다. 예: 6/26 제품명 1톤 등록"
    if qty_kg is None or qty_kg <= 0:
        return None, None, None, "수량을 인식하지 못했습니다. 예: 6/26 제품명 1톤 등록"

    product_part = raw
    product_part = re.sub(r"^/(reserveplan|reservedplan|계획예약|예약등록)\s*", " ", product_part, flags=re.IGNORECASE)

    date_patterns = [
        r"\d{4}[-./]\d{1,2}[-./]\d{1,2}",
        r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일?",
        r"\d{1,2}\s*월\s*\d{1,2}\s*일?",
        r"\b\d{1,2}\s*/\s*\d{1,2}\b",
        r"\b\d{1,2}\s*-\s*\d{1,2}\b",
        r"오늘|내일|모레",
    ]

    for pattern in date_patterns:
        product_part = re.sub(pattern, " ", product_part)

    product_part = re.sub(
        r"(\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(톤|t|kg|키로|킬로)\s*(에서|으로|로|을|를)?",
        " ",
        product_part,
        flags=re.IGNORECASE,
    )

    cleanup_patterns = [
        r"생산계획", r"생산등록", r"생산", r"계획",
        r"예약등록", r"예약", r"가예약", r"예정등록", r"계획예약",
        r"등록", r"저장", r"정정", r"수정", r"변경",
        r"해주세요", r"해줘", r"으로", r"로", r"에서",
    ]

    for pattern in cleanup_patterns:
        product_part = re.sub(pattern, " ", product_part, flags=re.IGNORECASE)

    product_part = re.sub(r"\s+", " ", product_part).strip(" ,/-_?:：")

    if not product_part:
        return None, None, None, "제품명을 인식하지 못했습니다. 예: 6/26 제품명 1톤 등록"

    return production_date, product_part, qty_kg, None


def resolve_product(product_text: str):
    product_text = str(product_text or "").strip()
    try:
        result = build_result(product_text, 1, extra_consumption={})
    except TypeError:
        try:
            result = build_result(product_text, 1)
        except Exception as e:
            return "", "", f"제품 조회 중 오류가 발생했습니다: {str(e)}"
    except Exception as e:
        return "", "", f"제품 조회 중 오류가 발생했습니다: {str(e)}"

    if not isinstance(result, dict) or not result.get("found"):
        return "", "", f"제품을 찾지 못했습니다: {product_text}"

    return str(result.get("제품코드") or ""), str(result.get("제품명") or product_text), None


def load_reserved_plans() -> pd.DataFrame:
    columns = [
        "예약ID", "생산일", "제품코드", "제품명", "예약수량kg", "상태",
        "등록일시", "등록자ID", "등록자명", "전환일시", "원문",
    ]
    if not RESERVED_PLAN_FILE.exists():
        return pd.DataFrame(columns=columns)

    try:
        df = pd.read_excel(RESERVED_PLAN_FILE)
    except Exception:
        return pd.DataFrame(columns=columns)

    for col in columns:
        if col not in df.columns:
            df[col] = ""

    return df[columns]


def save_reserved_plans(df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    df.to_excel(RESERVED_PLAN_FILE, index=False)


def make_reserved_id() -> str:
    return "R" + datetime.now().strftime("%Y%m%d%H%M%S")


def add_reserved_plan_from_text(text: str, user_id="", username="") -> str:
    production_date, product_text, qty_kg, err = parse_reserved_plan_text(text)
    if err:
        return f"❌ {err}"

    product_code, product_name, err = resolve_product(product_text)
    if err:
        return f"❌ {err}"

    df = load_reserved_plans()
    reserved_id = make_reserved_id()

    row = {
        "예약ID": reserved_id,
        "생산일": production_date,
        "제품코드": product_code,
        "제품명": product_name,
        "예약수량kg": float(qty_kg),
        "상태": "예약",
        "등록일시": _now_text(),
        "등록자ID": str(user_id),
        "등록자명": str(username or ""),
        "전환일시": "",
        "원문": text,
    }

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_reserved_plans(df)

    judge_lines = []
    try:
        result = build_result(product_code or product_name, float(qty_kg), extra_consumption={})
        shortage = result.get("부족", []) or []
        if shortage:
            judge_lines.append("참고판정: ❌ 현재 재고 기준 부족 가능")
            judge_lines.append("[부족 자재]")
            for idx, item in enumerate(shortage[:5], start=1):
                judge_lines.append(
                    f"{idx}. {item.get('자재명')} [{item.get('자재코드')}] "
                    f"부족 {fmt_num(item.get('부족수량', 0))}{item.get('배합단위', '')}"
                )
        else:
            judge_lines.append("참고판정: ✅ 현재 재고 기준 생산 가능")
    except Exception:
        judge_lines.append("참고판정: 계산 생략")

    lines = []
    lines.append("[예약 생산계획 등록 완료]")
    lines.append("실제 생산계획과 분리해서 저장했습니다.")
    lines.append("")
    lines.append(f"예약ID: {reserved_id}")
    lines.append(f"생산일: {production_date}")
    lines.append(f"제품: {product_name} [{product_code}]")
    lines.append(f"예약수량: {fmt_num(qty_kg)}kg")
    lines.append("상태: 예약")
    lines.append("")
    lines.extend(judge_lines)
    lines.append("")
    lines.append("실제 생산계획으로 전환하려면:")
    lines.append(f"/reserveactual {len(df)}")
    lines.append("")
    lines.append("예약 목록:")
    lines.append("/reservedplans")
    return "\n".join(lines)


def format_reserved_plan_list(limit: int = 80) -> str:
    df = load_reserved_plans()
    if df.empty:
        return "등록된 예약 생산계획이 없습니다."

    lines = []
    lines.append("[예약 생산계획 목록]")
    lines.append(f"총 {len(df)}건")
    lines.append("")

    for idx, row in df.tail(limit).iterrows():
        no = idx + 1
        lines.append(
            f"{no}. {str(row.get('생산일', '-'))[:10]} / "
            f"{row.get('제품명', '-')} [{row.get('제품코드', '-')}] / "
            f"{fmt_num(row.get('예약수량kg', 0))}kg / "
            f"{row.get('상태', '-')}"
        )

    lines.append("")
    lines.append("실제 생산계획 전환: /reserveactual 번호")
    lines.append("예약 삭제: /reservedel 번호")
    return "\n".join(lines)


def delete_reserved_plan(no: int) -> str:
    df = load_reserved_plans()
    if df.empty:
        return "삭제할 예약 생산계획이 없습니다."

    idx = int(no) - 1
    if idx < 0 or idx >= len(df):
        return f"해당 번호의 예약 생산계획이 없습니다: {no}"

    row = df.iloc[idx]
    df = df.drop(df.index[idx]).reset_index(drop=True)
    save_reserved_plans(df)

    return (
        "[예약 생산계획 삭제 완료]\n"
        f"번호: {no}\n"
        f"생산일: {row.get('생산일')}\n"
        f"제품: {row.get('제품명')} [{row.get('제품코드')}]\n"
        f"수량: {fmt_num(row.get('예약수량kg', 0))}kg"
    )


def convert_reserved_to_actual(no: int) -> str:
    try:
        from production_memory import add_production_plan
    except Exception as e:
        return f"❌ 실제 생산계획 전환 함수를 불러오지 못했습니다: {str(e)}"

    df = load_reserved_plans()
    if df.empty:
        return "전환할 예약 생산계획이 없습니다."

    idx = int(no) - 1
    if idx < 0 or idx >= len(df):
        return f"해당 번호의 예약 생산계획이 없습니다: {no}"

    row = df.iloc[idx]
    if str(row.get("상태", "")).strip() == "전환완료":
        return f"이미 실제 생산계획으로 전환된 예약입니다: {no}"

    production_date = str(row.get("생산일", "")).strip()[:10]
    product_code = str(row.get("제품코드", "")).strip()
    product_name = str(row.get("제품명", "")).strip()
    try:
        qty_kg = float(row.get("예약수량kg", 0) or 0)
    except Exception:
        qty_kg = 0.0

    if not production_date or not (product_code or product_name) or qty_kg <= 0:
        return "❌ 예약 데이터가 올바르지 않아 전환할 수 없습니다."

    saved, msg = add_production_plan(
        production_date,
        product_code or product_name,
        qty_kg,
        question=f"예약 생산계획 전환: {row.get('예약ID')}",
    )

    if saved:
        df.at[idx, "상태"] = "전환완료"
        df.at[idx, "전환일시"] = _now_text()
        save_reserved_plans(df)

    return (
        "[예약 생산계획 → 실제 생산계획 전환]\n\n"
        f"번호: {no}\n"
        f"생산일: {production_date}\n"
        f"제품: {product_name} [{product_code}]\n"
        f"수량: {fmt_num(qty_kg)}kg\n"
        f"저장: {'완료' if saved else '보류'}\n"
        f"{msg}"
    )
