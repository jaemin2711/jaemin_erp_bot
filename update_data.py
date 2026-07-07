import subprocess
from pathlib import Path
import sys
import re
import pandas as pd


BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

BOM_RAW = DATA_DIR / "erp_bom_raw.xlsx"
STOCK_RAW = DATA_DIR / "erp_stock_raw.xlsx"
PURCHASE_ITEMS_RAW = DATA_DIR / "purchase_items_raw.xlsx"

BOM_OUT = DATA_DIR / "bom.xlsx"
STOCK_OUT = DATA_DIR / "stock.xlsx"
VENDOR_OUT = DATA_DIR / "vendor_master.xlsx"
SUPPLIER_INFO_OUT = DATA_DIR / "supplier_info.xlsx"


def run_script(script_name: str):
    script_path = BASE_DIR / script_name

    if not script_path.exists():
        print(f"[오류] {script_name} 파일이 없습니다.")
        return False

    print()
    print("=" * 50)
    print(f"실행 중: {script_name}")
    print("=" * 50)

    # 중요:
    # capture_output=True로 받으면 윈도우 인코딩 문제 때문에 한글이 깨질 수 있음.
    # 하위 스크립트 출력을 콘솔에 직접 흘려보내면 한글이 정상 표시됨.
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=BASE_DIR
    )

    if result.returncode != 0:
        print(f"[오류] {script_name} 실행 실패")
        return False

    print(f"[완료] {script_name}")
    return True

    if not script_path.exists():
        print(f"[오류] {script_name} 파일이 없습니다.")
        return False

    print()
    print("=" * 50)
    print(f"실행 중: {script_name}")
    print("=" * 50)

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=BASE_DIR,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        print(f"[오류] {script_name} 실행 실패")
        return False

    print(f"[완료] {script_name}")
    return True


def get_file_date_from_name(file: Path, pattern: str):
    match = re.search(pattern, file.name)

    if match:
        try:
            return int(match.group(1))
        except Exception:
            pass

    return 0


def get_latest_stock_file():
    """
    재고 원본 파일 찾기.

    지원:
    1. data/erp_stock_raw.xlsx
    2. data/창고별 재고조회_YYYYMMDD.xlsx
    """
    if STOCK_RAW.exists():
        return STOCK_RAW

    files = []

    for file in DATA_DIR.glob("창고별 재고조회_*.xlsx"):
        if file.name.startswith("~$"):
            continue

        date_num = get_file_date_from_name(file, r"창고별 재고조회_(\d{8})")
        files.append((date_num, file.stat().st_mtime, file))

    if not files:
        return None

    files.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return files[0][2]


def has_stock_source():
    return get_latest_stock_file() is not None


def get_latest_vendor_file():
    """
    구매발주품목조회 원본 파일 찾기.

    지원:
    1. data/purchase_items_raw.xlsx
    2. data/구매발주품목조회_YYYYMMDD.xlsx
    """
    if PURCHASE_ITEMS_RAW.exists():
        return PURCHASE_ITEMS_RAW

    files = []

    for file in DATA_DIR.glob("구매발주품목조회_*.xlsx"):
        if file.name.startswith("~$"):
            continue

        date_num = get_file_date_from_name(file, r"구매발주품목조회_(\d{8})")
        files.append((date_num, file.stat().st_mtime, file))

    if not files:
        return None

    files.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return files[0][2]


def has_vendor_source():
    return get_latest_vendor_file() is not None


def verify_bom_file():
    if not BOM_OUT.exists():
        print(f"[오류] 배합비 변환 파일 없음: {BOM_OUT}")
        return False

    try:
        df = pd.read_excel(BOM_OUT)
    except Exception as e:
        print("[오류] bom.xlsx를 읽지 못했습니다.")
        print(e)
        return False

    required_cols = [
        "제품코드",
        "제품명",
        "기준수량",
        "자재코드",
        "자재명",
        "소요량",
        "단위",
    ]

    missing = [col for col in required_cols if col not in df.columns]

    if missing:
        print("[오류] bom.xlsx에 필요한 컬럼이 없습니다.")
        print("누락 컬럼:", ", ".join(missing))
        return False

    print("[확인] 배합비 파일 정상")
    print(f"- 행 수: {len(df)}")
    return True


def verify_stock_file():
    if not STOCK_OUT.exists():
        print(f"[오류] 재고 변환 파일 없음: {STOCK_OUT}")
        return False

    try:
        df = pd.read_excel(STOCK_OUT)
    except Exception as e:
        print("[오류] stock.xlsx를 읽지 못했습니다.")
        print(e)
        return False

    required_cols = [
        "자재코드",
        "자재명",
        "현재고",
        "가용재고",
        "단위",
        "재고기준창고",
    ]

    missing = [col for col in required_cols if col not in df.columns]

    if missing:
        print("[오류] stock.xlsx에 필요한 컬럼이 없습니다.")
        print("누락 컬럼:", ", ".join(missing))
        return False

    basis_values = (
        df["재고기준창고"]
        .astype(str)
        .str.replace(" ", "", regex=False)
        .str.strip()
        .dropna()
        .unique()
        .tolist()
    )

    ok = any(
        "원/부자재창고" in value or "원부자재창고" in value
        for value in basis_values
    )

    if not ok:
        print("[오류] stock.xlsx의 재고 기준이 원/부자재창고가 아닙니다.")
        print(f"감지된 재고기준창고 값: {basis_values}")
        return False

    print("[확인] 재고 파일 정상")
    print("[확인] 재고 기준: 원/부자재창고")
    print(f"- 행 수: {len(df)}")
    return True


