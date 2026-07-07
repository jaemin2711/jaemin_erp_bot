from bot_config import *
from bot_auth import is_allowed_user
from bot_io import save_usage_log, split_message, safe_reply_text
from bot_sessions import get_user_session
from plan_utils import parse_quantity_text
from product_alias_ocr import (
    should_review_ocr_auto_match,
    get_similar_product_candidates,
    resolve_text_product_alias,
)
from force_plan import force_add_production_plan


def parse_first_image_item(question: str):
    """
    이미지 OCR 문장에서 생산일/제품명/수량을 최대한 뽑습니다.

    image_parser가 보통 '6월 12일 제품명 3000kg 생산계획 등록 일괄' 형태로 넘기지만,
    OCR 결과에 '/'가 들어가면 multi_plan.parse_multi_items가 실패할 수 있어 보조 파서를 둡니다.
    """
    production_date = parse_production_date(question)
    items = parse_multi_items(question)

    if items:
        item = items[0]
        return {
            "production_date": production_date,
            "product_name": str(item.get("제품명", "")).strip(),
            "quantity_kg": float(item.get("생산수량kg", 0)),
        }

    q = str(question or "").strip()
    q_no_date = re.sub(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", " ", q)
    q_no_date = re.sub(r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일", " ", q_no_date)
    q_no_date = re.sub(r"\d{1,2}월\s*\d{1,2}일", " ", q_no_date)
    q_no_date = re.sub(r"\b\d{1,2}/\d{1,2}\b", " ", q_no_date)

    qty_match = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(톤|t|kg|키로|킬로)", q_no_date, flags=re.IGNORECASE)

    if not qty_match:
        return None

    raw_qty = qty_match.group(1).replace(",", "")
    unit = qty_match.group(2).lower()
    quantity_kg = float(raw_qty)

    if unit in ["톤", "t"]:
        quantity_kg *= 1000

    product_part = q_no_date[:qty_match.start()]
    product_part = product_part.replace("/", " ")
    product_part = re.sub(r"생산계획|생산등록|생산|계획|등록|일괄|가능|확인", " ", product_part)
    product_part = re.sub(r"\s+", " ", product_part).strip(" -_:/")

    if not product_part:
        return None

    return {
        "production_date": production_date,
        "product_name": product_part,
        "quantity_kg": quantity_kg,
    }


def make_image_candidate_keyboard(token: str, candidates: list):
    keyboard = []

    for idx, item in enumerate(candidates[:8]):
        code = str(item.get("제품코드", "")).strip()
        name = str(item.get("제품명", "")).strip()
        score = round(float(item.get("유사도", 0)) * 100)
        reason = item.get("매칭사유", "유사")
        label = f"{name} [{code}] {score}%"

        if idx == 0:
            label = "⭐ " + label

        keyboard.append([
            InlineKeyboardButton(
                label[:60],
                callback_data=f"imgsel|{token}|{idx}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "❌ 맞는 제품 없음 / 저장 안 함",
            callback_data=f"imgsel|{token}|cancel",
        )
    ])

    return InlineKeyboardMarkup(keyboard)


async def ask_image_product_choice(update: Update, chat_id: int, row_idx: int, total_count: int, question: str, product_name: str, quantity_kg: float, production_date: str):
    """
    제품명을 못 찾았을 때 후보 선택 버튼을 띄웁니다.
    """
    session = get_user_session(chat_id)
    candidates = get_similar_product_candidates(product_name, limit=8)

    if not candidates:
        await safe_reply_text(
            update,
            f"❓ [{row_idx}/{total_count}] 제품명을 찾지 못했습니다.\n\n"
            f"OCR 인식 제품명: {product_name}\n"
            f"수량: {fmt_num(quantity_kg)}kg\n"
            f"생산일: {production_date or '인식 실패'}\n\n"
            f"유사 제품 후보도 찾지 못했습니다. 제품명을 직접 입력해서 다시 등록해 주세요."
        )
        return

    token = uuid.uuid4().hex[:10]

    session["pending_image_product_choices"][token] = {
        "question": question,
        "row_idx": row_idx,
        "total_count": total_count,
        "ocr_product_name": product_name,
        "quantity_kg": float(quantity_kg),
        "production_date": production_date,
        "candidates": candidates,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    best = candidates[0]
    best_score = round(float(best.get("유사도", 0)) * 100)

    await safe_reply_text(
        update,
        f"❓ [{row_idx}/{total_count}] 제품명을 정확히 찾지 못했습니다.\n\n"
        f"OCR 인식 제품명: {product_name}\n"
        f"수량: {fmt_num(quantity_kg)}kg\n"
        f"생산일: {production_date or '인식 실패'}\n\n"
        f"가장 유사한 후보: {best.get('제품명')} [{best.get('제품코드')}] {best_score}%\n\n"
        f"아래에서 실제 제품명을 선택해 주세요.\n"
        f"선택한 제품으로 다시 생산 가능 여부를 확인하고, 가능하면 생산계획에 저장합니다.",
        reply_markup=make_image_candidate_keyboard(token, candidates),
    )


async def process_image_registration_question(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, question: str, row_idx: int, total_count: int):
    """
    사진에서 추출된 1개 제품 행을 독립 처리합니다.

    개선:
    - OCR 제품명 기억값을 먼저 확인합니다.
    - 기존 자동매칭이 너무 낮거나 OCR명과 인식 제품명이 많이 다르면 후보 선택으로 돌립니다.
    - 후보 버튼에서 사용자가 선택하면 다음부터 자동 기억매칭됩니다.
    """
    parsed = parse_first_image_item(question)

    if not parsed:
        text = f"❌ [{row_idx}/{total_count}] 이미지 행에서 제품명/수량을 읽지 못했습니다.\n원문: {question}"
        return text

    production_date = parsed.get("production_date")
    product_name = parsed.get("product_name")
    quantity_kg = float(parsed.get("quantity_kg") or 0)

    if not production_date:
        production_date = datetime.now().strftime("%Y-%m-%d")

    if not product_name or quantity_kg <= 0:
        return f"❌ [{row_idx}/{total_count}] 제품명 또는 수량을 인식하지 못했습니다.\n원문: {question}"

    memory_notice = None
    remembered = lookup_ocr_product_memory(product_name)

    try:
        extra_consumption = get_planned_consumption_until(production_date)

        if remembered:
            remembered_key = remembered.get("product_code") or remembered.get("product_name")
            result = await asyncio.to_thread(
                build_result,
                remembered_key,
                quantity_kg,
                extra_consumption=extra_consumption,
            )

            if result.get("found"):
                memory_notice = (
                    f"기억매칭: OCR '{product_name}' → "
                    f"{remembered.get('product_name')} [{remembered.get('product_code')}] "
                    f"({round(float(remembered.get('similarity', 1.0)) * 100)}%)"
                )
            else:
                # 기억값이 깨졌거나 제품코드가 바뀐 경우 기존 OCR명으로 다시 확인
                result = await asyncio.to_thread(
                    build_result,
                    product_name,
                    quantity_kg,
                    extra_consumption=extra_consumption,
                )
        else:
            result = await asyncio.to_thread(
                build_result,
                product_name,
                quantity_kg,
                extra_consumption=extra_consumption,
            )

    except Exception as e:
        return f"❌ [{row_idx}/{total_count}] 생산 가능 여부 확인 중 오류가 발생했습니다.\n제품명: {product_name}\n사유: {str(e)}"

    # 기억값이 없는 상태에서 자동매칭이 애매하면 바로 등록하지 않고 후보 선택으로 돌립니다.
    if not remembered and result.get("found") and should_review_ocr_auto_match(product_name, result):
        await ask_image_product_choice(
            update=update,
            chat_id=chat_id,
            row_idx=row_idx,
            total_count=total_count,
            question=question,
            product_name=product_name,
            quantity_kg=quantity_kg,
            production_date=production_date,
        )
        return "__IMAGE_PRODUCT_CHOICE_PENDING__"

    if not result.get("found"):
        await ask_image_product_choice(
            update=update,
            chat_id=chat_id,
            row_idx=row_idx,
            total_count=total_count,
            question=question,
            product_name=product_name,
            quantity_kg=quantity_kg,
            production_date=production_date,
        )
        return "__IMAGE_PRODUCT_CHOICE_PENDING__"

    product_code = result.get("제품코드") or product_name
    product_real_name = result.get("제품명") or product_name
    shortage_list = result.get("부족", [])
    is_possible = not shortage_list

    lines = []
    lines.append(f"[{row_idx}/{total_count}] 이미지 생산등록 처리")
    lines.append(f"생산일: {production_date}")
    lines.append(f"OCR 제품명: {product_name}")
    lines.append(f"인식 제품명: {product_real_name} [{product_code}]")

    if memory_notice:
        lines.append(memory_notice)

    lines.append(f"수량: {fmt_num(quantity_kg)}kg")

    match_info = result.get("match_info")

    if match_info:
        lines.append(
            f"자동매칭: {match_info.get('제품명')} [{match_info.get('제품코드')}] "
            f"{round(float(match_info.get('유사도', 0)) * 100)}%"
        )

    force_mode_on = False

    try:
        force_mode_on = bool(is_force_enabled_for_date(production_date))
    except Exception:
        force_mode_on = False

    if is_possible:
        saved, msg = await asyncio.to_thread(add_production_plan, production_date, product_code, quantity_kg, question=question)
        lines.append("판정: ✅ 생산 가능")
        lines.append("저장: 완료" if saved else "저장: 보류")
        lines.append(msg)
    elif force_mode_on:
        try:
            saved, msg = await asyncio.to_thread(
                force_add_production_plan,
                production_date,
                product_code,
                product_real_name,
                quantity_kg,
                question,
            )
            lines.append("판정: ❌ 생산 불가능")
            lines.append("강제등록 모드: ON")
            lines.append("처리: 강제등록 모드 ON이라 생산계획은 강제로 저장됨")
            lines.append("저장: 강제 완료" if saved else "저장: 보류")
            lines.append(msg)
        except Exception as e:
            lines.append("판정: ❌ 생산 불가능")
            lines.append("강제등록 모드: ON")
            lines.append(f"저장: 강제등록 처리 중 오류 - {str(e)}")
    else:
        lines.append("판정: ❌ 생산 불가능")
        lines.append("강제등록 모드: OFF")
        lines.append("저장: 안 함")
        lines.append("부족 자재가 있어 생산계획에 저장하지 않았습니다.")

    if shortage_list:
        lines.append("")
        lines.append("[부족 자재]")

        for idx, item in enumerate(shortage_list, start=1):
            lines.append(
                f"{idx}. {item['자재코드']} / {item['자재명']} - "
                f"필요 {fmt_num(item['필요수량'])}{item['배합단위']}, "
                f"가용 {fmt_num(item['가용재고'])}{item['재고단위']}, "
                f"부족 {fmt_num(item['부족수량'])}{item['배합단위']}"
            )

    return "\n".join(lines)


async def handle_image_product_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str, choice: str):
    """
    이미지 OCR 후 제품명 선택 버튼을 눌렀을 때 처리합니다.

    v6 개선:
    - 중복 클릭 방지
    - 무거운 재고 계산/build_result를 asyncio.to_thread로 처리
    - 버튼을 누르면 먼저 '처리 중' 메시지를 즉시 보여줌
    """
    query = update.callback_query
    chat_id = update.effective_chat.id
    session = get_user_session(chat_id)
    pending = session.get("pending_image_product_choices", {})

    data = pending.get(token)

    if not data:
        await query.edit_message_text(
            "⏳ 제품 선택 시간이 만료되었거나 이미 처리된 버튼입니다.\n"
            "사진을 다시 보내거나 제품명을 직접 입력해 주세요."
        )
        return

    if data.get("processing"):
        await query.answer("이미 처리 중입니다. 잠시만 기다려 주세요.", show_alert=False)
        return

    data["processing"] = True

    if choice == "cancel":
        pending.pop(token, None)
        await query.edit_message_text(
            f"⏭️ 저장하지 않았습니다.\n\n"
            f"OCR 인식 제품명: {data['ocr_product_name']}\n"
            f"수량: {fmt_num(data['quantity_kg'])}kg\n"
            f"생산일: {data['production_date']}"
        )
        return

    try:
        idx = int(choice)
        selected = data["candidates"][idx]
    except Exception:
        data["processing"] = False
        await query.edit_message_text("❌ 선택값을 처리하지 못했습니다. 다시 시도해 주세요.")
        return

    selected_code = str(selected.get("제품코드", "")).strip()
    selected_name = str(selected.get("제품명", "")).strip()
    selected_score = round(float(selected.get("유사도", 0)) * 100)

    remember_ocr_product(
        data.get("ocr_product_name"),
        selected_code,
        selected_name,
        source="image_button",
        score=selected_score,
    )

    await query.edit_message_text(
        f"⏳ 제품 선택 완료, 재고 계산 중입니다...\n\n"
        f"OCR 인식명: {data['ocr_product_name']}\n"
        f"선택 제품: {selected_name} [{selected_code}] {selected_score}%\n"
        f"수량: {fmt_num(data['quantity_kg'])}kg\n"
        f"생산일: {data['production_date']}\n\n"
        f"잠시만 기다려 주세요. 중복으로 누르지 않아도 됩니다."
    )

    production_date = data["production_date"] or datetime.now().strftime("%Y-%m-%d")
    quantity_kg = float(data["quantity_kg"])
    product_key = selected_code or selected_name

    try:
        extra_consumption = get_planned_consumption_until(production_date)
        result = await asyncio.to_thread(
            build_result,
            product_key,
            quantity_kg,
            extra_consumption=extra_consumption,
        )
    except Exception as e:
        final_text = f"❌ 선택 제품 처리 중 오류가 발생했습니다.\n사유: {str(e)}"
    else:
        lines = []
        lines.append("[이미지 제품명 재선택 처리 결과]")
        lines.append(f"생산일: {production_date}")
        lines.append(f"원래 OCR 제품명: {data['ocr_product_name']}")
        lines.append(f"선택 제품명: {selected_name} [{selected_code}]")
        lines.append(f"수량: {fmt_num(quantity_kg)}kg")

        if not result.get("found"):
            lines.append("판정: ❌ 제품 정보를 찾지 못함")
            lines.append("저장: 안 함")
        elif result.get("부족"):
            force_mode_on = is_force_enabled_for_date(production_date)
            if force_mode_on:
                saved, msg = await asyncio.to_thread(
                    force_add_production_plan,
                    production_date,
                    selected_code,
                    selected_name,
                    quantity_kg,
                    question=data["question"],
                )
                lines.append("판정: ❌ 생산 불가능")
                lines.append("강제등록 모드: ON")
                lines.append("처리: 강제등록 모드 ON이라 선택 제품도 강제 저장됨")
                lines.append("저장: 강제 완료" if saved else "저장: 보류")
                lines.append(msg)
            else:
                lines.append("판정: ❌ 생산 불가능")
                lines.append("강제등록 모드: OFF")
                lines.append("저장: 안 함")
            lines.append("")
            lines.append("[부족 자재]")

            for i, item in enumerate(result.get("부족", []), start=1):
                lines.append(
                    f"{i}. {item['자재코드']} / {item['자재명']} - "
                    f"필요 {fmt_num(item['필요수량'])}{item['배합단위']}, "
                    f"가용 {fmt_num(item['가용재고'])}{item['재고단위']}, "
                    f"부족 {fmt_num(item['부족수량'])}{item['배합단위']}"
                )
        else:
            saved, msg = await asyncio.to_thread(
                add_production_plan,
                production_date,
                product_key,
                quantity_kg,
                question=data["question"],
            )
            lines.append("판정: ✅ 생산 가능")
            lines.append("저장: 완료" if saved else "저장: 보류")
            lines.append(msg)

        final_text = "\n".join(lines)

    pending.pop(token, None)

    save_usage_log(
        update.effective_user.id,
        update.effective_user.username,
        f"이미지 제품선택:{data['ocr_product_name']} -> {selected_name} [{selected_code}]",
        final_text,
    )

    for part in split_message(final_text):
        await context.bot.send_message(chat_id=chat_id, text=part)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_should_process, _ = await should_process_group_message(update, context)

    if not group_should_process:
        return

    if not is_allowed_user(update.effective_user.id):
        if should_reply_unauthorized(update):
            await safe_reply_text(update, "❌ 이 봇을 사용할 권한이 없습니다.")
        return

    chat_id = update.effective_chat.id

    if not PHOTO_SUPPORT:
        await safe_reply_text(update, "이미지 분석용 모듈(image_parser)이 설정되지 않았습니다.")
        return

    temp_path = None

    # 1단계: 이미지 다운로드/OCR까지만 별도 try 처리
    try:
        await safe_reply_text(update, "이미지를 분석하고 있습니다. 잠시만 기다려주세요...")

        photo_file = await update.message.photo[-1].get_file()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            temp_path = tmp.name

        await photo_file.download_to_drive(temp_path)

        extracted_questions = await asyncio.to_thread(extract_questions_from_image, temp_path)

    except Exception as e:
        await safe_reply_text(
            update,
            f"❌ 사진 OCR 또는 다운로드 중 오류가 발생했습니다.\n사유: {str(e)}"
        )
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

    if not extracted_questions:
        await safe_reply_text(update, "이미지 내에서 생산 및 발주 관련 텍스트 추출에 실패했습니다.")
        return

    cleaned_questions = []

    for q in extracted_questions:
        q_fix = re.sub(
            r"(블루믹스34|블루믹스m|바이믹스310|바이믹스100|바이믹스151)(\d+)",
            r"\1 \2",
            q,
            flags=re.IGNORECASE,
        )
        cleaned_questions.append(q_fix)

    total_count = len(cleaned_questions)

    read_text = "[사진 분석 → 생산등록 검토 목록]"

    for idx, q in enumerate(cleaned_questions, start=1):
        read_text += f"\n{idx}. {q}"

    await safe_reply_text(update, read_text)

    processed_count = 0
    pending_count = 0
    error_count = 0
    send_error_count = 0

    # 2단계: 행별 독립 처리. 한 행에서 타임아웃/오류가 나도 다음 행을 계속 처리합니다.
    for idx, q in enumerate(cleaned_questions, start=1):
        try:
            final_text = await process_image_registration_question(
                update=update,
                context=context,
                chat_id=chat_id,
                question=q,
                row_idx=idx,
                total_count=total_count,
            )

            if final_text == "__IMAGE_PRODUCT_CHOICE_PENDING__":
                pending_count += 1
                save_usage_log(
                    update.effective_user.id,
                    update.effective_user.username,
                    f"사진분석:{q}",
                    "이미지 제품명 선택 대기",
                )
                await asyncio.sleep(0.2)
                continue

            if final_text == "__ASYNC_BUTTON_TRIGGERED__":
                pending_count += 1
                save_usage_log(
                    update.effective_user.id,
                    update.effective_user.username,
                    f"사진분석:{q}",
                    "제품 선택 버튼 표시",
                )
                await asyncio.sleep(0.2)
                continue

            save_usage_log(
                update.effective_user.id,
                update.effective_user.username,
                f"사진분석:{q}",
                final_text,
            )

            for part in split_message(final_text):
                ok, err = await safe_reply_text(update, part)
                if not ok:
                    send_error_count += 1
                    save_usage_log(
                        update.effective_user.id,
                        update.effective_user.username,
                        f"사진분석 전송실패:{q}",
                        err,
                    )

            processed_count += 1

        except Exception as e:
            error_count += 1
            err_text = (
                f"⚠️ [{idx}/{total_count}] 처리 중 오류가 발생했지만 다음 항목을 계속 처리합니다.\n"
                f"원문: {q}\n"
                f"사유: {str(e)}"
            )

            save_usage_log(
                update.effective_user.id,
                update.effective_user.username,
                f"사진분석 오류:{q}",
                str(e),
            )

            await safe_reply_text(update, err_text)

        await asyncio.sleep(0.2)

    summary_lines = []
    summary_lines.append("[사진 처리 완료]")
    summary_lines.append(f"전체 항목: {total_count}건")
    summary_lines.append(f"처리 완료: {processed_count}건")
    summary_lines.append(f"제품 선택 대기: {pending_count}건")
    summary_lines.append(f"처리 오류: {error_count}건")

    if send_error_count:
        summary_lines.append(f"메시지 전송 실패: {send_error_count}건")
        summary_lines.append("전송 실패가 있어도 저장 처리는 진행됐을 수 있습니다. /planlist로 확인해 주세요.")

    if pending_count:
        summary_lines.append("제품 선택 대기 항목은 버튼을 선택하면 별도로 재고 계산 후 저장됩니다.")

    await safe_reply_text(update, "\n".join(summary_lines))
