import os
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

load_dotenv()


BOM_FILE = Path("data/bom.xlsx")
STOCK_FILE = Path("data/stock.xlsx")
ALIAS_FILE = Path("data/product_aliases.csv")

TARGET_WAREHOUSE = "원/부자재창고"
def get_env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return float(default)



# 제품명 자동 매칭 기준
# 기본 0.95 이상이면 같은 제품으로 자동 판단. .env의 AUTO_MATCH_THRESHOLD로 조정 가능
AUTO_MATCH_THRESHOLD = get_env_float("AUTO_MATCH_THRESHOLD", 0.95)
# 기본 0.25 이상이면 후보 목록에 표시. .env의 CANDIDATE_THRESHOLD로 조정 가능
CANDIDATE_THRESHOLD = get_env_float("CANDIDATE_THRESHOLD", 0.25)

# 재고 부족 판단에서 제외할 자재 키워드
# 기본값: 부형제)탄산칼슘(SHFE-3), 부형제)곡분-왕겨(Chaff), 부형제)정제수(Purified Water)
# .env에 IGNORE_STOCK_MATERIALS=부형제)탄산칼슘(SHFE-3),부형제)곡분-왕겨(Chaff),부형제)정제수(Purified Water) 처럼 추가하면 확장 가능
IGNORE_STOCK_MATERIALS_ENV = os.getenv("IGNORE_STOCK_MATERIALS", "")
DEFAULT_IGNORE_STOCK_KEYWORDS = ["부형제)탄산칼슘(SHFE-3)", "부형제)곡분-왕겨(Chaff)", "부형제)정제수(Purified Water)","비타민 E 50%분말 (Vitamin E)", "비타민 B3 (Niacin-나이아신) 98%","비타민 A1000(Retinol Acetate)", "비타민 D3 500 (Cholecalciferol)"]


def get_ignore_stock_keywords():
    keywords = DEFAULT_IGNORE_STOCK_KEYWORDS.copy()

    if IGNORE_STOCK_MATERIALS_ENV.strip():
        extra = [
            x.strip()
            for x in IGNORE_STOCK_MATERIALS_ENV.split(",")
            if x.strip()
        ]
        keywords.extend(extra)

    # 중복 제거
    result = []
    seen = set()

    for keyword in keywords:
        key = normalize_product_text(keyword)

        if key and key not in seen:
            result.append(keyword)
            seen.add(key)

    return result


def is_ignore_stock_material(material_code, material_name):
    """
    탄산칼슘, 곡분처럼 재고를 관리하지 않거나 항상 사용 가능으로 볼 자재인지 판단합니다.
    자재명에 키워드가 포함되면 재고 부족 판단에서 제외합니다.
    """
    text = f"{material_code} {material_name}"
    text_key = normalize_product_text(text)

    for keyword in get_ignore_stock_keywords():
        keyword_key = normalize_product_text(keyword)

        if keyword_key and keyword_key in text_key:
            return True

    return False



def fmt_num(value):
    try:
        value = float(value)

        if value.is_integer():
            return f"{value:,.0f}"

        return f"{value:,.3f}".rstrip("0").rstrip(".")
    except Exception:
        return str(value)


def normalize_unit(unit):
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


def normalize_product_text(value):
    """
    제품명 비교용 정규화.
    공백, 기호, 괄호, 슬래시 등을 제거해서 비교합니다.
    """
    if value is None:
        return ""

    text = str(value).strip()
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()

    remove_words = [
        "생산계획",
        "생산등록",
        "등록",
        "생산",
        "가능",
        "가능여부",
        "확인",
        "kg",
        "kgs",
        "킬로",
        "키로",
        "톤",
        "ton",
        "tons",
    ]

    for word in remove_words:
        text = text.replace(word.lower(), "")

    text = text.replace(" ", "")
    text = text.replace("-", "")
    text = text.replace("_", "")
    text = text.replace("(", "")
    text = text.replace(")", "")
    text = text.replace("[", "")
    text = text.replace("]", "")
    text = text.replace("/", "")
    text = text.replace("\\", "")
    text = re.sub(r"[^0-9a-zA-Z가-힣]", "", text)

    return text


def normalize_product_text_for_ocr(value):
    """
    OCR 오류에 조금 더 관대한 제품명 정규화.
    기존 normalize_product_text보다 글자 혼동을 일부 보정합니다.
    """
    text = normalize_product_text(value)

    # 영어/숫자 OCR 혼동
    text = text.replace("０", "0")
    text = text.replace("１", "1")
    text = text.replace("Ｏ", "o")
    text = text.replace("ｏ", "o")
    text = text.replace("ｌ", "l")
    text = text.replace("Ｉ", "i")

    # 제품명 OCR에서 자주 발생하는 한글 혼동 일부 보정
    # 너무 과하게 바꾸면 오매칭이 생기므로 제한적으로만 적용
    replacements = {
        "얼디메이트": "얼티메이트",
        "얼터메이트": "얼티메이트",
        "울디메이트": "울티메이트",
        "울터메이트": "울티메이트",
        "메이느": "메이트",
        "메이트트": "메이트",
        "블루믹즈": "블루믹스",
        "바이믹즈": "바이믹스",
    }

    for src, dst in replacements.items():
        text = text.replace(src, dst)

    return text


