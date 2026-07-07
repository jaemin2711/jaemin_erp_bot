from bot_config import *
from bot_config import _improved_backup_known_data_files
from bot_sessions import get_user_session


def parse_quantity_text(text: str):
    """
    '3000', '3,000kg', '3톤', '3t', '6월 15일 3000kg' 같은 입력을 kg 숫자로 변환합니다.
    날짜와 수량이 같이 들어오면 단위가 붙은 마지막 수량을 우선 인식합니다.
    """
    raw = str(text or "").strip().lower()

    unit_matches = re.findall(
        r"(\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(톤|t|kg|키로|킬로)",
        raw,
    )

    if unit_matches:
        qty_text, unit = unit_matches[-1]
        qty = float(qty_text.replace(",", ""))

        if unit in ["톤", "t"]:
            qty *= 1000

        return qty

    number_matches = re.findall(
        r"\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?",
        raw,
    )

    if not number_matches:
        return None

    # 날짜와 같이 들어온 경우를 고려해 마지막 숫자를 수량으로 봅니다.
    qty = float(number_matches[-1].replace(",", ""))
    return qty


def parse_plan_date_input(text: str):
    """
    생산일 수정 입력을 YYYY-MM-DD로 변환합니다.
    지원 예:
    - 오늘, 내일, 모레
    - 6월 15일
    - 2026-06-15
    - 06/15
    """
    raw = str(text or "").strip()
    compact = raw.replace(" ", "")
    today = datetime.now().date()

    if not raw:
        return None

    if "오늘" in compact:
        return today.strftime("%Y-%m-%d")

    if "내일" in compact:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    if "모레" in compact:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    match_after = re.search(r"(\d+)\s*일\s*(뒤|후)", raw)
    if match_after:
        return (today + timedelta(days=int(match_after.group(1)))).strftime("%Y-%m-%d")

    parsed = parse_production_date(raw)
    if parsed:
        return normalize_plan_date(parsed)

    parsed_date = parse_plan_date(raw)
    if parsed_date:
        return parsed_date.strftime("%Y-%m-%d")

    # '15일'처럼 일자만 입력한 경우는 이번 달로 판단합니다.
    match_day_only = re.fullmatch(r"\s*(\d{1,2})\s*일?\s*", raw)
    if match_day_only:
        day = int(match_day_only.group(1))
        try:
            candidate = datetime(today.year, today.month, day).date()
            if candidate < today:
                # 이번 달 날짜가 이미 지났으면 다음 달로 처리합니다.
                if today.month == 12:
                    candidate = datetime(today.year + 1, 1, day).date()
                else:
                    candidate = datetime(today.year, today.month + 1, day).date()
            return candidate.strftime("%Y-%m-%d")
        except Exception:
            return None

    return None


def format_plan_summary_line(row, number=None):
    prefix = f"{number}. " if number is not None else ""
    return (
        f"{prefix}{row['생산일']} / {row['제품명']} [{row['제품코드']}] / "
        f"{fmt_num(row['생산수량kg'])}kg"
    )


def clean_plan_value(value, default=""):
    """
    생산계획 목록 표시용 값 정리.
    nan, NaT, None 같은 값을 빈값으로 바꿉니다.
    """
    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except Exception:
        pass

    text = str(value).strip()

    if text.lower() in ["nan", "nat", "none", "null"]:
        return default

    return text


def clean_plan_date(value):
    """
    날짜를 YYYY-MM-DD 형태로 정리합니다.
    """
    value = clean_plan_value(value)

    if not value:
        return ""

    try:
        dt = pd.to_datetime(value, errors="coerce")

        if not pd.isna(dt):
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass

    return str(value).split(" ")[0].strip()


def clean_plan_qty(value):
    """
    생산수량을 숫자로 정리합니다.
    """
    try:
        if pd.isna(value):
            return 0.0
    except Exception:
        pass

    text = str(value).replace(",", "").replace("kg", "").replace("KG", "").strip()

    try:
        return float(text)
    except Exception:
        return 0.0


