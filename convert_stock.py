import re
import pandas as pd
from pathlib import Path


DATA_DIR = Path("data")
OUT_FILE = DATA_DIR / "stock.xlsx"
TARGET_STOCK_COL_KEYWORD = "원/부자재창고"


def find_latest_stock_file():
    """
    data 폴더에서 창고별 재고조회_YYYYMMDD.xlsx 형식의 파일 중
    가장 최신 파일을 자동으로 찾는다.
    """
    files = []

    for file in DATA_DIR.glob("창고별 재고조회_*.xlsx"):
        if file.name.startswith("~$"):
            continue

        match = re.search(r"창고별 재고조회_(\d{8})", file.name)

        if match:
            date_num = int(match.group(1))
        else:
            date_num = 0

        files.append((date_num, file.stat().st_mtime, file))

    if not files:
        fallback = DATA_DIR / "erp_stock_raw.xlsx"
        if fallback.exists():
            return fallback

        raise FileNotFoundError(
            "재고 원본 엑셀을 찾지 못했습니다.\n"
            "data 폴더에 '창고별 재고조회_YYYYMMDD.xlsx' 파일을 넣어주세요."
        )

    files.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return files[0][2]


def find_header_row(preview):
    """
    영림원 엑셀 상단 제목/빈 줄을 건너뛰고
    품번, 품명 헤더가 있는 행을 찾는다.
    """
    for i in range(min(20, len(preview))):
        row_values = [str(v).strip() for v in preview.iloc[i].tolist()]
        if "품번" in row_values and "품명" in row_values:
            return i

    raise ValueError("엑셀에서 '품번', '품명' 헤더 행을 찾지 못했습니다.")


def normalize_col_name(value):
    """
    컬럼명 비교용 정리.
    줄바꿈, 공백, 특수문자 차이 때문에 못 찾는 문제 방지.
    """
    text = str(value).strip()
    text = text.replace("\n", "")
    text = text.replace("\r", "")
    text = text.replace(" ", "")
    text = text.replace("\t", "")
    return text


def pick_stock_column(df):
    """
    재고 기준 컬럼 선택.

    중요:
    생산가능 여부는 반드시 '원/부자재창고' 컬럼만 사용한다.
    전체 재고수량 컬럼은 절대 사용하지 않는다.
    """
    columns = list(df.columns)

    print("\n읽은 컬럼 목록:")
    for c in columns:
        print("-", c)

    # 1순위: 정확히 원/부자재창고 컬럼 찾기
    for c in columns:
        normalized = normalize_col_name(c)

        if "원/부자재창고" in normalized or "원부자재창고" in normalized:
            return c

    # 여기까지 왔다는 건 원/부자재창고 컬럼을 못 찾은 것
    # 절대 '재고수량'으로 대체하지 않는다.
    raise ValueError(
        "\n원/부자재창고 컬럼을 찾지 못했습니다.\n"
        "전체 재고수량으로 대체하지 않습니다.\n"
        "엑셀에 '원/부자재창고' 컬럼이 있는지 확인해주세요.\n"
    )


def to_number(series):
    """
    콤마가 들어간 숫자 문자도 숫자로 변환.
    """
    return (
        series
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
        .replace("", "0")
        .pipe(pd.to_numeric, errors="coerce")
        .fillna(0)
    )


def main():
    raw_file = find_latest_stock_file()

    print("=" * 50)
    print("재고 엑셀 변환 시작")
    print("=" * 50)
    print(f"선택된 원본 파일: {raw_file}")

    preview = pd.read_excel(raw_file, header=None)
    header_row = find_header_row(preview)

    df = pd.read_excel(raw_file, header=header_row)

    # 컬럼명 정리
    df.columns = [str(c).strip() for c in df.columns]

    # 빈 컬럼 제거
    df = df.loc[:, ~df.columns.str.contains("^Unnamed", na=False)]
    df = df.loc[:, df.columns.str.lower() != "nan"]

    required_cols = ["품번", "품명", "단위"]

    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"필수 컬럼이 없습니다: {col}")

    stock_col = pick_stock_column(df)

    # 안전장치: 선택된 컬럼이 원/부자재창고가 아니면 중단
    normalized_stock_col = normalize_col_name(stock_col)

    if "원/부자재창고" not in normalized_stock_col and "원부자재창고" not in normalized_stock_col:
        raise ValueError(
            f"잘못된 재고 컬럼이 선택되었습니다: {stock_col}\n"
            "생산가능 여부는 반드시 원/부자재창고 기준이어야 합니다."
        )

    stock_df = pd.DataFrame()
    stock_df["자재코드"] = df["품번"].astype(str).str.strip()
    stock_df["자재명"] = df["품명"].astype(str).str.strip()

    # 핵심: 전체 재고수량이 아니라 원/부자재창고 컬럼만 현재고로 저장
    stock_df["현재고"] = to_number(df[stock_col])

    stock_df["예약수량"] = 0
    stock_df["보류수량"] = 0
    stock_df["가용재고"] = stock_df["현재고"] - stock_df["예약수량"] - stock_df["보류수량"]
    stock_df["단위"] = df["단위"].astype(str).str.strip()
    stock_df["재고기준창고"] = "원/부자재창고"

    # 품번 없는 행 제거
    stock_df = stock_df[stock_df["자재코드"].notna()]
    stock_df = stock_df[stock_df["자재코드"] != ""]
    stock_df = stock_df[stock_df["자재코드"].str.lower() != "nan"]
    stock_df = stock_df[stock_df["자재코드"].str.upper() != "TOTAL"]
    stock_df = stock_df[stock_df["자재코드"] != "품번"]

    OUT_FILE.parent.mkdir(exist_ok=True)
    stock_df.to_excel(OUT_FILE, index=False)

    print()
    print("=" * 50)
    print("재고 변환 완료")
    print("=" * 50)
    print(f"사용한 재고 컬럼: {stock_col}")
    print("재고 기준: 원/부자재창고")
    print(f"저장 위치: {OUT_FILE}")
    print(f"총 행 수: {len(stock_df)}")
    print()
    print(stock_df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()