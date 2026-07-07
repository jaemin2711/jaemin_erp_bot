import os
import json
import re  # 정규표현식 모듈
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv()

# --- 클라이언트 초기화 ---
api_key_1 = os.getenv("OPENAI_API_KEY_1")
api_key_2 = os.getenv("OPENAI_API_KEY_2")
default_openai_key = os.getenv("OPENAI_API_KEY")

client_openai_1 = OpenAI(api_key=api_key_1 or default_openai_key)
client_openai_2 = OpenAI(api_key=api_key_2 or default_openai_key)

# Google Gemini 클라이언트
gemini_key = os.getenv("GEMINI_API_KEY")
try:
    from google import genai
    from google.genai import types
    client_gemini = genai.Client(api_key=gemini_key) if gemini_key else None
except ImportError:
    client_gemini = None


def parse_question(question_text: str) -> dict:
    """
    유저의 질문을 분석하여 제품명, 수량, 의도를 JSON 형태로 파싱합니다.
    OpenAI Key 1 ➔ OpenAI Key 2 ➔ Google Gemini ➔ 로컬 백업(Fallback) 순으로 우회합니다.
    """
    prompt = f"""
    사용자의 질문을 분석해서 JSON 형식으로만 답변하세요.
    질문: "{question_text}"

    [중요 수량 변환 규칙]
    - 사용자가 수량 단위로 '톤' 또는 't'를 사용한 경우, 반드시 1000을 곱해서 'kg' 단위 숫자로 환산하여 quantity에 넣으세요.
      (예: "6톤" -> 6000, "1.5t" -> 1500)
    - 'kg'이나 '킬로'로 말한 경우, 숫자 그대로 입력하세요.
      (예: "500kg" -> 500)
    - 숫자가 없는 경우 null을 반환하세요.
    
    반환 형식:
    {{
        "intent": "production_check" 또는 "show_plan" 또는 "delete_plan",
        "product_name": "제품명 또는 코드",
        "quantity": 숫자 (kg 단위로 환산된 순수 숫자만 입력),
        "date": "YYYY-MM-DD" (날짜 언급이 있으면 포함, 없으면 null)
    }}
    """

    # 1단계: OpenAI 첫 번째 무료 키로 시도
    try:
        response = client_openai_1.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)

    except RateLimitError:
        print("⚠️ [ai_parser] OpenAI 1번 키 제한 발생 ➔ 2번 키로 우회합니다.")
        
        # 2단계: OpenAI 두 번째 무료 키로 우회 시도
        try:
            response = client_openai_2.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
            
        except RateLimitError:
            print("⚠️ [ai_parser] OpenAI 모든 키 차단 ➔ 대피소 Google Gemini 호출합니다.")
            
            # 3단계: OpenAI 전멸 시 Google Gemini 플랜 B 발동
            if client_gemini:
                try:
                    response = client_gemini.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                        ),
                    )
                    return json.loads(response.text)
                except Exception as gemini_err:
                    print(f"❌ [ai_parser] Gemini 엔진마저 오류 발생: {str(gemini_err)}")
                    return fallback_parse(question_text)
            else:
                print("❌ [ai_parser] Google Gemini 가동 불가 ➔ 로컬 백업 가동")
                return fallback_parse(question_text)
                
    except Exception as e:
        print(f"🚨 [ai_parser] 기타 예외 발생: {str(e)}")
        return fallback_parse(question_text)


def fallback_parse(text: str) -> dict:
    """
    모든 AI API가 제한되거나 막혔을 때 작동하는 최후의 규칙 기반 방어선.
    날짜 추출 및 순수 제품명 발라내기 로직을 보완했습니다.
    """
    clean_text = text.replace(" ", "").lower()
    result = {"intent": "production_check", "product_name": None, "quantity": None, "date": None}
    
    # 1. 의도 파악
    if "조회" in clean_text or "목록" in clean_text:
        result["intent"] = "show_plan"
        return result
    if "취소" in clean_text or "삭제" in clean_text:
        result["intent"] = "delete_plan"

    # 2. 📅 기본 날짜 추출 (예: 2026-06-09 또는 06/09 등 형식 가이드)
    date_match = re.search(r'(\d{4}[-\./])?(\d{1,2})[-\./](\d{1,2})', text)
    if date_match:
        year = date_match.group(1) if date_match.group(1) else f"{datetime.now().year}-"
        month = f"{int(date_match.group(2)):02d}"
        day = f"{int(date_match.group(3)):02d}"
        result["date"] = f"{year.replace('/', '-').replace('.', '-')}{month}-{day}"
    else:
        # "6월9일" 형태 추출
        kor_date_match = re.search(r'(?:(\d{4})년)?\s*(\d{1,2})월\s*(\d{1,2})일', text)
        if kor_date_match:
            year = kor_date_match.group(1) if kor_date_match.group(1) else datetime.now().year
            month = f"{int(kor_date_match.group(2)):02d}"
            day = f"{int(kor_date_match.group(3)):02d}"
            result["date"] = f"{year}-{month}-{day}"

    # 3. 🔢 수량 및 단위 정밀 추출 (예: "10톤", "10t", "10kg")
    match_qty = re.search(r'(\d+(?:\.\d+)?)\s*(톤|t|kg|킬로)', clean_text)
    
    if match_qty:
        raw_val = float(match_qty.group(1))
        unit = match_qty.group(2)
        
        if '톤' in unit or 't' in unit:
            result["quantity"] = raw_val * 1000
        else:
            result["quantity"] = raw_val
    else:
        # 단위가 없더라도 문장 맨 뒤에 있는 숫자를 수량으로 간주
        match_pure_num = re.search(r'(\d+(?:\.\d+)?)(?:kg|톤|t|킬로|개|확인|가능|$)', clean_text)
        if match_pure_num:
            result["quantity"] = float(match_pure_num.group(1))

    # 4. 📦 제품명 추출 보완 (불필요한 수식어 및 숫자 완벽 제거)
    remove_pattern = r'\d+년|\d+월|\d+일|\d+자|\d+톤|\d+t|\d+kg|\d+|생산|가능|조회|목록|취소|삭제|등록|해줘| 확인|\?'
    name_clean = re.sub(remove_pattern, '', clean_text)
    
    if name_clean:
        result["product_name"] = name_clean.strip().upper()  # 제품코드를 고려해 대문자 변경

    return result