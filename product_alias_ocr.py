from bot_config import *
from bot_auth import is_allowed_user, is_admin_user
from bot_io import save_usage_log


def should_review_ocr_auto_match(ocr_name: str, result: dict) -> bool:
    """
    build_result가 자동매칭했더라도 OCR명과 실제 제품명이 너무 다르면 바로 등록하지 않고 후보 버튼으로 돌립니다.
    예: 트림토판10% -> TS) 비타40호 90% 같은 경우 방지
    """
    match_info = result.get("match_info")

    if not match_info:
        return False

    matched_name = str(match_info.get("제품명") or result.get("제품명") or "")
    matched_code = str(match_info.get("제품코드") or result.get("제품코드") or "")

    # OCR 원문에 제품코드가 직접 들어있으면 신뢰
    if matched_code and matched_code.lower() in str(ocr_name).lower():
        return False

    try:
        score = float(match_info.get("유사도", 0))
    except Exception:
        score = 0.0

    if score <= 1:
        score_percent = score * 100
    else:
        score_percent = score

    auto_threshold = float(os.getenv("OCR_AUTO_MATCH_MIN_SCORE", "95"))

    if score_percent < auto_threshold:
        return True

    try:
        ocr_key = normalize_candidate_text(ocr_name)
        matched_key = normalize_candidate_text(matched_name)
        name_similarity = SequenceMatcher(None, ocr_key, matched_key).ratio() * 100
    except Exception:
        return True

    name_threshold = float(os.getenv("OCR_AUTO_MATCH_NAME_SIMILARITY", "70"))

    if name_similarity < name_threshold:
        return True

    return False


def resolve_ocr_memory_target(target: str):
    """
    /ocradd에서 입력한 제품코드 또는 제품명을 실제 제품코드/제품명으로 해석합니다.
    """
    target = str(target or "").strip()

    if not target:
        return None, None, "제품코드 또는 제품명을 입력해 주세요."

    info = get_product_info(target)

    if info:
        return str(info.get("제품코드") or target), str(info.get("제품명") or target), None

    try:
        result = build_result(target, 1, extra_consumption={})
    except Exception as e:
        return None, None, f"제품 조회 중 오류가 발생했습니다: {str(e)}"

    if result.get("found"):
        return str(result.get("제품코드") or target), str(result.get("제품명") or target), None

    return None, None, f"제품을 찾지 못했습니다: {target}"


def parse_ocr_memory_add_text(text: str):
    """
    지원:
    /ocradd OCR명 => 제품코드
    /ocradd OCR명 = 제품명
    /ocradd OCR명, 제품코드
    """
    raw = str(text or "").strip()

    for prefix in ["/ocradd", "/ocrset", "ocradd", "ocrset"]:
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):].strip()
            break

    separators = ["=>", "->", "=", ","]

    for sep in separators:
        if sep in raw:
            left, right = raw.split(sep, 1)
            ocr_name = left.strip()
            target = right.strip()

            if not ocr_name or not target:
                return None, None, "형식이 올바르지 않습니다. 예: /ocradd 투불한우 => P10570"

            return ocr_name, target, None

    return None, None, "형식이 올바르지 않습니다. 예: /ocradd 투불한우 => P10570"

def load_bom_for_candidates():
    """
    제품 후보 검색 전용으로 배합비 파일만 읽습니다.
    stock.xlsx 오류 때문에 후보 버튼이 막히지 않도록 load_data()를 쓰지 않습니다.
    """
    if not BOM_FILE.exists():
        raise FileNotFoundError(f"배합비 파일이 없습니다: {BOM_FILE}")

    return pd.read_excel(BOM_FILE)


def normalize_candidate_text(value):
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"생산계획|생산등록|생산|계획|등록|가능|확인|kg|킬로|키로|톤", "", text)
    text = re.sub(r"[^0-9a-zA-Z가-힣]", "", text)
    # OCR 흔한 오인식 최소 보정
    text = text.replace("얼디메이트", "얼티메이트")
    text = text.replace("얼터메이트", "얼티메이트")
    text = text.replace("코팅비타fc", "코팅비타fc")
    return text


