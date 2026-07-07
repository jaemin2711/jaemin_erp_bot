from bot_config import *
from bot_auth import is_allowed_user
from bot_io import save_usage_log, split_message
from plan_utils import *


def strip_force_command_keywords(text: str):
    """
    강제등록 문장에서 명령어/불필요한 문구를 제거합니다.
    """
    raw = str(text or "").strip()

    replacements = [
        r"^/forceplan\s*",
        r"^/강제등록\s*",
        r"^/강제추가\s*",
        r"강제\s*생산계획\s*추가\s*등록",
        r"강제\s*생산계획\s*등록",
        r"강제\s*추가\s*등록",
        r"강제\s*등록",
        r"무조건\s*생산",
        r"생산계획",
        r"추가등록",
        r"추가\s*등록",
        r"등록",
    ]

    cleaned = raw

    for pattern in replacements:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,/")
    return cleaned


def parse_force_register_command_text(text: str):
    """
    생산계획 등록/저장/정정 명령 파싱.
    예:
    - /강제등록 6/18 만능곰팡이가드 1톤
    - 6/22 TS) 비타40호 500kg 저장
    - TS) 비타40호 1톤에서 500kg로 정정, 6/22 생산가능?
    - TS) 비타40호 1톤에서 500kg로 수정, 6/22 생산가능?
    """
    raw = str(text or "").strip()
    cleaned = strip_force_command_keywords(raw)

    production_date = parse_plan_date_input(cleaned)
    qty = parse_quantity_for_command(cleaned)

    if not production_date:
        return None, None, None, "생산일자를 인식하지 못했습니다. 예: 6/22 제품명 500kg 정정"

    if qty is None or qty <= 0:
        return None, None, None, "수량을 인식하지 못했습니다. 예: 6/22 제품명 500kg 정정"

    product_part = cleaned

    date_patterns = [
        r"\d{4}[-./]\d{1,2}[-./]\d{1,2}",
        r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일?",
        r"\d{1,2}\s*월\s*\d{1,2}\s*일?",
        r"\b\d{1,2}\s*/\s*\d{1,2}\b",
        r"\b\d{1,2}\s*-\s*\d{1,2}\b",
        r"오늘|내일|모레",
        r"\d+\s*일\s*(뒤|후)",
    ]

    for pattern in date_patterns:
        product_part = re.sub(pattern, " ", product_part)

    # "1톤에서 500kg로 정정" 같은 문장에서 기존수량/변경수량 모두 제거
    product_part = re.sub(
        r"(\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(톤|t|kg|키로|킬로)\s*(에서|으로|로)?",
        " ",
        product_part,
        flags=re.IGNORECASE,
    )

    product_part = re.sub(r"(?<![A-Za-z])\b\d+(?:,\d{3})*(?:\.\d+)?\b(?![A-Za-z])", " ", product_part)

    cleanup_patterns = [
        r"^/forceplan\s*",
        r"^/강제등록\s*",
        r"^/강제추가\s*",
        r"강제\s*생산계획\s*추가\s*등록",
        r"강제\s*생산계획\s*등록",
        r"강제\s*추가\s*등록",
        r"강제\s*등록",
        r"무조건\s*생산",
        r"생산\s*가능\s*여부",
        r"생산\s*가능",
        r"가능\s*\?",
        r"가능",
        r"확인",
        r"생산계획",
        r"생산등록",
        r"생산",
        r"계획",
        r"추가등록",
        r"추가\s*등록",
        r"등록",
        r"저장",
        r"정정",
        r"수정",
        r"변경",
        r"교체",
        r"해주세요",
        r"해줘",
        r"해라",
        r"바꿔",
    ]

    for pattern in cleanup_patterns:
        product_part = re.sub(pattern, " ", product_part, flags=re.IGNORECASE)

    product_part = re.sub(r"\b(에서|으로|로|에|를|을|은|는|이|가)\b", " ", product_part)
    product_part = re.sub(r"\s+", " ", product_part).strip(" ,/-_?:：")

    if not product_part:
        return None, None, None, "제품명을 인식하지 못했습니다. 예: 6/22 TS) 비타40호 500kg 정정"

    return production_date, product_part, qty, None


