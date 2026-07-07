import os
import re
import csv
import tempfile
import uuid
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

from openai import OpenAI
import pandas as pd

from plan_product_change import is_product_change_question, handle_product_change_question
from ai_parser import parse_question
from inventory_engine import check_production, build_result, find_similar_products, BOM_FILE
from purchase_order import is_purchase_request_question, create_purchase_request_from_result
from purchase_order_form import is_purchase_order_form_question, create_purchase_order_excel
from date_utils import parse_production_date
from production_memory import (
    format_plan_list,
    delete_production_plan,
    load_plans,
    get_product_info,
    fmt_num,
)
from multi_plan import is_multi_production_request, handle_multi_production_request, parse_multi_items
from summary_commands import (
    is_plan_shortage_summary_question,
    is_shortage_excel_question,
    handle_plan_shortage_summary,
    handle_shortage_excel,
)

try:
    from image_parser import extract_questions_from_image
    PHOTO_SUPPORT = True
except Exception:
    PHOTO_SUPPORT = False


load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ALLOWED_USER_IDS = os.getenv("ALLOWED_USER_IDS", "")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN이 .env 파일에 없습니다.")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

user_sessions = {}


def is_allowed_user(user_id: int) -> bool:
    """
    .env의 ALLOWED_USER_IDS로 사용자를 제한합니다.

    ALLOWED_USER_IDS가 비어 있으면 모든 사용자를 허용합니다.
    예:
    ALLOWED_USER_IDS=
    ALLOWED_USER_IDS=123456789
    ALLOWED_USER_IDS=123456789,987654321
    """
    if not ALLOWED_USER_IDS.strip():
        return True

    allowed = [x.strip() for x in ALLOWED_USER_IDS.split(",") if x.strip()]
    return str(user_id) in allowed


def save_usage_log(user_id, username, question, response_preview):
    """
    사용 기록을 usage_log.csv에 저장합니다.
    """
    log_file = "usage_log.csv"
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
    file_path = "register_users.csv"
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
        }
    if "pending_image_product_choices" not in user_sessions[chat_id]:
        user_sessions[chat_id]["pending_image_product_choices"] = {}

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


def load_bom_for_candidates():
    """
    제품 후보 검색용으로 bom.xlsx만 읽습니다.
    재고 파일 오류 때문에 후보 검색이 막히지 않도록 load_data() 대신 BOM_FILE만 사용합니다.
    """
    if not BOM_FILE.exists():
        raise FileNotFoundError(f"배합비 파일이 없습니다: {BOM_FILE}")

    return pd.read_excel(BOM_FILE)


def get_similar_product_candidates(product_name: str, limit: int = 5):
    """
    OCR 제품명이 실제 제품명과 정확히 맞지 않을 때 유사 제품 후보를 찾습니다.
    """
    try:
        bom_df = load_bom_for_candidates()
        return find_similar_products(bom_df, product_name, limit=limit)
    except Exception:
        return []


def build_image_registration_question(production_date, product_key, quantity_kg):
    """
    선택한 제품으로 생산계획 등록용 문장을 다시 만듭니다.
    """
    return f"{production_date} {product_key} {fmt_num(quantity_kg)}kg 생산계획 등록 일괄"


def make_image_product_choice_keyboard(token: str, candidates: list):
    """
    제품 선택 버튼을 만듭니다.
    callback_data 길이 제한을 피하기 위해 제품코드 대신 후보 index를 저장합니다.
    """
    keyboard = []

    for idx, item in enumerate(candidates[:5]):
        code = str(item.get("제품코드", "")).strip()
        name = str(item.get("제품명", "")).strip()
        score = round(float(item.get("유사도", 0)) * 100)

        prefix = "⭐ " if score >= 85 and idx == 0 else ""
        label = f"{prefix}{name} [{code}] {score}%"

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


