
from __future__ import annotations

import re
from datetime import datetime, date
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

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


def get_product_info(product_text):
    """
    현재 inventory_engine.py에 get_product_info 함수가 없는 버전도 있어서
    build_result()를 이용해 제품코드/제품명을 조회하는 호환 함수입니다.
    """
    product_text = str(product_text or "").strip()

    if not product_text:
        return None

    try:
        result = build_result(product_text, 1, extra_consumption={})
    except TypeError:
        try:
            result = build_result(product_text, 1)
        except Exception:
            return None
    except Exception:
        return None

    if not isinstance(result, dict) or not result.get("found"):
        return None

    return {
        "제품코드": result.get("제품코드") or "",
        "제품명": result.get("제품명") or product_text,
    }



DATA_DIR = Path("data")
PLAN_FILE = DATA_DIR / "production_plan.xlsx"


def normalize_text(value) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^0-9a-zA-Z가-힣]", "", text)
    return text


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
    """
    문장 안의 마지막 수량을 새 수량으로 봅니다.
    예:
    - 8,000kg을 14,000kg으로 변경 -> 14,000kg
    - 1톤에서 500kg로 정정 -> 500kg
    """
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


def is_plan_natural_change_text(text: str) -> bool:
    """
    자연어 생산계획 변경 문장인지 판단합니다.
    """
    raw = str(text or "").strip()
    compact = raw.replace(" ", "").lower()

    if not raw:
        return False

    if re.match(r"^/(수정|editplan)\s+\d+", raw, flags=re.IGNORECASE):
        return False

    if compact.startswith("/changeplan"):
        return True

    has_change_word = (
        "변경" in compact
        or "수정" in compact
        or "정정" in compact
        or "바꿔" in compact
        or "바꿈" in compact
    )

    if not has_change_word:
        return False

    return parse_date_text(raw) is not None and parse_quantity_kg(raw) is not None


def _get_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized = {normalize_text(c): c for c in df.columns}
    for cand in candidates:
        key = normalize_text(cand)
        if key in normalized:
            return normalized[key]
    return None


def _clean_plan_date(value) -> str:
    raw = str(value or "").strip()
    if not raw or raw.lower() in ["nan", "nat", "none", "null"]:
        return ""
    parsed = parse_date_text(raw)
    if parsed:
        return parsed
    try:
        return pd.to_datetime(raw).strftime("%Y-%m-%d")
    except Exception:
        return raw[:10]


def load_plan_file():
    if not PLAN_FILE.exists():
        return None, "생산계획 파일을 찾지 못했습니다: data/production_plan.xlsx"
    try:
        df = pd.read_excel(PLAN_FILE)
    except Exception as e:
        return None, f"생산계획 파일을 읽지 못했습니다: {str(e)}"
    df.columns = [str(c).strip() for c in df.columns]
    return df, None


def get_plan_columns(df: pd.DataFrame):
    date_col = _get_col(df, ["생산일", "생산일자", "일자"])
    code_col = _get_col(df, ["제품코드", "product_code", "code", "제품 code"])
    name_col = _get_col(df, ["제품명", "product_name", "name"])
    qty_col = _get_col(df, ["생산수량kg", "생산수량(kg)", "수량kg", "수량(kg)", "생산수량", "수량", "주문량"])
    return date_col, code_col, name_col, qty_col


def parse_change_text(text: str):
    raw = str(text or "").strip()
    clean = raw
    if clean.lower().startswith("/changeplan"):
        clean = clean[len("/changeplan"):].strip()

    production_date = parse_date_text(clean)
    new_qty = parse_quantity_kg(clean)

    if not production_date:
        return None, None, None, "생산일자를 인식하지 못했습니다. 예: 2026-06-24 제품명 14000kg으로 변경"
    if new_qty is None or new_qty <= 0:
        return None, None, None, "변경할 수량을 인식하지 못했습니다. 예: 2026-06-24 제품명 14000kg으로 변경"

    product_part = clean

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
        r"^/changeplan\s*",
        r"생산계획",
        r"생산등록",
        r"생산",
        r"계획",
        r"수량",
        r"변경",
        r"수정",
        r"정정",
        r"바꿔",
        r"바꿈",
        r"해주세요",
        r"해줘",
        r"해라",
        r"으로",
        r"로",
        r"에서",
    ]
    for pattern in cleanup_patterns:
        product_part = re.sub(pattern, " ", product_part, flags=re.IGNORECASE)

    product_part = re.sub(r"\s+", " ", product_part).strip(" ,/-_?:：")
    if not product_part:
        return None, None, None, "제품명을 인식하지 못했습니다. 예: 2026-06-24 CJ) 고킹토코 14000kg으로 변경"
    return production_date, product_part, new_qty, None


def resolve_product(product_text: str):
    product_text = str(product_text or "").strip()
    info = get_product_info(product_text)
    if info:
        return str(info.get("제품코드") or ""), str(info.get("제품명") or product_text), None
    try:
        result = build_result(product_text, 1, extra_consumption={})
    except Exception as e:
        return "", "", f"제품 조회 중 오류가 발생했습니다: {str(e)}"
    if result.get("found"):
        return str(result.get("제품코드") or ""), str(result.get("제품명") or product_text), None
    return "", "", f"제품을 찾지 못했습니다: {product_text}"


