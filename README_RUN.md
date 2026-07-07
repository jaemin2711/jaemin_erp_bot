# telegram-excel-bot 개선 패키지 실행 방법

이 ZIP은 기존 `jaemin2711/telegram-excel-bot` 저장소에 운영 안정화 기능을 추가하는 패치형 개선 패키지입니다.

제가 확인한 원본 저장소는 GitHub에서 archive/read-only 상태였고, 이 실행 환경에서는 원본 전체 ZIP을 컨테이너로 직접 복제하는 것이 제한되었습니다. 그래서 원본 파일을 덮어쓰는 방식이 아니라, 기존 저장소 폴더에 이 패키지를 넣고 `apply_improvements.py`를 실행하면 개선사항이 자동 적용되도록 구성했습니다.

## 적용되는 개선사항

1. `ALLOWED_USER_IDS`가 비어 있을 때 전체 허용하던 구조를 기본 차단으로 변경
2. `/whoami` 명령어 추가: 텔레그램 user_id 확인
3. `/status` 명령어 추가: 봇 상태, 주요 파일 존재 여부 확인
4. `/backup` 명령어 추가: 관리자 전용 수동 백업
5. `/logs` 명령어 추가: 관리자 전용 최근 오류 로그 확인
6. `logs/` 폴더 분리: 사용 기록, 등록 신청, 오류 로그 저장 위치 정리
7. `backups/` 폴더 추가: 생산계획 저장/삭제 전 백업 시도
8. `concurrent_updates(True)`를 `concurrent_updates(4)`로 완화
9. 전역 에러 핸들러 추가
10. `.env.example`, `requirements.txt`, 실행용 BAT 파일 추가

## 사용 순서

### 1. 기존 저장소 준비

이미 원본 저장소 폴더가 있다면 그 폴더를 사용하면 됩니다.

새로 받을 경우:

```bash
git clone https://github.com/jaemin2711/telegram-excel-bot.git
cd telegram-excel-bot
```

GitHub가 archive 상태여도 clone/download는 가능합니다.

### 2. ZIP 압축 해제

이 ZIP 안의 파일들을 원본 저장소 폴더 안에 복사합니다.

최종 구조 예시:

```text
telegram-excel-bot/
├─ telegram_bot.py
├─ ai_parser.py
├─ inventory_engine.py
├─ production_memory.py
├─ improvements/
├─ apply_improvements.py
├─ .env.example
├─ README_RUN.md
├─ requirements.txt
├─ install_and_patch.bat
└─ run_bot.bat
```

### 3. `.env` 만들기

`.env.example`을 복사해서 `.env`로 이름을 바꾼 뒤 값을 입력합니다.

```env
TELEGRAM_BOT_TOKEN=여기에_텔레그램_봇_토큰
OPENAI_API_KEY=여기에_OPENAI_API_KEY
ALLOWED_USER_IDS=123456789
ADMIN_USER_IDS=123456789
BOT_CONCURRENT_UPDATES=4
BOM_FILE=bom.xlsx
STOCK_FILE=stock.xlsx
PRODUCTION_PLAN_FILE=production_plans.xlsx
```

처음 ID를 모르면 봇 실행 후 `/whoami`를 입력해서 user_id를 확인하고 `.env`에 넣으면 됩니다.

### 4. 패치 적용

윈도우에서는:

```text
install_and_patch.bat 실행
```

또는 직접 실행:

```bash
python -m pip install -r requirements.txt
python apply_improvements.py
```

패치를 실행하면 기존 `telegram_bot.py`는 자동 백업됩니다.

예:

```text
telegram_bot.py.bak_20260614_153012
```

### 5. 봇 실행

```bash
python telegram_bot.py
```

윈도우에서는:

```text
run_bot.bat 실행
```

## 추가된 명령어

| 명령어 | 권한 | 설명 |
|---|---|---|
| `/whoami` | 전체 | 내 텔레그램 user_id 확인 |
| `/status` | 허용 사용자 | 봇 상태와 파일 존재 여부 확인 |
| `/backup` | 관리자 | 주요 엑셀 파일 수동 백업 |
| `/logs` | 관리자 | 최근 오류 로그 확인 |

## 주의사항

- `.env` 파일은 절대 GitHub에 올리지 마세요.
- `ALLOWED_USER_IDS`를 비워두면 개선 후에는 기본 차단됩니다.
- `/backup`과 `/logs`는 `ADMIN_USER_IDS`에 등록된 사람만 사용할 수 있습니다.
- 원본 `telegram_bot.py` 구조가 나중에 크게 바뀌면 `apply_improvements.py`의 자동 삽입 위치를 못 찾을 수 있습니다. 이 경우 백업 파일을 기준으로 수동 적용하면 됩니다.
- 생산계획 파일명이 다르면 `.env`의 `PRODUCTION_PLAN_FILE` 값을 실제 파일명으로 수정하세요.

## 되돌리기

패치가 마음에 들지 않으면 자동 생성된 백업 파일을 원래 이름으로 되돌리면 됩니다.

```bash
copy telegram_bot.py.bak_날짜시간 telegram_bot.py
```

리눅스/맥:

```bash
cp telegram_bot.py.bak_날짜시간 telegram_bot.py
```


## 들여쓰기 오류가 이미 난 경우
패치 후 `IndentationError`가 발생하면 아래 순서로 처리하세요.

1. 가장 안전한 방법: `telegram_bot.py.bak_날짜시간` 백업 파일을 `telegram_bot.py`로 복원
2. 이 패키지의 최신 `apply_improvements.py`로 다시 패치
3. 이미 패치된 파일을 바로 고치려면 `python repair_patched_bot.py` 실행
4. 마지막으로 `python -m py_compile telegram_bot.py`로 문법 확인