def extract_product_code_from_text(text):
    if text is None:
        return None

    text = str(text).upper()

    # 예: P10544, p10544
    match = re.search(r"\bP\s*[-_]?\s*\d+\b", text)

    if match:
        return re.sub(r"[^A-Z0-9]", "", match.group(0))

    return None


def char_ngram_score(a, b, n=2):
    a = normalize_product_text_for_ocr(a)
    b = normalize_product_text_for_ocr(b)

    if not a or not b:
        return 0.0

    if len(a) < n or len(b) < n:
        return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()

    a_set = {a[i:i + n] for i in range(len(a) - n + 1)}
    b_set = {b[i:i + n] for i in range(len(b) - n + 1)}

    if not a_set or not b_set:
        return 0.0

    return len(a_set & b_set) / len(a_set | b_set)


def similarity_score(a, b):
    """
    제품명 유사도 계산.
    반환값: 0.0 ~ 1.0
    """
    raw_a = str(a or "")
    raw_b = str(b or "")

    a_norm = normalize_product_text(raw_a)
    b_norm = normalize_product_text(raw_b)

    if not a_norm or not b_norm:
        return 0.0

    if a_norm == b_norm:
        return 1.0

    a_ocr = normalize_product_text_for_ocr(raw_a)
    b_ocr = normalize_product_text_for_ocr(raw_b)

    if a_ocr == b_ocr:
        return 0.98

    # 한쪽이 다른 쪽에 포함되면 꽤 높은 점수
    if a_norm in b_norm or b_norm in a_norm:
        return 0.95

    if a_ocr in b_ocr or b_ocr in a_ocr:
        return 0.93

    seq_score = SequenceMatcher(None, a_norm, b_norm).ratio()
    ocr_seq_score = SequenceMatcher(None, a_ocr, b_ocr).ratio()
    bigram_score = char_ngram_score(a_ocr, b_ocr, n=2)
    trigram_score = char_ngram_score(a_ocr, b_ocr, n=3)

    # 길이가 비슷할수록 신뢰도 상승
    length_ratio = min(len(a_ocr), len(b_ocr)) / max(len(a_ocr), len(b_ocr))

    final_score = max(
        seq_score,
        ocr_seq_score,
        (bigram_score * 0.65) + (length_ratio * 0.35),
        (trigram_score * 0.75) + (length_ratio * 0.25),
    )

    return float(max(0.0, min(final_score, 1.0)))


def normalize_col_name(value):
    """
    컬럼명/창고명 비교용 정리.
    공백, 줄바꿈, 탭을 제거해서 비교합니다.
    """
    text = str(value).strip()
    text = text.replace("\n", "")
    text = text.replace("\r", "")
    text = text.replace("\t", "")
    text = text.replace(" ", "")
    return text


def is_target_warehouse_text(value):
    """
    원/부자재창고 표기인지 확인.
    예: 원/부자재창고, 원부자재창고 둘 다 인정.
    """
    text = normalize_col_name(value)
    return "원/부자재창고" in text or "원부자재창고" in text


def to_number_series(series):
    """
    콤마가 들어간 숫자 문자열을 숫자로 변환.
    예: 1,234.5 → 1234.5
    """
    return (
        series
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
        .replace(["", "nan", "None", "NaN"], "0")
        .pipe(pd.to_numeric, errors="coerce")
        .fillna(0)
    )


def load_ocr_memory_aliases():
    """
    /ocradd, /ocrmemory로 저장한 data/ocr_product_memory.json 값을
    일반 텍스트 제품명 매칭에서도 별칭으로 사용합니다.
    """
    memory_file = Path("data/ocr_product_memory.json")

    if not memory_file.exists():
        return []

    try:
        import json
        data = json.loads(memory_file.read_text(encoding="utf-8"))
    except Exception:
        return []

    items = data.get("items", {}) if isinstance(data, dict) else {}

    if not isinstance(items, dict):
        return []

    rows = []

    for item in items.values():
        if not isinstance(item, dict):
            continue

        alias = str(item.get("ocr_name", "")).strip()
        code = str(item.get("product_code", "")).strip()
        name = str(item.get("product_name", "")).strip()

        if not alias or not (code or name):
            continue

        rows.append({
            "별칭": alias,
            "제품코드": code,
            "제품명": name,
            "별칭정리": normalize_product_text_for_ocr(alias),
            "출처": "ocr_memory",
        })

    return rows


