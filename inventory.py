import pandas as pd
from pathlib import Path
from datetime import datetime


BOM_FILE = Path("data/bom.xlsx")
STOCK_FILE = Path("data/stock.xlsx")


def load_data():
    if not BOM_FILE.exists():
        raise FileNotFoundError(f"배합비 파일이 없습니다: {BOM_FILE}")

    if not STOCK_FILE.exists():
        raise FileNotFoundError(f"재고 파일이 없습니다: {STOCK_FILE}")

    bom_df = pd.read_excel(BOM_FILE)
    stock_df = pd.read_excel(STOCK_FILE)

    return bom_df, stock_df


def fmt_num(value):
    try:
        value = float(value)
        if value.is_integer():
            return f"{value:,.0f}"
        return f"{value:,.3f}".rstrip("0").rstrip(".")
    except Exception:
        return str(value)
def normalize_unit(unit):
    """
    단위 표기를 비교용으로 통일한다.
    예: kg, KG, Kg, kG → kg
    """
    if unit is None:
        return ""

    unit = str(unit).strip()

    if unit.lower() in ["nan", "none", ""]:
        return ""

    u = unit.replace(" ", "").upper()

    if u in ["KG", "KGS", "KILOGRAM", "KILOGRAMS", "킬로", "키로"]:
        return "kg"

    if u in ["G", "GRAM", "GRAMS", "그램", "그람"]:
        return "g"

    if u in ["EA", "EACH", "PCS", "PC", "개"]:
        return "EA"

    if u in ["L", "LT", "LITER", "LITERS", "리터"]:
        return "L"

    if u in ["ML", "밀리리터"]:
        return "ml"

    return unit

