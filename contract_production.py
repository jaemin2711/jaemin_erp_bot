from __future__ import annotations

import re
from datetime import datetime, date
from pathlib import Path
from typing import Any

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

from production_memory import get_planned_consumption_until, add_production_plan

DATA_DIR = Path("data")
CONTRACT_FILE = DATA_DIR / "contract_production_rules.xlsx"


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _year() -> int:
    return datetime.now().year


def parse_date(value: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None

    m = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except Exception:
            return None

    m = re.search(r"(\d{1,2})[-./](\d{1,2})", text)
    if m:
        try:
            return date(_year(), int(m.group(1)), int(m.group(2))).strftime("%Y-%m-%d")
        except Exception:
            return None

    m = re.search(r"(?:(\d{4})년)?\s*(\d{1,2})월\s*(?:(\d{1,2})일?)?", text)
    if m:
        try:
            y = int(m.group(1)) if m.group(1) else _year()
            mo = int(m.group(2))
            d = int(m.group(3)) if m.group(3) else 1
            return date(y, mo, d).strftime("%Y-%m-%d")
        except Exception:
            return None
    return None


def parse_period(text: str) -> tuple[str | None, str | None]:
    raw = str(text or "")
    range_match = re.search(
        r"((?:\d{4}[-./])?\d{1,2}[-./]\d{1,2}|(?:\d{4}년)?\s*\d{1,2}월\s*\d{0,2}일?)\s*[~부터\-]\s*((?:\d{4}[-./])?\d{1,2}[-./]\d{1,2}|(?:\d{4}년)?\s*\d{1,2}월\s*\d{1,2}일?)",
        raw,
    )
    if range_match:
        return parse_date(range_match.group(1)), parse_date(range_match.group(2))

    start = None
    m = re.search(r"(?:(\d{4})년)?\s*(\d{1,2})월\s*(?:부터|시작)", raw)
    if m:
        y = int(m.group(1)) if m.group(1) else _year()
        start = date(y, int(m.group(2)), 1).strftime("%Y-%m-%d")

    end = None
    m = re.search(r"((?:\d{4}[-./])?\d{1,2}[-./]\d{1,2}|(?:\d{4}년)?\s*\d{1,2}월\s*\d{1,2}일?)\s*까지", raw)
    if m:
        end = parse_date(m.group(1))
    return start, end


def parse_qty_kg(text: str) -> float | None:
    raw = str(text or "").lower().replace(",", "")
    matches = list(re.finditer(r"(\d+(?:\.\d+)?)\s*(톤|t|kg|키로|킬로)", raw))
    if not matches:
        return None
    m = matches[-1]
    qty = float(m.group(1))
    if m.group(2) in ["톤", "t"]:
        qty *= 1000
    return qty


def parse_contract_text(text: str) -> tuple[dict[str, Any] | None, str | None]:
    raw = str(text or "").strip()
    start_date, end_date = parse_period(raw)
    monthly_qty = parse_qty_kg(raw)

    if not start_date:
        return None, "시작일을 인식하지 못했습니다. 예: 제품명 7월부터 12월31일까지 매월 5톤 계약생산 등록"
    if not end_date:
        return None, "종료일을 인식하지 못했습니다. 예: 제품명 7월부터 12월31일까지 매월 5톤 계약생산 등록"
    if not monthly_qty:
        return None, "월 생산수량을 인식하지 못했습니다. 예: 매월 5톤"

    product_part = raw
    for pat in [
        r"^/contractadd\s*", r"^/계약생산등록\s*", r"계약\s*생산\s*체크\s*등록", r"계약\s*생산\s*등록",
        r"계약생산", r"계약등록", r"장기생산", r"재고체크", r"체크", r"등록", r"매월", r"매달", r"월마다", r"한달에", r"부터", r"까지",
        r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", r"\d{1,2}[-./]\d{1,2}", r"(?:\d{4}년)?\s*\d{1,2}월\s*(?:\d{1,2}일?)?",
        r"(\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(톤|t|kg|키로|킬로)",
    ]:
        product_part = re.sub(pat, " ", product_part, flags=re.IGNORECASE)
    product_part = re.sub(r"\s+", " ", product_part).strip(" ,/-_?:：")
    if not product_part:
        return None, "제품명을 인식하지 못했습니다."

    product_info = get_product_info(product_part)
    if product_info:
        product_code = str(product_info.get("제품코드") or product_part)
        product_name = str(product_info.get("제품명") or product_part)
    else:
        test = build_result(product_part, 1, extra_consumption={})
        if not test.get("found"):
            return None, f"제품을 찾지 못했습니다: {product_part}"
        product_code = str(test.get("제품코드") or product_part)
        product_name = str(test.get("제품명") or product_part)

    return {
        "제품코드": product_code,
        "제품명": product_name,
        "시작일": start_date,
        "종료일": end_date,
        "반복주기": "매월",
        "월생산수량kg": float(monthly_qty),
        "상태": "활성",
        "원문": raw,
    }, None


def load_contracts() -> pd.DataFrame:
    cols = ["계약ID", "제품코드", "제품명", "시작일", "종료일", "반복주기", "월생산수량kg", "상태", "등록일시", "등록자ID", "등록자명", "원문"]
    if not CONTRACT_FILE.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_excel(CONTRACT_FILE)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols]