def load_product_aliases():
    """
    OCR 오인식/사용자 별칭을 불러옵니다.

    읽는 곳:
    1. data/product_aliases.csv
    2. data/ocr_product_memory.json
    """
    rows = []

    if ALIAS_FILE.exists():
        try:
            alias_df = pd.read_csv(ALIAS_FILE, encoding="utf-8-sig")
        except UnicodeDecodeError:
            try:
                alias_df = pd.read_csv(ALIAS_FILE, encoding="cp949")
            except Exception:
                alias_df = None
        except Exception:
            alias_df = None

        if alias_df is not None:
            alias_df.columns = [str(c).strip() for c in alias_df.columns]

            alias_col = None
            code_col = None
            name_col = None

            for col in alias_df.columns:
                n = normalize_col_name(col).lower()

                if n in ["별칭", "alias", "오인식명", "ocr명", "ocr제품명"]:
                    alias_col = col

                if n in ["제품코드", "productcode", "product_code", "code"]:
                    code_col = col

                if n in ["제품명", "productname", "product_name", "name"]:
                    name_col = col

            if alias_col and (code_col or name_col):
                for _, row in alias_df.iterrows():
                    alias = str(row.get(alias_col, "")).strip()

                    if not alias:
                        continue

                    rows.append({
                        "별칭": alias,
                        "제품코드": str(row.get(code_col, "")).strip() if code_col else "",
                        "제품명": str(row.get(name_col, "")).strip() if name_col else "",
                        "별칭정리": normalize_product_text_for_ocr(alias),
                        "출처": "product_aliases_csv",
                    })

    rows.extend(load_ocr_memory_aliases())

    result = []
    seen = set()

    for row in rows:
        key = (
            row.get("별칭정리", ""),
            str(row.get("제품코드", "")).upper(),
            normalize_product_text_for_ocr(row.get("제품명", "")),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(row)

    return result

def get_product_master_df(bom_df):
    required = ["제품코드", "제품명"]

    for col in required:
        if col not in bom_df.columns:
            raise ValueError(f"배합비 파일에 필요한 컬럼이 없습니다: {col}")

    product_df = (
        bom_df[["제품코드", "제품명"]]
        .dropna(subset=["제품코드", "제품명"])
        .drop_duplicates()
        .copy()
    )

    product_df["제품코드"] = product_df["제품코드"].astype(str).str.strip()
    product_df["제품명"] = product_df["제품명"].astype(str).str.strip()

    return product_df


def find_similar_products(bom_df, search_text, limit=10):
    """
    제품명/제품코드 유사 후보를 반환합니다.
    telegram_bot.py의 제품 선택 버튼에서 사용합니다.
    """
    search_text = str(search_text or "").strip()
    search_key = normalize_product_text(search_text)
    search_ocr_key = normalize_product_text_for_ocr(search_text)
    search_code = extract_product_code_from_text(search_text)

    if not search_key and not search_code:
        return []

    product_df = get_product_master_df(bom_df)
    aliases = load_product_aliases()

    candidates = {}

    def add_candidate(code, name, score, reason):
        code = str(code or "").strip()
        name = str(name or "").strip()

        if not code and not name:
            return

        key = code or name

        if key not in candidates or score > candidates[key]["유사도"]:
            candidates[key] = {
                "제품코드": code,
                "제품명": name,
                "유사도": float(score),
                "매칭사유": reason,
            }

    # 1. 별칭 매칭
    for alias in aliases:
        if not alias.get("별칭정리"):
            continue

        alias_score = similarity_score(search_ocr_key, alias["별칭정리"])

        if search_ocr_key == alias["별칭정리"]:
            alias_score = 0.99

        if alias_score >= CANDIDATE_THRESHOLD:
            matched_rows = product_df.copy()

            if alias.get("제품코드"):
                matched_rows = matched_rows[
                    matched_rows["제품코드"].astype(str).str.strip().str.upper()
                    == alias["제품코드"].upper()
                ]
            elif alias.get("제품명"):
                matched_rows = matched_rows[
                    matched_rows["제품명"].apply(normalize_product_text_for_ocr)
                    == normalize_product_text_for_ocr(alias["제품명"])
                ]

            for _, row in matched_rows.iterrows():
                add_candidate(row["제품코드"], row["제품명"], alias_score, "별칭")

    # 2. 제품 마스터 직접 비교
    for _, row in product_df.iterrows():
        code = str(row["제품코드"]).strip()
        name = str(row["제품명"]).strip()

        code_key = re.sub(r"[^0-9A-Z]", "", code.upper())
        name_key = normalize_product_text(name)
        name_ocr_key = normalize_product_text_for_ocr(name)

        score = similarity_score(search_text, name)
        reason = "제품명유사"

        # 제품코드가 입력됐으면 제품코드 우선
        if search_code:
            search_code_key = re.sub(r"[^0-9A-Z]", "", search_code.upper())

            if search_code_key == code_key:
                score = 1.0
                reason = "제품코드일치"
            elif search_code_key in code_key or code_key in search_code_key:
                score = max(score, 0.92)
                reason = "제품코드부분일치"

        # 사용자가 코드만 또는 코드 일부를 넣은 경우
        compact_upper = re.sub(r"[^0-9A-Z]", "", str(search_text).upper())

        if compact_upper and (compact_upper == code_key):
            score = 1.0
            reason = "제품코드일치"
        elif compact_upper and (compact_upper in code_key or code_key in compact_upper):
            score = max(score, 0.90)
            reason = "제품코드부분일치"

        if search_key == name_key or search_ocr_key == name_ocr_key:
            score = max(score, 0.98)
            reason = "제품명일치"

        if search_key and (search_key in name_key or name_key in search_key):
            score = max(score, 0.95)
            reason = "제품명포함"

        if search_ocr_key and (search_ocr_key in name_ocr_key or name_ocr_key in search_ocr_key):
            score = max(score, 0.93)
            reason = "OCR보정포함"

        if score >= CANDIDATE_THRESHOLD:
            add_candidate(code, name, score, reason)

    candidate_list = list(candidates.values())
    candidate_list.sort(key=lambda x: x["유사도"], reverse=True)

    return candidate_list[:limit]


def find_best_product_match(bom_df, product_name, threshold=AUTO_MATCH_THRESHOLD):
    """
    자동 매칭용 함수.
    threshold 이상이면 해당 제품을 자동 선택해도 된다고 판단합니다.
    """
    candidates = find_similar_products(bom_df, product_name, limit=5)

    if not candidates:
        return None, []

    best = candidates[0]

    if best["유사도"] >= threshold:
        return best, candidates

    return None, candidates


def find_raw_material_warehouse_column(stock_df):
    """
    stock.xlsx 안에서 원/부자재창고 컬럼을 찾습니다.
    """
    for col in stock_df.columns:
        if is_target_warehouse_text(col):
            return col

    return None


def prepare_stock_df(stock_df):
    """
    생산 가능 여부 계산 전에 재고 기준을 원/부자재창고로 맞춥니다.

    처리 방식:
    1. stock.xlsx 안에 '원/부자재창고' 컬럼이 직접 있으면 그 컬럼으로 가용재고를 다시 만듭니다.
    2. stock.xlsx가 이미 변환된 파일이라면 '재고기준창고' 값이 원/부자재창고인지 확인합니다.
    3. 둘 다 아니면 전체재고로 계산될 위험이 있으므로 중단합니다.
    """
    stock_df = stock_df.copy()
    stock_df.columns = [str(c).strip() for c in stock_df.columns]

    # 원본 ERP 컬럼명 대응
    if "자재코드" not in stock_df.columns and "품번" in stock_df.columns:
        stock_df["자재코드"] = stock_df["품번"].astype(str).str.strip()

    if "자재명" not in stock_df.columns and "품명" in stock_df.columns:
        stock_df["자재명"] = stock_df["품명"].astype(str).str.strip()

    raw_material_col = find_raw_material_warehouse_column(stock_df)

    # 경우 1: stock.xlsx 안에 원/부자재창고 컬럼이 직접 있는 경우
    if raw_material_col is not None:
        stock_df["현재고"] = to_number_series(stock_df[raw_material_col])

        if "예약수량" in stock_df.columns:
            stock_df["예약수량"] = to_number_series(stock_df["예약수량"])
        else:
            stock_df["예약수량"] = 0

        if "보류수량" in stock_df.columns:
            stock_df["보류수량"] = to_number_series(stock_df["보류수량"])
        else:
            stock_df["보류수량"] = 0

        stock_df["가용재고"] = stock_df["현재고"] - stock_df["예약수량"] - stock_df["보류수량"]
        stock_df["재고기준창고"] = TARGET_WAREHOUSE

        return stock_df

    # 경우 2: 이미 변환된 stock.xlsx인 경우
    if "재고기준창고" in stock_df.columns:
        basis_values = (
            stock_df["재고기준창고"]
            .astype(str)
            .apply(normalize_col_name)
            .dropna()
            .unique()
            .tolist()
        )

        basis_ok = any(
            "원/부자재창고" in value or "원부자재창고" in value
            for value in basis_values
        )

        if not basis_ok:
            raise ValueError(
                "stock.xlsx의 재고기준창고가 원/부자재창고가 아닙니다.\n"
                f"현재 감지된 기준: {basis_values}\n"
                "전체재고로 계산될 위험이 있어 중단합니다."
            )

        if "가용재고" not in stock_df.columns:
            raise ValueError("stock.xlsx에 가용재고 컬럼이 없습니다.")

        stock_df["가용재고"] = to_number_series(stock_df["가용재고"])

        if "현재고" in stock_df.columns:
            stock_df["현재고"] = to_number_series(stock_df["현재고"])
        else:
            stock_df["현재고"] = stock_df["가용재고"]

        stock_df["재고기준창고"] = TARGET_WAREHOUSE

        return stock_df

    # 경우 3: 기준 확인 불가
    column_list = ", ".join([str(c) for c in stock_df.columns])

    raise ValueError(
        "stock.xlsx에서 원/부자재창고 기준을 확인할 수 없습니다.\n"
        "현재 stock.xlsx가 전체재고 기준일 가능성이 있어 계산을 중단합니다.\n\n"
        f"현재 stock.xlsx 컬럼 목록:\n{column_list}\n\n"
        "해결 방법:\n"
        "1. 재고 변환 파일을 먼저 실행해서 data/stock.xlsx를 새로 만드세요.\n"
        "2. stock.xlsx에 '재고기준창고' 컬럼이 있고 값이 '원/부자재창고'인지 확인하세요.\n"
        "3. 또는 stock.xlsx 안에 '원/부자재창고' 컬럼이 직접 있어야 합니다."
    )


def load_data():
    if not BOM_FILE.exists():
        raise FileNotFoundError(f"배합비 파일이 없습니다: {BOM_FILE}")

    if not STOCK_FILE.exists():
        raise FileNotFoundError(f"재고 파일이 없습니다: {STOCK_FILE}")

    bom_df = pd.read_excel(BOM_FILE)
    stock_df = pd.read_excel(STOCK_FILE)

    # 핵심: 재고 데이터를 원/부자재창고 기준으로 강제 정리
    stock_df = prepare_stock_df(stock_df)

    return bom_df, stock_df


def get_bom_by_product_code(bom_df, product_code):
    if not product_code or "제품코드" not in bom_df.columns:
        return None

    code_key = re.sub(r"[^0-9A-Z]", "", str(product_code).upper())

    temp = bom_df.copy()
    temp["_제품코드정리"] = (
        temp["제품코드"]
        .astype(str)
        .str.upper()
        .apply(lambda x: re.sub(r"[^0-9A-Z]", "", x))
    )

    product_bom = temp[temp["_제품코드정리"] == code_key].copy()

    if product_bom.empty:
        return None

    product_bom = product_bom.drop(columns=["_제품코드정리"])
    first_product_code = product_bom.iloc[0]["제품코드"]

    return product_bom[product_bom["제품코드"] == first_product_code].copy()


def find_product_bom(bom_df, product_name, auto_match=True, threshold=AUTO_MATCH_THRESHOLD):
    """
    배합비에서 제품을 찾습니다.

    개선점:
    - 제품코드 우선 검색
    - 제품명 정확/포함 검색
    - OCR 보정 검색
    - 85% 이상 유사하면 자동 매칭
    - 85% 미만이면 None을 반환하고 build_result에서 후보 목록 제공
    """
    product_name = str(product_name or "").strip()

    if not product_name:
        return None

    product_code_in_question = extract_product_code_from_text(product_name)

    name_only = product_name

    if product_code_in_question:
        name_only = re.sub(r"\bP\s*[-_]?\s*\d+\b", "", name_only, flags=re.IGNORECASE).strip()

    # 1순위: 제품코드 검색
    if product_code_in_question:
        by_code = get_bom_by_product_code(bom_df, product_code_in_question)

        if by_code is not None and not by_code.empty:
            return by_code

    # 2순위: 제품코드만 입력한 경우 또는 코드 일부 검색
    by_code = get_bom_by_product_code(bom_df, product_name)

    if by_code is not None and not by_code.empty:
        return by_code

    # 3순위: 제품명 원문 포함 검색
    if name_only:
        product_bom = bom_df[
            bom_df["제품명"].astype(str).str.contains(name_only, case=False, na=False, regex=False)
        ].copy()

        if not product_bom.empty:
            first_product_code = product_bom.iloc[0]["제품코드"]
            return product_bom[product_bom["제품코드"] == first_product_code].copy()

    # 4순위: 제품명 공백 제거 검색
    if name_only:
        search_key_space = name_only.replace(" ", "")

        temp = bom_df.copy()
        temp["_제품명공백제거"] = temp["제품명"].astype(str).str.replace(" ", "", regex=False)

        product_bom = temp[
            temp["_제품명공백제거"].str.contains(search_key_space, case=False, na=False, regex=False)
        ].copy()

        if not product_bom.empty:
            product_bom = product_bom.drop(columns=["_제품명공백제거"])
            first_product_code = product_bom.iloc[0]["제품코드"]
            return product_bom[product_bom["제품코드"] == first_product_code].copy()

    # 5순위: 제품명 기호 제거/OCR 보정 검색
    if name_only:
        search_key = normalize_product_text(name_only)
        search_ocr_key = normalize_product_text_for_ocr(name_only)

        temp = bom_df.copy()
        temp["_제품명정리"] = temp["제품명"].apply(normalize_product_text)
        temp["_제품명OCR정리"] = temp["제품명"].apply(normalize_product_text_for_ocr)

        product_bom = temp[
            (temp["_제품명정리"] == search_key)
            | (temp["_제품명OCR정리"] == search_ocr_key)
            | (temp["_제품명정리"].str.contains(search_key, case=False, na=False, regex=False))
            | (temp["_제품명OCR정리"].str.contains(search_ocr_key, case=False, na=False, regex=False))
        ].copy()

        if not product_bom.empty:
            product_bom = product_bom.drop(columns=["_제품명정리", "_제품명OCR정리"])
            first_product_code = product_bom.iloc[0]["제품코드"]
            return product_bom[product_bom["제품코드"] == first_product_code].copy()

    # 6순위: 별칭 또는 유사도 자동 매칭
    if auto_match:
        best, candidates = find_best_product_match(bom_df, product_name, threshold=threshold)

        if best:
            by_code = get_bom_by_product_code(bom_df, best["제품코드"])

            if by_code is not None and not by_code.empty:
                by_code = by_code.copy()
                by_code.attrs["match_info"] = best
                return by_code

    return None


def build_result(product_name: str, request_qty: float = 1, extra_consumption=None):
    """
    extra_consumption:
    기존 생산계획으로 이미 사용 예정인 자재량.
    예: {"M10001": 300.5, "M10002": 20}

    계산 가용재고 = ERP 가용재고 - 기존 생산계획 사용 예정량
    """
    bom_df, stock_df = load_data()

    required_bom_cols = ["제품코드", "제품명", "기준수량", "자재코드", "자재명", "소요량", "단위"]
    required_stock_cols = ["자재코드", "자재명", "가용재고", "단위", "재고기준창고"]

    for col in required_bom_cols:
        if col not in bom_df.columns:
            raise ValueError(f"배합비 파일에 필요한 컬럼이 없습니다: {col}")

    for col in required_stock_cols:
        if col not in stock_df.columns:
            raise ValueError(f"재고 파일에 필요한 컬럼이 없습니다: {col}")

    product_bom = find_product_bom(bom_df, product_name)

    if product_bom is None or product_bom.empty:
        similar_products = find_similar_products(bom_df, product_name, limit=10)

        return {
            "found": False,
            "message": f"'{product_name}' 제품의 배합비를 찾을 수 없습니다.",
            "similar_products": similar_products,
            "search_text": product_name,
        }

    product_real_name = str(product_bom.iloc[0]["제품명"])
    product_code = str(product_bom.iloc[0]["제품코드"])
    match_info = product_bom.attrs.get("match_info")

    product_bom = product_bom.copy()
    product_bom["기준수량"] = pd.to_numeric(product_bom["기준수량"], errors="coerce").fillna(0)
    product_bom["소요량"] = pd.to_numeric(product_bom["소요량"], errors="coerce").fillna(0)
    stock_df["가용재고"] = pd.to_numeric(stock_df["가용재고"], errors="coerce").fillna(0)

    grouped_bom = (
        product_bom
        .groupby(["자재코드", "자재명", "단위"], as_index=False)
        .agg({
            "소요량": "sum",
            "기준수량": "max",
        })
    )

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
    shortages = []
    warnings = []
    zero_usage_rows = []
    max_possible_qty = None

    if extra_consumption is None:
        extra_consumption = {}

    if match_info:
        score_percent = round(float(match_info.get("유사도", 0)) * 100)
        warnings.append(
            f"제품명이 자동 매칭되었습니다: 입력 '{product_name}' → "
            f"{product_real_name} [{product_code}] / 유사도 {score_percent}%"
        )

    for _, row in grouped_bom.iterrows():
        material_code = str(row["자재코드"]).strip()
        material_name = str(row["자재명"]).strip()
        base_qty = float(row["기준수량"])
        bom_qty = float(row["소요량"])
        bom_unit = normalize_unit(row["단위"])

        if base_qty > 0:
            required_qty = bom_qty * float(request_qty) / base_qty
        else:
            required_qty = 0
            warnings.append(f"{material_code} / {material_name}: 기준수량이 0 또는 비정상입니다.")

        stock_match = grouped_stock[
            grouped_stock["자재코드"].astype(str).str.strip() == material_code
        ]

        if stock_match.empty:
            original_available_qty = 0
            stock_unit = bom_unit
            warnings.append(f"{material_code} / {material_name}: 재고 파일에서 자재코드를 찾지 못했습니다.")
        else:
            original_available_qty = float(stock_match.iloc[0]["가용재고"])
            stock_unit = normalize_unit(stock_match.iloc[0]["단위"])

        planned_used_qty = float(extra_consumption.get(material_code, 0))

        ignore_stock = is_ignore_stock_material(material_code, material_name)

        if ignore_stock:
            # 이 자재는 재고 부족 판단에서 제외합니다.
            # 필요수량만큼 사용 가능하다고 보고 생산 불가능 원인에서 빼기 위함입니다.
            available_qty = required_qty
            planned_used_qty = 0
        else:
            available_qty = max(original_available_qty - planned_used_qty, 0)

        unit_warning = ""

        if bom_unit and stock_unit and bom_unit != stock_unit:
            unit_warning = f" / 단위 확인 필요: 배합비 {bom_unit}, 재고 {stock_unit}"
            warnings.append(
                f"{material_code} / {material_name}: 배합비 단위({bom_unit})와 재고 단위({stock_unit})가 다릅니다."
            )

        if ignore_stock:
            shortage_qty = 0
            remaining_after_qty = 0
        else:
            shortage_qty = max(required_qty - available_qty, 0)
            remaining_after_qty = available_qty - required_qty

        possible_qty_by_material = None

        if ignore_stock:
            # 재고 무시 자재는 최대 생산 가능 수량의 병목에서 제외합니다.
            possible_qty_by_material = None
        elif bom_qty <= 0:
            zero_usage_rows.append(
                f"{material_code} / {material_name}: 소요량 0으로 최대 생산 가능 수량 계산에서 제외"
            )
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
            "원가용재고": original_available_qty,
            "계획차감수량": planned_used_qty,
            "가용재고": available_qty,
            "생산후잔량": remaining_after_qty,
            "부족수량": shortage_qty,
            "배합단위": bom_unit,
            "재고단위": stock_unit,
            "판정": status,
            "단위경고": unit_warning,
            "자재별가능수량": possible_qty_by_material,
            "재고무시": ignore_stock,
        }

        rows.append(item)

        if ignore_stock:
            warnings.append(
                f"{material_code} / {material_name}: 재고 무시 자재로 설정되어 부족 판단에서 제외되었습니다."
            )

        if shortage_qty > 0:
            shortages.append(item)

    bottlenecks = []

    if max_possible_qty is not None:
        for item in rows:
            possible = item.get("자재별가능수량")

            if possible is not None and abs(possible - max_possible_qty) < 0.0001:
                bottlenecks.append(item)

    return {
        "found": True,
        "제품코드": product_code,
        "제품명": product_real_name,
        "요청수량": float(request_qty),
        "최대가능수량": max_possible_qty,
        "상세": rows,
        "부족": shortages,
        "경고": warnings,
        "소요량0": zero_usage_rows,
        "병목": bottlenecks,
        "계획차감적용": bool(extra_consumption),
        "조회시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "재고기준": TARGET_WAREHOUSE,
        "match_info": match_info,
    }


