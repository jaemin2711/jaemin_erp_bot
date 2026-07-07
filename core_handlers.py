from bot_config import *
from bot_auth import is_allowed_user
from bot_io import save_usage_log, save_register_user, split_message
from bot_sessions import get_user_session
from plan_utils import format_plan_table_view
from plan_commands import (
    send_plan_manager,
    process_inline_plan_edit_command,
    process_inline_plan_delete_command,
    handle_pending_plan_qty_input,
    handle_plan_callback,
)
from force_plan import (
    process_force_register_command,
    process_single_plan_register_command,
    is_single_plan_register_text,
)
from reserved_contract import (
    contract_command,
    is_contract_message,
    reserved_plan_command,
    plan_natural_change_command,
)
from product_alias_ocr import apply_product_aliases_to_question, resolve_text_product_alias
from plan_reports import (
    plan_period_command,
    format_risk_report,
    handle_menu_callback,
)
from shortage_detail import check_all_remembered_plans, _is_real_production_shortage
from image_handlers import handle_image_product_choice_callback


async def version_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"봇 버전: {BOT_VERSION}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    text = """
안녕하세요. 텔레그램 ERP AI 비서입니다.

사용 예시:
1. 블루믹스 1000kg 생산 가능?
2. 오늘 생산계획 보여줘
3. 부족분 발주해줘
4. 생산계획 자재부족확인
5. 사진을 보내면 제품별로 생산 가능 여부 확인 후 가능한 제품만 생산계획에 등록합니다.

명령어:
/start - 시작 안내
/help - 사용법 보기
/id - 내 텔레그램 사용자 ID 확인
/register - 등록 신청
/planlist - 저장된 생산계획을 표 형식으로 보기
/plans - 저장된 생산계획 버튼으로 수량/일자 수정 및 취소
/수정 11, 6/18, 3톤 - 표 번호 기준 생산일/수량 변경
/취소 11 - 표 번호 기준 생산계획 취소
/강제등록 6/18 제품명 3톤 - 부족 자재가 있어도 생산계획 저장 후 준비할 부족 자재 확인
/ocrmemory - 이미지 OCR 제품명 기억 목록 보기
/ocrforget 제품명 - 잘못 기억된 OCR 제품명 매칭 삭제

