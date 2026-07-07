import pandas as pd
from pathlib import Path
from datetime import datetime

from inventory_engine import load_data, normalize_unit, fmt_num
from production_memory import load_plans, calculate_material_consumption


RESULT_DIR = Path("data/results")


def build_total_plan_consumption(production_date=None):
    """
    저장된 생산계획 전체 또는 특정 날짜까지의 생산계획 기준으로
    자재별 총 필요량을 계산한다.
    """
    plans = load_plans()

    if plans.empty:
        return {}, plans

    plans = plans.copy()
    plans["생산일"] = plans["생산일"].astype(str)

    if production_date:
        plans = plans[plans["생산일"] <= str(production_date)].copy()

    total_consumption = {}

    for _, plan in plans.iterrows():
        product_code = str(plan["제품코드"]).strip()
        product_name = str(plan["제품명"]).strip()
        qty = float(plan["생산수량kg"])

        product_key = product_code if product_code and product_code.lower() != "nan" else product_name

        consumption = calculate_material_consumption(product_key, qty)

        for material_code, amount in consumption.items():
            total_consumption[material_code] = total_consumption.get(material_code, 0) + amount

    return total_consumption, plans


def build_shortage_summary(production_date=None):
    """
    생산계획 기준 전체 부족 자재 요약 생성.
    """
    bom_df, stock_df = load_data()
    total_consumption, used_plans = build_total_plan_consumption(production_date)

    if used_plans.empty:
        return {
            "has_plan": False,
            "message": "저장된 생산계획이 없습니다.",
            "rows": [],
            "plans": used_plans,
        }

    if not total_consumption:
        return {
            "has_plan": True,
            "message": "생산계획은 있지만 계산할 자재 소요량이 없습니다.",
            "rows": [],
            "plans": used_plans,
        }

    stock_df = stock_df.copy()
    stock_df["가용재고"] = pd.to_numeric(stock_df["가용재고"], errors="coerce").fillna(0)

    grouped_stock = (
        stock_df
        .groupby(["자재코드"], as_index=False)
        .agg({
            "자재명": "first",
            "가용재고": "sum",
            "단위": "first",
        })
    )

    rows = []

    for material_code, required_qty in total_consumption.items():
        stock_match = grouped_stock[
            grouped_stock["자재코드"].astype(str).str.strip() == str(material_code).strip()
        ]

        if stock_match.empty:
            material_name = ""
            available_qty = 0
            unit = "kg"
        else:
            material_name = str(stock_match.iloc[0]["자재명"]).strip()
            available_qty = float(stock_match.iloc[0]["가용재고"])
            unit = normalize_unit(stock_match.iloc[0]["단위"])

        shortage_qty = max(required_qty - available_qty, 0)
        remain_qty = available_qty - required_qty

        rows.append({
            "자재코드": material_code,
            "자재명": material_name,
            "총필요수량": required_qty,
            "가용재고": available_qty,
            "부족수량": shortage_qty,
            "예상잔량": remain_qty,
            "단위": unit,
            "판정": "부족" if shortage_qty > 0 else "가능",
        })

    rows.sort(key=lambda x: (x["판정"] != "부족", -x["부족수량"]))

    return {
        "has_plan": True,
        "message": "생산계획 기준 자재 요약을 계산했습니다.",
        "rows": rows,
        "plans": used_plans,
    }


def format_shortage_summary(production_date=None, only_shortage=True):
    """
    텔레그램/CMD 출력용 부족 자재 요약.
    """
    result = build_shortage_summary(production_date)

    if not result["has_plan"]:
        return result["message"]

    rows = result["rows"]

    if only_shortage:
        rows = [r for r in rows if r["부족수량"] > 0]

    lines = []
    lines.append("=" * 50)

    if production_date:
        lines.append(f"[{production_date}까지 생산계획 기준 부족 자재 요약]")
    else:
        lines.append("[전체 생산계획 기준 부족 자재 요약]")

    lines.append("=" * 50)
    lines.append(f"조회시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    plans = result["plans"]

    lines.append("[반영된 생산계획]")
    for _, plan in plans.iterrows():
        lines.append(
            f"- {plan['생산일']} / {plan['제품코드']} / {plan['제품명']} / "
            f"{fmt_num(plan['생산수량kg'])}kg"
        )

    lines.append("")

    if not rows:
        lines.append("부족 자재 없음")
        lines.append("현재 저장된 생산계획 기준으로는 부족 자재가 없습니다.")
        lines.append("=" * 50)
        return "\n".join(lines)

    shortage_count = sum(1 for r in rows if r["부족수량"] > 0)

    if only_shortage:
        lines.append(f"[부족 자재] {len(rows)}개")
    else:
        lines.append(f"[자재 전체 요약] 부족 {shortage_count}개 / 전체 {len(rows)}개")

    lines.append("")

    for idx, item in enumerate(rows, start=1):
        lines.append(
            f"{idx}. {item['자재코드']} / {item['자재명']}\n"
            f"   총필요: {fmt_num(item['총필요수량'])}{item['단위']} / "
            f"가용: {fmt_num(item['가용재고'])}{item['단위']} / "
            f"부족: {fmt_num(item['부족수량'])}{item['단위']} / "
            f"예상잔량: {fmt_num(item['예상잔량'])}{item['단위']}"
        )

    lines.append("=" * 50)

    return "\n".join(lines)


def export_shortage_summary_excel(production_date=None, only_shortage=True):
    """
    생산계획 기준 부족 자재 요약을 엑셀로 저장한다.
    """
    result = build_shortage_summary(production_date)

    if not result["has_plan"]:
        return False, result["message"], None

    rows = result["rows"]

    if only_shortage:
        rows = [r for r in rows if r["부족수량"] > 0]

    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    date_text = production_date if production_date else "all"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    out_file = RESULT_DIR / f"shortage_summary_{date_text}_{timestamp}.xlsx"

    summary_df = pd.DataFrame(rows)

    plans_df = result["plans"].copy()

    with pd.ExcelWriter(out_file, engine="openpyxl") as writer:
        plans_df.to_excel(writer, index=False, sheet_name="반영생산계획")
        summary_df.to_excel(writer, index=False, sheet_name="부족자재요약")

    return True, f"엑셀 파일을 생성했습니다: {out_file}", out_file


if __name__ == "__main__":
    print(format_shortage_summary())