def format_not_found(result):
    lines = []
    lines.append(result["message"])
    lines.append("")

    similar_products = result.get("similar_products", [])

    if similar_products:
        lines.append("혹시 아래 제품 중 하나인가요?")
        lines.append("")

        for idx, item in enumerate(similar_products, start=1):
            score_percent = round(float(item["유사도"]) * 100)
            reason = item.get("매칭사유", "유사")

            lines.append(
                f"{idx}. {item['제품코드']} / {item['제품명']} "
                f"(유사도 {score_percent}% / {reason})"
            )

        lines.append("")
        lines.append("정확한 제품명 또는 제품코드로 다시 질문해주세요.")
        lines.append("")
        lines.append("예시:")
        lines.append(f"- {similar_products[0]['제품명']} 1000kg 생산 가능해?")
        lines.append(f"- {similar_products[0]['제품코드']} 1000kg 생산 가능해?")
    else:
        lines.append("비슷한 제품명을 찾지 못했습니다.")
        lines.append("")
        lines.append("제품명 또는 제품코드를 다시 확인해주세요.")
        lines.append("예: P10544 7800kg 생산 가능해?")

    return "\n".join(lines)


def get_low_remaining_rows(result, limit=5):
    rows = []

    for item in result.get("상세", []):
        if item["판정"] == "가능" and item["생산후잔량"] >= 0:
            rows.append(item)

    rows.sort(key=lambda x: x["생산후잔량"])

    return rows[:limit]