def fallback_similar_products(bom_df, search_text: str, limit: int = 8):
    """
    inventory_engine.find_similar_products가 후보를 못 만들 때 쓰는 마지막 안전장치.
    점수가 낮아도 상위 후보를 보여줘서 사용자가 직접 선택할 수 있게 합니다.
    """
    if "제품코드" not in bom_df.columns or "제품명" not in bom_df.columns:
        return []

    search_key = normalize_candidate_text(search_text)

    if not search_key:
        return []

    product_df = (
        bom_df[["제품코드", "제품명"]]
        .dropna(subset=["제품코드", "제품명"])
        .drop_duplicates()
        .copy()
    )

    rows = []

    for _, row in product_df.iterrows():
        code = str(row["제품코드"]).strip()
        name = str(row["제품명"]).strip()
        name_key = normalize_candidate_text(name)
        code_key = normalize_candidate_text(code)

        if not name_key and not code_key:
            continue

        score_name = SequenceMatcher(None, search_key, name_key).ratio() if name_key else 0
        score_code = 0.0

        if code_key:
            if search_key == code_key:
                score_code = 1.0
            elif search_key in code_key or code_key in search_key:
                score_code = 0.90
            else:
                score_code = SequenceMatcher(None, search_key, code_key).ratio() * 0.8

        score = max(score_name, score_code)

        # 아주 낮은 점수도 상위 후보에 넣는다. 제품명 선택 자체가 목적이기 때문.
        rows.append({
            "제품코드": code,
            "제품명": name,
            "유사도": float(score),
            "매칭사유": "후보보정",
        })

    rows.sort(key=lambda x: x["유사도"], reverse=True)
    return rows[:limit]


def get_similar_product_candidates(product_name: str, limit: int = 8):
    """
    OCR 제품명이 실제 제품명과 다를 때 보여줄 후보를 찾습니다.
    기본 후보가 없어도 fallback으로 상위 후보를 반드시 최대한 보여줍니다.
    """
    try:
        bom_df = load_bom_for_candidates()
        candidates = find_similar_products(bom_df, product_name, limit=limit) or []

        if candidates:
            return candidates[:limit]

        return fallback_similar_products(bom_df, product_name, limit=limit)
    except Exception:
        return []

def resolve_text_product_alias(product_name: str) -> str:
    """
    텍스트 입력 제품명도 OCR 기억값과 같은 사전을 사용합니다.
    예:
      /ocradd 비타40 => P10570
      사용자가 "비타40 1톤 가능?" 입력
      -> 내부적으로 P10570 또는 실제 제품명으로 처리
    """
    original = str(product_name or "").strip()
    if not original:
        return original

    try:
        remembered = lookup_ocr_product_memory(original)
    except Exception:
        remembered = None

    if remembered:
        return (
            str(remembered.get("product_code") or "").strip()
            or str(remembered.get("product_name") or "").strip()
            or original
        )

    return original


def apply_product_aliases_to_question(question: str) -> str:
    """
    기존 product_aliases.csv 방식은 사용하지 않습니다.
    제품명 추출 후 resolve_text_product_alias()에서 OCR/텍스트 통합 사전을 적용합니다.
    """
    return str(question or "")


def format_product_alias_list():
    """
    /aliaslist도 /ocrmemory와 같은 통합 사전을 보여줍니다.
    """
    text = format_ocr_product_memory()
    return (
        "[제품 별칭/이미지 OCR 통합 사전]\n"
        "아래 목록은 텍스트 별칭과 이미지 OCR 인식명에 공통 적용됩니다.\n\n"
        f"{text}"
    )


async def aliaslist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return
    await update.message.reply_text(format_product_alias_list())