그룹방 사용법:
- 그룹방에서는 봇 멘션/답글/트리거 단어가 있을 때만 반응합니다.
- 예: 봇 블루믹스 3톤 생산 가능?
- 예: @봇아이디 생산계획 자재부족확인
- 슬래시 명령어(/planlist, /plans 등)는 기존처럼 사용합니다.
강제등록 켜 - 모든 일반 생산계획 등록을 부족 자재가 있어도 강제 저장
강제등록 꺼 - 전체 강제등록 해제
6/20 강제등록 켜 - 해당 날짜만 일반등록도 강제 저장
6/20~6/25 강제등록 켜 - 해당 기간 일반등록도 강제 저장
강제등록 상태 - 강제등록 ON/OFF 상태 확인
"""
    await update.message.reply_text(text.strip())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_command(update, context)


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    msg = f"""
이름: {user.first_name or ''}
성: {user.last_name or ''}
username: @{user.username if user.username else '없음'}
텔레그램 ID: {user.id}
"""
    await update.message.reply_text(msg.strip())


async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_register_user(user)

    await update.message.reply_text(
        f"✅ 등록 신청이 완료되었습니다.\n"
        f"텔레그램 ID: {user.id}\n"
        f"관리자가 이 ID를 허용 목록에 추가하면 사용할 수 있습니다."
    )

async def process_question(chat_id: int, question: str, update_obj: Update = None) -> str:
    session = get_user_session(chat_id)
    question = apply_product_aliases_to_question(question)
    q_clean = question.replace(" ", "").lower()

    if "자재부족확인" in q_clean or "생산계획자재부족확인" in q_clean:
        return check_all_remembered_plans()

    try:
        if is_plan_shortage_summary_question(question):
            if is_shortage_excel_question(question):
                success, msg, out_file = handle_shortage_excel(question)
                return f"{msg}\n파일 위치: {out_file}" if success else msg

            return handle_plan_shortage_summary(question)

        if is_purchase_order_form_question(question):
            m = re.search(r"(PO\d+)", question.upper())
            p_no = m.group(1) if m else None

            try:
                out_file = create_purchase_order_excel(purchase_no=p_no)
                return f"구매발주서 엑셀 파일 생성이 완료되었습니다.\n파일: {out_file}"
            except Exception as e:
                return f"❌ 발주서 생성 중 오류가 발생했습니다: {str(e)}"

        if is_purchase_request_question(question):
            ctx = session.get("last_purchase_context")

            if not ctx:
                return "직전에 계산한 생산 불가능 내역이 없거나 세션이 만료되었습니다.\n먼저 제품 생산 검토를 진행해 주세요."

            res_text = check_production(
                ctx["product_name"],
                ctx["quantity"],
                intent="production_check",
            )
            order_msg = create_purchase_request_from_result(res_text)
            session["last_purchase_context"] = None
            return order_msg

        if is_product_change_question(question):
            return handle_product_change_question(question)

        if is_multi_production_request(question):
            return handle_multi_production_request(question)

        parsed = parse_question(question)

        intent = parsed.get("intent", "production_check")
        product_name = parsed.get("product_name")
        if product_name:
            product_name = resolve_text_product_alias(product_name)
        quantity = parsed.get("quantity")

        if intent == "show_plan":
            try:
                return format_plan_table_view()
            except Exception as e:
                return f"❌ 생산계획 목록을 조회하는 중 오류가 발생했습니다.\n사유: {str(e)}"

        if intent == "delete_plan":
            target_date = parsed.get("date") or datetime.now().strftime("%Y-%m-%d")

            if not product_name:
                return "❓ 취소하려는 제품명이 명확하지 않습니다.\n제품명을 포함하여 다시 말씀해 주세요."

            try:
                display_name = product_name.strip().upper()
                match_name = product_name.strip().lower()
                delete_result = delete_production_plan(target_date, match_name)
                return str(delete_result)
            except Exception as e:
                return f"❌ 계획 취소 처리 중 시스템 오류가 발생했습니다.\n사유: {str(e)}"

        if not product_name:
            return "❓ 질문에서 제품명을 인식하지 못했습니다.\n정확한 제품명을 포함하여 질문해 주세요."

        if quantity is None:
            quantity = 1

        explicit_date = parse_production_date(question)

        if float(quantity) <= 5.0 and ("톤" in question or "t" in question.lower()):
            quantity = float(quantity) * 1000

        answer = check_production(product_name, float(quantity), intent=intent)

        if (
            "찾을 수 없습니다" in answer
            and "혹시 아래 제품 중 하나인가요" in answer
            and update_obj
            and update_obj.message
        ):
            keyboard = []
            lines = answer.split("\n")

            for line in lines:
                match = re.search(r"\d+\.\s*([A-Za-z0-9_\-]+)\s*/\s*([^(\n]+)", line)

                if match:
                    code = match.group(1).strip()
                    name = match.group(2).strip()
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{name} [{code}]",
                            callback_data=f"sel_{code}",
                        )
                    ])

            if keyboard:
                keyboard.append([
                    InlineKeyboardButton(
                        "❌ 맞는 제품 없음 (넘어가기)",
                        callback_data="sel_cancel",
                    )
                ])

                reply_markup = InlineKeyboardMarkup(keyboard)

                session["pending_ocr_fix"] = {
                    "date": explicit_date or datetime.now().strftime("%Y-%m-%d"),
                    "quantity": float(quantity),
                    "question": question,
                }

                await update_obj.message.reply_text(
                    f"'[{product_name}]'의 정확한 배합비 코드를 찾지 못했습니다.\n"
                    f"아래 목록 중 매칭할 진짜 제품을 선택해 주세요:",
                    reply_markup=reply_markup,
                )

                return "__ASYNC_BUTTON_TRIGGERED__"

        has_shortage = _is_real_production_shortage(answer)

        if has_shortage:
            session["last_purchase_context"] = {
                "production_date": explicit_date or datetime.now().strftime("%Y-%m-%d"),
                "product_name": product_name,
                "quantity": float(quantity),
            }

            answer = "❌ [생산 불가능 판정 - 자재 부족]\n" + answer
            answer += "\n\n[발주 안내]\n부족 자재 발주요청서를 만들려면 '부족분 발주해줘'라고 입력하세요."
        else:
            answer = "✅ [생산 가능 판정]\n" + answer

        return answer

    except Exception as e:
        return f"처리 중 시스템 오류가 발생했습니다.\n사유: {str(e)}"


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.callback_query.answer("권한이 없습니다.", show_alert=True)
        return

    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    session = get_user_session(chat_id)
    data = query.data

    if data.startswith("menu|"):
        try:
            await handle_menu_callback(update, context, data)
        except Exception as e:
            await query.edit_message_text(f"❌ 메뉴 처리 중 오류가 발생했습니다.\n{str(e)}")
        return

    if data.startswith("plan|"):
        try:
            await handle_plan_callback(update, context, data)
        except Exception as e:
            await query.edit_message_text(f"❌ 생산계획 관리 처리 중 오류가 발생했습니다.\n{str(e)}")
        return

    if data.startswith("imgsel|"):
        try:
            _, token, choice = data.split("|", 2)
            await handle_image_product_choice_callback(update, context, token, choice)
        except Exception as e:
            await query.edit_message_text(f"❌ 이미지 제품 선택 처리 중 오류가 발생했습니다.\n{str(e)}")
        return

    if not data.startswith("sel_") or not session.get("pending_ocr_fix"):
        await query.edit_message_text(text="⏳ 이미 완료되었거나 만료된 세션 버튼입니다.")
        return

    fix_data = session["pending_ocr_fix"]
    session["pending_ocr_fix"] = None

    if data == "sel_cancel":
        await query.edit_message_text(text="⏭️ 해당 항목의 검토를 취소하고 다음 계획으로 넘어갑니다.")
        return

    selected_code = data.replace("sel_", "").strip()
    product_info = get_product_info(selected_code)
    p_name = product_info["제품명"] if product_info else selected_code

    await query.edit_message_text(text=f"매칭 수락 완료: [{p_name}] 코드로 재고 재분석을 실행합니다...")

    answer = await asyncio.to_thread(check_production, p_name, float(fix_data["quantity"]), intent="production_check")
    has_shortage = _is_real_production_shortage(answer)

    if has_shortage:
        session["last_purchase_context"] = {
            "production_date": fix_data["date"],
            "product_name": p_name,
            "quantity": float(fix_data["quantity"]),
        }

        answer = "❌ [생산 불가능 판정 - 자재 부족]\n" + answer
        answer += "\n\n[발주 안내]\n부족 자재 발주요청서를 만들려면 '부족분 발주해줘'라고 입력하세요."
    else:
        answer = "✅ [생산 가능 판정]\n" + answer

    save_usage_log(
        update.effective_user.id,
        update.effective_user.username,
        f"버튼선택:{selected_code}",
        answer,
    )

    for part in split_message(answer):
        await context.bot.send_message(chat_id=chat_id, text=part)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_should_process, group_cleaned_text = await should_process_group_message(update, context)

    if not group_should_process:
        return

    if not is_allowed_user(update.effective_user.id):
        if should_reply_unauthorized(update):
            await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    chat_id = update.effective_chat.id
    user_text = group_cleaned_text or update.message.text

    if is_contract_message(user_text):
        await contract_command(update, context)
        return

    if await handle_pending_plan_qty_input(update, context, user_text):
        return

    compact_text = user_text.replace(" ", "").lower()
    stripped_text = user_text.strip()
    if compact_text in ["오늘생산계획", "오늘계획", "오늘생산", "오늘일정"]:
        await plan_period_command(update, context, "today")
        return
    if compact_text in ["내일생산계획", "내일계획", "내일생산", "내일일정"]:
        await plan_period_command(update, context, "tomorrow")
        return
    if compact_text in ["이번주생산계획", "주간생산계획", "이번주계획", "주간계획"]:
        await plan_period_command(update, context, "week")
        return
    if compact_text in ["이번달생산계획", "월간생산계획", "이번달계획", "월간계획"]:
        await plan_period_command(update, context, "calendar")
        return
    if compact_text in ["부족위험", "자재위험", "리스크", "부족리스크"]:
        text = format_risk_report(days=7, title="[이번 주 부족 자재 위험 조회]")
        for part in split_message(text):
            await update.message.reply_text(part)
        return

    force_mode_result = apply_force_mode_command(user_text)
    if force_mode_result:
        save_usage_log(
            update.effective_user.id,
            update.effective_user.username,
            f"강제등록모드설정:{user_text}",
            force_mode_result,
        )
        await update.message.reply_text(force_mode_result)
        return

    if re.match(r"^/(수정|editplan)\b|^(수정|변경)\s*\d+", stripped_text, flags=re.IGNORECASE):
        await process_inline_plan_edit_command(update, context, user_text)
        return

    if re.match(r"^/(취소|삭제|delplan)\b|^(취소|삭제)\s*\d+", stripped_text, flags=re.IGNORECASE):
        await process_inline_plan_delete_command(update, context, user_text)
        return

    if (
        re.match(r"^/(강제등록|강제추가|forceplan)\b", stripped_text, flags=re.IGNORECASE)
        or "강제등록" in compact_text
        or "강제추가등록" in compact_text
        or ("강제" in compact_text and "등록" in compact_text)
    ):
        await process_force_register_command(update, context, user_text)
        return

    if is_reserved_register_text(user_text, update.effective_user.id):
        await reserved_plan_command(update, context)
        return

    if is_plan_natural_change_text(user_text):
        await plan_natural_change_command(update, context)
        return

    if is_single_plan_register_text(user_text):
        await process_single_plan_register_command(update, context, user_text)
        return

    if compact_text in ["생산계획보여줘", "생산계획목록보여줘", "생산계획조회", "생산계획표", "계획표", "계획보여줘"]:
        try:
            text = format_plan_table_view()
        except Exception as e:
            text = f"❌ 생산계획표를 만드는 중 오류가 발생했습니다.\n사유: {str(e)}"

        for part in split_message(text):
            await update.message.reply_text(part)
        return

    if compact_text in ["생산계획관리", "계획관리", "생산계획수정", "생산계획취소"]:
        await send_plan_manager(update, context, edit_message=False)
        return

    response_text = await process_question(chat_id, user_text, update_obj=update)

    if response_text == "__ASYNC_BUTTON_TRIGGERED__":
        save_usage_log(
            update.effective_user.id,
            update.effective_user.username,
            user_text,
            "제품 선택 버튼 표시",
        )
        return

    save_usage_log(
        update.effective_user.id,
        update.effective_user.username,
        user_text,
        response_text,
    )

    for part in split_message(response_text):
        await update.message.reply_text(part)
