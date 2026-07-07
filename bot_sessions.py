from bot_config import *

user_sessions = {}


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
