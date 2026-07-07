import pandas as pd
from pathlib import Path

RAW_FILE = Path("data/erp_bom_raw.xlsx")

if not RAW_FILE.exists():
    raise FileNotFoundError(f"배합비 원본 파일이 없습니다: {RAW_FILE}")

preview = pd.read_excel(RAW_FILE, header=None)

print("상위 15행 미리보기")
print(preview.head(15).to_string())

print("\n행별 값 확인")
for i in range(min(15, len(preview))):
    values = preview.iloc[i].astype(str).tolist()
    print(f"{i}행:", values)