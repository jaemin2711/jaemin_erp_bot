import re
import inspect

from plan_product_change import is_product_change_question, handle_product_change_question
from ai_parser import parse_question
from inventory_engine import check_production, build_result
from purchase_order import is_purchase_request_question, create_purchase_request_from_result
from purchase_order_form import is_purchase_order_form_question, create_purchase_order_excel
from date_utils import parse_production_date, remove_date_text
from production_memory import (
    get_planned_consumption_until,
    add_production_plan,
    format_plan_list,
    clear_plans,
    delete_production_plan,
    update_production_plan,
    format_applied_plans_until,
)
from multi_plan import is_multi_production_request, handle_multi_production_request

from summary_commands import (
    is_plan_shortage_summary_question,
    is_shortage_excel_question,
    handle_plan_shortage_summary,
    handle_shortage_excel,
)

def parse_quantity_kg(text: str):
    """
    문장에서 수량을 kg 기준으로 추출한다.
    여러 수량이 있으면 마지막 수량을 우선 사용한다.

    예:
    2톤을 1.5톤으로 변경 -> 1500
    1500kg으로 변경 -> 1500
    """
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


def remove_quantity_text(text: str):
    q = str(text)

    q = re.sub(r"\d+(?:\.\d+)?\s*톤", " ", q, flags=re.IGNORECASE)
    q = re.sub(r"\d+(?:\.\d+)?\s*t(?![a-zA-Z가-힣0-9])", " ", q, flags=re.IGNORECASE)
    q = re.sub(r"\d+(?:\.\d+)?\s*(kg|KG|키로|킬로)", " ", q)

    q = q.replace("천키로", " ")
    q = q.replace("천kg", " ")
    q = q.replace("천킬로", " ")

    q = re.sub(r"\s+", " ", q).strip()

    return q


def clean_product_query_for_plan_command(question: str):
    """
    생산계획 조회/삭제/수정 명령에서 제품명만 최대한 남긴다.
    """
    q = remove_date_text(question)
    q = remove_quantity_text(q)

    remove_words = [
        "생산계획",
        "계획",
        "생산",
        "보여줘",
        "보여",
        "조회",
        "확인",
        "삭제",
        "지워줘",
        "지워",
        "초기화",
        "변경",
        "수정",
        "바꿔줘",
        "바꿔",
        "으로",
        "로",
        "을",
        "를",
        "가능",
        "가능해",
        "가능한지",
    ]

    for word in remove_words:
        q = q.replace(word, " ")

    q = re.sub(r"\s+", " ", q).strip()

    return q if q else None


def is_plan_list_question(question: str):
    q = question.replace(" ", "")

    return (
        ("생산계획" in q or "계획" in q or "일정" in q)
        and ("보여" in q or "조회" in q or "확인" in q)
    )


def is_plan_clear_question(question: str):
    q = question.replace(" ", "")

    return (
        "초기화" in q
        and ("생산계획" in q or "계획" in q)
    )


def is_plan_delete_question(question: str):
    q = question.replace(" ", "")

    return (
        ("삭제" in q or "지워" in q)
        and ("생산계획" in q or "계획" in q)
    )


def is_plan_update_question(question: str):
    q = question.replace(" ", "")

    return (
        ("변경" in q or "수정" in q or "바꿔" in q)
        and ("생산계획" in q or "계획" in q or "생산수량" in q or "kg" in q or "톤" in q)
    )


def correct_intent(question: str, intent: str):
    """
    GPT가 intent를 잘못 분류해도 한 번 더 강제로 보정한다.
    특히 '상세 자재현황 보여줘'가 production_check로 잡혀서
    생산계획에 저장되는 문제를 방지한다.
    """
    q = question.replace(" ", "").lower()

    if (
        "상세" in q
        or "자재현황" in q
        or "전체자재" in q
        or "투입자재" in q
        or "자세히" in q
    ):
        return "detail"

    if (
        "부족" in q
        or "모자" in q
        or "부족자재" in q
        or "부족한것" in q
    ):
        return "shortage_only"

    if (
        "최대" in q
        or "몇kg" in q
        or "몇키로" in q
        or "몇톤" in q
        or "얼마나" in q
    ):
        return "max_possible"

    return intent


def check_with_optional_extra(product_name, quantity, intent, extra_consumption=None):
    """
    inventory_engine.py가 extra_consumption을 지원하면 생산계획 차감 계산을 적용한다.
    """
    sig = inspect.signature(check_production)

    if "extra_consumption" in sig.parameters:
        return check_production(
            product_name,
            float(quantity),
            intent,
            extra_consumption=extra_consumption,
        )

    return check_production(product_name, float(quantity), intent)


