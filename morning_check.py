import os
import asyncio
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from telegram import Bot

from production_summary import format_shortage_summary


load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_IDS = os.getenv("ALLOWED_TELEGRAM_CHAT_IDS", "")

STOCK_FILE = Path("data/stock.xlsx")
BOM_FILE = Path("data/bom.xlsx")
PLAN_FILE = Path("data/production_plan.xlsx")


def split_message(text: str, limit: int = 3900):
    if len(text) <= limit:
        return [text]

    parts = []
    current = ""

    for line in text.splitlines():
        if len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = line
        else:
            current += "\n" + line if current else line

    if current:
        parts.append(current)

    return parts


def get_chat_ids():
    ids = []

    for x in ALLOWED_CHAT_IDS.split(","):
        x = x.strip()
        if x:
            ids.append(x)

    return ids


def file_status_text(path: Path, label: str):
    if not path.exists():
        return f"- {label}: 파일 없음"

    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    today = datetime.now().date()

    status = "오늘 갱신됨" if mtime.date() == today else "오늘 갱신 아님"

    return f"- {label}: {mtime.strftime('%Y-%m-%d %H:%M:%S')} / {status}"


def build_morning_message():
    now = datetime.now()

    lines = []
    lines.append("📌 [오전 9시 생산계획 자동 점검]")
    lines.append(f"점검시각: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("[데이터 파일 상태]")
    lines.append(file_status_text(STOCK_FILE, "재고 파일 stock.xlsx"))
    lines.append(file_status_text(BOM_FILE, "배합비 파일 bom.xlsx"))
    lines.append(file_status_text(PLAN_FILE, "생산계획 production_plan.xlsx"))
    lines.append("")

    if STOCK_FILE.exists():
        stock_mtime = datetime.fromtimestamp(STOCK_FILE.stat().st_mtime)
        if stock_mtime.date() != now.date():
            lines.append("⚠️ 주의: 재고 파일이 오늘 갱신된 파일이 아닙니다.")
            lines.append("ERP에서 최신 창고별 재고조회 엑셀을 반영하지 않았다면 결과가 실제와 다를 수 있습니다.")
            lines.append("필요하면 update_data.bat 실행 후 다시 확인하세요.")
            lines.append("")
    else:
        lines.append("⚠️ 주의: stock.xlsx 파일이 없습니다.")
        lines.append("재고 변환 후 다시 점검해야 합니다.")
        lines.append("")

    lines.append(format_shortage_summary())

    return "\n".join(lines)


async def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN이 .env 파일에 없습니다.")

    chat_ids = get_chat_ids()

    if not chat_ids:
        raise RuntimeError("ALLOWED_TELEGRAM_CHAT_IDS가 .env 파일에 없습니다.")

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    message = build_morning_message()

    for chat_id in chat_ids:
        for part in split_message(message):
            await bot.send_message(chat_id=chat_id, text=part)


if __name__ == "__main__":
    asyncio.run(main())