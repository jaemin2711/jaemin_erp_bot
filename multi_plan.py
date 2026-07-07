import re
import inspect

from date_utils import parse_production_date, remove_date_text
from inventory_engine import check_production
from force_register_mode import is_force_enabled_for_date
from production_memory import (
    get_planned_consumption_until,
    add_production_plan,
    format_plan_list,
)


def fmt_num(value):
    try:
        value = float(value)
        if value.is_integer():
            return f"{value:,.0f}"
        return f"{value:,.3f}".rstrip("0").rstrip(".")
    except Exception:
        return str(value)


def parse_quantity_kg(text: str):
    q = str(text).replace(",", "").lower()

    m = re.search(r"(\d+(?:\.\d+)?)\s*톤", q)
    if m:
        return float(m.group(1)) * 1000

    m = re.search(r"(\d+(?:\.\d+)?)\s*t(?![a-zA-Z가-힣0-9])", q)
    if m:
        return float(m.group(1)) * 1000

    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|키로|킬로)", q)
    if m:
        return float(m.group(1))

    if "천키로" in q or "천kg" in q or "천킬로" in q:
        return 1000

    return None


def clean_product_name(text: str):
    q = str(text).strip()

    remove_words = [
        "생산계획", "계획", "등록", "추가", "생산", "가능", "가능해",
        "확인", "일정", "그리고", "또", "및", "품목", "제품",
        ":", "-", "·", "•",
    ]

    for word in remove_words:
        q = q.replace(word, " ")

    q = re.sub(r"\s+", " ", q).strip()

    return q


def parse_multi_items(question: str):
    """
    여러 제품 생산계획 입력을 제품별 항목으로 분리한다.

    지원 예:
    6월 8일 생산계획 등록
    스위트몰라 2톤
    PK-BV 10000kg

    또는:
    6월 8일 생산계획 등록, 스위트몰라 2톤, PK-BV 10000kg
    """
    q = remove_date_text(question)

    # 구분자 통일
    q = q.replace("，", ",")
    q = q.replace(";", "\n")
    q = q.replace("；", "\n")
    q = q.replace("、", ",")
    q = q.replace("/", "\n")

    parts = []
    for part in re.split(r"[\n,]+", q):
        part = part.strip()
        if part:
            parts.append(part)

    items = []

    # 제품명 + 수량 패턴
    # 제품명에 숫자가 있어도, 수량 단위가 붙은 부분을 기준으로 자른다.
    qty_pattern = r"(\d+(?:\.\d+)?\s*(?:톤|t|kg|키로|킬로)|천키로|천kg|천킬로)"

    for part in parts:
        matches = list(re.finditer(qty_pattern, part, flags=re.IGNORECASE))

        if not matches:
            continue

        # 한 줄에 하나의 제품이 있다고 보고 첫 번째 수량 사용
        m = matches[0]
        qty_text = m.group(1)
        product_part = part[:m.start()].strip()

        product_name = clean_product_name(product_part)
        qty_kg = parse_quantity_kg(qty_text)

        if product_name and qty_kg is not None:
            items.append({
                "제품명": product_name,
                "생산수량kg": float(qty_kg),
                "원본문장": part,
            })

    return items


def is_multi_production_request(question: str):
    """
    여러 제품 생산계획 등록 요청인지 판단한다.
    """
    q = question.replace(" ", "")

    if "초기화" in q or "삭제" in q or "변경" in q or "수정" in q:
        return False

    items = parse_multi_items(question)

    if len(items) >= 2:
        return True

    if ("일괄" in q or "여러" in q) and len(items) >= 1:
        return True

    return False


def check_with_optional_extra(product_name, quantity, intent, extra_consumption=None):
    sig = inspect.signature(check_production)

    if "extra_consumption" in sig.parameters:
        return check_production(
            product_name,
            float(quantity),
            intent,
            extra_consumption=extra_consumption,
        )

    return check_production(product_name, float(quantity), intent)