def shorten_text(text, max_len=18):
    """
    텔레그램 한 줄 표시가 너무 길어지지 않게 제품명을 줄입니다.
    """
    text = clean_plan_value(text)

    if len(text) <= max_len:
        return text

    return text[:max_len - 1] + "…"


def prepare_plans_for_display(plans):
    """
    load_plans() 결과를 보기 좋은 표 표시용 DataFrame으로 정리합니다.
    """
    if plans is None or plans.empty:
        return pd.DataFrame()

    df = plans.copy()

    # 필요한 컬럼이 없을 때도 죽지 않게 보정
    for col in ["생산일", "제품코드", "제품명", "생산수량kg"]:
        if col not in df.columns:
            df[col] = ""

    df["생산일"] = df["생산일"].apply(clean_plan_date)
    df["제품코드"] = df["제품코드"].apply(lambda x: clean_plan_value(x, "-"))
    df["제품명"] = df["제품명"].apply(lambda x: clean_plan_value(x, "-"))
    df["생산수량kg"] = df["생산수량kg"].apply(clean_plan_qty)

    df["_정렬일"] = pd.to_datetime(df["생산일"], errors="coerce")
    df = df.sort_values(by=["_정렬일", "제품코드", "제품명"], na_position="last").reset_index(drop=True)

    return df


def format_plan_table_view(max_rows=None):
    """
    텔레그램에서 한눈에 보기 좋은 생산계획 표를 만듭니다.

    특징:
    - 일자별 그룹
    - nan 제거
    - 총 건수/총 수량 표시
    - 제품명이 길면 자동 축약
    """
    plans = load_plans()
    df = prepare_plans_for_display(plans)

    if df.empty:
        return "현재 등록된 생산계획이 없습니다."

    total_count = len(df)
    total_qty = float(df["생산수량kg"].sum())

    if max_rows is not None:
        df = df.head(max_rows).copy()

    lines = []
    lines.append("[현재 등록된 생산계획표]")
    lines.append(f"총 {total_count}건 / 총 {fmt_num(total_qty)}kg")
    lines.append("")
    lines.append("번호 | 생산일 | 제품코드 | 제품명 | 수량")
    lines.append("-" * 44)

    display_no = 1

    for production_date, group in df.groupby("생산일", sort=False):
        date_qty = float(group["생산수량kg"].sum())
        lines.append(f"📅 {production_date}  ({len(group)}건 / {fmt_num(date_qty)}kg)")

        for _, row in group.iterrows():
            code = clean_plan_value(row.get("제품코드"), "-")
            name = shorten_text(row.get("제품명"), 18)
            qty = fmt_num(row.get("생산수량kg", 0))

            lines.append(
                f"{display_no:02d} | {production_date[5:] if len(production_date) >= 10 else production_date} | "
                f"{code} | {name} | {qty}kg"
            )
            display_no += 1

        lines.append("")

    if max_rows is not None and total_count > max_rows:
        lines.append(f"외 {total_count - max_rows}건이 더 있습니다.")

    lines.append("수정/취소는 /plans 를 입력하세요.")

    return "\n".join(lines).strip()


