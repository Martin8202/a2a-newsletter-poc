"""依查核結果做欄位層級處理、重複判斷、熱度門檻與精選（SPEC §6.3–§6.6）。"""
import copy
import fnmatch
import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit

from storage import failure

CORE = ("source_reachable", "event_supported", "in_date_range")
NOT_STATED = "來源未載明"
DEFAULT_CORRECTION = {"max_per_item": 3, "fields": [
    "title", "summary", "key_points", "published_date", "onprem_value.hardware",
    "onprem_value.inference_efficiency", "onprem_value.license", "onprem_value.compliance"]}
CORE_FIELDS = ("title", "summary", "published_date")
CONTENT_ACTIONS = ("corrected", "removed_unsupported", "not_stated")
KP = re.compile(r"key_points\[(\d+)\]$")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


def heat_rank(item):
    """熱度排序鍵（越大越熱，SPEC §6.4）：heat_metrics 分數加總，同分比社群數字最大值。"""
    ms = item.get("heat_metrics") or []
    return sum(m.get("score", 0) for m in ms), max([m.get("peak", 0) for m in ms] or [0])


def _recent_hn(item, lookback_days):
    """是否有建立於 lookback_days 內、題材相符的 HN 討論串（較早題材近期仍有社群熱議，SPEC §4.1）。"""
    return any(m.get("kind") == "hn" and m.get("ok") is True and not m.get("mismatch")
               and (m.get("age_days") or 1e9) <= lookback_days
               for m in item.get("heat_metrics") or [])


def _date_in_quote(d, quote):
    """原句中是否出現這個日期（ISO、斜線、中文、英文月份等常見寫法）。
    允許原句只有月日（如 GitHub 的「19 Oct」）：年份由呼叫端「必須落在期間內」的檢查保證。"""
    m = MONTHS[d.month - 1]
    forms = [d.isoformat(), f"{d.year}/{d.month}/{d.day}", f"{d.year}/{d.month:02}/{d.day:02}",
             f"{d.year}.{d.month:02}.{d.day:02}", f"{d.month}月{d.day}日",
             f"{m} {d.day}", f"{m[:3]} {d.day}", f"{d.day} {m}", f"{d.day} {m[:3]}"]
    return any(f in quote for f in forms)


def _target(item, field):
    """回傳 (容器, 鍵) 讓呼叫端讀寫該欄位文字；找不到回傳 (None, None)。"""
    m = KP.match(field)
    if m:
        kps = item.get("key_points") or []
        i = int(m[1])
        return (kps[i], "text") if i < len(kps) and isinstance(kps[i], dict) else (None, None)
    holder, _, key = field.rpartition(".")
    box = item.get(holder) if holder else item
    return (box, key) if isinstance(box, dict) and isinstance(box.get(key), str) else (None, None)


def _correctable(field, cfg):
    return field in cfg["fields"] or ("key_points" in cfg["fields"] and KP.match(field) is not None)