def save_contracts(df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    df.to_excel(CONTRACT_FILE, index=False)


def make_contract_id() -> str:
    return "C" + datetime.now().strftime("%Y%m%d%H%M%S")


def month_iter(start_date: str, end_date: str):
    start = pd.to_datetime(start_date).date()
    end = pd.to_datetime(end_date).date()
    y, m = start.year, start.month
    while True:
        first = date(y, m, 1)
        if first > end:
            break
        production_day = start if (y == start.year and m == start.month) else first
        if production_day <= end:
            yield production_day.strftime("%Y-%m-%d")
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1


def expand_contract_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "계약ID": row["계약ID"],
            "생산일": pdate,
            "제품코드": row["제품코드"],
            "제품명": row["제품명"],
            "생산수량kg": float(row["월생산수량kg"]),
        }
        for pdate in month_iter(str(row["시작일"]), str(row["종료일"]))
    ]


def add_contract_rule(data: dict[str, Any], user_id="", username="") -> str:
    df = load_contracts()
    row = {
        "계약ID": make_contract_id(),
        "제품코드": data["제품코드"],
        "제품명": data["제품명"],
        "시작일": data["시작일"],
        "종료일": data["종료일"],
        "반복주기": "매월",
        "월생산수량kg": float(data["월생산수량kg"]),
        "상태": "활성",
        "등록일시": _now_text(),
        "등록자ID": user_id,
        "등록자명": username,
        "원문": data.get("원문", ""),
    }
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_contracts(df)
    total_qty = sum(x["생산수량kg"] for x in expand_contract_row(row))
    return (
        "[계약생산 예약 등록 완료]\n\n"
        f"계약ID: {row['계약ID']}\n제품: {row['제품명']} [{row['제품코드']}]\n"
        f"기간: {row['시작일']} ~ {row['종료일']}\n반복: 매월\n"
        f"월 생산량: {fmt_num(row['월생산수량kg'])}kg\n총 예상 생산량: {fmt_num(total_qty)}kg\n\n"
        "체크: /contractcheck"
    )


def get_active_contracts() -> pd.DataFrame:
    df = load_contracts()
    if df.empty:
        return df
    return df[df["상태"].astype(str).str.strip() == "활성"].copy()


def expand_active_contracts() -> list[dict[str, Any]]:
    rows = []
    for _, row in get_active_contracts().iterrows():
        rows.extend(expand_contract_row(row.to_dict()))
    rows.sort(key=lambda x: x["생산일"])
    return rows


def format_contract_list() -> str:
    df = load_contracts()
    if df.empty:
        return "등록된 계약생산 예약이 없습니다."
    lines = ["[계약생산 예약 목록]", f"총 {len(df)}건", ""]
    for idx, row in df.iterrows():
        total_qty = sum(x["생산수량kg"] for x in expand_contract_row(row.to_dict()))
        lines.append(f"{idx+1}. {row.get('제품명')} [{row.get('제품코드')}] / {row.get('시작일')}~{row.get('종료일')} / 매월 {fmt_num(row.get('월생산수량kg', 0))}kg / 총 {fmt_num(total_qty)}kg / {row.get('상태')}")
    lines += ["", "삭제: /contractdel 번호", "체크: /contractcheck"]
    return "\n".join(lines)


