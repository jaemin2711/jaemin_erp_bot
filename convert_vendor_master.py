import re
import pandas as pd
from pathlib import Path
from datetime import datetime


DATA_DIR = Path("data")
OUT_FILE = DATA_DIR / "vendor_master.xlsx"
SUPPLIER_INFO_FILE = DATA_DIR / "supplier_info.xlsx"


VENDOR_COLUMNS = [
    "품번",
    "품명",
    "구매거래처",
    "단가",
    "단가기준일",
    "업체명",
    "대표자",
    "사업자번호",
    "주소",
    "담당자",
    "TEL",
    "FAX",
    "E-Mail",
    "규격",
    "단위",
    "제조사",
]


SUPPLIER_INFO_COLUMNS = [
    "구매거래처",
    "업체명",
    "대표자",
    "사업자번호",
    "주소",
    "담당자",
    "TEL",
    "FAX",
    "E-Mail",
]


def normalize_col_name(value):
    text = str(value).strip()
    text = text.replace("\n", "")
    text = text.replace("\r", "")
    text = text.replace("\t", "")
    text = text.replace(" ", "")
    return text


def normalize_text(value):
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in ["nan", "none"]:
        return ""

    return text


def to_number(value):
    try:
        text = str(value).replace(",", "").strip()
        if text == "" or text.lower() in ["nan", "none"]:
            return 0
        return float(text)
    except Exception:
        return 0


def get_file_date(file: Path):
    """
    구매발주품목조회_20260608.xlsx 파일명에서 날짜 추출.
    """
    match = re.search(r"구매발주품목조회_(\d{8})", file.name)

    if match:
        date_text = match.group(1)
        try:
            return datetime.strptime(date_text, "%Y%m%d").strftime("%Y-%m-%d")
        except Exception:
            pass

    return datetime.fromtimestamp(file.stat().st_mtime).strftime("%Y-%m-%d")


def find_purchase_item_files():
    files = []

    for file in DATA_DIR.glob("구매발주품목조회_*.xlsx"):
        if file.name.startswith("~$"):
            continue

        files.append(file)

    if not files:
        fallback = DATA_DIR / "purchase_items_raw.xlsx"
        if fallback.exists():
            return [fallback]

        raise FileNotFoundError(
            "구매발주품목조회 원본 엑셀을 찾지 못했습니다.\n"
            "data 폴더에 '구매발주품목조회_YYYYMMDD.xlsx' 파일을 넣어주세요."
        )

    files.sort(key=lambda x: (get_file_date(x), x.stat().st_mtime), reverse=True)

    return files


def find_header_row(preview):
    """
    상단 제목/빈 줄을 건너뛰고 품번, 품명 또는 구매거래처가 있는 헤더 행을 찾는다.
    """
    for i in range(min(30, len(preview))):
        row_values = [normalize_col_name(v) for v in preview.iloc[i].tolist()]

        has_item_code = any(v in ["품번", "품목번호", "품목코드", "자재코드"] for v in row_values)
        has_item_name = any(v in ["품명", "품목명", "자재명"] for v in row_values)
        has_vendor = any(v in ["구매거래처", "거래처", "공급처", "매입처"] for v in row_values)

        if has_item_code and has_item_name:
            return i

        if has_item_code and has_vendor:
            return i

    raise ValueError("엑셀에서 품번/품명 헤더 행을 찾지 못했습니다.")


def pick_column(df, aliases, required=True):
    """
    여러 후보 컬럼명 중 실제 엑셀에 있는 컬럼을 찾는다.
    """
    normalized_map = {}

    for col in df.columns:
        normalized_map[normalize_col_name(col)] = col

    for alias in aliases:
        key = normalize_col_name(alias)
        if key in normalized_map:
            return normalized_map[key]

    if required:
        raise ValueError(f"필수 컬럼을 찾지 못했습니다. 후보: {aliases}")

    return None


def load_supplier_info():
    """
    세부 거래처 정보 파일.
    없으면 빈 양식 파일을 만들어준다.
    """
    if not SUPPLIER_INFO_FILE.exists():
        empty_df = pd.DataFrame(columns=SUPPLIER_INFO_COLUMNS)
        SUPPLIER_INFO_FILE.parent.mkdir(exist_ok=True)
        empty_df.to_excel(SUPPLIER_INFO_FILE, index=False)

        return empty_df

    df = pd.read_excel(SUPPLIER_INFO_FILE)

    for col in SUPPLIER_INFO_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df[SUPPLIER_INFO_COLUMNS].copy()
    df["구매거래처"] = df["구매거래처"].astype(str).str.strip()

    return df


