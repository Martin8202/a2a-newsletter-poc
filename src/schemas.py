"""draft.json 結構驗證與 AI 輸出的 JSON 擷取（SPEC §5.1、§8.3）。"""
import json
import re
from datetime import date

SECTION_PREFIX = {"onprem": "L", "industry": "I"}
SIGNAL_TYPES = {"community", "media", "pain_point"}
SOURCE_TYPES = {"original", "discussion", "report", "tw_translation"}
ONPREM_KEYS = ("hardware", "inference_efficiency", "license", "compliance")
ITEM_REQUIRED = ("id", "section", "title", "summary", "published_date", "signals", "sources", "heat")
HEAT_KINDS = {"hn", "reddit", "hf_trending", "github", "media"}


def extract_json(text):
    """解析 AI 輸出：先整段解析，失敗則找第一個完整的 JSON 物件或陣列。找不到拋 ValueError。"""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for m in re.finditer(r"[\[{]", text):
        try:
            return decoder.raw_decode(text, m.start())[0]
        except json.JSONDecodeError:
            continue
    raise ValueError("輸出中找不到合法的 JSON")


def _is_date(value):
    try:
        date.fromisoformat(value)
        return isinstance(value, str) and len(value) == 10
    except (TypeError, ValueError):
        return False


def _is_url(value):
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _check_links(links, where, allowed_types, label_key, errors):
    if not isinstance(links, list) or not links:
        errors.append(f"{where}: 必須是非空陣列")
        return
    for i, link in enumerate(links):
        p = f"{where}[{i}]"
        if not isinstance(link, dict):
            errors.append(f"{p}: 必須是物件")
            continue
        if link.get("type") not in allowed_types:
            errors.append(f"{p}.type 不合法: {link.get('type')!r}")
        if not _is_url(link.get("url")):
            errors.append(f"{p}.url 不是 http(s) 網址")
        if not link.get(label_key):
            errors.append(f"{p}.{label_key} 不可為空")


def _check_heat(heat, where, errors):
    if not isinstance(heat, list) or not heat:
        errors.append(f"{where}.heat: 必須是非空陣列")
        return
    for i, h in enumerate(heat):
        p = f"{where}.heat[{i}]"
        if not isinstance(h, dict):
            errors.append(f"{p}: 必須是物件")
            continue
        if h.get("kind") not in HEAT_KINDS:
            errors.append(f"{p}.kind 不合法: {h.get('kind')!r}")
        v = h.get("value")
        if v is not None and not (isinstance(v, int) and not isinstance(v, bool) and v >= 0):
            errors.append(f"{p}.value 必須是非負整數或 null")
        if not _is_url(h.get("url")):
            errors.append(f"{p}.url 不是 http(s) 網址")


def _check_key_points(points, where, errors):
    """key_points 為選填（舊版草稿沒有）；有的話每點都要有文字、原句與 http(s) 連結（SPEC §5.1）。"""
    if not isinstance(points, list):
        errors.append(f"{where}.key_points 必須是陣列")
        return
    for i, p in enumerate(points):
        pp = f"{where}.key_points[{i}]"
        if not isinstance(p, dict):
            errors.append(f"{pp}: 必須是物件")
            continue
        for k in ("text", "quote"):
            if not isinstance(p.get(k), str) or not p[k].strip():
                errors.append(f"{pp}.{k} 不可為空")
        if not _is_url(p.get("url")):
            errors.append(f"{pp}.url 不是 http(s) 網址")


def validate_draft(draft):
    """回傳錯誤訊息清單；空清單代表通過。不拋例外，方便寫進日誌。"""
    errors = []
    if not isinstance(draft, dict):
        return ["最外層必須是 JSON 物件"]

    period = draft.get("period")
    if not isinstance(period, dict) or not (_is_date(period.get("start")) and _is_date(period.get("end"))):
        errors.append("period.start / period.end 必須是 YYYY-MM-DD")

    items = draft.get("items")
    if not isinstance(items, list):
        return errors + ["items 必須是陣列"]

    ids = set()
    for n, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"items[{n}]: 必須是物件")
            continue
        where = f"items[{n}]({item.get('id', '?')})"
        missing = [k for k in ITEM_REQUIRED if k not in item]
        if missing:
            errors.append(f"{where}: 缺少欄位 {missing}")

        section, item_id = item.get("section"), item.get("id")
        if section not in SECTION_PREFIX:
            errors.append(f"{where}.section 不合法: {section!r}")
        elif not (isinstance(item_id, str) and re.fullmatch(SECTION_PREFIX[section] + r"\d+", item_id)):
            errors.append(f"{where}.id 必須是 {SECTION_PREFIX[section]}+數字")
        if item_id in ids:
            errors.append(f"{where}.id 重複")
        ids.add(item_id)

        for key in ("title", "summary"):
            if key in item and not item[key]:
                errors.append(f"{where}.{key} 不可為空")
        if "published_date" in item and not _is_date(item["published_date"]):
            errors.append(f"{where}.published_date 必須是 YYYY-MM-DD")

        if section == "onprem":
            if not item.get("why_hot"):
                errors.append(f"{where}.why_hot 不可為空")
            value = item.get("onprem_value")
            if not isinstance(value, dict) or any(not value.get(k) for k in ONPREM_KEYS):
                errors.append(f"{where}.onprem_value 必須含 {list(ONPREM_KEYS)} 且不可為空")

        if "signals" in item:
            _check_links(item["signals"], f"{where}.signals", SIGNAL_TYPES, "evidence", errors)
        if "heat" in item:
            _check_heat(item["heat"], where, errors)
        if "key_points" in item:
            _check_key_points(item["key_points"], where, errors)
        if "sources" in item:
            _check_links(item["sources"], f"{where}.sources", SOURCE_TYPES, "label", errors)

    top3 = draft.get("top3")
    if not isinstance(top3, list):
        errors.append("top3 必須是陣列")
    else:
        for i, point in enumerate(top3):
            if not isinstance(point, dict) or not point.get("text"):
                errors.append(f"top3[{i}].text 不可為空")
                continue
            related = point.get("related_ids")
            if not isinstance(related, list) or not related:
                errors.append(f"top3[{i}].related_ids 必須是非空陣列")
            else:
                unknown = [r for r in related if r not in ids]
                if unknown:
                    errors.append(f"top3[{i}].related_ids 指向不存在的項目: {unknown}")

    return errors
