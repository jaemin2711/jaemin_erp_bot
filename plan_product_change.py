import re

from date_utils import parse_production_date, remove_date_text
from production_memory import (
    load_plans,
    save_plans,
    match_plan_rows,
    get_product_info,
    fmt_num,
)


def parse_quantity_kg(text: str):
    q = str(text).replace(",", "").lower()

    matches = []

    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*톤", q):
        matches.append(float(m.group(1)) * 1000)

    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*t(?![a-zA-Z가-힣0-9])", q):
        matches.append(float(m.group(1)) * 1000)

    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(kg|키로|킬로)", q):
        matches.append(float(m.group(1)))

    if "천키로" in q or "천kg" in q or "천킬로" in q:
        matches.append(1000)

    if not matches:
        return None

    return matches[-1]


def extract_new_product_key(question: str):
    """
    변경할 새 제품코드 추출.
    예: P10543
    """
    m = re.search(r"\bP\d+\b", str(question), flags=re.IGNORECASE)

    if not m:
        return None

    return m.group(0).upper()


def extract_old_product_key(question: str):
    """
    기존 생산계획에서 찾을 제품명 추출.

    예:
    6/8 트립토판20% 2톤을 P10543 제품으로 변경
    -> 트립토판20%
    """
    q = str(question)

    # 날짜 제거
    q = remove_date_text(q)

    # 새 제품코드 제거
    q = re.sub(r"\bP\d+\b", " ", q, flags=re.IGNORECASE)

    # 수량 제거
    q = re.sub(r"\d+(?:\.\d+)?\s*톤", " ", q, flags=re.IGNORECASE)
    q = re.sub(r"\d+(?:\.\d+)?\s*t(?![a-zA-Z가-힣0-9])", " ", q, flags=re.IGNORECASE)
    q = re.sub(r"\d+(?:\.\d+)?\s*(kg|KG|키로|킬로)", " ", q)
    q = q.replace("천키로", " ")
    q = q.replace("천kg", " ")
    q = q.replace("천킬로", " ")

    remove_words = [
        "제품으로",
        "제품",
        "변경",
        "변경해줘",
        "변경등록",
        "등록",
        "수정",
        "바꿔줘",
        "바꿔",
        "으로",
        "로",
        "을",
        "를",
        "생산계획",
        "계획",
        "생산",
    ]

    for word in remove_words:
        q = q.replace(word, " ")

    q = re.sub(r"\s+", " ", q).strip()

    return q if q else None


def is_product_change_question(question: str):
    """
    제품 자체를 다른 제품코드로 변경하는 질문인지 확인.
    """
    q = str(question).replace(" ", "").lower()

    has_change_word = "변경" in q or "수정" in q or "바꿔" in q
    has_product_word = "제품" in q or re.search(r"p\d+", q, flags=re.IGNORECASE)
    has_new_code = re.search(r"\bp\d+\b", str(question), flags=re.IGNORECASE) is not None

    return has_change_word and has_product_word and has_new_code


def handle_product_change_question(question: str):
    production_date = parse_production_date(question)
    old_product_key = extract_old_product_key(question)
    new_product_key = extract_new_product_key(question)
    new_qty = parse_quantity_kg(question)

    if not production_date:
        return (
            "제품 변경을 하려면 날짜를 포함해주세요.\n"
            "예: 6/8 트립토판20% 2톤을 P10543 제품으로 변경"
        )

    if not old_product_key:
        return (
            "기존 생산계획에서 찾을 제품명을 확인하지 못했습니다.\n"
            "예: 6/8 트립토판20% 2톤을 P10543 제품으로 변경"
        )

    if not new_product_key:
        return (
            "변경할 제품코드를 확인하지 못했습니다.\n"
            "예: 6/8 트립토판20% 2톤을 P10543 제품으로 변경"
        )

    if new_qty is None:
        return (
            "변경할 생산수량을 확인하지 못했습니다.\n"
            "예: 6/8 트립토판20% 2톤을 P10543 제품으로 변경"
        )

    plans = load_plans()

    if plans.empty:
        return "수정할 생산계획이 없습니다."

    matched = match_plan_rows(
        plans,
        production_date=production_date,
        product_key=old_product_key,
    )

    if matched.empty:
        return (
            "조건에 맞는 기존 생산계획을 찾지 못했습니다.\n\n"
            f"- 생산일: {production_date}\n"
            f"- 찾은 제품명: {old_product_key}\n\n"
            "생산계획을 먼저 확인해보세요.\n"
            "예: 생산계획 보여줘"
        )

    if len(matched) > 1:
        lines = []
        lines.append("수정 대상이 여러 개입니다.")
        lines.append("기존 제품명을 더 정확히 입력해주세요.")
        lines.append("")
        lines.append("[수정 후보]")

        for idx, row in enumerate(matched.itertuples(), start=1):
            lines.append(
                f"{idx}. {row.생산일} / {row.제품코드} / {row.제품명} / "
                f"{fmt_num(row.생산수량kg)}kg"
            )

        return "\n".join(lines)

    new_product_info = get_product_info(new_product_key)

    if new_product_info is None:
        return (
            "변경할 제품코드의 BOM 정보를 찾지 못했습니다.\n\n"
            f"- 입력 제품코드: {new_product_key}\n\n"
            "제품코드를 다시 확인해주세요."
        )

    idx = matched.index[0]

    old_date = str(plans.loc[idx, "생산일"])
    old_code = str(plans.loc[idx, "제품코드"])
    old_name = str(plans.loc[idx, "제품명"])
    old_qty = float(plans.loc[idx, "생산수량kg"])

    plans.loc[idx, "제품코드"] = new_product_info["제품코드"]
    plans.loc[idx, "제품명"] = new_product_info["제품명"]
    plans.loc[idx, "생산수량kg"] = float(new_qty)
    plans.loc[idx, "질문"] = question

    save_plans(plans)

    lines = []
    lines.append("생산계획 제품과 수량을 변경했습니다.")
    lines.append("")
    lines.append("[기존 계획]")
    lines.append(f"- 생산일: {old_date}")
    lines.append(f"- 제품코드: {old_code}")
    lines.append(f"- 제품명: {old_name}")
    lines.append(f"- 기존 수량: {fmt_num(old_qty)}kg")
    lines.append("")
    lines.append("[변경 후]")
    lines.append(f"- 생산일: {production_date}")
    lines.append(f"- 제품코드: {new_product_info['제품코드']}")
    lines.append(f"- 제품명: {new_product_info['제품명']}")
    lines.append(f"- 변경 수량: {fmt_num(new_qty)}kg")

    return "\n".join(lines)