def make_plan_token(session: dict, row, original_index: int):
    token = uuid.uuid4().hex[:10]
    session["pending_plan_actions"][token] = {
        "index": int(original_index),
        "production_date": str(row["생산일"]),
        "product_code": str(row["제품코드"]),
        "product_name": str(row["제품명"]),
        "qty_kg": float(row["생산수량kg"]),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return token


def get_plan_page_size():
    """
    /plans 버튼 목록 페이지당 표시 개수.
    텔레그램 인라인 키보드는 버튼 개수가 많으면 제한에 걸릴 수 있으므로
    기본 25개씩 페이지로 나눕니다.

    .env:
    PLANS_PAGE_SIZE=25
    """
    try:
        value = int(os.getenv("PLANS_PAGE_SIZE", "25"))
    except Exception:
        value = 25

    if value < 5:
        return 5

    if value > 40:
        return 40

    return value


def build_plan_manage_view(chat_id: int, page: int = 1):
    """
    현재 저장된 생산계획을 버튼으로 수정/취소할 수 있게 표시합니다.

    개선:
    - 기존에는 항목이 많으면 텔레그램 인라인 키보드 버튼 제한 때문에 50번 근처까지만 보이는 문제가 있었습니다.
    - 페이지 기능을 추가해서 전체 생산계획을 25개씩 나누어 볼 수 있게 했습니다.
    """
    session = get_user_session(chat_id)
    session["pending_plan_actions"] = {}
    session["pending_plan_edit_inputs"] = {}

    plans = load_plans()

    if plans is None or plans.empty:
        return "현재 등록된 생산계획이 없습니다.", None

    page_size = get_plan_page_size()

    temp_plans = plans.copy()
    temp_plans["_원본index"] = temp_plans.index
    temp_display = prepare_plans_for_display(temp_plans)

    if "_원본index" not in temp_display.columns:
        temp_display["_원본index"] = temp_plans.index

    total_count = len(temp_display)
    total_qty = float(temp_display["생산수량kg"].sum()) if "생산수량kg" in temp_display.columns else 0.0
    total_pages = max(1, (total_count + page_size - 1) // page_size)

    try:
        page = int(page)
    except Exception:
        page = 1

    page = max(1, min(page, total_pages))
    session["plan_manage_page"] = page

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_df = temp_display.iloc[start_idx:end_idx].copy()

    lines = []
    lines.append("[생산계획 관리]")
    lines.append(f"총 {total_count}건 / 총 {fmt_num(total_qty)}kg")
    lines.append(f"페이지 {page}/{total_pages} / 현재 {start_idx + 1}~{min(end_idx, total_count)}번 표시")
    lines.append("수정 또는 취소할 항목의 버튼을 누르세요.")
    lines.append("")
    lines.append("번호 | 생산일 | 제품코드 | 제품명 | 수량")
    lines.append("-" * 44)

    keyboard = []

    for local_no, (_, row) in enumerate(page_df.iterrows(), start=1):
        display_no = start_idx + local_no
        production_date = clean_plan_value(row.get("생산일"), "-")
        code = clean_plan_value(row.get("제품코드"), "-")
        name = shorten_text(row.get("제품명"), 18)
        qty = fmt_num(row.get("생산수량kg", 0))

        lines.append(
            f"{display_no:02d} | {production_date[5:] if len(production_date) >= 10 else production_date} | "
            f"{code} | {name} | {qty}kg"
        )

        original_idx = int(row.get("_원본index", display_no - 1))
        token = make_plan_token(session, row, original_idx)
        keyboard.append([
            InlineKeyboardButton(f"✏️ {display_no}번 수정", callback_data=f"plan|edit|{token}"),
            InlineKeyboardButton(f"🗑 {display_no}번 취소", callback_data=f"plan|del|{token}"),
        ])

    nav_buttons = []

    if page > 1:
        nav_buttons.append(InlineKeyboardButton("◀ 이전", callback_data=f"plan|page|{page - 1}"))

    nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="plan|noop|none"))

    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("다음 ▶", callback_data=f"plan|page|{page + 1}"))

    keyboard.append(nav_buttons)
    keyboard.append([
        InlineKeyboardButton("🔄 새로고침", callback_data=f"plan|page|{page}"),
        InlineKeyboardButton("닫기", callback_data="plan|close|none"),
    ])

    if total_pages > 1:
        lines.append("")
        lines.append("다른 번호를 보려면 아래 이전/다음 버튼을 누르세요.")
        lines.append("명령어 수정은 /수정 번호, 날짜, 수량 형식으로 전체 번호 기준 사용 가능합니다.")

    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


def get_plan_action(session: dict, token: str):
    return session.get("pending_plan_actions", {}).get(token)


