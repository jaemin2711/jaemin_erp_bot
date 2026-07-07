from bot_config import *
from bot_auth import is_allowed_user
from bot_io import save_usage_log, split_message
from bot_sessions import get_user_session
from plan_utils import *


async def process_inline_plan_edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    display_no, new_date, new_qty, err = parse_plan_edit_command_text(text)

    if err:
        await update.message.reply_text(f"❌ {err}")
        return True

    plan, err = get_plan_by_display_no(display_no)

    if err:
        await update.message.reply_text(f"❌ {err}")
        return True

    msg = update_plan_fields(plan, new_date=new_date, new_qty_kg=new_qty)

    title = (
        f"{display_no}번 / {plan['production_date']} / {plan['product_name']} "
        f"[{plan['product_code']}] / {fmt_num(plan['qty_kg'])}kg"
    )

    save_usage_log(
        update.effective_user.id,
        update.effective_user.username,
        f"생산계획 명령수정:{title} -> {new_date or '-'} / {fmt_num(new_qty) + 'kg' if new_qty else '-'}",
        msg,
    )

    await update.message.reply_text(
        f"✅ 생산계획 수정 처리 완료\n\n{msg}\n\n목록 확인: /planlist\n버튼 관리: /plans"
    )
    return True


async def process_inline_plan_delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    display_no, err = parse_plan_delete_command_text(text)

    if err:
        await update.message.reply_text(f"❌ {err}")
        return True

    plan, err = get_plan_by_display_no(display_no)

    if err:
        await update.message.reply_text(f"❌ {err}")
        return True

    msg = delete_production_plan(plan["production_date"], plan["product_code"])

    save_usage_log(
        update.effective_user.id,
        update.effective_user.username,
        f"생산계획 명령취소:{display_no}번 {plan['product_name']} [{plan['product_code']}]",
        msg,
    )

    await update.message.reply_text(
        f"🗑 생산계획 취소 처리 완료\n\n{msg}\n\n목록 확인: /planlist"
    )
    return True

async def editplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    await process_inline_plan_edit_command(update, context, update.message.text)


async def delplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    await process_inline_plan_delete_command(update, context, update.message.text)


async def forceplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    await process_force_register_command(update, context, update.message.text)

async def send_plan_manager(update: Update, context: ContextTypes.DEFAULT_TYPE, edit_message=False, page: int | None = None):
    chat_id = update.effective_chat.id
    session = get_user_session(chat_id)

    if page is None:
        page = int(session.get("plan_manage_page", 1) or 1)

    text, markup = build_plan_manage_view(chat_id, page=page)

    if edit_message and update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


async def planlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    try:
        text = format_plan_table_view()
    except Exception as e:
        text = f"❌ 생산계획표를 만드는 중 오류가 발생했습니다.\n사유: {str(e)}"

    for part in split_message(text):
        await update.message.reply_text(part)


async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    await send_plan_manager(update, context, edit_message=False)


