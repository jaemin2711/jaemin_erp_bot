#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
텍스트 별칭과 이미지 OCR 기억값 통합 패치

목표:
- /ocradd, /ocrset, /aliasadd, /aliasset를 하나의 제품 매칭 사전으로 통합
- /ocrmemory, /aliaslist도 같은 목록 표시
- /ocrforget, /aliasdel도 같은 사전에서 삭제
- 텍스트 질문의 제품명도 OCR 기억값을 먼저 조회해서 처리

사용:
    python unify_ocr_alias_memory_20260624.py
    python -m py_compile telegram_bot.py
"""

from pathlib import Path
from datetime import datetime
import re

BOT_FILE = Path("telegram_bot.py")
MARKER = "ERP_UNIFIED_ALIAS_MEMORY_20260624"

UNIFY_BLOCK = '\n# ===== ERP_UNIFIED_ALIAS_MEMORY_20260624 시작 =====\ndef resolve_text_product_alias(product_name: str) -> str:\n    """\n    텍스트 입력 제품명도 OCR 기억값과 같은 사전을 사용합니다.\n    예:\n      /ocradd 비타40 => P10570\n      사용자가 "비타40 1톤 가능?" 입력\n      -> 내부적으로 P10570 또는 실제 제품명으로 처리\n    """\n    original = str(product_name or "").strip()\n    if not original:\n        return original\n\n    try:\n        remembered = lookup_ocr_product_memory(original)\n    except Exception:\n        remembered = None\n\n    if remembered:\n        return (\n            str(remembered.get("product_code") or "").strip()\n            or str(remembered.get("product_name") or "").strip()\n            or original\n        )\n\n    return original\n\n\ndef apply_product_aliases_to_question(question: str) -> str:\n    """\n    기존 product_aliases.csv 방식은 사용하지 않습니다.\n    제품명 추출 후 resolve_text_product_alias()에서 OCR/텍스트 통합 사전을 적용합니다.\n    """\n    return str(question or "")\n\n\ndef format_product_alias_list():\n    """\n    /aliaslist도 /ocrmemory와 같은 통합 사전을 보여줍니다.\n    """\n    text = format_ocr_product_memory()\n    return (\n        "[제품 별칭/이미지 OCR 통합 사전]\\n"\n        "아래 목록은 텍스트 별칭과 이미지 OCR 인식명에 공통 적용됩니다.\\n\\n"\n        f"{text}"\n    )\n\n\nasync def aliaslist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):\n    if not is_allowed_user(update.effective_user.id):\n        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")\n        return\n    await update.message.reply_text(format_product_alias_list())\n\n\nasync def aliasadd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):\n    """\n    /aliasadd와 /ocradd를 같은 의미로 사용합니다.\n    실제 저장은 remember_ocr_product()에 통합 저장합니다.\n    """\n    if not is_allowed_user(update.effective_user.id):\n        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")\n        return\n    if not is_admin_user(update.effective_user.id):\n        await update.message.reply_text("❌ 제품 별칭/매칭 사전 관리는 관리자만 사용할 수 있습니다.\\n.env에 ADMIN_USER_IDS를 설정해 주세요.")\n        return\n\n    raw = update.message.text or ""\n    body = re.sub(r"^/(aliasadd|aliasset|ocradd|ocrset)\\s*", "", raw, flags=re.IGNORECASE).strip()\n\n    sep = None\n    for candidate in ["=>", "->", "=", ","]:\n        if candidate in body:\n            sep = candidate\n            break\n\n    if not sep:\n        await update.message.reply_text(\n            "형식이 올바르지 않습니다.\\n\\n"\n            "예시:\\n"\n            "/aliasadd 비타40 => P10570\\n"\n            "/ocradd 이미지인식명 => P10570\\n\\n"\n            "이제 /aliasadd와 /ocradd는 같은 통합 사전에 저장됩니다."\n        )\n        return\n\n    alias_name, target = [x.strip() for x in body.split(sep, 1)]\n    if not alias_name or not target:\n        await update.message.reply_text("별칭/OCR 인식명과 실제 제품코드 또는 제품명을 모두 입력해 주세요.")\n        return\n\n    product_code, product_name, err = resolve_ocr_memory_target(target)\n    if err:\n        await update.message.reply_text(f"❌ {err}")\n        return\n\n    item = remember_ocr_product(\n        alias_name,\n        product_code,\n        product_name,\n        source="unified_alias_admin",\n        score=100,\n    )\n\n    msg = (\n        "✅ 제품 매칭 사전에 등록했습니다.\\n\\n"\n        f"입력명: {item.get(\'ocr_name\')}\\n"\n        f"매칭 제품: {item.get(\'product_name\')} [{item.get(\'product_code\')}]\\n\\n"\n        "이제 아래 두 경우에 모두 적용됩니다.\\n"\n        "1. 텍스트 질문: 입력명 1톤 생산 가능?\\n"\n        "2. 이미지 OCR: 사진에서 입력명이 인식될 때"\n    )\n    save_usage_log(update.effective_user.id, update.effective_user.username, f"통합별칭등록:{alias_name}->{product_code}", msg)\n    await update.message.reply_text(msg)\n\n\nasync def aliasdel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):\n    """\n    /aliasdel과 /ocrforget를 같은 통합 사전 삭제 기능으로 사용합니다.\n    """\n    if not is_allowed_user(update.effective_user.id):\n        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")\n        return\n    if not is_admin_user(update.effective_user.id):\n        await update.message.reply_text("❌ 제품 별칭/매칭 사전 관리는 관리자만 사용할 수 있습니다.")\n        return\n\n    raw = update.message.text or ""\n    target = re.sub(r"^/(aliasdel|aliasdelete|aliasforget|ocrforget)\\s*", "", raw, flags=re.IGNORECASE).strip()\n    if not target:\n        await update.message.reply_text("삭제할 입력명을 적어 주세요.\\n예: /aliasdel 비타40\\n예: /ocrforget 이미지인식명")\n        return\n\n    ok = forget_ocr_product_memory(target)\n    if ok:\n        msg = f"✅ 제품 매칭 사전에서 삭제했습니다: {target}"\n    else:\n        msg = f"삭제할 값을 찾지 못했습니다: {target}"\n\n    save_usage_log(update.effective_user.id, update.effective_user.username, f"통합별칭삭제:{target}", msg)\n    await update.message.reply_text(msg)\n\n\nasync def product_command(update: Update, context: ContextTypes.DEFAULT_TYPE):\n    """\n    /product 검색도 통합 사전을 먼저 확인합니다.\n    """\n    if not is_allowed_user(update.effective_user.id):\n        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")\n        return\n\n    query = re.sub(r"^/product\\s*", "", update.message.text or "", flags=re.IGNORECASE).strip()\n    if not query:\n        await update.message.reply_text(\n            "검색할 제품명, 제품코드, 별칭을 입력해 주세요.\\n"\n            "예: /product 비타40\\n"\n            "예: /product P10570"\n        )\n        return\n\n    remembered = lookup_ocr_product_memory(query)\n    if remembered:\n        await update.message.reply_text(\n            "[통합 사전 검색 결과]\\n"\n            f"- 입력명: {query}\\n"\n            f"- 매칭 제품: {remembered.get(\'product_name\')} [{remembered.get(\'product_code\')}]\\n\\n"\n            "이 값은 텍스트 질문과 이미지 OCR에 모두 적용됩니다."\n        )\n        return\n\n    info = get_product_info(query)\n    if info:\n        await update.message.reply_text(\n            "[제품 검색 결과]\\n"\n            f"- 제품명: {info.get(\'제품명\')}\\n"\n            f"- 제품코드: {info.get(\'제품코드\')}\\n\\n"\n            f"별칭으로 등록하려면:\\n"\n            f"/aliasadd 원하는별칭 => {info.get(\'제품코드\')}"\n        )\n        return\n\n    candidates = get_similar_product_candidates(query, limit=10)\n    if not candidates:\n        await update.message.reply_text(f"제품을 찾지 못했습니다: {query}")\n        return\n\n    lines = ["[유사 제품 후보]", f"검색어: {query}", ""]\n    for idx, item in enumerate(candidates, start=1):\n        score = round(float(item.get("유사도", 0)) * 100)\n        lines.append(f"{idx}. {item.get(\'제품명\')} [{item.get(\'제품코드\')}] {score}%")\n    lines.append("")\n    lines.append("정확한 제품코드로 별칭을 등록할 수 있습니다.")\n    lines.append("예: /aliasadd 비타40 => 제품코드")\n    await update.message.reply_text("\\n".join(lines))\n\n\nasync def ocrmemory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):\n    """\n    기존 /ocrmemory, /ocradd, /ocrset, /ocrforget 명령어를 통합 사전 명령어로 유지합니다.\n    """\n    if not is_admin_user(update.effective_user.id):\n        await update.message.reply_text("❌ 제품 별칭/매칭 사전 관리는 관리자만 사용할 수 있습니다.\\n.env에 ADMIN_USER_IDS를 설정해 주세요.")\n        return\n\n    text = update.message.text or ""\n    cmd = text.split()[0].lower() if text.split() else ""\n\n    if cmd in ["/ocradd", "/ocrset"]:\n        await aliasadd_command(update, context)\n        return\n\n    if cmd == "/ocrforget":\n        await aliasdel_command(update, context)\n        return\n\n    await update.message.reply_text(format_product_alias_list())\n\n\ndef build_help_text():\n    lines = [\n        "[ERP AI 봇 명령어 목록]",\n        "",\n        "■ 기본 명령어",\n        "/start - 시작 안내",\n        "/help - 전체 명령어 및 사용법 보기",\n        "/menu - 버튼형 메뉴 열기",\n        "/id - 내 텔레그램 사용자 ID 확인",\n        "/register - 사용 등록 신청",\n        "/version - 현재 봇 버전 확인",\n        "",\n        "■ 생산계획 조회/관리",\n        "/planlist - 저장된 생산계획을 표 형식으로 보기",\n        "/plans 또는 /plan - 버튼으로 생산계획 수정/취소",\n        "/editplan - 생산계획 직접 수정",\n        "/delplan - 생산계획 직접 취소/삭제",\n        "/changeplan - 문장으로 생산계획 변경",\n        "/today - 오늘 생산계획 보기",\n        "/tomorrow - 내일 생산계획 보기",\n        "/week - 이번 주 생산계획 보기",\n        "/calendar - 이번 달 생산계획 보기",\n        "",\n        "■ 부족 자재 위험 조회",\n        "/risk - 오늘 이후 전체 생산계획 기준 부족 위험 조회",\n        "/riskweek - 이번 주 부족 위험 조회",\n        "/riskmonth - 한 달 부족 위험 조회",\n        "생산계획 자재부족확인 - 전체 생산계획 자재부족 상세 확인",\n        "",\n        "■ 작업 이력",\n        "/history - 최근 작업 이력 보기",\n        "/history 검색어 - 특정 제품/날짜/작업 검색",\n        "",\n        "■ 제품 검색/통합 별칭 사전",\n        "/product 제품명 - 제품 검색 및 통합 사전 조회",\n        "/aliasadd 별칭 => 제품코드 - 텍스트/이미지 공통 별칭 등록",\n        "/ocradd 인식명 => 제품코드 - /aliasadd와 동일",\n        "/aliaslist 또는 /ocrmemory - 통합 사전 목록 보기",\n        "/aliasdel 별칭 - 통합 사전 삭제",\n        "/ocrforget 인식명 - /aliasdel과 동일",\n        "",\n        "예:",\n        "/aliasadd 비타40 => P10570",\n        "/ocradd 사진에찍힌이름 => P10570",\n        "비타40 1톤 생산 가능?",\n        "",\n        "■ 생산 가능 여부 확인",\n        "예: 6/22 제품명 500kg 생산 가능?",\n        "예: 제품명 1톤 가능?",\n        "",\n        "■ 일반 생산계획 등록",\n        "등록/저장/정정/수정/변경 표현이 들어가면 생산계획 저장 의도로 처리합니다.",\n        "",\n        "■ 강제등록",\n        "/forceplan - 강제 생산계획 등록",\n        "/forcemode - 강제등록 모드 설정/확인",\n        "/forcestatus - 강제등록 상태 확인",\n        "/forceon - 전체 강제등록 ON",\n        "/forceoff - 전체 강제등록 OFF",\n        "",\n        "■ 계약생산",\n        "/contractadd - 계약생산 등록",\n        "/contractlist - 계약생산 목록 보기",\n        "/contractcheck - 계약생산 재고 체크",\n        "/contractdel 번호 - 계약생산 삭제",\n        "/contractplan 번호 월 - 계약생산을 실제 생산계획으로 전환",\n        "",\n        "■ 예약 생산",\n        "/reserveplan - 예약 생산 등록",\n        "/reservedplans - 예약 생산 목록 보기",\n        "/reservedel - 예약 생산 삭제",\n        "/reserveddelete - 예약 생산 삭제",\n        "/reserveactual - 예약 생산을 실제 생산계획으로 전환",\n        "/reservedactual - 예약 생산을 실제 생산계획으로 전환",\n        "",\n        "■ 운영 관리 명령어",\n        "/whoami - 내 사용자/권한 정보 확인",\n        "/status - 봇 상태 확인",\n        "/backup - 주요 데이터 백업",\n        "/logs - 최근 로그 확인",\n    ]\n    return "\\n".join(lines)\n# ===== ERP_UNIFIED_ALIAS_MEMORY_20260624 끝 =====\n'


def backup_file(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak_unified_alias_{stamp}")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup


def insert_unify_block(text: str) -> str:
    if MARKER in text:
        return text

    # 가장 안전한 위치: start_command 바로 앞.
    target = "\nasync def start_command"
    if target not in text:
        # 기존 기능팩이 있다면 그 끝부분 뒤에 넣는다.
        target2 = "# ===== ERP_FEATURE_PACK_20260624 끝 ====="
        if target2 in text:
            return text.replace(target2, target2 + "\n" + UNIFY_BLOCK.strip(), 1)
        raise RuntimeError("통합 블록 삽입 위치를 찾지 못했습니다.")

    return text.replace(target, "\n" + UNIFY_BLOCK.strip() + target, 1)


def insert_text_alias_resolution(text: str) -> str:
    """
    process_question 안에서 parsed product_name을 구한 뒤,
    통합 사전으로 한 번 더 해석하게 만든다.
    """
    if "resolve_text_product_alias(product_name)" in text:
        return text

    # 일반적으로 이 부분은 process_question 내부에 있다.
    old = '        product_name = parsed.get("product_name")\n        quantity = parsed.get("quantity")\n'
    new = (
        '        product_name = parsed.get("product_name")\n'
        '        if product_name:\n'
        '            product_name = resolve_text_product_alias(product_name)\n'
        '        quantity = parsed.get("quantity")\n'
    )
    if old in text:
        return text.replace(old, new, 1)

    # fallback: quantity 줄 앞에 삽입
    old2 = '        quantity = parsed.get("quantity")\n'
    new2 = (
        '        if product_name:\n'
        '            product_name = resolve_text_product_alias(product_name)\n'
        '        quantity = parsed.get("quantity")\n'
    )
    if old2 in text:
        return text.replace(old2, new2, 1)

    raise RuntimeError("process_question 안의 product_name/quantity 위치를 찾지 못했습니다.")


def ensure_alias_handlers(text: str) -> str:
    """
    /aliasadd, /aliaslist 핸들러가 없는 경우 추가.
    이미 있으면 건드리지 않는다.
    """
    anchor = '    app.add_handler(CommandHandler("help", production_help_command))\n'
    if anchor not in text:
        return text

    insert_lines = ""
    needed = [
        ('CommandHandler("aliasadd", aliasadd_command)', '    app.add_handler(CommandHandler("aliasadd", aliasadd_command))\n'),
        ('CommandHandler("aliasset", aliasadd_command)', '    app.add_handler(CommandHandler("aliasset", aliasadd_command))\n'),
        ('CommandHandler("aliaslist", aliaslist_command)', '    app.add_handler(CommandHandler("aliaslist", aliaslist_command))\n'),
        ('CommandHandler("aliasdel", aliasdel_command)', '    app.add_handler(CommandHandler("aliasdel", aliasdel_command))\n'),
        ('CommandHandler("aliasdelete", aliasdel_command)', '    app.add_handler(CommandHandler("aliasdelete", aliasdel_command))\n'),
        ('CommandHandler("aliasforget", aliasdel_command)', '    app.add_handler(CommandHandler("aliasforget", aliasdel_command))\n'),
    ]
    for marker, line in needed:
        if marker not in text:
            insert_lines += line

    if not insert_lines:
        return text

    return text.replace(anchor, anchor + insert_lines, 1)


def main():
    if not BOT_FILE.exists():
        raise SystemExit("telegram_bot.py 파일을 찾지 못했습니다. 봇 저장소 루트에서 실행하세요.")

    original = BOT_FILE.read_text(encoding="utf-8")
    backup = backup_file(BOT_FILE)

    text = original
    text = insert_unify_block(text)
    text = insert_text_alias_resolution(text)
    text = ensure_alias_handlers(text)

    BOT_FILE.write_text(text, encoding="utf-8")

    print("통합 패치 적용 완료")
    print(f"백업 파일: {backup}")
    print("")
    print("다음 명령어로 확인하세요:")
    print("python -m py_compile telegram_bot.py")
    print("")
    print("테스트 명령어:")
    print("/ocradd 비타40 => 실제제품코드")
    print("비타40 1톤 생산 가능?")
    print("/aliaslist")
    print("/ocrmemory")


if __name__ == "__main__":
    main()