def handle_multi_production_request(question: str):
    production_date = parse_production_date(question)
    if not production_date:
        return (
            "여러 제품 생산계획을 등록하려면 생산일을 같이 입력해주세요.\n\n"
            "예:\n"
            "6월 8일 생산계획 등록\n"
            "스위트몰라 2톤\n"
            "PK-BV 10000kg"
        )
    items = parse_multi_items(question)
    if not items:
        return (
            "등록할 제품과 수량을 찾지 못했습니다.\n\n"
            "예:\n"
            "6월 8일 생산계획 등록\n"
            "스위트몰라 2톤\n"
            "PK-BV 10000kg"
        )

    force_mode_on = is_force_enabled_for_date(production_date)
    lines = []
    lines.append("=" * 50)
    lines.append("[여러 제품 생산계획 등록]")
    lines.append("=" * 50)
    lines.append(f"생산일: {production_date}")
    lines.append(f"입력 제품 수: {len(items)}개")
    lines.append(f"강제등록 모드: {'ON' if force_mode_on else 'OFF'}")
    lines.append("")
    lines.append("[입력 항목]")
    for idx, item in enumerate(items, start=1):
        lines.append(f"{idx}. {item['제품명']} / {fmt_num(item['생산수량kg'])}kg")
    lines.append("")
    lines.append("[처리 결과]")

    saved_count = 0
    force_saved_count = 0
    failed_count = 0
    skipped_count = 0

    for idx, item in enumerate(items, start=1):
        product_name = item["제품명"]
        qty_kg = item["생산수량kg"]
        extra_consumption = get_planned_consumption_until(production_date)
        answer = check_with_optional_extra(product_name, qty_kg, "production_check", extra_consumption=extra_consumption)
        is_possible = "판정: 생산 가능" in answer and "판정: 생산 불가능" not in answer
        lines.append("")
        lines.append("-" * 40)
        lines.append(f"{idx}. {product_name} / {fmt_num(qty_kg)}kg")

        if is_possible:
            saved, msg = add_production_plan(production_date, product_name, qty_kg, question=question)
            if saved:
                saved_count += 1
                lines.append("판정: 생산 가능")
                lines.append("저장: 완료")
                lines.append(msg)
            else:
                skipped_count += 1
                lines.append("판정: 생산 가능")
                lines.append("저장: 보류")
                lines.append(msg)
        elif force_mode_on:
            saved, msg = add_production_plan(production_date, product_name, qty_kg, question=question)
            if saved:
                force_saved_count += 1
                lines.append("판정: 생산 불가능")
                lines.append("강제등록 모드: ON")
                lines.append("저장: 강제 완료")
                lines.append(msg)
            else:
                skipped_count += 1
                lines.append("판정: 생산 불가능")
                lines.append("강제등록 모드: ON")
                lines.append("저장: 보류")
                lines.append(msg)
            capture = False
            for line in answer.splitlines():
                if "[부족 자재]" in line:
                    capture = True
                    lines.append("")
                    lines.append("[부족 자재]")
                    continue
                if capture:
                    if line.startswith("상세 자재 현황") or line.startswith("="):
                        break
                    lines.append(line)
        else:
            failed_count += 1
            lines.append("판정: 생산 불가능")
            lines.append("강제등록 모드: OFF")
            lines.append("저장: 안 함")
            lines.append("사유: 생산 불가능으로 판단되어 생산계획에 저장하지 않았습니다.")
            capture = False
            for line in answer.splitlines():
                if "[부족 자재]" in line:
                    capture = True
                    lines.append("")
                    lines.append("[부족 자재]")
                    continue
                if capture:
                    if line.startswith("상세 자재 현황") or line.startswith("="):
                        break
                    lines.append(line)

    lines.append("")
    lines.append("=" * 50)
    lines.append("[등록 요약]")
    lines.append(f"저장 완료: {saved_count}개")
    lines.append(f"강제 저장 완료: {force_saved_count}개")
    lines.append(f"저장 보류/중복: {skipped_count}개")
    lines.append(f"생산 불가능: {failed_count}개")
    lines.append("=" * 50)
    lines.append("")
    lines.append(format_plan_list(production_date=production_date))
    return "\n".join(lines)