def delete_contract(no: int) -> str:
    df = load_contracts()
    if df.empty:
        return "삭제할 계약생산 예약이 없습니다."
    idx = int(no) - 1
    if idx < 0 or idx >= len(df):
        return f"해당 번호의 계약생산 예약이 없습니다: {no}"
    row = df.iloc[idx]
    df = df.drop(df.index[idx]).reset_index(drop=True)
    save_contracts(df)
    return f"[계약생산 예약 삭제 완료]\n번호: {no}\n제품: {row.get('제품명')} [{row.get('제품코드')}]\n기간: {row.get('시작일')} ~ {row.get('종료일')}"


def simulate_contracts() -> str:
    expanded = expand_active_contracts()
    if not expanded:
        return "활성 상태의 계약생산 예약이 없습니다."

    lines = ["[계약생산 재고 시뮬레이션]", f"활성 계약 가상 생산계획: {len(expanded)}건", ""]
    running_extra: dict[str, float] = {}
    shortage_events = []

    for row in expanded:
        p_date = row["생산일"]
        p_key = row["제품코드"] or row["제품명"]
        p_name = row["제품명"]
        p_qty = float(row["생산수량kg"])

        try:
            planned_extra = get_planned_consumption_until(p_date) or {}
        except Exception:
            planned_extra = {}

        extra = dict(planned_extra)
        for mat_code, qty in running_extra.items():
            extra[mat_code] = extra.get(mat_code, 0) + qty

        result = build_result(p_key, p_qty, extra_consumption=extra)
        shortage = result.get("부족", []) or []
        detail = result.get("상세", []) or []

        if shortage:
            lines.append(f"{p_date} / {p_name} / {fmt_num(p_qty)}kg → ❌ 부족 예상")
            shortage_events.append({"생산일": p_date, "제품명": p_name, "수량": p_qty, "부족": shortage})
            for item in shortage[:8]:
                lines.append(f"  - {item.get('자재명')} [{item.get('자재코드')}] 부족 {fmt_num(item.get('부족수량', 0))}{item.get('배합단위', '')}")
        else:
            lines.append(f"{p_date} / {p_name} / {fmt_num(p_qty)}kg → ✅ 가능")

        for item in detail:
            code = str(item.get("자재코드", "")).strip()
            req = float(item.get("필요수량", 0) or 0)
            if code:
                running_extra[code] = running_extra.get(code, 0) + req

    lines.append("")
    if not shortage_events:
        lines.append("✅ 현재 재고와 기존 생산계획 기준으로 계약기간 내 부족 예상 자재가 없습니다.")
    else:
        first = shortage_events[0]
        lines += ["[최초 부족 발생]", f"- {first['생산일']} / {first['제품명']} / {fmt_num(first['수량'])}kg", "", "[조치 필요]", "부족 예상 자재를 계약 생산월 이전에 확보해야 합니다."]
    return "\n".join(lines)


def convert_contract_month_to_plan(no: int, month_text: str) -> str:
    df = load_contracts()
    if df.empty:
        return "등록된 계약생산 예약이 없습니다."
    idx = int(no) - 1
    if idx < 0 or idx >= len(df):
        return f"해당 번호의 계약생산 예약이 없습니다: {no}"
    row = df.iloc[idx].to_dict()
    target = parse_date(month_text)
    if not target:
        return "월을 인식하지 못했습니다. 예: /contractplan 1 7월"
    target_dt = pd.to_datetime(target)
    candidates = [x for x in expand_contract_row(row) if pd.to_datetime(x["생산일"]).year == target_dt.year and pd.to_datetime(x["생산일"]).month == target_dt.month]
    if not candidates:
        return f"해당 계약에 {target_dt.month}월 생산 예정 물량이 없습니다."
    item = candidates[0]
    saved, msg = add_production_plan(item["생산일"], item["제품코드"], float(item["생산수량kg"]), question=f"계약생산 전환: {row.get('계약ID')}")
    return f"[계약생산 → 실제 생산계획 전환]\n\n계약번호: {no}\n생산일: {item['생산일']}\n제품: {item['제품명']} [{item['제품코드']}]\n수량: {fmt_num(item['생산수량kg'])}kg\n저장: {'완료' if saved else '보류'}\n{msg}"
