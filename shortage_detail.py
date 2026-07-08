from bot_config import *
from plan_utils import clean_plan_value


def _shortage_detail_parse_plan_qty_kg(row):
    possible_qty_headers = [
        "주문량",
        "생산수량kg",
        "생산수량(kg)",
        "수량(kg)",
        "생산수량",
        "수량",
    ]

    for header in possible_qty_headers:
        if header not in row:
            continue

        raw_val = row.get(header)

        if raw_val is None:
            continue

        raw_val_str = str(raw_val).strip().lower()

        if not raw_val_str or raw_val_str in ["nan", "nat", "none", "null"]:
            continue

        match_qty = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(톤|t|kg|킬로|키로)?", raw_val_str)

        if match_qty:
            val = float(match_qty.group(1).replace(",", ""))
            unit = match_qty.group(2) if match_qty.group(2) else ""

            if "톤" in unit or unit == "t":
                val *= 1000

            if val > 0:
                return val

        try:
            val = float(raw_val_str.replace(",", ""))
            if val > 0:
                return val
        except Exception:
            pass

    return 0.0


def _shortage_detail_normalize_plan_df(plans_df):
    if plans_df is None or plans_df.empty:
        return plans_df

    df = plans_df.copy()
    date_col = "생산일" if "생산일" in df.columns else ("생산일자" if "생산일자" in df.columns else None)

    if not date_col:
        return df

    last_valid_date = datetime.now().strftime("%Y-%m-%d")
    updated_dates = []

    for _, row in df.iterrows():
        raw_date = str(row.get(date_col, "")).strip()

        if raw_date in ['"', '""', "〃", "위와 같음", "동일"]:
            updated_dates.append(last_valid_date)
            continue

        if raw_date and raw_date.lower() not in ["nan", "nat", "none", "null"]:
            last_valid_date = normalize_plan_date(raw_date.split(" ")[0])

        updated_dates.append(last_valid_date)

    df[date_col] = updated_dates
    df["_정렬일"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.sort_values(by=["_정렬일"], na_position="last").reset_index(drop=True)

    if date_col != "생산일":
        df["생산일"] = df[date_col]

    return df


def _shortage_detail_add_usage(usage_by_material, code, entry):
    code = str(code or "").strip()
    if not code:
        return

    if code not in usage_by_material:
        usage_by_material[code] = []

    usage_by_material[code].append(entry)


def _shortage_detail_format_usage_entries(entries, max_rows=20):
    if not entries:
        return ["    - 사용처 상세를 찾지 못했습니다."]

    lines = []
    total_qty_by_unit = {}

    for idx, entry in enumerate(entries[:max_rows], start=1):
        unit = entry.get("material_unit") or ""
        material_qty = float(entry.get("material_qty") or 0)
        total_qty_by_unit[unit] = total_qty_by_unit.get(unit, 0.0) + material_qty

        lines.append(
            f"    {idx}) {entry.get('production_date')} / "
            f"{entry.get('product_name')} [{entry.get('product_code')}] / "
            f"생산 {fmt_num(entry.get('product_qty_kg', 0))}kg → "
            f"자재 {fmt_num(material_qty)}{unit}"
        )

    if len(entries) > max_rows:
        lines.append(f"    ... 외 {len(entries) - max_rows}건")

    total_parts = [
        f"{fmt_num(qty)}{unit}"
        for unit, qty in total_qty_by_unit.items()
    ]

    if total_parts:
        lines.append(f"    합계 사용 예정: {', '.join(total_parts)}")

    return lines


def check_all_remembered_plans():
    """
    현재 기억된 전체 생산계획을 순서대로 확인하고,
    부족 자재별로 실제로 더 채워야 하는 총 부족량을 계산합니다.

    핵심 계산식:
        총 부족량 = 전체 생산계획 필요량 합계 - 보유 가용재고

    기존 '최대 부족량'은 특정 생산계획 판정 순간의 부족분이라서
    전체 발주/구매 판단에는 혼동이 생길 수 있어 출력하지 않습니다.
    """

    def _safe_float(value, default=0.0):
        try:
            if value is None:
                return default
            text = str(value).replace(",", "").strip()
            if text == "" or text.lower() in ["nan", "none", "null", "nat"]:
                return default
            return float(text)
        except Exception:
            return default

    def _get_original_available_qty(shortage_item):
        """
        build_result() 결과에서 원래 보유 가용재고를 가져옵니다.
        우선순위:
        1) 원가용재고가 있으면 그대로 사용
        2) 없으면 가용재고 + 계획차감수량으로 원래 재고를 복원
        3) 둘 다 없으면 가용재고만 사용
        """
        if "원가용재고" in shortage_item:
            return _safe_float(shortage_item.get("원가용재고"), 0.0)

        available_now = _safe_float(shortage_item.get("가용재고"), 0.0)
        planned_deduction = _safe_float(shortage_item.get("계획차감수량"), 0.0)
        return available_now + planned_deduction

    try:
        plans_df = load_plans()
    except Exception as e:
        return f"❌ 생산계획 파일을 읽어오는 중 오류가 발생했습니다: {str(e)}"

    if plans_df is None or plans_df.empty:
        return "현재 등록된 생산계획이 없거나 파일이 비어 있습니다."

    plans_df = _shortage_detail_normalize_plan_df(plans_df)

    lines = []
    lines.append("=" * 50)
    lines.append("[현재 기억된 생산계획 전체 가능여부 확인]")
    lines.append(f"조회시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("개선: 부족 자재별 사용처와 실제 총 부족량 표시")
    lines.append("=" * 50)

    running_extra_consumption = {}
    usage_by_material = {}
    shortage_summary = {}

    for idx, row in plans_df.iterrows():
        p_date = str(row.get("생산일", row.get("생산일자", ""))).split(" ")[0]
        p_key = str(row.get("제품코드", row.get("제품명", ""))).strip()
        p_qty = _shortage_detail_parse_plan_qty_kg(row)

        if not p_key:
            lines.append(f"[{p_date}] 제품코드/제품명이 비어 있어 건너뜀")
            lines.append("-" * 50)
            continue

        product_info = get_product_info(p_key)
        if not product_info:
            lines.append(f"[{p_date}] {p_key} {fmt_num(p_qty)}kg -> ❌ 배합비 없음")
            lines.append("-" * 50)
            continue

        p_name = product_info.get("제품명", p_key)
        p_code = product_info.get("제품코드", p_key)

        # 반드시 제품코드로 BOM 조회
        lookup_key = p_code or p_key or p_name

        result_dict = build_result(
            lookup_key,
            p_qty,
            extra_consumption=running_extra_consumption,)

        detail_list = result_dict.get("상세", []) or []
        shortage_list = result_dict.get("부족", []) or []

        current_usage_by_material = {}
        for mat_item in detail_list:
            m_code = str(mat_item.get("자재코드", "")).strip()
            m_name = str(mat_item.get("자재명", "")).strip()
            m_req = _safe_float(mat_item.get("필요수량", 0), 0.0)
            m_unit = str(mat_item.get("배합단위", "") or "")

            if not m_code:
                continue

            matched_product_code = result_dict.get("제품코드", p_code)
            matched_product_name = result_dict.get("제품명", p_name)

            entry = {
                "production_date": p_date,
                "product_code": matched_product_code,
                "product_name": matched_product_name,
                ...
            }

            if m_code not in current_usage_by_material:
                current_usage_by_material[m_code] = []
            current_usage_by_material[m_code].append(entry)

        if shortage_list:
            status_text = "❌ 생산 불가능 (자재 부족)"
            short_mats = [
                f"{m.get('자재명')}({fmt_num(m.get('부족수량', 0))}{m.get('배합단위', '')} 쇼트)"
                for m in shortage_list
            ]
            detail_text = f"└ 부족내역: {', '.join(short_mats)}"
        else:
            status_text = "✅ 생산 가능 (자재 여유)"
            detail_text = "└ 원/부자재 가용 재고 충족"

        lines.append(f"[{p_date}] {p_name} ({fmt_num(p_qty)}kg) -> {status_text}")
        lines.append(detail_text)

        if shortage_list:
            lines.append("└ 부족 자재 사용처")

            for shortage in shortage_list:
                m_code = str(shortage.get("자재코드", "")).strip()
                m_name = str(shortage.get("자재명", "")).strip()
                m_unit = str(shortage.get("배합단위", "") or "")
                stock_unit = str(shortage.get("재고단위", m_unit) or m_unit)
                shortage_qty = _safe_float(shortage.get("부족수량", 0), 0.0)
                original_available_qty = _get_original_available_qty(shortage)

                entries_until_now = []
                entries_until_now.extend(usage_by_material.get(m_code, []))
                entries_until_now.extend(current_usage_by_material.get(m_code, []))
                total_usage_until_now = sum(
                    _safe_float(x.get("material_qty", 0), 0.0) for x in entries_until_now
                )
                current_total_shortage = max(total_usage_until_now - original_available_qty, 0.0)

                if m_code not in shortage_summary:
                    shortage_summary[m_code] = {
                        "material_code": m_code,
                        "material_name": m_name,
                        "material_unit": m_unit,
                        "available_stock_qty": original_available_qty,
                        "available_stock_unit": stock_unit,
                        "first_shortage_date": p_date,
                        "first_shortage_product": p_name,
                    }
                else:
                    # 같은 자재는 보통 원가용재고가 동일하지만,
                    # 앞선 값이 비어 있고 뒤에서 값이 잡히는 경우 보정합니다.
                    old_stock = _safe_float(shortage_summary[m_code].get("available_stock_qty", 0), 0.0)
                    if old_stock <= 0 and original_available_qty > 0:
                        shortage_summary[m_code]["available_stock_qty"] = original_available_qty
                    if not shortage_summary[m_code].get("available_stock_unit"):
                        shortage_summary[m_code]["available_stock_unit"] = stock_unit

                lines.append(
                    f" - {m_name} [{m_code}] / 이번 판정 부족 {fmt_num(shortage_qty)}{m_unit}"
                )
                lines.append(
                    f"   보유 가용재고 {fmt_num(original_available_qty)}{stock_unit} / "
                    f"누적 필요량 {fmt_num(total_usage_until_now)}{m_unit} / "
                    f"현재 기준 부족량 {fmt_num(current_total_shortage)}{m_unit}"
                )

                for usage_line in _shortage_detail_format_usage_entries(entries_until_now, max_rows=8):
                    lines.append(usage_line)

        for mat_item in detail_list:
            m_code = str(mat_item.get("자재코드", "")).strip()
            m_req = _safe_float(mat_item.get("필요수량", 0), 0.0)

            if not m_code:
                continue

            running_extra_consumption[m_code] = running_extra_consumption.get(m_code, 0.0) + m_req

            for entry in current_usage_by_material.get(m_code, []):
                _shortage_detail_add_usage(usage_by_material, m_code, entry)

        lines.append("-" * 50)

    if shortage_summary:
        lines.append("")
        lines.append("=" * 50)
        lines.append("[부족 자재별 사용처 요약]")
        lines.append("전체 생산계획 필요량에서 보유 가용재고를 뺀 실제 총 부족량입니다.")
        lines.append("=" * 50)

        summary_rows = []
        for m_code, info in shortage_summary.items():
            entries = usage_by_material.get(m_code, [])
            total_usage = sum(_safe_float(x.get("material_qty", 0), 0.0) for x in entries)
            available_stock = _safe_float(info.get("available_stock_qty", 0), 0.0)
            total_shortage = max(total_usage - available_stock, 0.0)

            summary_rows.append({
                "material_code": m_code,
                "material_name": info.get("material_name"),
                "unit": info.get("material_unit", ""),
                "stock_unit": info.get("available_stock_unit", info.get("material_unit", "")),
                "first_shortage_date": info.get("first_shortage_date"),
                "first_shortage_product": info.get("first_shortage_product"),
                "available_stock": available_stock,
                "total_usage": total_usage,
                "total_shortage": total_shortage,
                "entries": entries,
            })

        # 실제 채워야 할 부족량이 큰 자재부터 표시합니다.
        summary_rows.sort(key=lambda x: x["total_shortage"], reverse=True)

        for row in summary_rows:
            lines.append(f"■ {row['material_name']} [{row['material_code']}]")
            lines.append(
                f" - 최초 부족 발생: {row['first_shortage_date']} / {row['first_shortage_product']}"
            )
            lines.append(f" - 보유 가용재고: {fmt_num(row['available_stock'])}{row['stock_unit']}")
            lines.append(f" - 전체 생산계획 필요량: {fmt_num(row['total_usage'])}{row['unit']}")
            lines.append(f" - 총 부족량: {fmt_num(row['total_shortage'])}{row['unit']}")
            lines.append(" - 사용처:")

            for usage_line in _shortage_detail_format_usage_entries(row["entries"], max_rows=30):
                lines.append(usage_line)

            lines.append("")
    else:
        lines.append("")
        lines.append("[부족 자재별 사용처 요약]")
        lines.append("현재 생산계획 기준 부족 자재가 없습니다.")

    return "\n".join(lines).strip()



def _is_real_production_shortage(answer: str) -> bool:
    """
    check_production() 결과 본문을 기준으로 실제 생산 불가능 여부를 판단합니다.

    기존 문제:
    - answer 안에 "부족"이라는 단어만 있어도 불가능으로 처리함.
    - 재고무시 자재 안내문인 "부족 판단에서 제외" 때문에
      본문은 생산 가능인데도 상단 헤더가 생산 불가능으로 붙는 문제가 있었음.

    판단 우선순위:
    1) 본문에 "판정: 생산 가능"이 있으면 가능으로 확정
    2) 본문에 "판정: 생산 불가능/불가"가 있으면 불가능
    3) 명확한 부족 수량/부족 내역이 있을 때만 불가능
    """
    text = str(answer or "")
    compact = re.sub(r"\s+", "", text)

    # 가능 판정을 최우선으로 봅니다.
    # 아래쪽에 "부족 판단에서 제외" 같은 문구가 있어도 여기서 가능 처리됩니다.
    possible_markers = [
        "판정:생산가능",
        "판정：생산가능",
        "[생산가능판정]",
        "생산가능판정",
        "요청수량생산가능",
        "생산가능합니다",
    ]
    if any(marker in compact for marker in possible_markers):
        return False

    impossible_markers = [
        "판정:생산불가능",
        "판정：생산불가능",
        "판정:생산불가",
        "판정：생산불가",
        "[생산불가능판정",
        "생산불가능판정",
        "생산불가판정",
        "생산불가능합니다",
        "생산불가합니다",
    ]
    if any(marker in compact for marker in impossible_markers):
        return True

    # 마지막 보조 판단:
    # 단순히 "부족"이라는 단어가 아니라, 실제 부족 내역/부족 수량 문구가 있는 경우만 불가능 처리.
    # "부족 판단에서 제외"는 여기에서 걸리지 않게 함.
    shortage_patterns = [
        r"부족\s*수량\s*[:：]\s*(?!0(?:\.0+)?\s*(?:kg|g|톤|t)?\b)",
        r"총\s*부족\s*량\s*[:：]\s*(?!0(?:\.0+)?\s*(?:kg|g|톤|t)?\b)",
        r"부족\s*내역\s*[:：]",
        r"부족\s*자재\s*[:：]",
        r"자재\s*부족\s*[:：]",
    ]
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in shortage_patterns)