def force_add_production_plan(production_date: str, product_code: str, product_name: str, qty_kg: float, question: str = ""):
    """
    자재 부족 여부와 관계없이 생산계획을 저장합니다.
    같은 날짜/같은 제품코드가 이미 있으면 중복 저장하지 않고 안내합니다.
    """
    production_date = normalize_plan_date(production_date)
    product_code = str(product_code or "").strip()
    product_name = str(product_name or "").strip()
    qty_kg = float(qty_kg)

    plans = load_plans()

    if plans is None or plans.empty:
        plans = pd.DataFrame(columns=["생산일", "제품코드", "제품명", "생산수량kg", "질문", "등록시각", "등록구분"])
    else:
        plans = plans.copy()

    for col in ["생산일", "제품코드", "제품명", "생산수량kg", "질문", "등록시각", "등록구분"]:
        if col not in plans.columns:
            plans[col] = ""

    duplicate = plans[
        (plans["생산일"].apply(normalize_plan_date) == production_date)
        & (plans["제품코드"].astype(str).str.strip() == product_code)
    ]

    if not duplicate.empty:
        dup_qty = pd.to_numeric(duplicate["생산수량kg"], errors="coerce").fillna(0).sum()
        return False, (
            "같은 날짜에 같은 제품의 생산계획이 이미 있어 강제 추가등록하지 않았습니다.\n"
            f"- 생산일: {production_date}\n"
            f"- 제품: {product_name} [{product_code}]\n"
            f"- 기존 수량: {fmt_num(dup_qty)}kg\n\n"
            "수량을 바꾸려면 /planlist 번호 확인 후 /수정 번호, 날짜, 수량 형식으로 변경해 주세요."
        )

    new_row = {
        "생산일": production_date,
        "제품코드": product_code,
        "제품명": product_name,
        "생산수량kg": qty_kg,
        "질문": question,
        "등록시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "등록구분": "강제",
    }

    plans = pd.concat([plans, pd.DataFrame([new_row])], ignore_index=True)
    save_plans(plans)

    return True, (
        "강제 생산계획을 저장했습니다.\n"
        f"- 생산일: {production_date}\n"
        f"- 제품: {product_name} [{product_code}]\n"
        f"- 수량: {fmt_num(qty_kg)}kg"
    )


def format_shortage_prepare_text(result):
    """
    강제등록 후 준비해야 할 부족 자재를 보기 좋게 표시합니다.
    """
    shortages = result.get("부족", [])

    if not shortages:
        return "현재 기준 부족 자재는 없습니다."

    lines = []
    lines.append("[준비 필요 부족 자재]")

    for idx, item in enumerate(shortages, start=1):
        lines.append(
            f"{idx}. {item['자재코드']} / {item['자재명']}\n"
            f"   필요 {fmt_num(item['필요수량'])}{item['배합단위']} / "
            f"가용 {fmt_num(item['가용재고'])}{item['재고단위']} / "
            f"부족 {fmt_num(item['부족수량'])}{item['배합단위']}"
        )

    return "\n".join(lines)

