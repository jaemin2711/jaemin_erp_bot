from bot_config import *
from bot_auth import is_allowed_user
from bot_io import split_message
from plan_utils import prepare_plans_for_display, clean_plan_value, clean_plan_qty, clean_plan_date, shorten_text, format_plan_table_view
from plan_commands import send_plan_manager


def _plan_df_with_dates():
    plans = load_plans()
    df = prepare_plans_for_display(plans)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["_date"] = pd.to_datetime(df["생산일"], errors="coerce").dt.date
    df = df.dropna(subset=["_date"])
    return df


def format_plan_range_view(start_date, end_date, title: str):
    df = _plan_df_with_dates()
    if df.empty:
        return "현재 등록된 생산계획이 없습니다."

    target = df[(df["_date"] >= start_date) & (df["_date"] <= end_date)].copy()
    if target.empty:
        return f"{title}\n해당 기간에 등록된 생산계획이 없습니다."

    total_qty = float(target["생산수량kg"].sum())
    lines = [title, f"기간: {start_date} ~ {end_date}", f"총 {len(target)}건 / 총 {fmt_num(total_qty)}kg", ""]
    no = 1
    for production_date, group in target.groupby("생산일", sort=True):
        day_qty = float(group["생산수량kg"].sum())
        lines.append(f"■ {production_date} ({len(group)}건 / {fmt_num(day_qty)}kg)")
        for _, row in group.iterrows():
            lines.append(f"{no}. {row.get('제품명')} [{row.get('제품코드')}] / {fmt_num(row.get('생산수량kg', 0))}kg")
            no += 1
        lines.append("")
    return "\n".join(lines).strip()


