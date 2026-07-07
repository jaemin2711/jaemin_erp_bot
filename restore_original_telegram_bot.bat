@echo off
setlocal
if not exist backup_before_modular_refactor\telegram_bot.py (
  echo ERROR: backup_before_modular_refactor\telegram_bot.py 를 찾지 못했습니다.
  exit /b 1
)
copy /Y backup_before_modular_refactor\telegram_bot.py telegram_bot.py
echo 복구 완료: 기존 telegram_bot.py를 되돌렸습니다.
endlocal