def format_full(result):
    if not result["found"]:
        return format_not_found(result)

    lines = []
    lines.append("=" * 50)
    lines.append("[생산 가능 여부 확인]")
    lines.append("=" * 50)
    lines.append(f"제품코드: {result['제품코드']}")
    lines.append(f"제품명: {result['제품명']}")
    lines.append(f"요청 생산수량: {fmt_num(result['요청수량'])}kg")
    lines.append(f"조회시각: {result['조회시각']}")
    lines.append(f"재고 기준: {result.get('재고기준', TARGET_WAREHOUSE)}")

    match_info = result.get("match_info")

    if match_info:
        lines.append(
            f"제품명 자동매칭: {match_info.get('제품명')} "
            f"[{match_info.get('제품코드')}] "
            f"유사도 {round(float(match_info.get('유사도', 0)) * 100)}%"
        )

    if result.get("계획차감적용"):
        lines.append("기존 생산계획 차감: 적용")

    lines.append("")

    if result["부족"]:
        lines.append("판정: 생산 불가능")
        lines.append(f"부족 자재 수: {len(result['부족'])}개")
    else:
        lines.append("판정: 생산 가능")
        lines.append("원/부자재창고 가용재고 기준으로 요청 수량 생산 가능합니다.")

    lines.append("")

    if result["최대가능수량"] is not None:
        lines.append(f"원/부자재창고 기준 최대 생산 가능 수량: {fmt_num(result['최대가능수량'])}kg")
    else:
        lines.append("현재 재고 기준 최대 생산 가능 수량: 계산 불가")

    lines.append("")

    if result["부족"]:
        lines.append("[부족 자재]")

        for idx, item in enumerate(result["부족"], start=1):
            plan_text = ""

            if item["계획차감수량"] > 0:
                plan_text = f" / 기존계획차감 {fmt_num(item['계획차감수량'])}{item['재고단위']}"

            lines.append(
                f"{idx}. {item['자재코드']} / {item['자재명']}\n"
                f" 필요: {fmt_num(item['필요수량'])}{item['배합단위']} / "
                f"가용: {fmt_num(item['가용재고'])}{item['재고단위']} / "
                f"부족: {fmt_num(item['부족수량'])}{item['배합단위']}"
                f"{plan_text}"
                f"{item['단위경고']}"
            )

        lines.append("")
    else:
        low_rows = get_low_remaining_rows(result, limit=5)

        if low_rows:
            lines.append("[생산 후 잔량 낮은 자재]")

            for idx, item in enumerate(low_rows, start=1):
                plan_text = ""

                if item["계획차감수량"] > 0:
                    plan_text = f" / 기존계획차감 {fmt_num(item['계획차감수량'])}{item['재고단위']}"

                lines.append(
                    f"{idx}. {item['자재코드']} / {item['자재명']}: "
                    f"생산 후 잔량 {fmt_num(item['생산후잔량'])}{item['재고단위']}"
                    f"{plan_text}"
                )

            lines.append("")

        lines.append("상세 자재 현황이 필요하면 '상세 자재현황 보여줘'라고 질문하세요.")

    if result["경고"]:
        lines.append("")
        lines.append("[확인 필요]")

        for w in result["경고"]:
            lines.append(f"- {w}")

    lines.append("=" * 50)

    return "\n".join(lines)


