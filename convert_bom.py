import pandas as pd
from pathlib import Path

RAW_FILE = Path("data/erp_bom_raw.xlsx")
OUT_FILE = Path("data/bom.xlsx")

if not RAW_FILE.exists():
    raise FileNotFoundError(f"배합비 원본 파일이 없습니다: {RAW_FILE}")

# 상단 제목/빈 줄이 있을 수 있으므로 헤더 행 자동 탐색
preview = pd.read_excel(RAW_FILE, header=None)

header_row = None
for i in range(min(20, len(preview))):
    row_values = [str(v).strip() for v in preview.iloc[i].tolist()]
    if "제품코드" in row_values and "제품명" in row_values and "자재코드" in row_values:
        header_row = i
        break

if header_row is None:
    raise ValueError("배합비 엑셀에서 헤더 행을 찾지 못했습니다. 제품코드/제품명/자재코드 컬럼을 확인하세요.")

df = pd.read_excel(RAW_FILE, header=header_row)

# 컬럼명 정리
df.columns = [str(c).strip() for c in df.columns]

# 빈 컬럼 제거
df = df.loc[:, ~df.columns.str.contains("^Unnamed", na=False)]
df = df.loc[:, df.columns.str.lower() != "nan"]

print("읽은 배합비 컬럼 목록:")
for c in df.columns:
    print("-", c)

required_cols = ["제품코드", "제품명", "기준수량", "자재코드", "자재명", "소요량", "단위"]

for col in required_cols:
    if col not in df.columns:
        raise ValueError(f"필수 컬럼이 없습니다: {col}")

bom_df = pd.DataFrame()
bom_df["제품코드"] = df["제품코드"].astype(str).str.strip()
bom_df["제품명"] = df["제품명"].astype(str).str.strip()
bom_df["기준수량"] = (
    df["기준수량"]
    .astype(str)
    .str.replace(",", "", regex=False)
    .str.strip()
)
bom_df["자재코드"] = df["자재코드"].astype(str).str.strip()
bom_df["자재명"] = df["자재명"].astype(str).str.strip()
bom_df["소요량"] = (
    df["소요량"]
    .astype(str)
    .str.replace(",", "", regex=False)
    .str.strip()
)
bom_df["단위"] = df["단위"].astype(str).str.strip()

# 숫자 변환
bom_df["기준수량"] = pd.to_numeric(bom_df["기준수량"], errors="coerce").fillna(0)
bom_df["소요량"] = pd.to_numeric(bom_df["소요량"], errors="coerce").fillna(0)

# 빈 행 제거
bom_df = bom_df[bom_df["제품코드"].notna()]
bom_df = bom_df[bom_df["제품코드"] != ""]
bom_df = bom_df[bom_df["제품코드"].str.lower() != "nan"]

bom_df = bom_df[bom_df["자재코드"].notna()]
bom_df = bom_df[bom_df["자재코드"] != ""]
bom_df = bom_df[bom_df["자재코드"].str.lower() != "nan"]

# 소요량 0인 행은 일단 제거하지 않음
# 실제 배합비에서 0 투입 자재도 확인용으로 남겨둘 수 있음

OUT_FILE.parent.mkdir(exist_ok=True)
bom_df.to_excel(OUT_FILE, index=False)

print()
print("배합비 변환 완료")
print(f"저장 위치: {OUT_FILE}")
print(f"총 행 수: {len(bom_df)}")
print()
print(bom_df.head(10).to_string(index=False))