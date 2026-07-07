import asyncio

from bot_config import BOT_VERSION
from app_setup import build_application


def main():
    print("텔레그램 ERP AI 비서 서버 가동 중...")
    print(f"기능: 모듈 분리 구조 / {BOT_VERSION}")
    print("정지하려면 Ctrl + C를 누르세요.")

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = build_application()
    app.run_polling()


if __name__ == "__main__":
    main()