def format_detail(result):
    if not result["found"]:
        return format_not_found(result)

    lines = []
    lines.append("=" * 50)
    lines.append("[상세 자재 현황]")
    lines.append("=" * 50)
    lines.append(f"제품코드: {result['제품코드']}")
    lines.append(f"제품명: {result['제품명']}")
    lines.append(f"요청 생산수량: {fmt_num(result['요청수량'])}kg")
    lines.append(f"조회시각: {result['조회시각']}")

    match_info = result.get("match_info")

    if match_info:
        lines.append(
            f"제품명 자동매칭: {match_info.get('제품명')} "
            f"[{match_info.get('제품코드')}] "
            f"유사도 {round(float(match_info.get('유사도', 0)) * 100)}%"
        )

    if result.get("계획차감적용"):
        lines.append("기존 생산계획 차감: 적용")

    lines.append("")

    if result["부족"]:
        lines.append("판정: 생산 불가능")
        lines.append(f"부족 자재 수: {len(result['부족'])}개")
    else:
        lines.append("판정: 생산 가능")

    lines.append("")

    if result["최대가능수량"] is not None:
        lines.append(f"현재 재고 기준 최대 생산 가능 수량: {fmt_num(result['최대가능수량'])}kg")
    else:
        lines.append("현재 재고 기준 최대 생산 가능 수량: 계산 불가")

    lines.append("")
    lines.append("[전체 자재 현황]")

    for item in result["상세"]:
        plan_text = ""

        if item["계획차감수량"] > 0:
            plan_text = f" / 기존계획차감 {fmt_num(item['계획차감수량'])}{item['재고단위']}"

        lines.append(
            f"- {item['자재코드']} / {item['자재명']}: "
            f"필요 {fmt_num(item['필요수량'])}{item['배합단위']} / "
            f"ERP가용 {fmt_num(item['원가용재고'])}{item['재고단위']} / "
            f"계산가용 {fmt_num(item['가용재고'])}{item['재고단위']} / "
            f"생산후잔량 {fmt_num(item['생산후잔량'])}{item['재고단위']} / "
            f"판정 {item['판정']}"
            f"{' / 재고무시' if item.get('재고무시') else ''}"
            f"{plan_text}"
            f"{item['단위경고']}"
        )

    if result["경고"]:
        lines.append("")
        lines.append("[확인 필요]")

        for w in result["경고"]:
            lines.append(f"- {w}")

    lines.append("=" * 50)

    return "\n".join(lines)