async def ask_image_product_choice(update: Update, chat_id: int, row_idx: int, total_count: int, question: str, product_name: str, quantity_kg: float, production_date):
    """
    이미지 OCR 제품명을 찾지 못했을 때 유사 제품 선택 버튼을 띄웁니다.
    선택 후에는 handle_image_product_choice_callback()에서 다시 생산 가능 여부를 확인하고,
    가능하면 생산계획에 저장합니다.
    """
    session = get_user_session(chat_id)
    candidates = get_similar_product_candidates(product_name, limit=5)

    if not candidates:
        await update.message.reply_text(
            f"❌ [{row_idx}/{total_count}] 제품명을 찾지 못했습니다.\n\n"
            f"OCR 인식 제품명: {product_name}\n"
            f"수량: {fmt_num(quantity_kg)}kg\n"
            f"생산일: {production_date}\n\n"
            f"유사 제품 후보도 찾지 못해 저장하지 않았습니다.\n"
            f"제품명을 직접 입력해서 다시 등록해 주세요."
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

    text = (
        f"❓ [{row_idx}/{total_count}] 제품명을 정확히 찾지 못했습니다.\n\n"
        f"OCR 인식 제품명: {product_name}\n"
        f"수량: {fmt_num(quantity_kg)}kg\n"
        f"생산일: {production_date}\n\n"
        f"가장 유사한 후보: {best.get('제품명')} [{best.get('제품코드')}] {best_score}%\n\n"
        f"아래에서 실제 제품명을 선택해 주세요.\n"
        f"선택한 제품으로 다시 생산 가능 여부를 확인하고, 가능하면 생산계획에 저장합니다."
    )

    await update.message.reply_text(
        text,
        reply_markup=make_image_product_choice_keyboard(token, candidates),
    )


async def process_image_registration_question(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, question: str, row_idx: int, total_count: int):
    """
    사진에서 추출된 생산계획 1행을 처리합니다.

    핵심:
    - 제품명이 정확히 있으면 기존 process_question()으로 처리
    - 제품명이 없으면 생산 불가능으로 끝내지 않고 유사제품 선택 버튼을 띄움
    """
    production_date = parse_production_date(question)
    items = parse_multi_items(question)

    if production_date and items:
        item = items[0]
        product_name = str(item.get("제품명", "")).strip()
        quantity_kg = float(item.get("생산수량kg", 0))

        if product_name and quantity_kg > 0:
            product_info = get_product_info(product_name)

            if product_info is None:
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

    return await process_question(chat_id, question, update_obj=update)


async def handle_image_product_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str, choice: str):
    """
    이미지 OCR 후 제품명 선택 버튼을 눌렀을 때 처리합니다.
    """
    query = update.callback_query
    chat_id = update.effective_chat.id
    session = get_user_session(chat_id)
    pending = session.get("pending_image_product_choices", {})

    data = pending.pop(token, None)

    if not data:
        await query.edit_message_text(
            "⏳ 제품 선택 시간이 만료되었거나 이미 처리된 버튼입니다.\n"
            "사진을 다시 보내거나 제품명을 직접 입력해 주세요."
        )
        return

    if choice == "cancel":
        await query.edit_message_text(
            f"⏭️ 저장하지 않았습니다.\n\n"
            f"OCR 인식 제품명: {data['ocr_product_name']}\n"
            f"수량: {fmt_num(data['quantity_kg'])}kg\n"
            f"생산일: {data['production_date']}"
        )
        return

    try:
        choice_idx = int(choice)
        selected = data["candidates"][choice_idx]
    except Exception:
        await query.edit_message_text("❌ 선택값을 처리하지 못했습니다. 다시 시도해 주세요.")
        return

    selected_code = str(selected.get("제품코드", "")).strip()
    selected_name = str(selected.get("제품명", "")).strip()
    selected_score = round(float(selected.get("유사도", 0)) * 100)

    new_question = build_image_registration_question(
        data["production_date"],
        selected_code or selected_name,
        data["quantity_kg"],
    )

    await query.edit_message_text(
        f"✅ 제품 선택 완료\n\n"
        f"OCR 인식명: {data['ocr_product_name']}\n"
        f"선택 제품: {selected_name} [{selected_code}] {selected_score}%\n\n"
        f"이 제품으로 생산 가능 여부를 다시 확인하고, 가능하면 생산계획에 저장합니다."
    )

    final_text = await process_question(chat_id, new_question, update_obj=None)

    save_usage_log(
        update.effective_user.id,
        update.effective_user.username,
        f"이미지 제품선택:{data['ocr_product_name']} -> {selected_name} [{selected_code}]",
        final_text,
    )

    prefix = (
        f"[이미지 제품명 재선택 처리 결과]\n"
        f"원래 OCR 제품명: {data['ocr_product_name']}\n"
        f"선택 제품명: {selected_name} [{selected_code}]\n\n"
    )

    for part in split_message(prefix + final_text):
        await context.bot.send_message(chat_id=chat_id, text=part)


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
5. 사진을 보내면 이미지 안의 생산계획을 분석합니다.