def convert_one_file(file: Path):
    file_date = get_file_date(file)

    preview = pd.read_excel(file, header=None)
    header_row = find_header_row(preview)

    df = pd.read_excel(file, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    df = df.loc[:, ~df.columns.str.contains("^Unnamed", na=False)]
    df = df.loc[:, df.columns.str.lower() != "nan"]

    print(f"\n원본 파일: {file}")
    print(f"기준일: {file_date}")
    print("읽은 컬럼 목록:")
    for c in df.columns:
        print("-", c)

    item_code_col = pick_column(df, ["품번", "품목번호", "품목코드", "자재코드"])
    item_name_col = pick_column(df, ["품명", "품목명", "자재명"])
    vendor_col = pick_column(df, ["구매거래처", "거래처", "공급처", "매입처"])
    price_col = pick_column(df, ["단가", "구매단가", "매입단가"], required=False)

    spec_col = pick_column(df, ["규격", "규격/상세", "규격상세"], required=False)
    unit_col = pick_column(df, ["단위", "구매단위", "재고단위"], required=False)
    maker_col = pick_column(df, ["제조사", "메이커", "Maker"], required=False)

    out = pd.DataFrame()
    out["품번"] = df[item_code_col].astype(str).str.strip()
    out["품명"] = df[item_name_col].astype(str).str.strip()
    out["구매거래처"] = df[vendor_col].astype(str).str.strip()

    if price_col:
        out["단가"] = df[price_col].apply(to_number)
    else:
        out["단가"] = 0

    out["단가기준일"] = file_date

    out["규격"] = df[spec_col].astype(str).str.strip() if spec_col else ""
    out["단위"] = df[unit_col].astype(str).str.strip() if unit_col else ""
    out["제조사"] = df[maker_col].astype(str).str.strip() if maker_col else ""

    out = out[out["품번"].notna()]
    out = out[out["품번"] != ""]
    out = out[out["품번"].str.lower() != "nan"]
    out = out[out["품번"] != "품번"]

    out = out[out["구매거래처"].notna()]
    out = out[out["구매거래처"].str.lower() != "nan"]

    return out


def main():
    print("=" * 50)
    print("구매 거래처/단가 마스터 변환 시작")
    print("=" * 50)

    DATA_DIR.mkdir(exist_ok=True)

    files = find_purchase_item_files()

    all_rows = []

    for file in files:
        try:
            converted = convert_one_file(file)
            all_rows.append(converted)
        except Exception as e:
            print(f"[주의] 파일 변환 실패: {file}")
            print(e)

    if not all_rows:
        raise ValueError("변환할 구매발주품목 데이터가 없습니다.")

    vendor_df = pd.concat(all_rows, ignore_index=True)

    vendor_df["품번"] = vendor_df["품번"].astype(str).str.strip()
    vendor_df["구매거래처"] = vendor_df["구매거래처"].astype(str).str.strip()
    vendor_df["단가"] = pd.to_numeric(vendor_df["단가"], errors="coerce").fillna(0)

    vendor_df["_단가기준일"] = pd.to_datetime(vendor_df["단가기준일"], errors="coerce")

    # 핵심:
    # 같은 품번이 여러 날짜에 있으면 가장 최근 단가를 사용한다.
    # 같은 품번+거래처가 여러 개여도 최근 날짜 우선.
    vendor_df = vendor_df.sort_values(["품번", "_단가기준일"], ascending=[True, True])
    vendor_df = vendor_df.drop_duplicates(subset=["품번"], keep="last")

    vendor_df = vendor_df.drop(columns=["_단가기준일"])

    supplier_df = load_supplier_info()

    if not supplier_df.empty:
        supplier_df["구매거래처"] = supplier_df["구매거래처"].astype(str).str.strip()

        vendor_df = vendor_df.merge(
            supplier_df,
            on="구매거래처",
            how="left",
            suffixes=("", "_거래처정보")
        )
    else:
        for col in ["업체명", "대표자", "사업자번호", "주소", "담당자", "TEL", "FAX", "E-Mail"]:
            vendor_df[col] = ""

    # 업체명 없으면 구매거래처를 업체명으로 임시 사용
    vendor_df["업체명"] = vendor_df["업체명"].fillna("")
    vendor_df.loc[vendor_df["업체명"].astype(str).str.strip() == "", "업체명"] = vendor_df["구매거래처"]

    for col in VENDOR_COLUMNS:
        if col not in vendor_df.columns:
            vendor_df[col] = ""

    vendor_df = vendor_df[VENDOR_COLUMNS].copy()
    vendor_df = vendor_df.sort_values(["구매거래처", "품번"], ascending=True)

    OUT_FILE.parent.mkdir(exist_ok=True)
    vendor_df.to_excel(OUT_FILE, index=False)

    print()
    print("=" * 50)
    print("구매 거래처/단가 마스터 변환 완료")
    print("=" * 50)
    print(f"저장 위치: {OUT_FILE}")
    print(f"세부 거래처 정보 파일: {SUPPLIER_INFO_FILE}")
    print(f"총 품목 수: {len(vendor_df)}")
    print()
    print(vendor_df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()