def format_max_possible(result):
    if not result["found"]:
        return format_not_found(result)

    lines = []
    lines.append("=" * 50)
    lines.append("[최대 생산 가능 수량]")
    lines.append("=" * 50)
    lines.append(f"제품코드: {result['제품코드']}")
    lines.append(f"제품명: {result['제품명']}")
    lines.append(f"조회시각: {result['조회시각']}")

    match_info = result.get("match_info")

    if match_info:
        lines.append(
            f"제품명 자동매칭: {match_info.get('제품명')} "
            f"[{match_info.get('제품코드')}] "
            f"유사도 {round(float(match_info.get('유사도', 0)) * 100)}%"
        )

    if result.get("계획차감적용"):
        lines.append("기존 생산계획 차감: 적용")

    lines.append("")

    if result["최대가능수량"] is None:
        lines.append("현재 재고 기준 최대 생산 가능 수량을 계산할 수 없습니다.")
    else:
        lines.append(f"현재 재고 기준 최대 생산 가능 수량: {fmt_num(result['최대가능수량'])}kg")

    if result["병목"]:
        lines.append("")
        lines.append("[제한 자재]")

        for idx, item in enumerate(result["병목"], start=1):
            plan_text = ""

            if item["계획차감수량"] > 0:
                plan_text = f" / 기존계획차감 {fmt_num(item['계획차감수량'])}{item['재고단위']}"

            lines.append(
                f"{idx}. {item['자재코드']} / {item['자재명']} "
                f"(계산가용 {fmt_num(item['가용재고'])}{item['재고단위']}"
                f"{plan_text})"
            )

    lines.append("=" * 50)

    return "\n".join(lines)


