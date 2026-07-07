# telegram_bot.py 모듈 분리 v2 리포트

## 기준
- 입력 파일: /mnt/data/telegram_bot.py
- 원본 실제 파일 크기: 182,493 bytes
- 원본 정규화 후 라인 수: 4,821 lines
- 원본 top-level 함수 수: 121개

## 결과
- 새 telegram_bot.py 크기: 498 bytes
- 새 telegram_bot.py 라인 수: 23 lines
- 분리된 Python 모듈: 15개
- 분리 후 전체 Python 코드 크기 합계: 166,637 bytes
- 분리 후 전체 Python 라인 수: 4,610 lines

## 분리 구조

| 파일 | 역할 |
|---|---|
| telegram_bot.py | 실행 진입점만 유지 |
| app_setup.py | ApplicationBuilder 및 핸들러 등록 |
| bot_config.py | 환경변수, 공통 import, 운영 안정화 명령 연결 |
| bot_auth.py | 사용자/관리자 권한 확인 |
| bot_sessions.py | 사용자 세션 저장소 |
| bot_io.py | 로그 저장, 메시지 분할, 안전 전송 |
| plan_utils.py | 생산계획 파싱, 정리, 표/버튼 생성, 수정 로직 |
| plan_commands.py | /plans, /planlist, /editplan, /delplan 및 버튼 콜백 |
| force_plan.py | 강제등록, 일반 저장/정정, 강제등록 모드 |
| reserved_contract.py | 예약 생산계획, 계약생산, 자연어 생산계획 변경 |
| product_alias_ocr.py | 제품 검색, 통합 별칭/OCR 사전 |
| image_handlers.py | 사진 OCR 등록 및 이미지 제품 선택 콜백 |
| plan_reports.py | 오늘/내일/주간/월간 계획, 리스크, 이력, 메뉴, 도움말 |
| shortage_detail.py | 전체 생산계획 자재부족 상세 분석 |
| core_handlers.py | 일반 메시지 라우팅, 공통 콜백 라우팅, 기본 명령 |

## 제거/정리한 항목
- 중복 정의되어 실제로는 뒤에서 덮어써지던 함수 블록 제거
- 사용되지 않는 초기 product_aliases.csv 방식 명령 블록 제거
- OpenAI client 직접 생성 제거: telegram_bot.py 내부에서 사용되지 않았음
- main()의 대량 handler 등록 코드를 app_setup.py로 이동

## 검증
- `python -m py_compile *.py` 통과
- 실제 Telegram 토큰, .env, 엑셀 데이터 파일을 사용한 런타임 검증은 사용 환경에서 수행 필요

## 적용
1. ZIP 압축을 프로젝트 루트에 풀기
2. 프로젝트 루트에서 `apply_modular_refactor_v2.bat` 실행
3. `python -m py_compile *.py` 또는 BAT 결과 확인
4. 봇 실행