async def aliasadd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /aliasadd와 /ocradd를 같은 의미로 사용합니다.
    실제 저장은 remember_ocr_product()에 통합 저장합니다.
    """
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return
    if not is_admin_user(update.effective_user.id):
        await update.message.reply_text("❌ 제품 별칭/매칭 사전 관리는 관리자만 사용할 수 있습니다.\n.env에 ADMIN_USER_IDS를 설정해 주세요.")
        return

    raw = update.message.text or ""
    body = re.sub(r"^/(aliasadd|aliasset|ocradd|ocrset)\s*", "", raw, flags=re.IGNORECASE).strip()

    sep = None
    for candidate in ["=>", "->", "=", ","]:
        if candidate in body:
            sep = candidate
            break

    if not sep:
        await update.message.reply_text(
            "형식이 올바르지 않습니다.\n\n"
            "예시:\n"
            "/aliasadd 비타40 => P10570\n"
            "/ocradd 이미지인식명 => P10570\n\n"
            "이제 /aliasadd와 /ocradd는 같은 통합 사전에 저장됩니다."
        )
        return

    alias_name, target = [x.strip() for x in body.split(sep, 1)]
    if not alias_name or not target:
        await update.message.reply_text("별칭/OCR 인식명과 실제 제품코드 또는 제품명을 모두 입력해 주세요.")
        return

    product_code, product_name, err = resolve_ocr_memory_target(target)
    if err:
        await update.message.reply_text(f"❌ {err}")
        return

    item = remember_ocr_product(
        alias_name,
        product_code,
        product_name,
        source="unified_alias_admin",
        score=100,
    )

    msg = (
        "✅ 제품 매칭 사전에 등록했습니다.\n\n"
        f"입력명: {item.get('ocr_name')}\n"
        f"매칭 제품: {item.get('product_name')} [{item.get('product_code')}]\n\n"
        "이제 아래 두 경우에 모두 적용됩니다.\n"
        "1. 텍스트 질문: 입력명 1톤 생산 가능?\n"
        "2. 이미지 OCR: 사진에서 입력명이 인식될 때"
    )
    save_usage_log(update.effective_user.id, update.effective_user.username, f"통합별칭등록:{alias_name}->{product_code}", msg)
    await update.message.reply_text(msg)


async def aliasdel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /aliasdel과 /ocrforget를 같은 통합 사전 삭제 기능으로 사용합니다.
    """
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return
    if not is_admin_user(update.effective_user.id):
        await update.message.reply_text("❌ 제품 별칭/매칭 사전 관리는 관리자만 사용할 수 있습니다.")
        return

    raw = update.message.text or ""
    target = re.sub(r"^/(aliasdel|aliasdelete|aliasforget|ocrforget)\s*", "", raw, flags=re.IGNORECASE).strip()
    if not target:
        await update.message.reply_text("삭제할 입력명을 적어 주세요.\n예: /aliasdel 비타40\n예: /ocrforget 이미지인식명")
        return

    ok = forget_ocr_product_memory(target)
    if ok:
        msg = f"✅ 제품 매칭 사전에서 삭제했습니다: {target}"
    else:
        msg = f"삭제할 값을 찾지 못했습니다: {target}"

    save_usage_log(update.effective_user.id, update.effective_user.username, f"통합별칭삭제:{target}", msg)
    await update.message.reply_text(msg)


async def product_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /product 검색도 통합 사전을 먼저 확인합니다.
    """
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    query = re.sub(r"^/product\s*", "", update.message.text or "", flags=re.IGNORECASE).strip()
    if not query:
        await update.message.reply_text(
            "검색할 제품명, 제품코드, 별칭을 입력해 주세요.\n"
            "예: /product 비타40\n"
            "예: /product P10570"
        )
        return

    remembered = lookup_ocr_product_memory(query)
    if remembered:
        await update.message.reply_text(
            "[통합 사전 검색 결과]\n"
            f"- 입력명: {query}\n"
            f"- 매칭 제품: {remembered.get('product_name')} [{remembered.get('product_code')}]\n\n"
            "이 값은 텍스트 질문과 이미지 OCR에 모두 적용됩니다."
        )
        return

    info = get_product_info(query)
    if info:
        await update.message.reply_text(
            "[제품 검색 결과]\n"
            f"- 제품명: {info.get('제품명')}\n"
            f"- 제품코드: {info.get('제품코드')}\n\n"
            f"별칭으로 등록하려면:\n"
            f"/aliasadd 원하는별칭 => {info.get('제품코드')}"
        )
        return

    candidates = get_similar_product_candidates(query, limit=10)
    if not candidates:
        await update.message.reply_text(f"제품을 찾지 못했습니다: {query}")
        return

    lines = ["[유사 제품 후보]", f"검색어: {query}", ""]
    for idx, item in enumerate(candidates, start=1):
        score = round(float(item.get("유사도", 0)) * 100)
        lines.append(f"{idx}. {item.get('제품명')} [{item.get('제품코드')}] {score}%")
    lines.append("")
    lines.append("정확한 제품코드로 별칭을 등록할 수 있습니다.")
    lines.append("예: /aliasadd 비타40 => 제품코드")
    await update.message.reply_text("\n".join(lines))


async def ocrmemory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    기존 /ocrmemory, /ocradd, /ocrset, /ocrforget 명령어를 통합 사전 명령어로 유지합니다.
    """
    if not is_admin_user(update.effective_user.id):
        await update.message.reply_text("❌ 제품 별칭/매칭 사전 관리는 관리자만 사용할 수 있습니다.\n.env에 ADMIN_USER_IDS를 설정해 주세요.")
        return

    text = update.message.text or ""
    cmd = text.split()[0].lower() if text.split() else ""

    if cmd in ["/ocradd", "/ocrset"]:
        await aliasadd_command(update, context)
        return

    if cmd == "/ocrforget":
        await aliasdel_command(update, context)
        return

    await update.message.reply_text(format_product_alias_list())