async def handle_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    query = update.callback_query
    chat_id = update.effective_chat.id
    session = get_user_session(chat_id)
    parts = data.split("|")
    action = parts[1] if len(parts) > 1 else ""
    token = parts[2] if len(parts) > 2 else ""

    if action == "close":
        await query.edit_message_text("생산계획 관리 창을 닫았습니다.")
        return

    if action == "refresh":
        await send_plan_manager(update, context, edit_message=True)
        return

    if action == "page":
        try:
            page_no = int(token)
        except Exception:
            page_no = int(session.get("plan_manage_page", 1) or 1)

        await send_plan_manager(update, context, edit_message=True, page=page_no)
        return

    if action == "noop":
        await query.answer("현재 페이지입니다.", show_alert=False)
        return

    plan = get_plan_action(session, token)

    if not plan:
        await query.edit_message_text(
            "⏳ 이 버튼은 만료되었거나 이미 처리되었습니다.\n"
            "다시 /plans 를 입력해서 새로 열어주세요."
        )
        return

    title = (
        f"{plan['production_date']} / {plan['product_name']} "
        f"[{plan['product_code']}] / {fmt_num(plan['qty_kg'])}kg"
    )

    if action == "edit":
        await query.edit_message_text(
            f"[생산계획 수정]\n{title}\n\n수정할 항목을 선택하세요.",
            reply_markup=make_plan_edit_menu_keyboard(token),
        )
        return

    if action == "editqty":
        await query.edit_message_text(
            f"[생산계획 수량 변경]\n{title}\n\n변경할 수량을 선택하세요.",
            reply_markup=make_plan_qty_keyboard(token),
        )
        return

    if action == "editdate":
        await query.edit_message_text(
            f"[생산계획 일자 변경]\n{title}\n\n변경할 생산일자를 선택하세요.",
            reply_markup=make_plan_date_keyboard(token),
        )
        return

    if action == "customqty":
        session["pending_plan_edit_inputs"][str(update.effective_user.id)] = {
            "token": token,
            "mode": "qty",
        }
        await query.edit_message_text(
            f"[직접 수량 입력]\n{title}\n\n"
            "변경할 수량을 메시지로 입력하세요.\n"
            "예: 3000 또는 3,000kg 또는 3톤"
        )
        return

    if action == "customdate":
        session["pending_plan_edit_inputs"][str(update.effective_user.id)] = {
            "token": token,
            "mode": "date",
        }
        await query.edit_message_text(
            f"[직접 생산일 입력]\n{title}\n\n"
            "변경할 생산일자를 메시지로 입력하세요.\n"
            "예: 6월 15일 또는 2026-06-15 또는 내일"
        )
        return

    if action == "customboth":
        session["pending_plan_edit_inputs"][str(update.effective_user.id)] = {
            "token": token,
            "mode": "both",
        }
        await query.edit_message_text(
            f"[생산일+수량 직접 입력]\n{title}\n\n"
            "변경할 생산일자와 수량을 함께 입력하세요.\n"
            "예: 6월 15일 3000kg\n"
            "예: 2026-06-15 3톤"
        )
        return

    # 예전 버전 callback 호환: plan|custom|token 은 수량 직접입력으로 처리
    if action == "custom":
        session["pending_plan_edit_inputs"][str(update.effective_user.id)] = {
            "token": token,
            "mode": "qty",
        }
        await query.edit_message_text(
            f"[직접 수량 입력]\n{title}\n\n"
            "변경할 수량을 메시지로 입력하세요.\n"
            "예: 3000 또는 3,000kg 또는 3톤"
        )
        return

    if action == "qty":
        qty_text = parts[3] if len(parts) > 3 else ""
        new_qty = parse_quantity_text(qty_text)

        if new_qty is None or new_qty <= 0:
            await query.edit_message_text("❌ 수량을 인식하지 못했습니다. 다시 시도해 주세요.")
            return

        msg = update_plan_fields(plan, new_qty_kg=new_qty)
        await query.edit_message_text(
            f"✅ 수량 수정 처리 완료\n\n{msg}\n\n다시 보려면 /plans 를 입력하세요."
        )
        save_usage_log(
            update.effective_user.id,
            update.effective_user.username,
            f"생산계획 버튼수량수정:{title} -> {fmt_num(new_qty)}kg",
            msg,
        )
        return

    if action == "date":
        date_text = parts[3] if len(parts) > 3 else ""
        new_date = parse_plan_date_input(date_text)

        if not new_date:
            await query.edit_message_text("❌ 생산일자를 인식하지 못했습니다. 다시 시도해 주세요.")
            return

        msg = update_plan_fields(plan, new_date=new_date)
        await query.edit_message_text(
            f"✅ 일자 수정 처리 완료\n\n{msg}\n\n다시 보려면 /plans 를 입력하세요."
        )
        save_usage_log(
            update.effective_user.id,
            update.effective_user.username,
            f"생산계획 버튼일자수정:{title} -> {new_date}",
            msg,
        )
        return

    if action == "del":
        await query.edit_message_text(
            f"[생산계획 취소 확인]\n{title}\n\n정말 이 생산계획을 취소할까요?",
            reply_markup=make_plan_delete_confirm_keyboard(token),
        )
        return

    if action == "confirmdel":
        msg = delete_production_plan(plan["production_date"], plan["product_code"])
        await query.edit_message_text(
            f"🗑 취소 처리 완료\n\n{msg}\n\n다시 보려면 /plans 를 입력하세요."
        )
        save_usage_log(
            update.effective_user.id,
            update.effective_user.username,
            f"생산계획 버튼취소:{title}",
            msg,
        )
        return

    await query.edit_message_text("❌ 알 수 없는 생산계획 관리 명령입니다.")


