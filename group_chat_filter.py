from __future__ import annotations

import os
import re
from typing import Tuple

GROUP_CHAT_TYPES = {"group", "supergroup"}


def is_group_chat(update) -> bool:
    chat = getattr(update, "effective_chat", None)
    return bool(chat and getattr(chat, "type", None) in GROUP_CHAT_TYPES)


def get_group_chat_mode() -> str:
    """
    group mode:
    - mention: 그룹에서는 봇 멘션/봇 답글/트리거 단어가 있을 때만 반응
    - all: 그룹에서도 기존처럼 모든 메시지 반응
    - off: 그룹 일반 메시지/사진은 무시, slash command와 callback만 사용
    """
    return os.getenv("GROUP_CHAT_MODE", "mention").strip().lower() or "mention"


def get_trigger_words() -> list[str]:
    raw = os.getenv("BOT_TRIGGER_WORDS", "봇,ERP,재고봇,생산봇")
    words = [x.strip() for x in raw.split(",") if x.strip()]
    return words or ["봇"]


async def get_bot_username(context) -> str:
    cached = context.bot_data.get("_bot_username")
    if cached:
        return str(cached)
    me = await context.bot.get_me()
    username = getattr(me, "username", "") or ""
    context.bot_data["_bot_username"] = username
    return username


def _is_reply_to_bot(update, bot_username: str) -> bool:
    msg = getattr(update, "message", None)
    if not msg or not getattr(msg, "reply_to_message", None):
        return False
    reply_user = getattr(msg.reply_to_message, "from_user", None)
    if not reply_user:
        return False
    if getattr(reply_user, "is_bot", False) and bot_username:
        return (getattr(reply_user, "username", "") or "").lower() == bot_username.lower()
    return bool(getattr(reply_user, "is_bot", False))


def _strip_mention(text: str, bot_username: str) -> tuple[bool, str]:
    if not text or not bot_username:
        return False, text
    mention = "@" + bot_username
    pattern = re.compile(re.escape(mention), re.IGNORECASE)
    if not pattern.search(text):
        return False, text
    cleaned = pattern.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return True, cleaned


def _strip_trigger_word(text: str) -> tuple[bool, str]:
    raw = str(text or "").strip()
    if not raw:
        return False, raw
    for word in get_trigger_words():
        pattern = re.compile(rf"^\s*{re.escape(word)}[\s,:：\-]+", re.IGNORECASE)
        if pattern.search(raw):
            cleaned = pattern.sub("", raw).strip()
            return True, cleaned
    return False, raw


async def should_process_group_message(update, context) -> Tuple[bool, str]:
    msg = getattr(update, "message", None)
    text = getattr(msg, "text", None) or getattr(msg, "caption", None) or ""

    if not is_group_chat(update):
        return True, text

    mode = get_group_chat_mode()

    if mode == "all":
        return True, text

    if mode == "off":
        return False, text

    bot_username = await get_bot_username(context)

    if _is_reply_to_bot(update, bot_username):
        return True, text

    mentioned, cleaned = _strip_mention(text, bot_username)
    if mentioned:
        return True, cleaned

    triggered, cleaned = _strip_trigger_word(text)
    if triggered:
        return True, cleaned

    return False, text


def should_reply_unauthorized(update) -> bool:
    if not is_group_chat(update):
        return True
    raw = os.getenv("GROUP_REPLY_UNAUTHORIZED", "false").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}
