import re
import pandas as pd
from pathlib import Path
from datetime import datetime


PURCHASE_FILE = Path("data/purchase_request.xlsx")


PURCHASE_COLUMNS = [
    "발주요청번호",
    "발주요청일시",
    "생산일",
    "제품코드",
    "제품명",
    "자재코드",
    "자재명",
    "필요수량",
    "가용재고",
    "부족수량",
    "발주요청수량",
    "단위",
    "상태",
    "비고",
]


def fmt_num(value):
    try:
        value = float(value)
        if value.is_integer():
            return f"{value:,.0f}"
        return f"{value:,.3f}".rstrip("0").rstrip(".")
    except Exception:
        return str(value)


def load_purchase_requests():
    if not PURCHASE_FILE.exists():
        return pd.DataFrame(columns=PURCHASE_COLUMNS)

    df = pd.read_excel(PURCHASE_FILE)

    for col in PURCHASE_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[PURCHASE_COLUMNS].copy()


def save_purchase_requests(df):
    PURCHASE_FILE.parent.mkdir(exist_ok=True)

    if df.empty:
        df = pd.DataFrame(columns=PURCHASE_COLUMNS)
    else:
        for col in PURCHASE_COLUMNS:
            if col not in df.columns:
                df[col] = ""

        df = df[PURCHASE_COLUMNS].copy()

    df.to_excel(PURCHASE_FILE, index=False)


def make_purchase_no():
    return "PO" + datetime.now().strftime("%Y%m%d%H%M%S")


def is_purchase_request_question(question: str):
    """
    발주 요청 명령 감지.
    예:
    - 부족분 발주해줘
    - 부족 자재 발주 진행
    - 발주요청 만들어줘
    - 발주 등록
    """
    q = str(question).replace(" ", "")

    if "발주" not in q:
        return False

    keywords = [
        "부족",
        "요청",
        "진행",
        "등록",
        "만들",
        "생성",
        "해줘",
    ]

    return any(word in q for word in keywords)


def create_purchase_request_from_result(result, production_date=None):
    """
    inventory_engine.build_result() 결과에서 부족 자재만 발주요청으로 저장한다.
    """
    if not result:
        return "발주요청을 만들 계산 결과가 없습니다. 먼저 생산 가능 여부를 확인해주세요."

    if not result.get("found"):
        return "제품 배합비를 찾지 못한 상태라 발주요청을 만들 수 없습니다."

    shortages = result.get("부족", [])

    if not shortages:
        return "부족 자재가 없어 발주요청을 만들지 않았습니다."

    purchase_df = load_purchase_requests()

    purchase_no = make_purchase_no()
    request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    product_code = result.get("제품코드", "")
    product_name = result.get("제품명", "")
    production_date = production_date or ""

    new_rows = []
    skipped_rows = []

    for item in shortages:
        material_code = str(item.get("자재코드", "")).strip()
        material_name = str(item.get("자재명", "")).strip()

        need_qty = float(item.get("필요수량", 0))
        available_qty = float(item.get("가용재고", 0))
        shortage_qty = float(item.get("부족수량", 0))
        unit = str(item.get("배합단위", item.get("재고단위", ""))).strip()

        if shortage_qty <= 0:
            continue

        # 같은 생산일/제품/자재가 이미 발주대기 또는 발주진행이면 중복 생성 방지
        if not purchase_df.empty:
            dup = purchase_df[
                (purchase_df["생산일"].astype(str) == str(production_date)) &
                (purchase_df["제품코드"].astype(str) == str(product_code)) &
                (purchase_df["자재코드"].astype(str) == str(material_code)) &
                (purchase_df["상태"].astype(str).isin(["발주대기", "발주진행"]))
            ]

            if not dup.empty:
                skipped_rows.append(f"{material_code} / {material_name}")
                continue

        new_rows.append({
            "발주요청번호": purchase_no,
            "발주요청일시": request_time,
            "생산일": production_date,
            "제품코드": product_code,
            "제품명": product_name,
            "자재코드": material_code,
            "자재명": material_name,
            "필요수량": need_qty,
            "가용재고": available_qty,
            "부족수량": shortage_qty,
            "발주요청수량": shortage_qty,
            "단위": unit,
            "상태": "발주대기",
            "비고": "생산 가능 여부 확인 중 부족 자재 자동 생성",
        })

    if not new_rows:
        lines = []
        lines.append("새로 생성된 발주요청이 없습니다.")
        if skipped_rows:
            lines.append("")
            lines.append("이미 발주대기/발주진행 상태인 자재:")
            for item in skipped_rows:
                lines.append(f"- {item}")
        return "\n".join(lines)

    purchase_df = pd.concat([purchase_df, pd.DataFrame(new_rows)], ignore_index=True)
    save_purchase_requests(purchase_df)

    lines = []
    lines.append("부족 자재 발주요청을 생성했습니다.")
    lines.append("")
    lines.append(f"발주요청번호: {purchase_no}")
    lines.append(f"저장 위치: {PURCHASE_FILE}")
    lines.append("")
    lines.append("[발주요청 자재]")

    for idx, row in enumerate(new_rows, start=1):
        lines.append(
            f"{idx}. {row['자재코드']} / {row['자재명']} / "
            f"발주요청수량 {fmt_num(row['발주요청수량'])}{row['단위']}"
        )

    if skipped_rows:
        lines.append("")
        lines.append("[중복으로 제외된 자재]")
        for item in skipped_rows:
            lines.append(f"- {item}")

    return "\n".join(lines)