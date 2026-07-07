import os
import json
import base64
import mimetypes
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    raise RuntimeError("OPENAI_API_KEY가 .env 파일에 없습니다.")

client = OpenAI(api_key=api_key)

IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.4-mini"))


def extract_json(text: str) -> dict:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError(f"이미지 분석 결과에서 JSON을 찾지 못했습니다.\n응답 내용:\n{text}")

    return json.loads(text[start:end + 1])


def fmt_number(value):
    try:
        value = float(str(value).replace(",", "").strip())

        if value.is_integer():
            return str(int(value))

        return str(value).rstrip("0").rstrip(".")
    except Exception:
        return str(value).strip()


def normalize_unit(unit):
    unit = str(unit or "").strip().lower()

    if unit in ["t", "ton", "tons", "톤"]:
        return "톤"

    if unit in ["kg", "키로", "킬로", "kilogram", "kilograms"]:
        return "kg"

    return "kg"


def safe_int(value):
    try:
        if value is None or str(value).strip() == "":
            return None

        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return None


def make_date_from_parts(year, month, day) -> Optional[datetime]:
    month = safe_int(month)
    day = safe_int(day)

    if month is None or day is None:
        return None

    year = safe_int(year) or datetime.now().year

    try:
        return datetime(year, month, day)
    except Exception:
        return None


def build_question_from_schedule_row(row: dict) -> Optional[str]:
    """
    이미지 표 행을 생산계획 등록 문장으로 변환합니다.

    우선순위:
    1. 표에 '생산일자', '생산일', '제조일'이 있으면 그 날짜를 그대로 생산일로 사용
    2. 생산일자가 없고 '도착일'만 있으면 기존 방식대로 도착일 - 2일을 생산일로 계산

    반환 예:
    6월 14일 블루믹스 P001 1000kg 생산계획 등록 일괄
    """
    product_name = str(row.get("product_name", "") or "").strip()
    product_code = str(row.get("product_code", "") or "").strip()
    quantity = row.get("quantity", None)
    unit = normalize_unit(row.get("unit", "kg"))

    if not product_name and not product_code:
        return None

    if quantity is None or str(quantity).strip() == "":
        return None

    # 1순위: 생산일자 직접 사용
    production_date = make_date_from_parts(
        row.get("production_year"),
        row.get("production_month"),
        row.get("production_day"),
    )

    # 2순위: 도착일 - 2일
    if production_date is None:
        arrival_date = make_date_from_parts(
            row.get("arrival_year"),
            row.get("arrival_month"),
            row.get("arrival_day"),
        )

        if arrival_date is not None:
            production_date = arrival_date - timedelta(days=2)

    if production_date is None:
        return None

    product_part = product_name

    if product_code:
        product_part = f"{product_name} {product_code}".strip()

    qty_text = fmt_number(quantity)

    if unit == "톤":
        qty_part = f"{qty_text}톤"
    else:
        qty_part = f"{qty_text}kg"

    return (
        f"{production_date.month}월 {production_date.day}일 "
        f"{product_part} {qty_part} 생산계획 등록 일괄"
    )


