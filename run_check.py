import sys
from datetime import datetime
from pathlib import Path
import pandas as pd

# -----------------------------------------------------------------------------
# 1. 기존 엔진 및 생산계획 모듈 임포트
# -----------------------------------------------------------------------------
try:
    from inventory_engine import check_production, build_result
    from production_memory import (
        get_planned_consumption_until,
        get_product_info,
        add_production_plan,
        load_plans,  # 엑셀 계획을 읽어오기 위해 추가
        fmt_num
    )
except ImportError as e:
    print(f"❌ 모듈 임포트 실패: {e}")
    print("inventory_engine.py와 production_memory.py 파일이 'run_check.py'와 같은 폴더에 있는지 확인하세요.")
    sys.exit(1)


# -----------------------------------------------------------------------------
# 2. [기능 1] 등록할 때 가능 여부를 명확히 판정하고 알려주는 함수
# -----------------------------------------------------------------------------
def smart_check_and_add_plan(production_date, product_key, qty_kg, question="", intent="production_check"):
    """
    등록 요청이 들어왔을 때 가용성을 체크하여 
    '생산 가능/불가능' 여부를 유저에게 명확히 알리고 안전하게 등록합니다.
    """
    product_info = get_product_info(product_key)
    if not product_info:
        return f"❌ '{product_key}' 제품의 배합비 정보를 찾을 수 없습니다."
    
    product_name = product_info["제품명"]
    
    # 지정일 이전까지의 누적 소요량 계산
    extra_consumption = get_planned_consumption_until(production_date)
    
    # 자재 검증 리포트 및 결과 데이터 빌드
    report_text = check_production(
        product_name=product_name,
        request_qty=qty_kg,
        intent=intent,
        extra_consumption=extra_consumption
    )
    
    result_dict = build_result(product_name, qty_kg, extra_consumption=extra_consumption)
    shortage_list = result_dict.get("부족", [])
    
    # 부족 여부 판정
    has_shortage = False
    if isinstance(shortage_list, list) and len(shortage_list) > 0:
        has_shortage = True
    elif "부족" in report_text or "불가능" in report_text:
        has_shortage = True
            
    # 결과 출력 조립
    if result_dict.get("found") and not has_shortage:
        # 가용 재고가 충분한 경우 등록 진행
        success, message = add_production_plan(production_date, product_key, qty_kg, question)
        
        final_response = (
            f"✅ [생산 가능 판정]\n"
            f"현재 원/부자재 창고 재고로 {product_name} {fmt_num(qty_kg)}kg 생산이 가능합니다.\n\n"
            f"{report_text}\n\n"
            f"💾 [시스템 계획 등록 결과]\n"
            f"└ {message}"
        )
    else:
        # 자재가 부족해도 일단 등록은 하되, '⚠️ 불가능/자재부족' 상태임을 확실히 경고
        # (만약 자재가 부족할 때 등록 자체를 막고 싶다면 아래 add_production_plan 줄을 지우시면 됩니다)
        success, message = add_production_plan(production_date, product_key, qty_kg, question)
        
        final_response = (
            f"❌ [생산 불가능 판정 - 자재 부족]\n"
            f"⚠️ 원부자재 재고가 부족합니다! 하지만 요청하신 계획은 일단 엑셀에 기록되었습니다.\n\n"
            f"{report_text}\n\n"
            f"💾 [시스템 계획 등록 결과]\n"
            f"└ {message}"
        )
        
    return final_response