def make_plan_edit_menu_keyboard(token: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("수량 변경", callback_data=f"plan|editqty|{token}"),
            InlineKeyboardButton("일자 변경", callback_data=f"plan|editdate|{token}"),
        ],
        [
            InlineKeyboardButton("수량+일자 직접입력", callback_data=f"plan|customboth|{token}"),
        ],
        [
            InlineKeyboardButton("뒤로", callback_data="plan|refresh|none"),
        ],
    ])


def make_plan_qty_keyboard(token: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("500kg", callback_data=f"plan|qty|{token}|500"),
            InlineKeyboardButton("1,000kg", callback_data=f"plan|qty|{token}|1000"),
            InlineKeyboardButton("1,500kg", callback_data=f"plan|qty|{token}|1500"),
        ],
        [
            InlineKeyboardButton("2,000kg", callback_data=f"plan|qty|{token}|2000"),
            InlineKeyboardButton("3,000kg", callback_data=f"plan|qty|{token}|3000"),
            InlineKeyboardButton("5,000kg", callback_data=f"plan|qty|{token}|5000"),
        ],
        [
            InlineKeyboardButton("직접 입력", callback_data=f"plan|customqty|{token}"),
            InlineKeyboardButton("뒤로", callback_data=f"plan|edit|{token}"),
        ],
    ])


def make_plan_date_keyboard(token: str):
    today = datetime.now().date()
    d0 = today
    d1 = today + timedelta(days=1)
    d2 = today + timedelta(days=2)
    d3 = today + timedelta(days=3)
    d7 = today + timedelta(days=7)

    def label(d):
        return d.strftime("%m/%d")

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"오늘 {label(d0)}", callback_data=f"plan|date|{token}|{d0.strftime('%Y-%m-%d')}"),
            InlineKeyboardButton(f"내일 {label(d1)}", callback_data=f"plan|date|{token}|{d1.strftime('%Y-%m-%d')}"),
        ],
        [
            InlineKeyboardButton(f"모레 {label(d2)}", callback_data=f"plan|date|{token}|{d2.strftime('%Y-%m-%d')}"),
            InlineKeyboardButton(f"+3일 {label(d3)}", callback_data=f"plan|date|{token}|{d3.strftime('%Y-%m-%d')}"),
            InlineKeyboardButton(f"+7일 {label(d7)}", callback_data=f"plan|date|{token}|{d7.strftime('%Y-%m-%d')}"),
        ],
        [
            InlineKeyboardButton("직접 입력", callback_data=f"plan|customdate|{token}"),
            InlineKeyboardButton("뒤로", callback_data=f"plan|edit|{token}"),
        ],
    ])


def make_plan_delete_confirm_keyboard(token: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 취소 확정", callback_data=f"plan|confirmdel|{token}"),
            InlineKeyboardButton("돌아가기", callback_data="plan|refresh|none"),
        ]
    ])


def locate_plan_index(plans, plan):
    """
    버튼 생성 당시 저장한 index를 우선 사용하고, 파일이 정렬/수정된 경우 날짜+제품코드로 다시 찾습니다.
    """
    old_index = plan.get("index")
    old_date = normalize_plan_date(plan.get("production_date"))
    old_code = str(plan.get("product_code", "")).strip()

    if old_index in plans.index:
        row = plans.loc[old_index]
        row_date = normalize_plan_date(row["생산일"])
        row_code = str(row["제품코드"]).strip()

        if row_date == old_date and row_code == old_code:
            return old_index, None

    matched = plans[
        (plans["생산일"].apply(normalize_plan_date) == old_date)
        & (plans["제품코드"].astype(str).str.strip() == old_code)
    ].copy()

    if matched.empty:
        return None, "조건에 맞는 생산계획을 찾지 못했습니다. 다시 /plans 로 목록을 새로 열어주세요."

    if len(matched) > 1:
        return None, "같은 날짜/같은 제품 계획이 여러 개입니다. 엑셀에서 확인하거나 다시 /plans 로 새로고침해 주세요."

    return matched.index[0], None