def is_single_plan_register_text(text: str):
    """
    단일 제품 일반 생산계획 등록/저장/정정/변경 문장인지 판단합니다.

    중요:
    - '생산 가능?'만 있는 문장은 저장하지 않습니다.
    - 강제등록 ON 상태여도 '등록/저장/정정/수정/변경' 같은 저장 의도 키워드가 있어야 저장합니다.

    저장 처리 예:
    - 6/22 TS) 비타40호 500kg 저장
    - 6/22 TS) 비타40호 500kg 등록
    - TS) 비타40호 1톤에서 500kg로 정정, 6/22 생산가능?
    - TS) 비타40호 500kg로 변경, 6/22 생산가능?

    단순 확인 예:
    - 6/22 TS) 비타40호 500kg 생산 가능?
    """
    raw = str(text or "").strip()
    compact = raw.replace(" ", "").lower()

    if not raw:
        return False

    # 강제 모드 ON/OFF 설정 명령은 제외
    if (
        "강제등록켜" in compact
        or "강제등록꺼" in compact
        or "강제등록상태" in compact
        or "강제모드" in compact
        or "강제기간등록" in compact
    ):
        return False

    # 직접 강제등록 명령은 기존 process_force_register_command로 처리
    if compact.startswith("/강제등록") or compact.startswith("/강제추가") or compact.startswith("/forceplan"):
        return False

    # 번호 기반 수정은 기존 /수정 로직이 처리
    if re.match(r"^/(수정|editplan)\s+\d+", raw, flags=re.IGNORECASE):
        return False

    # 저장 의도 키워드가 반드시 있어야 함
    has_save_intent = (
        "등록" in compact
        or "저장" in compact
        or "정정" in compact
        or "수정" in compact
        or "변경" in compact
        or "추가등록" in compact
    )

    if not has_save_intent:
        return False

    # 날짜와 수량이 같이 있어야 생산계획 등록/정정으로 본다.
    try:
        has_date = bool(parse_plan_date_input(raw))
    except Exception:
        has_date = False

    try:
        has_qty = parse_quantity_for_command(raw) is not None
    except Exception:
        has_qty = False

    if not has_date or not has_qty:
        return False

    try:
        if is_multi_production_request(raw):
            return False
    except Exception:
        pass

    return True