# -----------------------------------------------------------------------------
# 3. [기능 2] "생산계획 자재부족확인" 명령어용 전체 기억 내역 검증 함수
# -----------------------------------------------------------------------------
def check_all_remembered_plans():
    """
    엑셀(production_plan.xlsx)에 기억된 모든 생산계획을 처음부터 끝까지 읽어서
    각 계획별로 현재 창고 재고 기준 '생산 가능 여부'를 전부 확인해 주는 함수입니다.
    """
    # 1. 등록된 계획 파일 로드
    try:
        plans_df = load_plans()
    except Exception as e:
        return f"❌ 생산계획 파일을 읽어오는 중 오류가 발생했습니다: {e}"
        
    if plans_df.empty:
        return "📂 현재 등록된 생산계획이 없거나 파일이 비어 있습니다."
        
    lines = []
    lines.append("=" * 60)
    lines.append(f"📋 [현재 기억된 생산계획 전체 가능여부 확인] 조회시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 60)
    
    # 날짜 순서대로 정렬해서 보기 좋게 출력
    if "생산일자" in plans_df.columns:
        plans_df = plans_df.sort_values(by="생산일자")
        
    # 누적 차감을 시뮬레이션하기 위한 빈 딕셔너리
    running_extra_consumption = {}
    
    # 2. 기억된 계획을 하나씩 순회하며 검증
    for idx, row in plans_df.iterrows():
        p_date = str(row.get("생산일자", "")).split(" ")[0] # 날짜 포맷 정리
        p_key = str(row.get("제품코드", row.get("제품명", "")))
        p_qty = float(row.get("생산수량(kg)", row.get("수량", 0)))
        
        product_info = get_product_info(p_key)
        if not product_info:
            lines.append(f"📍 [{p_date}] {p_key} {fmt_num(p_qty)}kg -> ❌ 배합비 없음 (확인 불가)")
            continue
            
        p_name = product_info["제품명"]
        
        # 현재 계획을 검증 (이전 계획들이 먹은 자재 running_extra_consumption 반영)
        result_dict = build_result(p_name, p_qty, extra_consumption=running_extra_consumption)
        shortage_list = result_dict.get("부족", [])
        
        # 가능 여부 판단
        if isinstance(shortage_list, list) and len(shortage_list) > 0:
            status_text = f"❌ 생산 불가능 (부족 자재: {len(shortage_list)}개 항목)"
            # 어떤 자재가 부족한지 간략히 표시
            short_mats = [f"{m['자재명']}({fmt_num(m['부족수량'])}{m['배합단위']} 부족)" for m in shortage_list]
            detail_text = f"    └ 부족내역: {', '.join(short_mats)}"
        else:
            status_text = "✅ 생산 가능 (자재 여유)"
            detail_text = "    └ 원/부자재 가용 재고 충족"
            
        lines.append(f"📍 [{p_date}] {p_name} ({fmt_num(p_qty)}kg) -> {status_text}")
        lines.append(detail_text)
        
        # [핵심] 다음 날짜 계획 검증을 위해 현재 계획이 사용한 자재 소요량을 누적 시킵니다.
        # 이 처리를 해야 7/14이 자재를 먹고 남은 잔량으로 8/14을 정확하게 판정합니다.
        for mat_item in result_dict.get("상세", []):
            m_code = mat_item["자재코드"]
            m_req = mat_item["필요수량"]
            running_extra_consumption[m_code] = running_extra_consumption.get(m_code, 0) + m_req
            
        lines.append("-" * 60)
        
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# 4. 단독 실행 및 명령어 시뮬레이션용 메인 블록
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("⚙️ 시스템 구동 모드를 선택하세요.")
    print("1. 새 생산계획 등록 및 가능여부 확인")
    print("2. 생산계획 자재부족확인 (전체 기억 내용 검증)")
    
    mode = input("번호를 입력하세요 (1 또는 2): ").strip()
    
    if mode == "1":
        print("\n--- [1. 새 생산계획 등록 모드] ---")
        input_date = input("생산일 입력 (예: 7/14): ").strip()
        input_product = input("제품명/코드 입력 (예: ir2-dog): ").strip()
        input_qty = input("생산수량(kg) 입력 (예: 10000): ").strip()
        
        try:
            qty = float(input_qty)
            output = smart_check_and_add_plan(input_date, input_product, qty, question="수동등록")
            print("\n" + output)
        except ValueError:
            print("❌ 수량은 숫자만 입력해 주세요.")
            
    elif mode == "2" or mode == "생산계획 자재부족확인":
        print("\n--- [2. 전체 생산계획 자재부족확인 모드] ---")
        output = check_all_remembered_plans()
        print("\n" + output)
        
    else:
        print("❌ 올바른 모드를 선택해 주세요.")