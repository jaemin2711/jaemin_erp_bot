from bot_config import *
from bot_auth import is_allowed_user
from bot_io import save_usage_log, split_message


async def reserved_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    예약 생산계획 등록/목록/삭제/실제전환.
    특정 ID는 일반 등록 문장도 실제 생산계획이 아니라 예약 생산계획으로 저장됩니다.
    """
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    text = update.message.text or ""
    compact = text.replace(" ", "").lower()

    if compact.startswith("/reservedplans") or compact in ["예약목록", "계획예약목록", "예약생산계획목록"]:
        await update.message.reply_text(format_reserved_plan_list())
        return

    if compact.startswith("/reservedel") or compact.startswith("/reserveddelete") or compact.startswith("/예약삭제"):
        m = re.search(r"(\d+)", text)
        if not m:
            await update.message.reply_text("삭제할 예약 번호를 입력해 주세요. 예: /reservedel 1")
            return
        await update.message.reply_text(delete_reserved_plan(int(m.group(1))))
        return

    if compact.startswith("/reserveactual") or compact.startswith("/reservedactual") or compact.startswith("/예약전환"):
        m = re.search(r"(\d+)", text)
        if not m:
            await update.message.reply_text("전환할 예약 번호를 입력해 주세요. 예: /reserveactual 1")
            return
        result = await asyncio.to_thread(convert_reserved_to_actual, int(m.group(1)))
        await update.message.reply_text(result)
        return

    result = await asyncio.to_thread(
        add_reserved_plan_from_text,
        text,
        update.effective_user.id,
        update.effective_user.username,
    )

    try:
        save_usage_log(
            update.effective_user.id,
            update.effective_user.username,
            f"예약생산계획:{text}",
            result,
        )
    except Exception:
        pass

    for part in split_message(result):
        await update.message.reply_text(part)


async def plan_natural_change_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    result_text = await asyncio.to_thread(
        update_plan_by_natural_change,
        update.message.text,
        update.effective_user.id,
        update.effective_user.username,
    )

    try:
        save_usage_log(
            update.effective_user.id,
            update.effective_user.username,
            f"생산계획자연어변경:{update.message.text}",
            result_text,
        )
    except Exception:
        pass

    for part in split_message(result_text):
        await update.message.reply_text(part)

async def contract_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    계약생산 예약 관리.
    """
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    text = update.message.text or ""
    compact = text.replace(" ", "").lower()

    if compact.startswith("/contractlist") or compact in ["계약생산목록", "계약목록"]:
        await update.message.reply_text(format_contract_list())
        return

    if compact.startswith("/contractcheck") or compact in ["계약생산체크", "계약재고체크", "계약생산재고체크"]:
        result = await asyncio.to_thread(simulate_contracts)
        for part in split_message(result):
            await update.message.reply_text(part)
        return

    if compact.startswith("/contractdel") or compact.startswith("/계약삭제"):
        m = re.search(r"(\d+)", text)
        if not m:
            await update.message.reply_text("삭제할 번호를 입력해 주세요. 예: /contractdel 1")
            return
        await update.message.reply_text(delete_contract(int(m.group(1))))
        return

    if compact.startswith("/contractplan"):
        m = re.search(r"/contractplan\s+(\d+)\s+(.+)", text, flags=re.IGNORECASE)
        if not m:
            await update.message.reply_text("형식: /contractplan 번호 월\n예: /contractplan 1 7월")
            return
        result = await asyncio.to_thread(convert_contract_month_to_plan, int(m.group(1)), m.group(2))
        await update.message.reply_text(result)
        return

    data, err = parse_contract_text(text)
    if err:
        await update.message.reply_text(
            f"❌ {err}\n\n"
            "예시:\n"
            "/contractadd 제품명 5톤 2026-07-01~2026-12-31 매월\n"
            "제품명 7월부터 12월31일까지 매월 5톤 계약생산 등록"
        )
        return

    result = add_contract_rule(
        data,
        user_id=update.effective_user.id,
        username=update.effective_user.username,
    )

    try:
        save_usage_log(
            update.effective_user.id,
            update.effective_user.username,
            f"계약생산등록:{data.get('제품명')} {fmt_num(data.get('월생산수량kg'))}kg",
            result,
        )
    except Exception:
        pass

    await update.message.reply_text(result)


def is_contract_message(text: str) -> bool:
    compact = str(text or "").replace(" ", "").lower()
    return (
        compact.startswith("/contract")
        or compact.startswith("/계약생산")
        or "계약생산" in compact
        or "계약재고체크" in compact
    )
