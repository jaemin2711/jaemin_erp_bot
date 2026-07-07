import re
import unicodedata
import pandas as pd
from pathlib import Path
from datetime import datetime, date

from inventory_engine import load_data, find_product_bom


PLAN_FILE = Path("data/production_plan.xlsx")
DONE_PLAN_FILE = Path("data/production_plan_done.xlsx")


PLAN_COLUMNS = [
    "생산일",
    "제품코드",
    "제품명",
    "생산수량kg",
    "질문",
    "등록시각",
]


def normalize_text(value):
    if value is None:
        return ""

    text = str(value).strip()
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()

    text = text.replace(" ", "")
    text = text.replace("-", "")
    text = text.replace("_", "")
    text = text.replace("(", "")
    text = text.replace(")", "")
    text = text.replace("[", "")
    text = text.replace("]", "")
    text = text.replace("/", "")
    text = text.replace("\\", "")

    text = re.sub(r"[^0-9a-zA-Z가-힣]", "", text)

    return text


def extract_product_code_from_text(text):
    if text is None:
        return None

    text = str(text).upper()
    match = re.search(r"\bP\d+\b", text)

    if match:
        return match.group(0)

    return None


def fmt_num(value):
    try:
        value = float(value)
        if value.is_integer():
            return f"{value:,.0f}"
        return f"{value:,.3f}".rstrip("0").rstrip(".")
    except Exception:
        return str(value)