async def handle_pending_plan_qty_input(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    chat_id = update.effective_chat.id
    session = get_user_session(chat_id)
    user_id = str(update.effective_user.id)
    pending = session.get("pending_plan_edit_inputs", {}).pop(user_id, None)

    if not pending:
        return False

    # 예전 버전 호환: pending 값이 token 문자열이면 수량 수정으로 처리
    if isinstance(pending, str):
        token = pending
        mode = "qty"
    else:
        token = pending.get("token")
        mode = pending.get("mode", "qty")

    plan = get_plan_action(session, token)

    if not plan:
        await update.message.reply_text(
            "⏳ 수정 대기가 만료되었습니다. 다시 /plans 를 입력해서 수정해 주세요."
        )
        return True

    title = (
        f"{plan['production_date']} / {plan['product_name']} "
        f"[{plan['product_code']}] / {fmt_num(plan['qty_kg'])}kg"
    )

    if mode == "qty":
        new_qty = parse_quantity_text(user_text)

        if new_qty is None or new_qty <= 0:
            session["pending_plan_edit_inputs"][user_id] = pending
            await update.message.reply_text(
                "❌ 수량을 인식하지 못했습니다. 숫자로 다시 입력해 주세요.\n"
                "예: 3000 또는 3,000kg 또는 3톤"
            )
            return True

        msg = update_plan_fields(plan, new_qty_kg=new_qty)
        log_text = f"생산계획 직접수량수정:{title} -> {fmt_num(new_qty)}kg"
        result_title = "✅ 생산계획 수량을 수정했습니다."

    elif mode == "date":
        new_date = parse_plan_date_input(user_text)

        if not new_date:
            session["pending_plan_edit_inputs"][user_id] = pending
            await update.message.reply_text(
                "❌ 생산일자를 인식하지 못했습니다. 다시 입력해 주세요.\n"
                "예: 6월 15일 또는 2026-06-15 또는 내일"
            )
            return True

        msg = update_plan_fields(plan, new_date=new_date)
        log_text = f"생산계획 직접일자수정:{title} -> {new_date}"
        result_title = "✅ 생산계획 일자를 수정했습니다."

    elif mode == "both":
        new_date = parse_plan_date_input(user_text)
        new_qty = parse_quantity_text(user_text)

        if not new_date or new_qty is None or new_qty <= 0:
            session["pending_plan_edit_inputs"][user_id] = pending
            await update.message.reply_text(
                "❌ 생산일자 또는 수량을 인식하지 못했습니다. 다시 입력해 주세요.\n"
                "예: 6월 15일 3000kg\n"
                "예: 2026-06-15 3톤"
            )
            return True

        msg = update_plan_fields(plan, new_date=new_date, new_qty_kg=new_qty)
        log_text = f"생산계획 직접일자수량수정:{title} -> {new_date} / {fmt_num(new_qty)}kg"
        result_title = "✅ 생산계획 일자와 수량을 수정했습니다."

    else:
        await update.message.reply_text("❌ 알 수 없는 수정 방식입니다. 다시 /plans 를 입력해 주세요.")
        return True

    save_usage_log(
        update.effective_user.id,
        update.effective_user.username,
        log_text,
        msg,
    )

    await update.message.reply_text(
        f"{result_title}\n\n{msg}\n\n목록을 다시 보려면 /plans 를 입력하세요."
    )
    return True