async def process_single_plan_register_command(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """
    일반 단일 생산계획 등록/저장/정정 처리.

    등록/저장/정정/수정/변경 키워드가 있는 문장만 여기로 들어옵니다.
    강제등록 모드가 켜진 날짜면 부족 자재가 있어도 저장합니다.
    """
    production_date, product_text, qty_kg, err = parse_force_register_command_text(text)

    if err:
        await update.message.reply_text(f"❌ {err}")
        return True

    try:
        extra_consumption = get_planned_consumption_until(production_date)
        result = await asyncio.to_thread(
            build_result,
            product_text,
            qty_kg,
            extra_consumption=extra_consumption,
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ 생산계획 등록 전 생산 가능 여부 확인 중 오류가 발생했습니다.\n"
            f"사유: {str(e)}"
        )
        return True

    if not result.get("found"):
        await update.message.reply_text(
            f"❌ 제품명을 찾지 못해 생산계획에 저장하지 않았습니다.\n"
            f"- 입력 제품명: {product_text}\n"
            f"제품코드 또는 정확한 제품명으로 다시 입력해 주세요."
        )
        return True

    product_code = result.get("제품코드") or product_text
    product_name = result.get("제품명") or product_text
    shortage_list = result.get("부족", [])

    try:
        force_mode_on = is_force_enabled_for_date(production_date)
    except Exception:
        force_mode_on = False

    lines = []
    lines.append("[일반 생산계획 등록/정정]")
    lines.append(f"생산일: {production_date}")
    lines.append(f"제품: {product_name} [{product_code}]")
    lines.append(f"수량: {fmt_num(qty_kg)}kg")
    lines.append(f"강제등록 모드: {'ON' if force_mode_on else 'OFF'}")
    lines.append("처리기준: 등록/저장/정정/수정/변경 키워드가 있어 생산계획 저장 의도로 처리")
    lines.append("")

    if shortage_list and not force_mode_on:
        lines.append("판정: ❌ 생산 불가능")
        lines.append("저장: 안 함")
        lines.append("사유: 부족 자재가 있어 생산계획에 저장하지 않았습니다.")
        lines.append("")
        lines.append("[부족 자재]")

        for idx, item in enumerate(shortage_list, start=1):
            lines.append(
                f"{idx}. {item['자재코드']} / {item['자재명']} - "
                f"필요 {fmt_num(item['필요수량'])}{item['배합단위']}, "
                f"가용 {fmt_num(item['가용재고'])}{item['재고단위']}, "
                f"부족 {fmt_num(item['부족수량'])}{item['배합단위']}"
            )

    elif shortage_list and force_mode_on:
        saved, msg = await asyncio.to_thread(
            force_add_production_plan,
            production_date,
            product_code,
            product_name,
            qty_kg,
            text,
        )

        lines.append("판정: ❌ 생산 불가능")
        lines.append("처리: 강제등록 모드 ON이라 부족 자재가 있어도 저장 시도")
        lines.append("저장: 강제 완료" if saved else "저장: 보류")
        lines.append(msg)
        lines.append("")
        lines.append("[부족 자재]")

        for idx, item in enumerate(shortage_list, start=1):
            lines.append(
                f"{idx}. {item['자재코드']} / {item['자재명']} - "
                f"필요 {fmt_num(item['필요수량'])}{item['배합단위']}, "
                f"가용 {fmt_num(item['가용재고'])}{item['재고단위']}, "
                f"부족 {fmt_num(item['부족수량'])}{item['배합단위']}"
            )

    else:
        saved, msg = await asyncio.to_thread(
            add_production_plan,
            production_date,
            product_code,
            qty_kg,
            question=text,
        )

        lines.append("판정: ✅ 생산 가능")
        lines.append("저장: 완료" if saved else "저장: 보류")
        lines.append(msg)

    final_text = "\n".join(lines)

    save_usage_log(
        update.effective_user.id,
        update.effective_user.username,
        f"일반등록정정:{production_date} {product_text} {fmt_num(qty_kg)}kg",
        final_text,
    )

    for part in split_message(final_text):
        await update.message.reply_text(part)

    return True


async def process_force_register_command(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    production_date, product_text, qty_kg, err = parse_force_register_command_text(text)

    if err:
        await update.message.reply_text(f"❌ {err}")
        return True

    try:
        extra_consumption = get_planned_consumption_until(production_date)
        result = await asyncio.to_thread(
            build_result,
            product_text,
            qty_kg,
            extra_consumption=extra_consumption,
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ 강제등록 전 생산 가능 여부 확인 중 오류가 발생했습니다.\n"
            f"사유: {str(e)}"
        )
        return True

    if not result.get("found"):
        lines = []
        lines.append("❌ 제품명을 찾지 못해 강제등록하지 않았습니다.")
        lines.append(f"- 입력 제품명: {product_text}")

        similar = result.get("similar_products", [])

        if similar:
            lines.append("")
            lines.append("[유사 제품 후보]")
            for idx, item in enumerate(similar[:8], start=1):
                score = round(float(item.get("유사도", 0)) * 100)
                lines.append(f"{idx}. {item.get('제품명')} [{item.get('제품코드')}] {score}%")

            lines.append("")
            lines.append("제품코드 또는 정확한 제품명으로 다시 입력해 주세요.")
            lines.append("예: /강제등록 6/18 P10525 3톤")

        await update.message.reply_text("\n".join(lines))
        return True

    product_code = result.get("제품코드") or product_text
    product_name = result.get("제품명") or product_text
    shortage_list = result.get("부족", [])

    saved, save_msg = await asyncio.to_thread(
        force_add_production_plan,
        production_date,
        product_code,
        product_name,
        qty_kg,
        text,
    )

    lines = []
    lines.append("[강제 생산계획 추가등록]")
    lines.append(save_msg)
    lines.append("")

    if shortage_list:
        lines.append("판정: ❗ 현재 재고 기준 생산 불가능")
        lines.append("처리: 생산계획은 강제로 저장됨" if saved else "처리: 저장 안 됨")
        lines.append("아래 부족 자재를 준비해야 합니다.")
    else:
        lines.append("판정: ✅ 현재 재고 기준 생산 가능")
        lines.append("처리: 생산계획 저장 완료" if saved else "처리: 저장 안 됨")

    lines.append("")
    lines.append(format_shortage_prepare_text(result))

    save_usage_log(
        update.effective_user.id,
        update.effective_user.username,
        f"강제등록:{production_date} {product_text} {fmt_num(qty_kg)}kg",
        "\n".join(lines),
    )

    for part in split_message("\n".join(lines)):
        await update.message.reply_text(part)

    return True

async def forceplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/forceplan 명령어 진입점."""
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    await process_force_register_command(update, context, update.message.text)



async def force_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    result = apply_force_mode_command(update.message.text)

    if not result:
        result = get_force_mode_status_text()

    save_usage_log(
        update.effective_user.id,
        update.effective_user.username,
        f"강제등록모드설정:{update.message.text}",
        result,
    )

    await update.message.reply_text(result)