def apply_fields(item, review, cfg, period):
    """欄位層級處理（SPEC §6.5）。不修改傳入的 item。
    回傳 (新 item, edits, error, date_fixed)；error 為 None 或 (failed_check, 原因)。"""
    fields = review.get("fields") or []
    if not isinstance(fields, list) or not all(isinstance(f, dict) for f in fields):
        return None, [], ("correction_rejected", "fields 格式錯誤"), False
    new = copy.deepcopy(item)
    links = ({l["url"] for l in item["sources"] + item.get("signals", [])}
             | {k.get("url") for k in item.get("key_points") or [] if isinstance(k, dict)})
    edits, drop_kp, n_corr, date_fixed = [], set(), 0, False

    for n, f in enumerate(fields, 1):
        field, verdict = f.get("field") or "", f.get("verdict")
        if verdict not in ("unsupported", "contradicted"):
            continue  # 查核者多列了「有依據」的欄位，忽略
        if field == "why_hot" and "why_hot" in new:  # why_hot 不校正，有問題就不顯示
            edits.append({"action": "removed_unsupported", "field": field, "wrong": new.pop("why_hot"),
                          "reason": f.get("reason", "")})
            continue
        if verdict == "unsupported":
            if field in CORE_FIELDS:
                # 嚴格：查核者的逐欄判定比 core 總結可靠（評估集離線重算：信任 core 會讓誤留從 0–1 則增加到 2–9 則）
                flag = "in_date_range" if field == "published_date" else "event_supported"
                return None, [], (flag, f"核心欄位無依據：{field}（{f.get('reason', '')}）"), False
            m = KP.match(field)
            if m:
                box, _ = _target(new, field)
                if box is None:
                    return None, [], ("correction_rejected", f"第 {n} 筆：{field} 不存在"), False
                drop_kp.add(int(m[1]))
                edits.append({"action": "removed_unsupported", "field": field, "wrong": box["text"],
                              "reason": f.get("reason", "")})
            elif field.startswith("onprem_value."):
                box, key = _target(new, field)
                if box is not None and box[key] not in (NOT_STATED, "不適用"):
                    edits.append({"action": "not_stated", "field": field, "wrong": box[key],
                                  "reason": f.get("reason", "")})
                    box[key] = NOT_STATED
            continue  # 其他欄位（如 signals）不顯示，忽略

        # contradicted：機械驗證後校正（驗證失敗 → 整則剔除）
        n_corr += 1
        wrong, correct, quote, url = (f.get(k) for k in ("wrong", "correct", "quote", "url"))
        if n_corr > cfg["max_per_item"]:
            return None, [], ("correction_rejected", f"校正超過 {cfg['max_per_item']} 筆"), False
        if not all(isinstance(v, str) for v in (wrong, correct, quote, url)):
            return None, [], ("correction_rejected", f"第 {n} 筆校正缺少 wrong / correct / quote / url"), False
        if not _correctable(field, cfg):
            return None, [], ("correction_rejected", f"第 {n} 筆：{field} 不可校正"), False
        if not quote.strip() or url not in links:
            return None, [], ("correction_rejected", f"第 {n} 筆：缺少原句或連結不屬於本則"), False
        if field == "published_date":
            try:
                d = date.fromisoformat(correct)
            except ValueError:
                return None, [], ("correction_rejected", f"第 {n} 筆：日期格式錯誤 {correct!r}"), False
            if not period["start"] <= correct <= period["end"]:
                return None, [], ("correction_rejected", f"第 {n} 筆：校正後日期 {correct} 不在期間內"), False
            if not _date_in_quote(d, quote):
                return None, [], ("correction_rejected", f"第 {n} 筆：原句中找不到日期 {correct}"), False
            new["published_date"], date_fixed = correct, True
        else:
            box, key = _target(new, field)
            if box is None:
                return None, [], ("correction_rejected", f"第 {n} 筆：{field} 不存在"), False
            if not wrong or box[key].count(wrong) != 1:
                return None, [], ("correction_rejected", f"第 {n} 筆：錯值在 {field} 中不是恰好出現 1 次"), False
            if not correct or correct not in quote:
                return None, [], ("correction_rejected", f"第 {n} 筆：對值不在原句中"), False
            box[key] = box[key].replace(wrong, correct)
        edits.append({"action": "corrected", "field": field, "wrong": wrong, "correct": correct,
                      "quote": quote, "url": url})

    if drop_kp:
        new["key_points"] = [k for i, k in enumerate(new["key_points"]) if i not in drop_kp]
    metrics = new.get("heat_metrics") or []
    for h in review.get("heat_links") or []:
        idx = h.get("index") if isinstance(h, dict) else None
        if isinstance(idx, int) and 0 <= idx < len(metrics) and h.get("match") is False:
            metrics[idx].update(score=0, peak=0, mismatch=True)
            edits.append({"action": "heat_mismatch", "field": f"heat[{idx}]", "reason": h.get("reason", "")})
    return new, edits, None, date_fixed


def _norm_url(url):
    p = urlsplit(url)
    host = (p.hostname or "").lower().removeprefix("www.")
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not fnmatch.fnmatch(k, "utm_*")])
    return host + p.path.rstrip("/") + (f"?{query}" if query else "")


def dedupe(items):
    """共用相同來源網址的視為重複，保留熱度高者（SPEC §6.6）。回傳 (保留, [(被剔除項目, 保留者 id)])。"""
    seen, keep_ids, dups = {}, set(), []
    for it in sorted(items, key=heat_rank, reverse=True):
        urls = {_norm_url(s["url"]) for s in it["sources"]}
        hit = next((seen[u] for u in urls if u in seen), None)
        if hit:
            dups.append((it, hit))
            continue
        seen.update({u: it["id"] for u in urls})
        keep_ids.add(it["id"])
    return [i for i in items if i["id"] in keep_ids], dups


def describe_edit(e):
    if e["action"] == "corrected":
        return f"{e['field']}：{e['wrong']} → {e['correct']}"
    if e["action"] == "heat_mismatch":
        return f"{e['field']}：題材不符，計 0 分（{e.get('reason', '')}）"
    return f"{e['field']}：{'改為來源未載明' if e['action'] == 'not_stated' else '已移除'}（{e.get('reason', '')}）"