def check_production(product_name: str, request_qty: float):
    bom_df, stock_df = load_data()

    required_bom_cols = ["제품코드", "제품명", "기준수량", "자재코드", "자재명", "소요량", "단위"]
    required_stock_cols = ["자재코드", "자재명", "가용재고", "단위"]

    for col in required_bom_cols:
        if col not in bom_df.columns:
            raise ValueError(f"배합비 파일에 필요한 컬럼이 없습니다: {col}")

    for col in required_stock_cols:
        if col not in stock_df.columns:
            raise ValueError(f"재고 파일에 필요한 컬럼이 없습니다: {col}")

    product_bom = bom_df[
        bom_df["제품명"].astype(str).str.contains(str(product_name), case=False, na=False)
    ].copy()

    if product_bom.empty:
        product_list = bom_df["제품명"].dropna().astype(str).drop_duplicates().head(20).tolist()

        lines = []
        lines.append(f"'{product_name}' 제품의 배합비를 찾을 수 없습니다.")
        lines.append("")
        lines.append("검색 가능한 제품명 예시:")
        for name in product_list:
            lines.append(f"- {name}")

        return "\n".join(lines)

    product_real_name = str(product_bom.iloc[0]["제품명"])
    product_code = str(product_bom.iloc[0]["제품코드"])

    # 숫자 변환
    product_bom["기준수량"] = pd.to_numeric(product_bom["기준수량"], errors="coerce").fillna(0)
    product_bom["소요량"] = pd.to_numeric(product_bom["소요량"], errors="coerce").fillna(0)
    stock_df["가용재고"] = pd.to_numeric(stock_df["가용재고"], errors="coerce").fillna(0)

    # 같은 자재가 여러 줄이면 합산
    grouped_bom = (
        product_bom
        .groupby(["자재코드", "자재명", "단위"], as_index=False)
        .agg({
            "소요량": "sum",
            "기준수량": "max"
        })
    )

    # 재고도 같은 자재코드가 여러 줄이면 합산
    grouped_stock = (
        stock_df
        .groupby(["자재코드"], as_index=False)
        .agg({
            "자재명": "first",
            "가용재고": "sum",
            "단위": "first"
        })
    )

    result_rows = []
    shortage_rows = []
    warning_rows = []
    zero_usage_rows = []

    max_possible_qty = None

    for _, row in grouped_bom.iterrows():
        material_code = str(row["자재코드"]).strip()
        material_name = str(row["자재명"]).strip()
        base_qty = float(row["기준수량"])
        bom_qty = float(row["소요량"])
        bom_unit = normalize_unit(row["단위"])

        if base_qty <= 0:
            warning_rows.append(f"{material_name}: 기준수량이 0 또는 비정상입니다.")
            required_qty = 0
        else:
            required_qty = bom_qty * request_qty / base_qty

        stock_match = grouped_stock[grouped_stock["자재코드"].astype(str).str.strip() == material_code]

        if stock_match.empty:
            available_qty = 0
            stock_unit = bom_unit
            warning_rows.append(f"{material_name}: 재고 파일에서 자재코드 {material_code}를 찾지 못했습니다.")
        else:
            available_qty = float(stock_match.iloc[0]["가용재고"])
            stock_unit = normalize_unit(stock_match.iloc[0]["단위"])

        unit_warning = ""
        if bom_unit and stock_unit and bom_unit != stock_unit:
            unit_warning = f" / 단위 확인 필요: 배합비 {bom_unit}, 재고 {stock_unit}"
            warning_rows.append(f"{material_name}: 배합비 단위({bom_unit})와 재고 단위({stock_unit})가 다릅니다.")

        shortage_qty = max(required_qty - available_qty, 0)

        # 소요량 0인 자재는 최대 생산 가능 수량 계산에서 제외
        if bom_qty <= 0:
            possible_qty_by_material = None
            zero_usage_rows.append(f"{material_name}: 소요량 0으로 최대 생산 가능 수량 계산에서 제외")
        else:
            possible_qty_by_material = available_qty * base_qty / bom_qty

            if max_possible_qty is None:
                max_possible_qty = possible_qty_by_material
            else:
                max_possible_qty = min(max_possible_qty, possible_qty_by_material)

        status = "가능" if shortage_qty == 0 else "부족"

        item = {
            "자재코드": material_code,
            "자재명": material_name,
            "필요수량": required_qty,
            "가용재고": available_qty,
            "부족수량": shortage_qty,
            "배합단위": bom_unit,
            "재고단위": stock_unit,
            "판정": status,
            "단위경고": unit_warning,
        }

        result_rows.append(item)

        if shortage_qty > 0:
            shortage_rows.append(item)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = []
    lines.append("=" * 50)
    lines.append("[생산 가능 여부 확인]")
    lines.append("=" * 50)
    lines.append(f"제품코드: {product_code}")
    lines.append(f"제품명: {product_real_name}")
    lines.append(f"요청 생산수량: {fmt_num(request_qty)}")
    lines.append(f"조회시각: {now}")
    lines.append("")

    if shortage_rows:
        lines.append("판정: 생산 불가능")
        lines.append(f"부족 자재 수: {len(shortage_rows)}개")
    else:
        lines.append("판정: 생산 가능")
        lines.append("현재 가용재고 기준으로 요청 수량 생산 가능합니다.")

    lines.append("")

    if max_possible_qty is not None:
        lines.append(f"현재 재고 기준 최대 생산 가능 수량: {fmt_num(max_possible_qty)}")
    else:
        lines.append("현재 재고 기준 최대 생산 가능 수량: 계산 불가")

    lines.append("")

    if shortage_rows:
        lines.append("[부족 자재]")
        for idx, item in enumerate(shortage_rows, start=1):
            unit = item["배합단위"]
            lines.append(
                f"{idx}. {item['자재코드']} / {item['자재명']}\n"
                f"   필요: {fmt_num(item['필요수량'])}{unit} / "
                f"가용: {fmt_num(item['가용재고'])}{item['재고단위']} / "
                f"부족: {fmt_num(item['부족수량'])}{unit}"
                f"{item['단위경고']}"
            )
        lines.append("")

    lines.append("[상세 자재 현황]")
    for item in result_rows:
        unit = item["배합단위"]
        lines.append(
            f"- {item['자재코드']} / {item['자재명']}: "
            f"필요 {fmt_num(item['필요수량'])}{unit} / "
            f"가용 {fmt_num(item['가용재고'])}{item['재고단위']} / "
            f"판정 {item['판정']}"
            f"{item['단위경고']}"
        )

    if warning_rows:
        lines.append("")
        lines.append("[확인 필요]")
        for w in warning_rows:
            lines.append(f"- {w}")

    if zero_usage_rows:
        lines.append("")
        lines.append("[소요량 0 자재]")
        for z in zero_usage_rows:
            lines.append(f"- {z}")

    lines.append("=" * 50)

    return "\n".join(lines)


if __name__ == "__main__":
    product = input("제품명을 입력하세요: ")
    qty = float(input("생산수량을 입력하세요: "))

    answer = check_production(product, qty)
    print()
    print(answer)