def format_shortage_only(result):
    if not result["found"]:
        return format_not_found(result)

    lines = []
    lines.append("=" * 50)
    lines.append("[부족 자재 확인]")
    lines.append("=" * 50)
    lines.append(f"제품코드: {result['제품코드']}")
    lines.append(f"제품명: {result['제품명']}")
    lines.append(f"요청 생산수량: {fmt_num(result['요청수량'])}kg")
    lines.append(f"조회시각: {result['조회시각']}")

    match_info = result.get("match_info")

    if match_info:
        lines.append(
            f"제품명 자동매칭: {match_info.get('제품명')} "
            f"[{match_info.get('제품코드')}] "
            f"유사도 {round(float(match_info.get('유사도', 0)) * 100)}%"
        )

    if result.get("계획차감적용"):
        lines.append("기존 생산계획 차감: 적용")

    lines.append("")

    if not result["부족"]:
        lines.append("부족 자재 없음")
        lines.append("현재 가용재고 기준으로 요청 수량 생산 가능합니다.")
    else:
        lines.append(f"부족 자재 수: {len(result['부족'])}개")
        lines.append("")

        for idx, item in enumerate(result["부족"], start=1):
            plan_text = ""

            if item["계획차감수량"] > 0:
                plan_text = f" / 기존계획차감 {fmt_num(item['계획차감수량'])}{item['재고단위']}"

            lines.append(
                f"{idx}. {item['자재코드']} / {item['자재명']}\n"
                f" 필요: {fmt_num(item['필요수량'])}{item['배합단위']} / "
                f"가용: {fmt_num(item['가용재고'])}{item['재고단위']} / "
                f"부족: {fmt_num(item['부족수량'])}{item['배합단위']}"
                f"{plan_text}"
                f"{item['단위경고']}"
            )

    lines.append("=" * 50)

    return "\n".join(lines)


def check_production(product_name: str, request_qty: float = 1, intent: str = "production_check", extra_consumption=None):
    result = build_result(product_name, request_qty, extra_consumption=extra_consumption)

    if intent == "max_possible":
        return format_max_possible(result)

    if intent == "shortage_only":
        return format_shortage_only(result)

    if intent == "detail":
        return format_detail(result)

    return format_full(result)


if __name__ == "__main__":
    product = input("제품명을 입력하세요: ")
    qty = float(input("생산수량을 입력하세요: "))
    print(check_production(product, qty, "production_check"))
