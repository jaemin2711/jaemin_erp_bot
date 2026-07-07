from __future__ import annotations

import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path

CONFIG_FILE = Path("data/force_register_mode.json")


def parse_force_date(value) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None

    compact = text.replace(" ", "")
    today = datetime.now().date()

    if compact == "오늘":
        return today.strftime("%Y-%m-%d")
    if compact == "내일":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if compact == "모레":
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    patterns = [
        (r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", "ymd"),
        (r"(\d{1,2})[-./](\d{1,2})", "md"),
        (r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일?", "kor"),
    ]

    for pattern, mode in patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        try:
            if mode == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif mode == "md":
                y, mo, d = today.year, int(m.group(1)), int(m.group(2))
            else:
                y = int(m.group(1)) if m.group(1) else today.year
                mo, d = int(m.group(2)), int(m.group(3))
            return date(y, mo, d).strftime("%Y-%m-%d")
        except Exception:
            return None

    return None


def load_force_config() -> dict:
    if not CONFIG_FILE.exists():
        return {"global_force": False, "force_dates": [], "force_ranges": [], "updated_at": ""}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data.setdefault("global_force", False)
    data.setdefault("force_dates", [])
    data.setdefault("force_ranges", [])
    data.setdefault("updated_at", "")
    return data


def save_force_config(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(exist_ok=True)
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def set_global_force(enabled: bool) -> str:
    data = load_force_config()
    data["global_force"] = bool(enabled)
    save_force_config(data)
    return "✅ 전체 강제등록 모드를 켰습니다." if enabled else "✅ 전체 강제등록 모드를 껐습니다."


def enable_force_date(production_date: str) -> str:
    target = parse_force_date(production_date)
    if not target:
        return "❌ 날짜를 인식하지 못했습니다. 예: 6/20 강제등록 켜"
    data = load_force_config()
    dates = set(data.get("force_dates", []))
    dates.add(target)
    data["force_dates"] = sorted(dates)
    save_force_config(data)
    return f"✅ {target} 강제등록을 켰습니다."


def disable_force_date(production_date: str) -> str:
    target = parse_force_date(production_date)
    if not target:
        return "❌ 날짜를 인식하지 못했습니다. 예: 6/20 강제등록 꺼"
    data = load_force_config()
    dates = set(data.get("force_dates", []))
    dates.discard(target)
    data["force_dates"] = sorted(dates)
    save_force_config(data)
    return f"✅ {target} 강제등록을 껐습니다."


def enable_force_range(start_date: str, end_date: str) -> str:
    start = parse_force_date(start_date)
    end = parse_force_date(end_date)
    if not start or not end:
        return "❌ 기간 날짜를 인식하지 못했습니다. 예: 6/20~6/25 강제등록 켜"
    if start > end:
        start, end = end, start
    data = load_force_config()
    ranges = data.get("force_ranges", [])
    item = {"start": start, "end": end}
    if item not in ranges:
        ranges.append(item)
    ranges.sort(key=lambda x: (x.get("start", ""), x.get("end", "")))
    data["force_ranges"] = ranges
    save_force_config(data)
    return f"✅ {start} ~ {end} 강제 기간등록을 켰습니다."


def disable_force_range(start_date: str, end_date: str) -> str:
    start = parse_force_date(start_date)
    end = parse_force_date(end_date)
    if not start or not end:
        return "❌ 기간 날짜를 인식하지 못했습니다. 예: 6/20~6/25 강제등록 꺼"
    if start > end:
        start, end = end, start
    data = load_force_config()
    data["force_ranges"] = [x for x in data.get("force_ranges", []) if not (x.get("start") == start and x.get("end") == end)]
    save_force_config(data)
    return f"✅ {start} ~ {end} 강제 기간등록을 껐습니다."


def is_force_enabled_for_date(production_date) -> bool:
    target = parse_force_date(production_date)
    if not target:
        return False
    data = load_force_config()
    if data.get("global_force"):
        return True
    if target in set(data.get("force_dates", [])):
        return True
    for item in data.get("force_ranges", []):
        start = item.get("start")
        end = item.get("end")
        if start and end and start <= target <= end:
            return True
    return False


def get_force_mode_status_text() -> str:
    data = load_force_config()
    lines = ["[강제등록 모드 상태]", f"전체 강제등록: {'ON' if data.get('global_force') else 'OFF'}", ""]
    dates = data.get("force_dates", [])
    ranges = data.get("force_ranges", [])
    lines.append("[날짜별 강제등록]")
    lines.extend([f"- {d}" for d in dates] if dates else ["- 없음"])
    lines.append("")
    lines.append("[기간 강제등록]")
    lines.extend([f"- {x.get('start')} ~ {x.get('end')}" for x in ranges] if ranges else ["- 없음"])
    if data.get("updated_at"):
        lines.append("")
        lines.append(f"마지막 변경: {data.get('updated_at')}")
    lines.append("")
    lines.append("예시:")
    lines.append("- 강제등록 켜")
    lines.append("- 강제등록 꺼")
    lines.append("- 6/20 강제등록 켜")
    lines.append("- 6/20 강제등록 꺼")
    lines.append("- 6/20~6/25 강제등록 켜")
    lines.append("- 강제등록 상태")
    return "\n".join(lines)


def apply_force_mode_command(text: str) -> str | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    compact = raw.replace(" ", "").lower()

    if compact in ["강제등록상태", "강제모드상태", "강제기간등록상태", "/forcestatus", "/forcemode"] or ("강제등록" in compact and "상태" in compact):
        return get_force_mode_status_text()

    has_switch = any(x in compact for x in ["켜", "on", "꺼", "off"])
    has_mode_word = any(x in compact for x in ["강제모드", "강제등록모드", "강제기간등록", "강제등록"])
    if not has_switch or not has_mode_word:
        return None

    enabled = ("켜" in compact) or ("on" in compact)

    range_match = re.search(
        r"((?:\d{4}[-./])?\d{1,2}[-./]\d{1,2}|\d{1,2}\s*월\s*\d{1,2}\s*일?)\s*(?:~|부터|\s-\s)\s*((?:\d{4}[-./])?\d{1,2}[-./]\d{1,2}|\d{1,2}\s*월\s*\d{1,2}\s*일?)",
        raw,
    )
    if range_match:
        return enable_force_range(range_match.group(1), range_match.group(2)) if enabled else disable_force_range(range_match.group(1), range_match.group(2))

    date_match = re.search(r"((?:\d{4}[-./])?\d{1,2}[-./]\d{1,2}|\d{1,2}\s*월\s*\d{1,2}\s*일?)", raw)
    if date_match:
        return enable_force_date(date_match.group(1)) if enabled else disable_force_date(date_match.group(1))

    return set_global_force(enabled)
