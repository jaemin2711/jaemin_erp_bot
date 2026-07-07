from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

MEMORY_FILE = Path("data/ocr_product_memory.json")


def normalize_ocr_product_text(value) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKC", text).lower()

    remove_words = [
        "생산계획", "생산등록", "생산", "계획", "등록",
        "가능", "확인", "kg", "킬로", "키로", "톤", "일괄",
    ]

    for word in remove_words:
        text = text.replace(word, "")

    replacements = {
        "투불": "투뿔",
        "투쁠": "투뿔",
        "얼디메이트": "얼티메이트",
        "얼터메이트": "얼티메이트",
    }

    for src, dst in replacements.items():
        text = text.replace(src, dst)

    return re.sub(r"[^0-9a-zA-Z가-힣]", "", text)


def load_ocr_product_memory() -> dict:
    if not MEMORY_FILE.exists():
        return {"items": {}, "updated_at": ""}

    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    if not isinstance(data, dict):
        data = {}

    data.setdefault("items", {})
    data.setdefault("updated_at", "")
    return data


def save_ocr_product_memory(data: dict) -> None:
    MEMORY_FILE.parent.mkdir(exist_ok=True)
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    MEMORY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def remember_ocr_product(ocr_name, product_code, product_name, source="button", score=None) -> dict:
    ocr_raw = str(ocr_name or "").strip()
    code = str(product_code or "").strip()
    name = str(product_name or "").strip()
    key = normalize_ocr_product_text(ocr_raw)

    if not key or not code:
        return {}

    data = load_ocr_product_memory()
    items = data.setdefault("items", {})
    old = items.get(key, {})
    count = int(old.get("count", 0) or 0) + 1

    item = {
        "ocr_name": ocr_raw,
        "ocr_key": key,
        "product_code": code,
        "product_name": name,
        "source": source,
        "score": score,
        "count": count,
        "first_seen": old.get("first_seen") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    history = old.get("history", [])

    if not isinstance(history, list):
        history = []

    history.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ocr_name": ocr_raw,
        "product_code": code,
        "product_name": name,
        "source": source,
        "score": score,
    })

    item["history"] = history[-30:]
    items[key] = item
    save_ocr_product_memory(data)
    return item


def lookup_ocr_product_memory(ocr_name, min_similarity=0.92) -> dict | None:
    key = normalize_ocr_product_text(ocr_name)

    if not key:
        return None

    data = load_ocr_product_memory()
    items = data.get("items", {})

    if key in items:
        item = dict(items[key])
        item["match_type"] = "exact"
        item["similarity"] = 1.0
        return item

    best_item = None
    best_score = 0.0

    for saved_key, item in items.items():
        score = SequenceMatcher(None, key, saved_key).ratio()

        if score > best_score:
            best_score = score
            best_item = item

    if best_item and best_score >= min_similarity:
        item = dict(best_item)
        item["match_type"] = "similar"
        item["similarity"] = float(best_score)
        return item

    return None


def forget_ocr_product_memory(ocr_name) -> bool:
    key = normalize_ocr_product_text(ocr_name)

    if not key:
        return False

    data = load_ocr_product_memory()
    items = data.get("items", {})

    if key in items:
        items.pop(key, None)
        save_ocr_product_memory(data)
        return True

    target = str(ocr_name or "").strip()

    for saved_key, item in list(items.items()):
        if item.get("ocr_name") == target or item.get("product_name") == target or item.get("product_code") == target:
            items.pop(saved_key, None)
            save_ocr_product_memory(data)
            return True

    return False


def format_ocr_product_memory(limit=100) -> str:
    data = load_ocr_product_memory()
    items = list(data.get("items", {}).values())

    if not items:
        return (
            "현재 기억된 OCR 제품명 매칭이 없습니다.\n\n"
            "사전등록 예시:\n"
            "/ocradd 투불한우 => P10570\n"
            "/ocradd 트림토판10% => P실제제품코드"
        )

    items.sort(key=lambda x: x.get("last_seen", ""), reverse=True)

    lines = []
    lines.append("[OCR 제품명 기억 목록]")
    lines.append(f"총 {len(items)}건")
    lines.append("")

    for idx, item in enumerate(items[:limit], start=1):
        lines.append(
            f"{idx}. OCR: {item.get('ocr_name')} → "
            f"{item.get('product_name')} [{item.get('product_code')}] "
            f"/ 사용 {item.get('count', 0)}회 / 출처 {item.get('source', '-')} / 최근 {item.get('last_seen', '-')}"
        )

    if len(items) > limit:
        lines.append(f"... 외 {len(items) - limit}건")

    lines.append("")
    lines.append("사전등록: /ocradd OCR명 => 제품코드")
    lines.append("삭제: /ocrforget OCR명")
    return "\n".join(lines)