def find_plan_row(df: pd.DataFrame, production_date: str, product_text: str, product_code: str, product_name: str):
    date_col, code_col, name_col, qty_col = get_plan_columns(df)
    if not date_col or not qty_col or not (code_col or name_col):
        return None, [], "생산계획 파일의 필수 컬럼을 찾지 못했습니다. 필요 컬럼: 생산일, 제품코드/제품명, 생산수량kg"

    candidates = []

    for idx, row in df.iterrows():
        row_date = _clean_plan_date(row.get(date_col))
        if row_date != production_date:
            continue

        row_code = str(row.get(code_col, "")).strip() if code_col else ""
        row_name = str(row.get(name_col, "")).strip() if name_col else ""
        score = 0.0

        if product_code and row_code and normalize_text(product_code) == normalize_text(row_code):
            score = 1.0
        else:
            target_key = normalize_text(f"{product_text} {product_code} {product_name}")
            row_key = normalize_text(f"{row_code} {row_name}")
            score = SequenceMatcher(None, target_key, row_key).ratio()
            row_name_key = normalize_text(row_name)
            product_name_key = normalize_text(product_name)
            product_text_key = normalize_text(product_text)

            if product_name_key and row_name_key == product_name_key:
                score = max(score, 0.98)
            elif product_text_key and (product_text_key in row_name_key or row_name_key in product_text_key):
                score = max(score, 0.94)

        candidates.append({
            "index": idx,
            "score": score,
            "생산일": row_date,
            "제품코드": row_code,
            "제품명": row_name,
            "수량": row.get(qty_col),
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    if not candidates:
        return None, [], None

    best = candidates[0]
    if best["score"] < 0.45:
        return None, candidates[:5], None
    return best, candidates[:5], None


def _to_float_qty(value) -> float:
    if value is None:
        return 0.0
    text = str(value).replace(",", "").strip()
    parsed = parse_quantity_kg(text)
    if parsed is not None:
        return parsed
    try:
        return float(text)
    except Exception:
        return 0.0


def update_plan_by_natural_change(text: str, user_id="", username="") -> str:
    production_date, product_text, new_qty, err = parse_change_text(text)
    if err:
        return f"❌ {err}"

    product_code, product_name, err = resolve_product(product_text)
    if err:
        return f"❌ {err}"

    df, err = load_plan_file()
    if err:
        return f"❌ {err}"

    date_col, code_col, name_col, qty_col = get_plan_columns(df)
    plan, candidates, err = find_plan_row(df, production_date, product_text, product_code, product_name)
    if err:
        return f"❌ {err}"

    if not plan:
        lines = []
        lines.append("[생산계획 변경 실패]")
        lines.append(f"생산일: {production_date}")
        lines.append(f"입력 제품: {product_text}")
        lines.append(f"인식 제품: {product_name} [{product_code}]")
        lines.append(f"변경 수량: {fmt_num(new_qty)}kg")
        lines.append("")
        lines.append("❌ 같은 날짜의 해당 제품 생산계획을 찾지 못했습니다.")
        if candidates:
            lines.append("")
            lines.append("[같은 날짜 유사 후보]")
            for idx, c in enumerate(candidates, start=1):
                lines.append(
                    f"{idx}. {c.get('제품명')} [{c.get('제품코드')}] / "
                    f"수량 {c.get('수량')} / 유사도 {round(c.get('score', 0) * 100)}%"
                )
        lines.append("")
        lines.append("새로 등록하려면 '등록' 또는 '저장' 키워드를 사용하세요.")
        lines.append(f"예: {production_date} {product_name} {fmt_num(new_qty)}kg 저장")
        return "\n".join(lines)

    idx = plan["index"]
    old_qty = _to_float_qty(df.at[idx, qty_col])
    diff = float(new_qty) - float(old_qty)

    df.at[idx, qty_col] = float(new_qty)

    if code_col and product_code:
        df.at[idx, code_col] = product_code
    if name_col and product_name:
        df.at[idx, name_col] = product_name

    for col in ["수정일시", "수정원문", "수정자ID", "수정자명"]:
        if col not in df.columns:
            df[col] = ""

    df.at[idx, "수정일시"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df.at[idx, "수정원문"] = str(text)
    df.at[idx, "수정자ID"] = str(user_id)
    df.at[idx, "수정자명"] = str(username or "")

    DATA_DIR.mkdir(exist_ok=True)
    df.to_excel(PLAN_FILE, index=False)

    lines = []
    lines.append("[생산계획 변경 완료]")
    lines.append(f"생산일: {production_date}")
    lines.append(f"제품: {product_name} [{product_code}]")
    lines.append(f"계획번호: {int(idx) + 1}")
    lines.append(f"매칭점수: {round(float(plan.get('score', 0)) * 100)}%")
    lines.append("")
    lines.append(f"기존 수량: {fmt_num(old_qty)}kg")
    lines.append(f"변경 수량: {fmt_num(new_qty)}kg")
    lines.append(f"차이: {fmt_num(diff)}kg")
    lines.append("")
    lines.append("✅ 기존 생산계획 수량을 변경했습니다.")
    lines.append("확인: /plans 또는 /planlist")
    return "\n".join(lines)