명령어:
/start - 시작 안내
/help - 사용법 보기
/id - 내 텔레그램 사용자 ID 확인
/register - 등록 신청
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


def check_all_remembered_plans():
    try:
        plans_df = load_plans()
    except Exception as e:
        return f"❌ 생산계획 파일을 읽어오는 중 오류가 발생했습니다: {str(e)}"

    if plans_df is None or plans_df.empty:
        return "현재 등록된 생산계획이 없거나 파일이 비어 있습니다."

    lines = []
    lines.append("=" * 50)
    lines.append("[현재 기억된 생산계획 전체 가능여부 확인]")
    lines.append(f"조회시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 50)

    last_valid_date = datetime.now().strftime("%Y-%m-%d")
    date_col = "생산일" if "생산일" in plans_df.columns else ("생산일자" if "생산일자" in plans_df.columns else None)

    if date_col:
        updated_dates = []

        for idx, row in plans_df.iterrows():
            raw_date = str(row[date_col]).strip()

            if raw_date in ['"', '""', '〃', '위와 같음', '동일']:
                updated_dates.append(last_valid_date)
            else:
                if raw_date and raw_date != "nan":
                    last_valid_date = raw_date.split(" ")[0]
                updated_dates.append(last_valid_date)

        plans_df[date_col] = updated_dates
        plans_df = plans_df.sort_values(by=date_col)

    running_extra_consumption = {}

    for idx, row in plans_df.iterrows():
        p_date = str(row.get("생산일", row.get("생산일자", ""))).split(" ")[0]
        p_key = str(row.get("제품코드", row.get("제품명", ""))).strip()
        p_qty = 0.0

        possible_qty_headers = [
            "주문량",
            "생산수량kg",
            "생산수량(kg)",
            "수량(kg)",
            "생산수량",
            "수량",
        ]

        for header in possible_qty_headers:
            if header in row and row[header] is not None and str(row[header]).strip() != "":
                raw_val_str = str(row[header]).strip().lower()
                match_qty = re.search(r"(\d+(?:\.\d+)?)\s*(톤|t|kg|킬로)?", raw_val_str)

                if match_qty:
                    val = float(match_qty.group(1))
                    unit = match_qty.group(2) if match_qty.group(2) else ""

                    if "톤" in unit or "t" in unit:
                        p_qty = val * 1000
                    else:
                        p_qty = val

                    if p_qty > 0:
                        break
                else:
                    try:
                        p_qty = float(raw_val_str.replace(",", ""))
                        if p_qty > 0:
                            break
                    except ValueError:
                        continue

        product_info = get_product_info(p_key)

        if not product_info:
            lines.append(f"[{p_date}] {p_key} {fmt_num(p_qty)}kg -> ❌ 배합비 없음")
            continue

        p_name = product_info["제품명"]
        result_dict = build_result(p_name, p_qty, extra_consumption=running_extra_consumption)
        shortage_list = result_dict.get("부족", [])

        if isinstance(shortage_list, list) and len(shortage_list) > 0:
            status_text = "❌ 생산 불가능 (자재 부족)"
            short_mats = [
                f"{m['자재명']}({fmt_num(m['부족수량'])}{m['배합단위']} 쇼트)"
                for m in shortage_list
            ]
            detail_text = f"└ 부족내역: {', '.join(short_mats)}"
        else:
            status_text = "✅ 생산 가능 (자재 여유)"
            detail_text = "└ 원/부자재 가용 재고 충족"

        lines.append(f"[{p_date}] {p_name} ({fmt_num(p_qty)}kg) -> {status_text}")
        lines.append(detail_text)

        for mat_item in result_dict.get("상세", []):
            m_code = mat_item["자재코드"]
            m_req = mat_item["필요수량"]
            running_extra_consumption[m_code] = running_extra_consumption.get(m_code, 0) + m_req

        lines.append("-" * 50)

    return "\n".join(lines)


async def process_question(chat_id: int, question: str, update_obj: Update = None) -> str:
    session = get_user_session(chat_id)
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
        quantity = parsed.get("quantity")

        if intent == "show_plan":
            try:
                plan_summary = format_plan_list()

                if not plan_summary or plan_summary.strip() == "":
                    return "현재 저장된 생산계획 일정이 없습니다."

                return f"[현재 등록된 생산계획 목록]\n\n{plan_summary}"
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

                success = delete_result[0] if isinstance(delete_result, tuple) else bool(delete_result)
                msg = (
                    delete_result[1]
                    if isinstance(delete_result, tuple) and len(delete_result) > 1
                    else "기록에서 삭제되었습니다."
                )

                if success:
                    return f"✅ {target_date} 자 [{display_name}] 생산 계획이 성공적으로 취소되었습니다.\n비고: {msg}"

                return f"❌ 취소 실패: {target_date} 일정에 [{display_name}] 제품 계획을 찾을 수 없습니다."
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

        has_shortage = "생산 불가능" in answer or "부족" in answer

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

    if data.startswith("imgsel|"):
        try:
            _, token, choice = data.split("|", 2)
            await handle_image_product_choice_callback(update, context, token, choice)
        except Exception as e:
            await query.edit_message_text(f"❌ 제품 선택 처리 중 오류가 발생했습니다.\n{str(e)}")
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

    answer = check_production(p_name, float(fix_data["quantity"]), intent="production_check")
    has_shortage = "생산 불가능" in answer or "부족" in answer

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
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    chat_id = update.effective_chat.id
    user_text = update.message.text

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


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    chat_id = update.effective_chat.id

    if not PHOTO_SUPPORT:
        await update.message.reply_text("이미지 분석용 모듈(image_parser)이 설정되지 않았습니다.")
        return

    temp_path = None

    try:
        await update.message.reply_text("이미지를 분석하고 있습니다. 잠시만 기다려주세요...")

        photo_file = await update.message.photo[-1].get_file()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            temp_path = tmp.name

        await photo_file.download_to_drive(temp_path)

        extracted_questions = extract_questions_from_image(temp_path)

        if not extracted_questions:
            await update.message.reply_text("이미지 내에서 생산 및 발주 관련 텍스트 추출에 실패했습니다.")
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

        read_text = "[사진 분석 → 생산등록 검토 목록]"

        for idx, q in enumerate(cleaned_questions, start=1):
            read_text += f"\n{idx}. {q}"

        await update.message.reply_text(read_text)

        for idx, q in enumerate(cleaned_questions, start=1):
            final_text = await process_image_registration_question(
                update=update,
                context=context,
                chat_id=chat_id,
                question=q,
                row_idx=idx,
                total_count=len(cleaned_questions),
            )

            if final_text == "__IMAGE_PRODUCT_CHOICE_PENDING__":
                save_usage_log(
                    update.effective_user.id,
                    update.effective_user.username,
                    f"사진분석:{q}",
                    "제품명 선택 대기",
                )
                continue

            if final_text == "__ASYNC_BUTTON_TRIGGERED__":
                save_usage_log(
                    update.effective_user.id,
                    update.effective_user.username,
                    f"사진분석:{q}",
                    "제품 선택 버튼 표시",
                )
                continue

            if len(cleaned_questions) > 1:
                final_text = f"[{idx}/{len(cleaned_questions)} 행 처리 결과]\n\n" + final_text

            save_usage_log(
                update.effective_user.id,
                update.effective_user.username,
                f"사진분석:{q}",
                final_text,
            )

            for part in split_message(final_text):
                await update.message.reply_text(part)

    except Exception as e:
        await update.message.reply_text(f"❌ 사진 처리 중 오류가 발생했습니다.\n{str(e)}")

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def main():
    print("텔레그램 ERP AI 비서 서버 가동 중...")
    print("기능: 도움말 / ID 확인 / 등록 신청 / 관리자 제한 / 사용 로그")
    print("정지하려면 Ctrl + C를 누르세요.")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("register", register_command))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))

    app.run_polling()


if __name__ == "__main__":
    main()