def verify_vendor_master_file():
    if not VENDOR_OUT.exists():
        print(f"[주의] 거래처/단가 마스터 파일 없음: {VENDOR_OUT}")
        return False

    try:
        df = pd.read_excel(VENDOR_OUT)
    except Exception as e:
        print("[오류] vendor_master.xlsx를 읽지 못했습니다.")
        print(e)
        return False

    required_cols = [
        "품번",
        "품명",
        "구매거래처",
        "단가",
        "단가기준일",
        "업체명",
        "대표자",
        "사업자번호",
        "주소",
    ]

    missing = [col for col in required_cols if col not in df.columns]

    if missing:
        print("[오류] vendor_master.xlsx에 필요한 컬럼이 없습니다.")
        print("누락 컬럼:", ", ".join(missing))
        return False

    print("[확인] 거래처/단가 마스터 파일 정상")
    print(f"- 행 수: {len(df)}")

    if SUPPLIER_INFO_OUT.exists():
        print(f"[확인] 거래처 상세정보 파일 있음: {SUPPLIER_INFO_OUT}")
    else:
        print(f"[안내] supplier_info.xlsx가 아직 없습니다.")
        print("convert_vendor_master.py 실행 시 자동 생성될 수 있습니다.")

    return True


def main():
    print("=" * 50)
    print("ERP 엑셀 데이터 갱신")
    print("=" * 50)

    DATA_DIR.mkdir(exist_ok=True)

    print()
    print("[원본 파일 확인]")

    if BOM_RAW.exists():
        print(f"배합비 원본 확인: {BOM_RAW}")
    else:
        print(f"[주의] 배합비 원본 없음: {BOM_RAW}")

    latest_stock_file = get_latest_stock_file()

    if latest_stock_file:
        print(f"재고 원본 확인: {latest_stock_file}")
    else:
        print("[주의] 재고 원본 없음")
        print(f"- {STOCK_RAW}")
        print("- 또는 data/창고별 재고조회_YYYYMMDD.xlsx")

    latest_vendor_file = get_latest_vendor_file()

    if latest_vendor_file:
        print(f"구매발주품목 원본 확인: {latest_vendor_file}")
    else:
        print("[주의] 구매발주품목조회 원본 없음")
        print(f"- {PURCHASE_ITEMS_RAW}")
        print("- 또는 data/구매발주품목조회_YYYYMMDD.xlsx")

    ok_bom = False
    ok_stock = False
    ok_vendor = False

    print()
    print("[변환 실행]")

    if BOM_RAW.exists():
        ok_bom = run_script("convert_bom.py")
    else:
        print()
        print("[건너뜀] 배합비 원본이 없어 convert_bom.py를 실행하지 않았습니다.")

    if has_stock_source():
        ok_stock = run_script("convert_stock.py")
    else:
        print()
        print("[건너뜀] 재고 원본이 없어 convert_stock.py를 실행하지 않았습니다.")

    if has_vendor_source():
        ok_vendor = run_script("convert_vendor_master.py")
    else:
        print()
        print("[건너뜀] 구매발주품목조회 원본이 없어 convert_vendor_master.py를 실행하지 않았습니다.")

    print()
    print("[최종 결과 파일 확인]")

    if BOM_OUT.exists():
        print(f"배합비 변환 파일 있음: {BOM_OUT}")
    else:
        print(f"[오류] 배합비 변환 파일 없음: {BOM_OUT}")

    if STOCK_OUT.exists():
        print(f"재고 변환 파일 있음: {STOCK_OUT}")
    else:
        print(f"[오류] 재고 변환 파일 없음: {STOCK_OUT}")

    if VENDOR_OUT.exists():
        print(f"거래처/단가 마스터 파일 있음: {VENDOR_OUT}")
    else:
        print(f"[주의] 거래처/단가 마스터 파일 없음: {VENDOR_OUT}")

    if SUPPLIER_INFO_OUT.exists():
        print(f"거래처 상세정보 파일 있음: {SUPPLIER_INFO_OUT}")
    else:
        print(f"[안내] 거래처 상세정보 파일 없음: {SUPPLIER_INFO_OUT}")

    print()
    print("[파일 내용 검증]")

    bom_verified = verify_bom_file() if BOM_OUT.exists() else False
    stock_verified = verify_stock_file() if STOCK_OUT.exists() else False
    vendor_verified = verify_vendor_master_file() if VENDOR_OUT.exists() else False

    print()
    print("=" * 50)
    print("갱신 결과 요약")
    print("=" * 50)
    print(f"배합비 변환 실행: {'성공' if ok_bom else '미실행 또는 실패'}")
    print(f"재고 변환 실행: {'성공' if ok_stock else '미실행 또는 실패'}")
    print(f"거래처/단가 변환 실행: {'성공' if ok_vendor else '미실행 또는 실패'}")
    print(f"배합비 검증: {'정상' if bom_verified else '확인 필요'}")
    print(f"재고 검증: {'정상' if stock_verified else '확인 필요'}")
    print(f"거래처/단가 검증: {'정상' if vendor_verified else '확인 필요'}")
    print("=" * 50)

    if bom_verified and stock_verified:
        print()
        print("필수 데이터 갱신 완료.")
        print("재고 기준은 원/부자재창고입니다.")

        if vendor_verified:
            print("거래처/단가 마스터도 갱신되었습니다.")
        else:
            print("거래처/단가 마스터는 아직 없거나 확인이 필요합니다.")
            print("구매발주품목조회_YYYYMMDD.xlsx 파일을 data 폴더에 넣고 다시 실행하세요.")

        print()
        print("이제 아래 명령으로 실행하면 됩니다.")
        print("python ask.py")
    else:
        print()
        print("데이터 갱신에 문제가 있습니다.")
        print("위 오류를 확인하세요.")

    print("=" * 50)


if __name__ == "__main__":
    main()