def parse_plan_date(value):
    """
    생산일 값을 date 형식으로 변환한다.

    지원 예:
    - 2026-06-02
    - 2026.06.02
    - 2026/06/02
    - 20260602
    - 6월 2일
    - 2026년 6월 2일
    - 엑셀 날짜 형식
    """
    if value is None:
        return None

    if isinstance(value, pd.Timestamp):
        return value.date()

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = str(value).strip()

    if not text or text.lower() == "nan":
        return None

    text = text.replace(" 00:00:00", "")

    # 20260602
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except Exception:
            pass

    # 2026-06-02 / 2026.06.02 / 2026/06/02
    for fmt in ["%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"]:
        try:
            return datetime.strptime(text, fmt).date()
        except Exception:
            pass

    # 06-02 / 06.02 / 06/02 → 올해 연도 사용
    for fmt in ["%m-%d", "%m.%d", "%m/%d"]:
        try:
            parsed = datetime.strptime(text, fmt).date()
            return date(datetime.now().year, parsed.month, parsed.day)
        except Exception:
            pass

    # 6월 2일 / 2026년 6월 2일
    match = re.search(r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일?", text)
    if match:
        year = int(match.group(1)) if match.group(1) else datetime.now().year
        month = int(match.group(2))
        day = int(match.group(3))

        try:
            return date(year, month, day)
        except Exception:
            return None

    try:
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.notna(parsed):
            return parsed.date()
    except Exception:
        pass

    return None


def normalize_plan_date(value):
    """
    생산일을 YYYY-MM-DD 형태로 통일한다.
    """
    parsed = parse_plan_date(value)

    if parsed is None:
        return str(value).strip()

    return parsed.strftime("%Y-%m-%d")


def load_plans(cleanup=True):
    """
    생산계획 엑셀을 읽는다.
    cleanup=True이면 오늘보다 지난 생산계획을 먼저 자동 정리한다.
    """
    if cleanup:
        cleanup_past_plans()
        return load_plans(cleanup=False)

    if not PLAN_FILE.exists():
        return pd.DataFrame(columns=PLAN_COLUMNS)

    df = pd.read_excel(PLAN_FILE)

    for col in PLAN_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df[PLAN_COLUMNS].copy()

    if not df.empty:
        df["생산일"] = df["생산일"].apply(normalize_plan_date)
        df["제품코드"] = df["제품코드"].astype(str)
        df["제품명"] = df["제품명"].astype(str)
        df["생산수량kg"] = pd.to_numeric(df["생산수량kg"], errors="coerce").fillna(0)
        df["질문"] = df["질문"].astype(str)
        df["등록시각"] = df["등록시각"].astype(str)

    return df


def save_plans(df):
    """
    생산계획을 data/production_plan.xlsx에 저장한다.
    """
    PLAN_FILE.parent.mkdir(exist_ok=True)

    if df.empty:
        df = pd.DataFrame(columns=PLAN_COLUMNS)
    else:
        for col in PLAN_COLUMNS:
            if col not in df.columns:
                df[col] = ""

        df = df[PLAN_COLUMNS].copy()
        df["생산일"] = df["생산일"].apply(normalize_plan_date)
        df["생산수량kg"] = pd.to_numeric(df["생산수량kg"], errors="coerce").fillna(0)
        df = df.sort_values(["생산일", "제품코드", "등록시각"], ascending=True)

    df.to_excel(PLAN_FILE, index=False)


def cleanup_past_plans(today=None, archive=True):
    """
    오늘보다 이전 생산계획을 자동 정리한다.

    예:
    오늘이 2026-06-08이면
    2026-06-02, 2026-06-07 계획은 정리
    2026-06-08, 2026-06-09 계획은 유지
    """
    if today is None:
        today_date = datetime.now().date()
    else:
        today_date = parse_plan_date(today)

    if today_date is None:
        today_date = datetime.now().date()

    if not PLAN_FILE.exists():
        return 0, pd.DataFrame(columns=PLAN_COLUMNS)

    plans = load_plans(cleanup=False)

    if plans.empty:
        return 0, plans

    plans = plans.copy()
    plans["_생산일자"] = plans["생산일"].apply(parse_plan_date)

    old_mask = plans["_생산일자"].notna() & (plans["_생산일자"] < today_date)

    old_plans = plans[old_mask].drop(columns=["_생산일자"]).copy()
    remain_plans = plans[~old_mask].drop(columns=["_생산일자"]).copy()

    if old_plans.empty:
        return 0, old_plans

    if archive:
        archive_df = old_plans.copy()
        archive_df["처리구분"] = "생산일 경과 자동정리"
        archive_df["처리일시"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if DONE_PLAN_FILE.exists():
            old_archive = pd.read_excel(DONE_PLAN_FILE)
            archive_df = pd.concat([old_archive, archive_df], ignore_index=True)

        DONE_PLAN_FILE.parent.mkdir(exist_ok=True)
        archive_df.to_excel(DONE_PLAN_FILE, index=False)

    save_plans(remain_plans)

    return len(old_plans), old_plans


def format_cleanup_message():
    """
    텔레그램에서 지난 생산계획 정리 결과를 보여줄 때 사용.
    """
    deleted_count, deleted_df = cleanup_past_plans()

    if deleted_count == 0:
        return "정리할 지난 생산계획이 없습니다."

    lines = []
    lines.append(f"지난 생산계획 {deleted_count}건을 정리했습니다.")
    lines.append("")
    lines.append(format_plan_rows(deleted_df, title="[자동 정리된 생산계획]"))
    lines.append("")
    lines.append("정리된 자료는 data/production_plan_done.xlsx에 보관했습니다.")

    return "\n".join(lines)


def get_product_info(product_key):
    bom_df, _ = load_data()
    product_bom = find_product_bom(bom_df, product_key)

    if product_bom is None or product_bom.empty:
        return None

    return {
        "제품코드": str(product_bom.iloc[0]["제품코드"]).strip(),
        "제품명": str(product_bom.iloc[0]["제품명"]).strip(),
    }


def calculate_material_consumption(product_key, qty_kg):
    """
    특정 제품을 qty_kg 만큼 생산할 때 필요한 자재량 계산.
    """
    bom_df, _ = load_data()
    product_bom = find_product_bom(bom_df, product_key)

    if product_bom is None or product_bom.empty:
        return {}

    product_bom = product_bom.copy()
    product_bom["기준수량"] = pd.to_numeric(product_bom["기준수량"], errors="coerce").fillna(0)
    product_bom["소요량"] = pd.to_numeric(product_bom["소요량"], errors="coerce").fillna(0)

    consumption = {}

    for _, row in product_bom.iterrows():
        material_code = str(row["자재코드"]).strip()
        base_qty = float(row["기준수량"])
        bom_qty = float(row["소요량"])

        if not material_code or material_code.lower() == "nan":
            continue

        if base_qty <= 0 or bom_qty <= 0:
            continue

        required_qty = bom_qty * float(qty_kg) / base_qty
        consumption[material_code] = consumption.get(material_code, 0) + required_qty

    return consumption


def match_plan_rows(plans, production_date=None, product_key=None):
    """
    생산계획에서 날짜/제품 조건에 맞는 행을 찾는다.
    product_key는 제품명 또는 제품코드 모두 가능.
    """
    if plans.empty:
        return plans.copy()

    matched = plans.copy()

    if production_date:
        target_date = normalize_plan_date(production_date)
        matched = matched[
            matched["생산일"].apply(normalize_plan_date) == target_date
        ].copy()

    if product_key:
        key = str(product_key).strip()
        code = extract_product_code_from_text(key)
        norm_key = normalize_text(key)

        if code:
            code_key = code.replace(" ", "").upper()
            matched = matched[
                matched["제품코드"].astype(str).str.replace(" ", "", regex=False).str.upper() == code_key
            ].copy()
        else:
            matched["_제품명정리"] = matched["제품명"].apply(normalize_text)
            matched = matched[
                matched["_제품명정리"].apply(
                    lambda x: norm_key in x or x in norm_key if norm_key and x else False
                )
            ].copy()

            if "_제품명정리" in matched.columns:
                matched = matched.drop(columns=["_제품명정리"])

    return matched


def format_plan_rows(df, title="[생산계획]"):
    if df.empty:
        return "조회된 생산계획이 없습니다."

    lines = []
    lines.append(title)

    for idx, row in enumerate(df.itertuples(index=False), start=1):
        생산일 = getattr(row, "생산일")
        제품코드 = getattr(row, "제품코드")
        제품명 = getattr(row, "제품명")
        생산수량kg = getattr(row, "생산수량kg")
        등록시각 = getattr(row, "등록시각")

        lines.append(
            f"{idx}. {생산일} / {제품코드} / {제품명} / "
            f"{fmt_num(생산수량kg)}kg / 등록 {등록시각}"
        )

    return "\n".join(lines)


def format_plan_list(production_date=None, product_key=None):
    plans = load_plans()

    if plans.empty:
        return "저장된 생산계획이 없습니다."

    matched = match_plan_rows(plans, production_date=production_date, product_key=product_key)

    title = "[저장된 생산계획]"

    if production_date and product_key:
        title = f"[{production_date} / {product_key} 생산계획]"
    elif production_date:
        title = f"[{production_date} 생산계획]"
    elif product_key:
        title = f"[{product_key} 생산계획]"

    return format_plan_rows(matched, title=title)


def add_production_plan(production_date, product_key, qty_kg, question=""):
    """
    생산 가능으로 판단된 계획만 저장한다.
    같은 날짜/같은 제품이 이미 있으면 중복 저장하지 않고 변경 안내.
    단, 지난 날짜의 생산계획은 저장하지 않는다.
    """
    plan_date = parse_plan_date(production_date)

    if plan_date is not None and plan_date < datetime.now().date():
        return False, (
            "지난 날짜의 생산계획은 저장하지 않았습니다.\n"
            f"- 입력한 생산일: {normalize_plan_date(production_date)}\n"
            "이미 생산이 진행된 일정으로 보고 기록 대상에서 제외합니다."
        )

    production_date = normalize_plan_date(production_date)

    product_info = get_product_info(product_key)

    if product_info is None:
        return False, "제품 정보를 찾지 못해 생산계획에 저장하지 않았습니다."

    plans = load_plans()

    product_code = product_info["제품코드"]
    product_name = product_info["제품명"]

    if not plans.empty:
        same_product_same_date = plans[
            (plans["생산일"].apply(normalize_plan_date) == production_date) &
            (plans["제품코드"].astype(str) == str(product_code))
        ].copy()

        if not same_product_same_date.empty:
            existing_qty = same_product_same_date["생산수량kg"].astype(float).sum()

            if abs(existing_qty - float(qty_kg)) < 0.0001:
                return False, (
                    "동일한 생산계획이 이미 저장되어 있어 중복 저장하지 않았습니다.\n"
                    f"- {production_date} / {product_code} / {product_name} / {fmt_num(existing_qty)}kg"
                )

            return False, (
                "같은 날짜에 같은 제품의 생산계획이 이미 있습니다.\n"
                f"- 기존: {production_date} / {product_code} / {product_name} / {fmt_num(existing_qty)}kg\n"
                f"- 새 요청: {fmt_num(qty_kg)}kg\n\n"
                "수량을 바꾸려면 아래처럼 입력하세요.\n"
                f"예: {production_date} {product_name} {fmt_num(qty_kg)}kg으로 변경"
            )

    new_row = {
        "생산일": production_date,
        "제품코드": product_code,
        "제품명": product_name,
        "생산수량kg": float(qty_kg),
        "질문": question,
        "등록시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    plans = pd.concat([plans, pd.DataFrame([new_row])], ignore_index=True)
    save_plans(plans)

    return True, f"{production_date} / {product_name} / {fmt_num(qty_kg)}kg 생산계획을 저장했습니다."


def delete_production_plan(production_date=None, product_key=None):
    """
    특정 생산계획 삭제.
    - 날짜만 있으면 해당 날짜 전체 삭제
    - 날짜 + 제품 있으면 해당 날짜 해당 제품 삭제
    - 제품만 있고 여러 날짜가 걸리면 삭제하지 않고 후보 표시
    """
    plans = load_plans()

    if plans.empty:
        return "삭제할 생산계획이 없습니다."

    if not production_date and not product_key:
        return "삭제 조건이 없습니다. 예: 6월 8일 스위트몰라 계획 삭제"

    matched = match_plan_rows(plans, production_date=production_date, product_key=product_key)

    if matched.empty:
        return "조건에 맞는 생산계획을 찾지 못했습니다."

    if product_key and not production_date and len(matched) > 1:
        lines = []
        lines.append("삭제 대상이 여러 개입니다.")
        lines.append("정확한 날짜를 포함해서 다시 입력해주세요.")
        lines.append("")
        lines.append(format_plan_rows(matched, title="[삭제 후보]"))
        return "\n".join(lines)

    matched_index = matched.index
    remain = plans.drop(index=matched_index).copy()
    save_plans(remain)

    lines = []
    lines.append("아래 생산계획을 삭제했습니다.")
    lines.append("")
    lines.append(format_plan_rows(matched, title="[삭제된 생산계획]"))

    return "\n".join(lines)


def update_production_plan(production_date, product_key, new_qty_kg):
    """
    특정 날짜/제품 생산계획 수량 변경.
    날짜와 제품이 모두 있어야 안정적으로 변경 가능.
    """
    plans = load_plans()

    if plans.empty:
        return "수정할 생산계획이 없습니다."

    if not production_date or not product_key:
        return "수정하려면 날짜와 제품명을 함께 입력해주세요. 예: 6월 8일 스위트몰라 1500kg으로 변경"

    production_date = normalize_plan_date(production_date)

    matched = match_plan_rows(plans, production_date=production_date, product_key=product_key)

    if matched.empty:
        return "조건에 맞는 생산계획을 찾지 못했습니다."

    if len(matched) > 1:
        lines = []
        lines.append("수정 대상이 여러 개입니다.")
        lines.append("제품명 또는 제품코드를 더 정확히 입력해주세요.")
        lines.append("")
        lines.append(format_plan_rows(matched, title="[수정 후보]"))
        return "\n".join(lines)

    idx = matched.index[0]

    old_qty = float(plans.loc[idx, "생산수량kg"])
    plans.loc[idx, "생산수량kg"] = float(new_qty_kg)
    plans.loc[idx, "등록시각"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    save_plans(plans)

    return (
        "생산계획 수량을 변경했습니다.\n"
        f"- 생산일: {plans.loc[idx, '생산일']}\n"
        f"- 제품코드: {plans.loc[idx, '제품코드']}\n"
        f"- 제품명: {plans.loc[idx, '제품명']}\n"
        f"- 기존 수량: {fmt_num(old_qty)}kg\n"
        f"- 변경 수량: {fmt_num(new_qty_kg)}kg"
    )


def get_applied_plans_until(production_date):
    """
    해당 생산일 이전/동일 날짜에 저장된 생산계획 목록 반환.
    단, 오늘보다 지난 생산계획은 load_plans() 단계에서 자동 정리된다.
    """
    plans = load_plans()

    if plans.empty:
        return plans.copy()

    target_date = parse_plan_date(production_date)

    if target_date is None:
        return plans.iloc[0:0].copy()

    plans = plans.copy()
    plans["_생산일자"] = plans["생산일"].apply(parse_plan_date)

    applied = plans[
        plans["_생산일자"].notna() &
        (plans["_생산일자"] <= target_date)
    ].copy()

    applied = applied.drop(columns=["_생산일자"])

    return applied


def format_applied_plans_until(production_date):
    applied = get_applied_plans_until(production_date)

    if applied.empty:
        return ""

    lines = []
    lines.append("[반영된 기존 생산계획]")

    for _, row in applied.iterrows():
        lines.append(
            f"- {row['생산일']} / {row['제품코드']} / {row['제품명']} / "
            f"{fmt_num(row['생산수량kg'])}kg"
        )

    lines.append("")
    lines.append("위 생산계획에 필요한 자재를 차감한 뒤 계산했습니다.")

    return "\n".join(lines)


def get_planned_consumption_until(production_date):
    """
    해당 생산일 이전/동일 날짜의 생산계획을 모두 반영한다.

    예:
    오늘이 6월 8일이고 6월 9일 생산 가능 여부를 계산하면
    6월 2일 같은 지난 계획은 자동 정리되어 반영되지 않고,
    6월 8일과 6월 9일 계획만 반영된다.
    """
    target_plans = get_applied_plans_until(production_date)

    if target_plans.empty:
        return {}

    total_consumption = {}

    for _, plan in target_plans.iterrows():
        product_code = str(plan["제품코드"]).strip()
        product_name = str(plan["제품명"]).strip()
        qty = float(plan["생산수량kg"])

        product_key = product_code if product_code and product_code.lower() != "nan" else product_name

        consumption = calculate_material_consumption(product_key, qty)

        for material_code, amount in consumption.items():
            total_consumption[material_code] = total_consumption.get(material_code, 0) + amount

    return total_consumption


def clear_plans():
    if PLAN_FILE.exists():
        PLAN_FILE.unlink()

    return "저장된 생산계획을 모두 삭제했습니다."