def update_plan_fields(plan: dict, new_qty_kg=None, new_date=None):
    """
    생산계획의 수량과 생산일자를 수정합니다.
    new_qty_kg, new_date 둘 중 하나만 있어도 수정 가능하고, 둘 다 있으면 동시에 수정합니다.
    """
    plans = load_plans()

    if plans is None or plans.empty:
        return "수정할 생산계획이 없습니다."

    idx, err = locate_plan_index(plans, plan)

    if err:
        return err

    old_date = normalize_plan_date(plans.loc[idx, "생산일"])
    old_code = str(plans.loc[idx, "제품코드"]).strip()
    old_name = str(plans.loc[idx, "제품명"]).strip()
    old_qty = float(plans.loc[idx, "생산수량kg"])

    target_date = old_date
    target_qty = old_qty

    if new_date:
        target_date = normalize_plan_date(new_date)
        parsed_target_date = parse_plan_date(target_date)

        if parsed_target_date is None:
            return f"생산일자를 인식하지 못했습니다: {new_date}"

        if parsed_target_date < datetime.now().date():
            return (
                "지난 날짜로는 생산계획을 변경하지 않았습니다.\n"
                f"- 입력한 생산일: {target_date}"
            )

    if new_qty_kg is not None:
        try:
            target_qty = float(new_qty_kg)
        except Exception:
            return "수량을 숫자로 인식하지 못했습니다."

        if target_qty <= 0:
            return "수량은 0보다 커야 합니다."

    # 날짜를 바꿀 때 같은 날짜/같은 제품이 이미 있으면 중복 방지
    duplicate = plans[
        (plans.index != idx)
        & (plans["생산일"].apply(normalize_plan_date) == target_date)
        & (plans["제품코드"].astype(str).str.strip() == old_code)
    ].copy()

    if not duplicate.empty:
        dup_qty = duplicate["생산수량kg"].astype(float).sum()
        return (
            "같은 날짜에 같은 제품의 생산계획이 이미 있어 변경하지 않았습니다.\n"
            f"- 대상 날짜: {target_date}\n"
            f"- 제품: {old_name} [{old_code}]\n"
            f"- 기존 등록 수량: {fmt_num(dup_qty)}kg\n\n"
            "기존 계획을 먼저 취소하거나 수량 수정으로 처리해 주세요."
        )

    plans.loc[idx, "생산일"] = target_date
    plans.loc[idx, "생산수량kg"] = float(target_qty)
    plans.loc[idx, "등록시각"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    _improved_backup_known_data_files("before_save_plans")

    save_plans(plans)
    return (
        "생산계획을 변경했습니다.\n"
        f"- 제품코드: {old_code}\n"
        f"- 제품명: {old_name}\n"
        f"- 기존 생산일: {old_date}\n"
        f"- 변경 생산일: {target_date}\n"
        f"- 기존 수량: {fmt_num(old_qty)}kg\n"
        f"- 변경 수량: {fmt_num(target_qty)}kg"
    )


def get_plan_by_display_no(display_no: int):
    """
    /planlist 또는 생산계획 표에 보이는 번호 기준으로 생산계획 1개를 찾습니다.
    번호는 화면에 표시된 정렬 순서 기준입니다.
    """
    plans = load_plans()

    if plans is None or plans.empty:
        return None, "현재 등록된 생산계획이 없습니다."

    try:
        display_no = int(display_no)
    except Exception:
        return None, "번호를 숫자로 인식하지 못했습니다."

    if display_no <= 0:
        return None, "번호는 1 이상이어야 합니다."

    temp_plans = plans.copy()
    temp_plans["_원본index"] = temp_plans.index
    display_df = prepare_plans_for_display(temp_plans)

    if display_no > len(display_df):
        return None, f"{display_no}번 생산계획을 찾지 못했습니다. 현재 목록은 {len(display_df)}건입니다."

    row = display_df.iloc[display_no - 1]
    original_idx = int(row.get("_원본index", display_no - 1))

    plan = {
        "index": original_idx,
        "production_date": clean_plan_value(row.get("생산일"), ""),
        "product_code": clean_plan_value(row.get("제품코드"), ""),
        "product_name": clean_plan_value(row.get("제품명"), ""),
        "qty_kg": float(row.get("생산수량kg", 0)),
        "display_no": display_no,
    }

    return plan, None


def remove_date_expressions_for_qty(text: str):
    """
    날짜 숫자가 수량으로 잘못 잡히지 않도록 날짜 표현을 제거합니다.
    예: '6/18, 3톤' -> ', 3톤'
    """
    t = str(text or "")

    patterns = [
        r"\d{4}[-./]\d{1,2}[-./]\d{1,2}",
        r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일?",
        r"\d{1,2}\s*월\s*\d{1,2}\s*일?",
        r"\b\d{1,2}\s*/\s*\d{1,2}\b",
        r"\b\d{1,2}\s*-\s*\d{1,2}\b",
        r"오늘|내일|모레",
        r"\d+\s*일\s*(뒤|후)",
    ]

    for pattern in patterns:
        t = re.sub(pattern, " ", t)

    return re.sub(r"\s+", " ", t).strip()


def parse_quantity_for_command(text: str):
    """
    명령어용 수량 파서.
    날짜와 같이 입력된 경우 날짜 숫자를 제거한 뒤 수량을 찾습니다.
    """
    raw = str(text or "").strip()

    # 단위가 붙은 수량을 먼저 찾습니다.
    unit_matches = re.findall(
        r"(\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(톤|t|kg|키로|킬로)",
        raw,
        flags=re.IGNORECASE,
    )

    if unit_matches:
        qty_text, unit = unit_matches[-1]
        qty = float(qty_text.replace(",", ""))

        if unit.lower() in ["톤", "t"]:
            qty *= 1000

        return qty

    # 단위가 없으면 날짜 표현을 제거한 뒤 남은 숫자를 수량으로 봅니다.
    qty_area = remove_date_expressions_for_qty(raw)
    number_matches = re.findall(
        r"\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?",
        qty_area,
    )

    if not number_matches:
        return None

    qty = float(number_matches[-1].replace(",", ""))

    # 날짜의 일자 같은 작은 숫자가 잘못 수량으로 잡히는 것을 방지합니다.
    if qty <= 31 and any(x in raw for x in ["/", "월", "-", "오늘", "내일", "모레"]):
        return None

    return qty


def parse_plan_edit_command_text(text: str):
    """
    /수정 11, 6/18, 3톤
    수정 11 6월18일 3000kg
    /editplan 11, 6/18, 3톤
    형태를 파싱합니다.
    """
    raw = str(text or "").strip()

    raw = re.sub(r"^/(수정|editplan)\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^(수정|변경)\s*", "", raw, flags=re.IGNORECASE)
    raw = raw.strip()

    match_no = re.match(r"^(\d+)", raw)

    if not match_no:
        return None, None, None, "수정할 번호를 찾지 못했습니다. 예: /수정 11, 6/18, 3톤"

    display_no = int(match_no.group(1))
    rest = raw[match_no.end():].strip(" ,/")

    if not rest:
        return display_no, None, None, "변경할 생산일자 또는 수량을 입력해 주세요. 예: /수정 11, 6/18, 3톤"

    new_date = parse_plan_date_input(rest)
    new_qty = parse_quantity_for_command(rest)

    if not new_date and new_qty is None:
        return display_no, None, None, "생산일자 또는 수량을 인식하지 못했습니다. 예: /수정 11, 6/18, 3톤"

    return display_no, new_date, new_qty, None


def parse_plan_delete_command_text(text: str):
    """
    /취소 11
    /삭제 11
    취소 11
    /delplan 11
    형태를 파싱합니다.
    """
    raw = str(text or "").strip()
    raw = re.sub(r"^/(취소|삭제|delplan)\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^(취소|삭제)\s*", "", raw, flags=re.IGNORECASE)
    raw = raw.strip()

    match_no = re.match(r"^(\d+)", raw)

    if not match_no:
        return None, "취소할 번호를 찾지 못했습니다. 예: /취소 11"

    return int(match_no.group(1)), None
