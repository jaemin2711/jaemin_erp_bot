from bot_config import *


def save_usage_log(user_id, username, question, response_preview):
    """
    사용 기록을 usage_log.csv에 저장합니다.
    """
    Path("logs").mkdir(exist_ok=True)
    log_file = str(Path("logs") / "usage_log.csv")
    file_exists = os.path.exists(log_file)

    with open(log_file, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(["시간", "user_id", "username", "질문", "응답요약"])

        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user_id,
            username or "",
            question,
            str(response_preview)[:300],
        ])


def save_register_user(user):
    """
    /register 명령어를 입력한 사용자의 정보를 register_users.csv에 저장합니다.
    """
    Path("logs").mkdir(exist_ok=True)
    file_path = str(Path("logs") / "register_users.csv")
    file_exists = os.path.exists(file_path)

    with open(file_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(["시간", "user_id", "username", "first_name", "last_name"])

        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user.id,
            user.username or "",
            user.first_name or "",
            user.last_name or "",
        ])


def get_user_session(chat_id: int) -> dict:
    if chat_id not in user_sessions:
        user_sessions[chat_id] = {
            "last_purchase_context": None,
            "pending_ocr_fix": None,
            "pending_image_product_choices": {},
            "pending_plan_actions": {},
            "pending_plan_edit_inputs": {},
        }

    if "pending_image_product_choices" not in user_sessions[chat_id]:
        user_sessions[chat_id]["pending_image_product_choices"] = {}

    if "pending_plan_actions" not in user_sessions[chat_id]:
        user_sessions[chat_id]["pending_plan_actions"] = {}

    if "pending_plan_edit_inputs" not in user_sessions[chat_id]:
        user_sessions[chat_id]["pending_plan_edit_inputs"] = {}

    return user_sessions[chat_id]


def split_message(text: str, limit: int = 3900):
    """
    텔레그램 메시지 길이 제한에 걸리지 않도록 긴 메시지를 나눕니다.
    """
    if text is None:
        return [""]

    text = str(text)

    if len(text) <= limit:
        return [text]

    parts = []
    current = ""

    for line in text.splitlines():
        if len(current) + len(line) + 1 > limit:
            if current:
                parts.append(current)
            current = line
        else:
            current += "\n" + line if current else line

    if current:
        parts.append(current)

    return parts


async def safe_reply_text(update: Update, text: str, reply_markup=None, retry: int = 2):
    """
    텔레그램 전송 타임아웃이 발생해도 전체 사진 처리가 멈추지 않게 하는 안전 전송 함수입니다.
    실패하면 False와 오류 내용을 반환합니다.
    """
    last_error = None

    for attempt in range(retry + 1):
        try:
            await update.message.reply_text(text, reply_markup=reply_markup)
            return True, None
        except Exception as e:
            last_error = e
            await asyncio.sleep(1.0 + attempt)

    return False, str(last_error)


async def safe_send_bot_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, retry: int = 2):
    """
    context.bot.send_message용 안전 전송 함수입니다.
    """
    last_error = None

    for attempt in range(retry + 1):
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
            return True, None
        except Exception as e:
            last_error = e
            await asyncio.sleep(1.0 + attempt)

    return False, str(last_error)