async def plan_period_command(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return

    today = datetime.now().date()
    if mode == "today":
        start_date = end_date = today
        title = "[오늘 생산계획]"
    elif mode == "tomorrow":
        start_date = end_date = today + timedelta(days=1)
        title = "[내일 생산계획]"
    elif mode == "week":
        start_date = today
        end_date = today + timedelta(days=7)
        title = "[이번 주 생산계획]"
    elif mode == "calendar":
        start_date = today.replace(day=1)
        if today.month == 12:
            next_month = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month = today.replace(month=today.month + 1, day=1)
        end_date = next_month - timedelta(days=1)
        title = f"[{today.month}월 생산계획]"
    else:
        start_date = today
        end_date = today + timedelta(days=7)
        title = "[생산계획]"

    text = format_plan_range_view(start_date, end_date, title)
    for part in split_message(text):
        await update.message.reply_text(part)


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await plan_period_command(update, context, "today")


async def tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await plan_period_command(update, context, "tomorrow")


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await plan_period_command(update, context, "week")


async def calendar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await plan_period_command(update, context, "calendar")


def format_risk_report(days: int | None = None, title: str = "[부족 자재 위험 조회]"):
    df = _plan_df_with_dates()
    if df.empty:
        return "현재 등록된 생산계획이 없습니다."

    today = datetime.now().date()
    target = df[df["_date"] >= today].copy()
    if days is not None:
        target = target[target["_date"] <= today + timedelta(days=days)].copy()

    if target.empty:
        return f"{title}\n조회 대상 생산계획이 없습니다."

    target = target.sort_values(by=["_date", "제품코드", "제품명"]).reset_index(drop=True)
    running_extra_consumption = {}
    shortage_rows = []
    checked_count = 0

    for _, row in target.iterrows():
        checked_count += 1
        production_date = str(row.get("생산일", "")).split(" ")[0]
        product_code = str(row.get("제품코드", "")).strip()
        product_name = str(row.get("제품명", "")).strip()
        qty = float(row.get("생산수량kg", 0) or 0)

        product_key = product_code or product_name
        info = get_product_info(product_key)
        if info:
            product_key = info.get("제품명") or product_key
            product_name = info.get("제품명") or product_name
            product_code = info.get("제품코드") or product_code

        try:
            result = build_result(product_key, qty, extra_consumption=running_extra_consumption)
        except Exception as e:
            shortage_rows.append({"date": production_date, "product": f"{product_name} [{product_code}]", "qty": qty, "error": str(e)})
            continue

        for item in result.get("부족", []) or []:
            shortage_rows.append({
                "date": production_date,
                "product": f"{product_name} [{product_code}]",
                "qty": qty,
                "material_code": item.get("자재코드", ""),
                "material_name": item.get("자재명", ""),
                "shortage_qty": item.get("부족수량", 0),
                "unit": item.get("배합단위", "") or item.get("재고단위", ""),
            })

        for detail in result.get("상세", []) or []:
            m_code = str(detail.get("자재코드", "")).strip()
            m_req = float(detail.get("필요수량", 0) or 0)
            if m_code:
                running_extra_consumption[m_code] = running_extra_consumption.get(m_code, 0) + m_req

    lines = [title, f"조회시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}", f"검토 생산계획: {checked_count}건", ""]
    if not shortage_rows:
        lines.append("✅ 현재 조회 범위에서는 부족 위험 자재가 없습니다.")
        return "\n".join(lines)

    lines.append(f"❗ 부족 위험 {len(shortage_rows)}건")
    lines.append("")
    for idx, item in enumerate(shortage_rows[:50], start=1):
        if item.get("error"):
            lines.append(f"{idx}. {item['date']} / {item['product']} / {fmt_num(item['qty'])}kg")
            lines.append(f"   - 오류: {item['error']}")
            continue
        lines.append(f"{idx}. {item['date']} / {item['product']} / {fmt_num(item['qty'])}kg")
        lines.append(f"   - 부족: {item.get('material_name')} [{item.get('material_code')}] {fmt_num(item.get('shortage_qty', 0))}{item.get('unit', '')}")

    if len(shortage_rows) > 50:
        lines.append("")
        lines.append(f"외 {len(shortage_rows) - 50}건이 더 있습니다.")
    return "\n".join(lines).strip()


async def risk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return
    text = format_risk_report(days=None, title="[전체 부족 자재 위험 조회]")
    for part in split_message(text):
        await update.message.reply_text(part)


async def riskweek_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return
    text = format_risk_report(days=7, title="[이번 주 부족 자재 위험 조회]")
    for part in split_message(text):
        await update.message.reply_text(part)


async def riskmonth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return
    text = format_risk_report(days=31, title="[한 달 부족 자재 위험 조회]")
    for part in split_message(text):
        await update.message.reply_text(part)


def format_history_log(keyword: str = "", max_rows: int = 30):
    log_file = Path("logs") / "usage_log.csv"
    if not log_file.exists():
        return "아직 작업 이력 로그가 없습니다."

    rows = []
    try:
        with open(log_file, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if keyword:
                    blob = " ".join(str(v) for v in row.values())
                    if keyword.lower() not in blob.lower():
                        continue
                rows.append(row)
    except Exception as e:
        return f"❌ 작업 이력을 읽는 중 오류가 발생했습니다.\n사유: {str(e)}"

    if not rows:
        return f"검색어에 맞는 작업 이력이 없습니다: {keyword}"

    rows = rows[-max_rows:]
    rows.reverse()
    title = "[최근 작업 이력]" if not keyword else f"[작업 이력 검색: {keyword}]"
    lines = [title, f"표시: 최근 {len(rows)}건", ""]
    for idx, row in enumerate(rows, start=1):
        time_text = row.get("시간", "")
        username = row.get("username", "") or row.get("user_id", "")
        question = str(row.get("질문", "")).replace("\n", " ")[:80]
        preview = str(row.get("응답요약", "")).replace("\n", " ")[:80]
        lines.append(f"{idx}. {time_text} / {username}")
        lines.append(f"   - 작업: {question}")
        if preview:
            lines.append(f"   - 결과: {preview}")
    return "\n".join(lines).strip()


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return
    keyword = re.sub(r"^/history\s*", "", update.message.text or "", flags=re.IGNORECASE).strip()
    result = format_history_log(keyword=keyword, max_rows=30)
    for part in split_message(result):
        await update.message.reply_text(part)


def build_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("오늘 계획", callback_data="menu|today"), InlineKeyboardButton("내일 계획", callback_data="menu|tomorrow")],
        [InlineKeyboardButton("이번 주 계획", callback_data="menu|week"), InlineKeyboardButton("이번 달 계획", callback_data="menu|calendar")],
        [InlineKeyboardButton("생산계획 목록", callback_data="menu|planlist"), InlineKeyboardButton("생산계획 관리", callback_data="menu|plans")],
        [InlineKeyboardButton("부족 위험", callback_data="menu|risk"), InlineKeyboardButton("작업 이력", callback_data="menu|history")],
        [InlineKeyboardButton("별칭 목록", callback_data="menu|aliaslist"), InlineKeyboardButton("도움말", callback_data="menu|help")],
    ])


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_user(update.effective_user.id):
        await update.message.reply_text("❌ 이 봇을 사용할 권한이 없습니다.")
        return
    await update.message.reply_text("[ERP 봇 메뉴]\n원하는 기능을 선택하세요.", reply_markup=build_menu_keyboard())


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    query = update.callback_query
    action = data.split("|", 1)[1] if "|" in data else ""

    if action == "today":
        d = datetime.now().date()
        text = format_plan_range_view(d, d, "[오늘 생산계획]")
    elif action == "tomorrow":
        d = datetime.now().date() + timedelta(days=1)
        text = format_plan_range_view(d, d, "[내일 생산계획]")
    elif action == "week":
        today = datetime.now().date()
        text = format_plan_range_view(today, today + timedelta(days=7), "[이번 주 생산계획]")
    elif action == "calendar":
        today = datetime.now().date()
        start_date = today.replace(day=1)
        if today.month == 12:
            next_month = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month = today.replace(month=today.month + 1, day=1)
        end_date = next_month - timedelta(days=1)
        text = format_plan_range_view(start_date, end_date, f"[{today.month}월 생산계획]")
    elif action == "planlist":
        text = format_plan_table_view()
    elif action == "plans":
        await send_plan_manager(update, context, edit_message=True)
        return
    elif action == "risk":
        text = format_risk_report(days=7, title="[이번 주 부족 자재 위험 조회]")
    elif action == "history":
        text = format_history_log(max_rows=10)
    elif action == "aliaslist":
        text = format_product_alias_list()
    elif action == "help":
        text = "전체 명령어는 /help 를 입력해서 확인하세요."
    else:
        text = "알 수 없는 메뉴입니다."

    if len(text) > 3900:
        text = text[:3800] + "\n\n내용이 길어 일부만 표시했습니다. 자세히 보려면 명령어를 직접 입력하세요."
    await query.edit_message_text(text=text, reply_markup=build_menu_keyboard())

