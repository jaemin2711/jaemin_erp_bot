@echo off
setlocal

echo [1/5] 현재 폴더 확인
echo TARGET=%CD%

if not exist telegram_bot.py (
  echo ERROR: 현재 폴더에 telegram_bot.py가 없습니다.
  echo 프로젝트 루트 폴더에서 실행해 주세요.
  exit /b 1
)

echo [2/5] 백업 생성
set BACKUP_DIR=backup_before_modular_refactor
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
copy /Y telegram_bot.py "%BACKUP_DIR%\telegram_bot.py" >nul

echo [3/5] 모듈 파일 복사
copy /Y "%~dp0app_setup.py" "app_setup.py" >nul
copy /Y "%~dp0bot_auth.py" "bot_auth.py" >nul
copy /Y "%~dp0bot_config.py" "bot_config.py" >nul
copy /Y "%~dp0bot_io.py" "bot_io.py" >nul
copy /Y "%~dp0bot_sessions.py" "bot_sessions.py" >nul
copy /Y "%~dp0core_handlers.py" "core_handlers.py" >nul
copy /Y "%~dp0force_plan.py" "force_plan.py" >nul
copy /Y "%~dp0image_handlers.py" "image_handlers.py" >nul
copy /Y "%~dp0plan_commands.py" "plan_commands.py" >nul
copy /Y "%~dp0plan_reports.py" "plan_reports.py" >nul
copy /Y "%~dp0plan_utils.py" "plan_utils.py" >nul
copy /Y "%~dp0product_alias_ocr.py" "product_alias_ocr.py" >nul
copy /Y "%~dp0reserved_contract.py" "reserved_contract.py" >nul
copy /Y "%~dp0shortage_detail.py" "shortage_detail.py" >nul
copy /Y "%~dp0telegram_bot.py" "telegram_bot.py" >nul

echo [4/5] 문법 검사
python -m py_compile telegram_bot.py bot_config.py bot_auth.py bot_sessions.py bot_io.py plan_utils.py plan_commands.py force_plan.py reserved_contract.py product_alias_ocr.py image_handlers.py plan_reports.py shortage_detail.py core_handlers.py app_setup.py
if errorlevel 1 (
  echo ERROR: 문법 검사 실패. 백업을 복구하세요.
  echo 복구: copy /Y backup_before_modular_refactor\telegram_bot.py telegram_bot.py
  exit /b 1
)

echo [5/5] 완료
echo telegram_bot.py가 가벼운 진입점으로 교체되고 기능 모듈이 분리되었습니다.
echo 실행 전 .env와 데이터 파일이 기존 위치에 있는지 확인하세요.
endlocal