def extract_questions_from_image(image_path: str) -> list[str]:
    """
    이미지에서 생산계획 표를 추출하여 생산계획 등록 문장 리스트로 변환합니다.

    핵심 변경:
    - 이미지 표에 '생산일자', '생산일', '제조일' 컬럼이 있으면 그 값을 생산일로 사용합니다.
    - 사진에서 나온 행은 '생산 가능해?'가 아니라 '생산계획 등록'으로 변환합니다.
    """
    path = Path(image_path)

    if not path.exists():
        raise FileNotFoundError(f"이미지 파일이 없습니다: {image_path}")

    mime_type, _ = mimetypes.guess_type(str(path))

    if not mime_type:
        mime_type = "image/jpeg"

    with open(path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = """
이미지를 분석해서 ERP 생산계획 등록용 JSON으로 변환해라.
반드시 JSON만 출력해라.
설명문, 마크다운 코드블록, 주석은 절대로 포함하지 마라.

출력 형식:
{
  "questions": [],
  "schedule_rows": [
    {
      "product_name": "제품명",
      "product_code": "제품코드 또는 빈문자",
      "quantity": 숫자,
      "unit": "t 또는 kg",
      "production_year": 숫자 또는 null,
      "production_month": 숫자 또는 null,
      "production_day": 숫자 또는 null,
      "arrival_year": 숫자 또는 null,
      "arrival_month": 숫자 또는 null,
      "arrival_day": 숫자 또는 null
    }
  ]
}

가장 중요한 날짜 규칙:
1. 표에 '생산일자', '생산 일자', '생산일', '제조일', '작업일' 컬럼이 있으면 그 날짜를 production_year, production_month, production_day에 넣어라.
2. 표에 '도착일', '납품일', '출고일'만 있고 생산일자가 없으면 그 날짜를 arrival_year, arrival_month, arrival_day에 넣어라.
3. production_month/day와 arrival_month/day가 둘 다 보이면 production_month/day를 우선한다.
4. 연도가 보이지 않으면 year는 null로 둔다.
5. 날짜 칸이 큰따옴표("), ditto mark(〃), '상동', '동일'이면 바로 위 행의 날짜와 완전히 같다는 뜻이다. 반드시 위 행 날짜를 그대로 이어서 넣어라.
6. 날짜가 '재고확보', '미정', 빈칸이면 schedule_rows에서 제외한다.

제품/수량 규칙:
1. 제품명, 제품코드, 수량, 단위를 최대한 정확히 읽어라.
2. 숫자 콤마는 제거한다. 예: 7,800 -> 7800
3. '2 t', '2톤'은 quantity: 2, unit: "t"
4. '500 kg', '500키로'는 quantity: 500, unit: "kg"
5. 단위가 없으면 기본값 unit: "kg"
6. 빈 행, 제목 행, 합계 행, 안내문 행은 제외한다.
7. 제품명 또는 수량이 없으면 제외한다.

중요:
- 이미지에 표가 있으면 questions는 비워두고 schedule_rows만 채워라.
- 표가 없고 단순 텍스트만 있으면 questions에 원문을 넣어도 된다.
"""

    response = client.responses.create(
        model=IMAGE_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt,
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{mime_type};base64,{image_base64}",
                    },
                ],
            }
        ],
    )

    raw_text = response.output_text.strip()
    data = extract_json(raw_text)

    final_questions = []

    # 1. 표 행 처리
    schedule_rows = data.get("schedule_rows", [])

    if isinstance(schedule_rows, list) and len(schedule_rows) > 0:
        for row in schedule_rows:
            if not isinstance(row, dict):
                continue

            q = build_question_from_schedule_row(row)

            if q:
                final_questions.append(q)

    # 2. 표가 없는 단순 이미지일 경우
    else:
        questions = data.get("questions", [])

        if isinstance(questions, list):
            for q in questions:
                q = str(q).strip().strip('"').strip("'")

                if not q:
                    continue

                # 단순 텍스트도 가능 여부가 아니라 등록 문장에 가깝게 변환
                q = q.replace("생산 가능해?", "").replace("생산 가능", "").strip()

                if "생산계획" not in q and "생산등록" not in q:
                    q = f"{q} 생산계획 등록 일괄"
                elif "일괄" not in q:
                    q = f"{q} 일괄"

                final_questions.append(q)

    # 중복 제거
    cleaned = []
    seen = set()

    for q in final_questions:
        q = " ".join(str(q).split())

        if q and q not in seen:
            cleaned.append(q)
            seen.add(q)

    return cleaned


def extract_question_from_image(image_path: str) -> str:
    questions = extract_questions_from_image(image_path)

    if not questions:
        return ""

    return questions[0]


if __name__ == "__main__":
    image_path = input("이미지 경로를 입력하세요: ").strip()
    questions = extract_questions_from_image(image_path)

    print("[이미지에서 읽은 생산등록 목록]")

    for q in questions:
        print("-", q)
