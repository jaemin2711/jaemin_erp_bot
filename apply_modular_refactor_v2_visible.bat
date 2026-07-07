@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "LOG_FILE=%SCRIPT_DIR%apply_modular_refactor_v2_debug.log"

echo ==================================================
echo  Modular Refactor v2 적용 스크립트 - 화면 유지/로그 저장
echo ==================================================
echo.
echo 로그 파일: %LOG_FILE%
echo.

> "%LOG_FILE%" echo [%DATE% %TIME%] START apply_modular_refactor_v2_visible
>> "%LOG_FILE%" echo SCRIPT_DIR=%SCRIPT_DIR%
>> "%LOG_FILE%" echo CURRENT_DIR=%CD%

if not "%~1"=="" (
  set "TARGET_DIR=%~1"
) else (
  set "TARGET_DIR=%CD%"
)

echo 현재 적용 대상 폴더: !TARGET_DIR!
echo.

if not exist "!TARGET_DIR!\telegram_bot.py" (
  echo 현재 폴더에 telegram_bot.py가 없습니다.
  echo 프로젝트 루트 폴더 경로를 입력해 주세요.
  echo 예: C:\erp_ai_assistant
  set /p TARGET_DIR=프로젝트 폴더: 
)

if not exist "!TARGET_DIR!\telegram_bot.py" (
  echo.
  echo [실패] 대상 폴더에 telegram_bot.py가 없습니다: !TARGET_DIR!
  >> "%LOG_FILE%" echo ERROR missing telegram_bot.py in !TARGET_DIR!
  goto :END_FAIL
)

if not exist "!TARGET_DIR!\inventory_engine.py" (
  echo.
  echo [주의] 대상 폴더에 inventory_engine.py가 없습니다.
  echo 실제 프로젝트 루트가 아닐 가능성이 큽니다.
  echo 계속 적용하려면 Y를 입력하세요. 취소하려면 Enter.
  set /p CONTINUE_APPLY=계속할까요? [Y/N]: 
  if /I not "!CONTINUE_APPLY!"=="Y" goto :END_CANCEL
)

for %%F in (
  app_setup.py bot_auth.py bot_config.py bot_io.py bot_sessions.py core_handlers.py
  force_plan.py image_handlers.py plan_commands.py plan_reports.py plan_utils.py
  product_alias_ocr.py reserved_contract.py shortage_detail.py telegram_bot.py
) do (
  if not exist "%SCRIPT_DIR%%%F" (
    echo [실패] 모듈 파일이 없습니다: %SCRIPT_DIR%%%F
    >> "%LOG_FILE%" echo ERROR missing module %SCRIPT_DIR%%%F
    goto :END_FAIL
  )
)

set "BACKUP_DIR=!TARGET_DIR!\backup_before_modular_refactor_%DATE:~0,4%%DATE:~5,2%%DATE:~8,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%"
set "BACKUP_DIR=!BACKUP_DIR: =0!"

echo [1/5] 백업 생성: !BACKUP_DIR!
mkdir "!BACKUP_DIR!" >nul 2>&1
copy /Y "!TARGET_DIR!\telegram_bot.py" "!BACKUP_DIR!\telegram_bot.py" >nul
if errorlevel 1 (
  echo [실패] 기존 telegram_bot.py 백업 실패
  >> "%LOG_FILE%" echo ERROR backup failed
  goto :END_FAIL
)
>> "%LOG_FILE%" echo BACKUP_DIR=!BACKUP_DIR!

echo [2/5] 모듈 파일 복사
for %%F in (
  app_setup.py bot_auth.py bot_config.py bot_io.py bot_sessions.py core_handlers.py
  force_plan.py image_handlers.py plan_commands.py plan_reports.py plan_utils.py
  product_alias_ocr.py reserved_contract.py shortage_detail.py telegram_bot.py
) do (
  copy /Y "%SCRIPT_DIR%%%F" "!TARGET_DIR!\%%F" >nul
  if errorlevel 1 (
    echo [실패] 복사 실패: %%F
    >> "%LOG_FILE%" echo ERROR copy failed %%F
    copy /Y "!BACKUP_DIR!\telegram_bot.py" "!TARGET_DIR!\telegram_bot.py" >nul
    goto :END_FAIL
  )
)

echo [3/5] Python 확인
set "PYTHON_CMD=python"
%PYTHON_CMD% --version >nul 2>&1
if errorlevel 1 (
  set "PYTHON_CMD=py -3"
  %PYTHON_CMD% --version >nul 2>&1
  if errorlevel 1 (
    echo [실패] python 또는 py -3 명령을 찾지 못했습니다.
    >> "%LOG_FILE%" echo ERROR python not found
    copy /Y "!BACKUP_DIR!\telegram_bot.py" "!TARGET_DIR!\telegram_bot.py" >nul
    goto :END_FAIL
  )
)
%PYTHON_CMD% --version
>> "%LOG_FILE%" echo PYTHON_CMD=!PYTHON_CMD!

echo [4/5] 문법 검사
pushd "!TARGET_DIR!"
%PYTHON_CMD% -m py_compile telegram_bot.py bot_config.py bot_auth.py bot_sessions.py bot_io.py plan_utils.py plan_commands.py force_plan.py reserved_contract.py product_alias_ocr.py image_handlers.py plan_reports.py shortage_detail.py core_handlers.py app_setup.py >> "%LOG_FILE%" 2>&1
set "COMPILE_RC=!ERRORLEVEL!"
popd

if not "!COMPILE_RC!"=="0" (
  echo [실패] 문법 검사 실패. 원본 telegram_bot.py를 복구했습니다.
  copy /Y "!BACKUP_DIR!\telegram_bot.py" "!TARGET_DIR!\telegram_bot.py" >nul
  echo 자세한 오류는 로그를 확인하세요:
  echo %LOG_FILE%
  goto :END_FAIL
)

echo [5/5] 적용 완료
>> "%LOG_FILE%" echo SUCCESS

echo.
echo 적용 완료입니다.
echo 대상 폴더: !TARGET_DIR!
echo 원본 백업: !BACKUP_DIR!\telegram_bot.py
echo.
echo 다음 검증 명령:
echo   cd /d "!TARGET_DIR!"
echo   python telegram_bot.py
echo.
goto :END_OK

:END_CANCEL
echo.
echo 사용자가 적용을 취소했습니다.
>> "%LOG_FILE%" echo CANCELLED
pause
exit /b 2

:END_FAIL
echo.
echo 실패했습니다. 이 창의 메시지와 로그 파일을 확인해 주세요.
echo 로그 파일: %LOG_FILE%
pause
exit /b 1

:END_OK
pause
exit /b 0