def main():
    print("ERP 생산 가능 여부 AI 비서")
    print("예시: 6월 8일 스위트몰라 2톤 생산 가능해?")
    print("예시: 6월 9일 스위트몰라 3톤 생산 가능해?")
    print("예시: 6월 8일 생산계획 등록, 스위트몰라 1톤, PK-BV 10000kg")
    print("예시: 생산계획 보여줘")
    print("예시: 6월 8일 생산계획 보여줘")
    print("예시: 6월 8일 스위트몰라 계획 삭제")
    print("예시: 6월 8일 스위트몰라 1500kg으로 변경")
    print("예시: 상세 자재현황 보여줘")
    print("예시: 생산계획 초기화")
    print("종료하려면 exit 입력")
    print("-" * 50)

    last_product_name = None
    last_quantity = None
    last_date = None
    last_purchase_context = None

    while True:
        question = input("\n질문: ").strip()

        if question.lower() in ["exit", "quit", "종료"]:
            print("종료합니다.")
            break

        try:
            production_date = parse_production_date(question)

            # 사용자가 이번 질문에 날짜를 직접 입력했는지 여부
            # 날짜 없는 이어 묻기는 계산에는 직전 날짜를 쓸 수 있지만,
            # 생산계획 저장은 하지 않는다.
            explicit_production_date = production_date is not None

            # 0-0. 부족 자재 발주요청 생성
            if is_purchase_request_question(question):
                if last_purchase_context is None:
                    print()
                    print("발주요청을 만들 기준이 없습니다.")
                    print("먼저 생산 가능 여부를 확인해주세요.")
                    print("예: 6월 8일 스위트몰라 2톤 생산 가능해?")
                    continue

                order_date = production_date or last_purchase_context.get("production_date")
                order_product = last_purchase_context.get("product_name")
                order_qty = last_purchase_context.get("quantity")

                if not order_product or not order_qty:
                    print()
                    print("발주요청을 만들 제품명 또는 생산수량 정보가 없습니다.")
                    print("먼저 생산 가능 여부를 다시 확인해주세요.")
                    continue

                order_extra_consumption = None

                if order_date:
                    order_extra_consumption = get_planned_consumption_until(order_date)

                order_result = build_result(
                    order_product,
                    float(order_qty),
                    extra_consumption=order_extra_consumption,
                )

                print()
                print(create_purchase_request_from_result(order_result, production_date=order_date))
                continue

            if production_date:
                last_date = production_date

            # 0-0. 구매발주서 엑셀 생성
            if is_purchase_order_form_question(question):
                print()

                try:
                    out_file = create_purchase_order_excel()
                    print("구매발주서를 생성했습니다.")
                    print(f"저장 위치: {out_file}")
                except Exception as e:
                    print("구매발주서 생성 중 오류가 발생했습니다.")
                    print(str(e))
                    print()
                    print("먼저 아래 순서로 진행했는지 확인해주세요.")
                    print("1. 생산 가능 여부 확인")
                    print("2. 부족 자재 발생")
                    print("3. 부족분 발주해줘")
                    print("4. 발주서 만들어줘")

                continue

            # 0-1. 생산계획 기준 부족 자재 엑셀 생성
            if is_shortage_excel_question(question):
                print()
                msg, out_file = handle_shortage_excel(question)
                print(msg)
                continue

            # 0-2. 생산계획 기준 부족 자재 요약
            if is_plan_shortage_summary_question(question):
                print()
                print(handle_plan_shortage_summary(question))
                continue

            # 1. 생산계획 초기화
            if is_plan_clear_question(question):
                print()
                print(clear_plans())
                continue

            # 2. 생산계획 조회
            if is_plan_list_question(question):
                product_key = clean_product_query_for_plan_command(question)

                print()
                print(format_plan_list(production_date=production_date, product_key=product_key))
                continue

            # 3. 생산계획 삭제
            if is_plan_delete_question(question):
                product_key = clean_product_query_for_plan_command(question)

                print()
                print(delete_production_plan(production_date=production_date, product_key=product_key))
                continue

            # 3-1. 제품 자체 변경 + 수량 변경
            if is_product_change_question(question):
                print()
                print(handle_product_change_question(question))
                continue

            # 4. 생산계획 수정
            if is_plan_update_question(question):
                product_key = clean_product_query_for_plan_command(question)
                new_qty = parse_quantity_kg(question)

                if not production_date:
                    print()
                    print("수정하려면 날짜를 포함해주세요.")
                    print("예: 6월 8일 스위트몰라 1500kg으로 변경")
                    continue

                if not product_key:
                    print()
                    print("수정할 제품명을 찾지 못했습니다.")
                    print("예: 6월 8일 스위트몰라 1500kg으로 변경")
                    continue

                if new_qty is None:
                    print()
                    print("변경할 생산수량을 찾지 못했습니다.")
                    print("예: 6월 8일 스위트몰라 1500kg으로 변경")
                    continue

                print()
                print(update_production_plan(production_date, product_key, new_qty))
                continue

            # 4-1. 여러 제품 생산계획 일괄 등록
            if is_multi_production_request(question):
                print()
                print(handle_multi_production_request(question))
                continue

            # 5. 일반 생산 가능 여부 / 부족 / 상세 / 최대 질문
            cleaned_question = remove_date_text(question)
            parsed = parse_question(cleaned_question)

            product_name = parsed.get("product_name")
            quantity = parsed.get("quantity")
            intent = parsed.get("intent", "production_check")
            unit = parsed.get("unit", "kg")

            # GPT intent가 틀려도 질문 문구 기준으로 재보정
            intent = correct_intent(question, intent)

            if not product_name:
                if last_product_name:
                    product_name = last_product_name
                    print(f"\n[참고] 제품명이 없어 직전 제품명 '{product_name}' 기준으로 확인합니다.")
                else:
                    print("\n제품명을 찾지 못했습니다.")
                    print("예: 6월 8일 스위트몰라 2톤 생산 가능해?")
                    continue
            else:
                last_product_name = product_name

            if quantity is None:
                if intent == "max_possible":
                    quantity = last_quantity if last_quantity is not None else 1
                elif last_quantity is not None:
                    quantity = last_quantity
                    print(f"[참고] 수량이 없어 직전 수량 {quantity:,.2f}kg 기준으로 확인합니다.")
                else:
                    print("\n생산수량을 찾지 못했습니다.")
                    print("예: 6월 8일 스위트몰라 2톤 생산 가능해?")
                    continue
            else:
                last_quantity = quantity

            # 날짜가 없는 이어 묻기는 계산용으로만 직전 날짜를 사용
            if not production_date and last_date:
                production_date = last_date

            extra_consumption = None
            applied_plan_text = ""

            if production_date:
                extra_consumption = get_planned_consumption_until(production_date)
                applied_plan_text = format_applied_plans_until(production_date)

            print("\n[질문 분석 결과]")
            print(f"생산일: {production_date if production_date else '미지정'}")
            print(f"제품명: {product_name}")
            print(f"생산수량: {float(quantity):,.2f}kg")
            print(f"질문유형: {intent}")
            print(f"단위: {unit}")

            if production_date:
                print(f"반영 기준: {production_date} 이전/동일 날짜 생산계획 차감")

            if applied_plan_text:
                print()
                print(applied_plan_text)

            answer = check_with_optional_extra(
                product_name,
                float(quantity),
                intent,
                extra_consumption=extra_consumption,
            )

            print("\n" + answer)

            # 부족분 발주요청에 사용할 직전 계산 기준 저장
            last_purchase_context = {
                "production_date": production_date,
                "product_name": product_name,
                "quantity": float(quantity),
            }

            if "판정: 생산 불가능" in answer:
                print()
                print("[발주 안내]")
                print("부족 자재 발주요청서를 만들려면 '부족분 발주해줘'라고 입력하세요.")

            # 직접 날짜를 입력한 production_check 질문만 생산계획으로 저장한다.
            # 상세/부족/최대/날짜 없는 이어묻기는 절대 저장하지 않는다.
            if explicit_production_date and intent == "production_check":
                is_possible = (
                    "판정: 생산 가능" in answer
                    and "판정: 생산 불가능" not in answer
                )

                print()
                print("[생산계획 기억]")

                if is_possible:
                    saved, msg = add_production_plan(
                        production_date,
                        product_name,
                        float(quantity),
                        question=question,
                    )
                    print(msg)
                else:
                    print("생산 불가능으로 판단되어 생산계획에 저장하지 않았습니다.")

        except Exception as e:
            print("\n오류가 발생했습니다.")
            print(str(e))


if __name__ == "__main__":
    main()