def apply_review(draft, review, run_date, min_passed=3, collected=None, keep=None, correction=None,
                 min_heat_score=0, lookback_days=None):
    """回傳 (final, failures)。final 含 items、top3、insufficient、stats、decisions（SPEC §5.5）。"""
    cfg = correction or DEFAULT_CORRECTION
    by_id = {r.get("id"): r for r in review.get("items", []) if isinstance(r, dict)}
    errors = review.get("errors") or {}
    fails, decisions, kept = [], {}, []

    def drop(item, checks, issues, stage="review"):
        fails.append(failure(run_date, "review", item["id"], item["title"], checks, issues,
                             [s["url"] for s in item["sources"]]))
        decisions[item["id"]] = {"status": "dropped", "stage": stage, "reasons": checks}

    for item in draft["items"]:
        r = by_id.get(item["id"])
        if r is None:
            drop(item, ["not_reviewed"], [errors.get(item["id"], "未查核")])
            continue
        core = r.get("core") if isinstance(r.get("core"), dict) else {}
        failed = [k for k in CORE if core.get(k) is not True]
        issues = [str(x) for x in r.get("issues") or []]
        if "source_reachable" in failed or "event_supported" in failed:
            drop(item, failed, issues or ["查核者未說明原因"])
            continue
        new, edits, err, date_fixed = apply_fields(item, r, cfg, draft["period"])
        if err:
            drop(item, [err[0]], [err[1]] + issues)
            continue
        if failed == ["in_date_range"] and (date_fixed or (lookback_days and _recent_hn(new, lookback_days))):
            failed = []  # 發布日已依原句校正到期間內，或期間內有題材相符的 HN 討論（§6.5）
        if failed:
            drop(item, failed, issues or ["查核者未說明原因"])
            continue
        new["edits"] = edits
        kept.append(new)

    kept, dups = dedupe(kept)
    for it, winner in dups:
        drop(it, ["duplicate"], [f"與 {winner} 共用來源，視為重複報導"], stage="dedupe")
    if min_heat_score:
        def floor(i):  # 單一數字，或 {section: 門檻}（未列的區不設門檻）
            return min_heat_score.get(i["section"], 0) if isinstance(min_heat_score, dict) else min_heat_score
        for it in [i for i in kept if heat_rank(i)[0] < floor(i)]:
            drop(it, ["low_heat"], [f"熱度分數 {heat_rank(it)[0]:g} 低於門檻 {floor(it):g}"], stage="heat")
        kept = [i for i in kept if i["id"] not in decisions]

    for it in kept:  # 只為保留的項目記錄修改，方便追溯
        for e in it["edits"]:
            fails.append(failure(run_date, "correct", it["id"], it["title"], [e["action"]], [describe_edit(e)],
                                 [e["url"]] if e.get("url") else [], extra={"edit": e}))

    passed = len(kept)
    corrected = sum(1 for i in kept if any(e["action"] in CONTENT_ACTIONS for e in i["edits"]))
    chosen = kept
    if keep:
        ranked = sorted(kept, key=heat_rank, reverse=True)
        ids = {i["id"] for s in ("onprem", "industry") for i in [y for y in ranked if y["section"] == s][:keep.get(s)]}
        chosen = [i for i in ranked if i["id"] in ids]  # 依熱度由高到低排列
    chosen_ids = {i["id"] for i in chosen}
    for it in kept:
        selected = it["id"] in chosen_ids
        decisions[it["id"]] = {"status": "kept" if selected else "not_selected",
                               "stage": "selected" if selected else "rank", "reasons": [],
                               "edits": sum(e["action"] in CONTENT_ACTIONS for e in it["edits"])}

    top3 = []
    for point in draft.get("top3", []):
        alive = [i for i in point["related_ids"] if i in chosen_ids]
        if alive:
            top3.append({**point, "related_ids": alive})

    total = collected if collected is not None else len(draft["items"])
    final = {"period": draft["period"], "top3": top3, "items": chosen,
             "insufficient": len(chosen) < min_passed, "decisions": decisions,
             "stats": {"collected": total, "passed": passed, "failed": total - passed, "shown": len(chosen),
                       "corrected": corrected}}
    return final, fails


def apply_top3(final, verdicts, run_date):
    """依焦點比對結果過濾 final["top3"]（SPEC §6.6）。verdicts 為 None（比對失敗）時整段不顯示。回傳 failures。"""
    if verdicts is None:
        final["top3"] = []
        return []
    by_index = {v.get("index"): v for v in verdicts if isinstance(v, dict)}
    kept, fails = [], []
    for n, point in enumerate(final["top3"]):
        v = by_index.get(n, {})
        if v.get("verdict") == "pass":
            kept.append(point)
        else:
            fails.append(failure(run_date, "review", None, point["text"], ["top3"],
                                 [v.get("reason") or "焦點比對未通過或未回報"]))
    final["top3"] = kept
    return fails