def build_help_text():
    lines = [
        "[ERP AI 봇 명령어 목록]",
        "",
        "■ 기본 명령어",
        "/start - 시작 안내",
        "/help - 전체 명령어 및 사용법 보기",
        "/menu - 버튼형 메뉴 열기",
        "/id - 내 텔레그램 사용자 ID 확인",
        "/register - 사용 등록 신청",
        "/version - 현재 봇 버전 확인",
        "",
        "■ 생산계획 조회/관리",
        "/planlist - 저장된 생산계획을 표 형식으로 보기",
        "/plans 또는 /plan - 버튼으로 생산계획 수정/취소",
        "/editplan - 생산계획 직접 수정",
        "/delplan - 생산계획 직접 취소/삭제",
        "/changeplan - 문장으로 생산계획 변경",
        "/today - 오늘 생산계획 보기",
        "/tomorrow - 내일 생산계획 보기",
        "/week - 이번 주 생산계획 보기",
        "/calendar - 이번 달 생산계획 보기",
        "",
        "■ 부족 자재 위험 조회",
        "/risk - 오늘 이후 전체 생산계획 기준 부족 위험 조회",
        "/riskweek - 이번 주 부족 위험 조회",
        "/riskmonth - 한 달 부족 위험 조회",
        "생산계획 자재부족확인 - 전체 생산계획 자재부족 상세 확인",
        "",
        "■ 작업 이력",
        "/history - 최근 작업 이력 보기",
        "/history 검색어 - 특정 제품/날짜/작업 검색",
        "",
        "■ 제품 검색/통합 별칭 사전",
        "/product 제품명 - 제품 검색 및 통합 사전 조회",
        "/aliasadd 별칭 => 제품코드 - 텍스트/이미지 공통 별칭 등록",
        "/ocradd 인식명 => 제품코드 - /aliasadd와 동일",
        "/aliaslist 또는 /ocrmemory - 통합 사전 목록 보기",
        "/aliasdel 별칭 - 통합 사전 삭제",
        "/ocrforget 인식명 - /aliasdel과 동일",
        "",
        "예:",
        "/aliasadd 비타40 => P10570",
        "/ocradd 사진에찍힌이름 => P10570",
        "비타40 1톤 생산 가능?",
        "",
        "■ 생산 가능 여부 확인",
        "예: 6/22 제품명 500kg 생산 가능?",
        "예: 제품명 1톤 가능?",
        "",
        "■ 일반 생산계획 등록",
        "등록/저장/정정/수정/변경 표현이 들어가면 생산계획 저장 의도로 처리합니다.",
        "",
        "■ 강제등록",
        "/forceplan - 강제 생산계획 등록",
        "/forcemode - 강제등록 모드 설정/확인",
        "/forcestatus - 강제등록 상태 확인",
        "/forceon - 전체 강제등록 ON",
        "/forceoff - 전체 강제등록 OFF",
        "",
        "■ 계약생산",
        "/contractadd - 계약생산 등록",
        "/contractlist - 계약생산 목록 보기",
        "/contractcheck - 계약생산 재고 체크",
        "/contractdel 번호 - 계약생산 삭제",
        "/contractplan 번호 월 - 계약생산을 실제 생산계획으로 전환",
        "",
        "■ 예약 생산",
        "/reserveplan - 예약 생산 등록",
        "/reservedplans - 예약 생산 목록 보기",
        "/reservedel - 예약 생산 삭제",
        "/reserveddelete - 예약 생산 삭제",
        "/reserveactual - 예약 생산을 실제 생산계획으로 전환",
        "/reservedactual - 예약 생산을 실제 생산계획으로 전환",
        "",
        "■ 운영 관리 명령어",
        "/whoami - 내 사용자/권한 정보 확인",
        "/status - 봇 상태 확인",
        "/backup - 주요 데이터 백업",
        "/logs - 최근 로그 확인",
    ]
    return "\n".join(lines)

async def production_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for part in split_message(build_help_text()):
        await update.message.reply_text(part)
