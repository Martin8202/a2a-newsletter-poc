"""呼叫 claude 查核：每則獨立一次（SPEC §6.3），以及「3 大焦點」文字比對（§6.6）。"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from agents.runner import AgentError, AgentPermissionError, AgentQuotaError, run_agent
from schemas import extract_json

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / "prompts" / "reviewer.md"
TOP3_PROMPT = ROOT / "prompts" / "top3.md"
TOP3_WRITE_PROMPT = ROOT / "prompts" / "top3_write.md"


def render_item_prompt(item, start_date, end_date, path=PROMPT):
    text = Path(path).read_text(encoding="utf-8")
    text = text.replace("{start_date}", start_date).replace("{end_date}", end_date)
    return text + "\n" + json.dumps(item, ensure_ascii=False, indent=2)


def _parse_item(out):
    r = extract_json(out)
    if not isinstance(r, dict) or not isinstance(r.get("core"), dict):
        raise ValueError("查核輸出缺少 core 物件")
    for key in ("fields", "heat_links", "issues"):
        r.setdefault(key, [])
        if not isinstance(r[key], list):
            raise ValueError(f"查核輸出的 {key} 必須是陣列")
    return r


def review_items(cfg, draft, start_date, end_date):
    """每則一次 claude -p，同時最多 concurrency 則。回傳 {"items": [...], "errors": {id: 原因}}。
    單則失敗只記入 errors；全部失敗拋 AgentError；權限被拒拋 AgentPermissionError（重試也沒用）。"""
    c = cfg["agents"]["reviewer"]
    args = ["-p", "--model", c["model"], "--allowedTools", " ".join(c["allowed_tools"])]

    def one(item):
        r = run_agent(c["command"], args, _parse_item, c["timeout_seconds"], c["retries"],
                      input_text=render_item_prompt(item, start_date, end_date))
        r["id"] = item["id"]  # 以呼叫時的 id 為準，不信任模型回填
        return r

    results, errors = [], {}
    ex = ThreadPoolExecutor(max_workers=max(1, int(c.get("concurrency", 1))))
    try:
        futures = {ex.submit(one, item): item["id"] for item in draft["items"]}
        for fut in as_completed(futures):
            item_id = futures[fut]
            try:
                results.append(fut.result())
                logging.info("查核完成 %s（%d/%d）", item_id, len(results) + len(errors), len(futures))
            except (AgentPermissionError, AgentQuotaError):
                raise  # 重試與其他則也會遇到同樣問題：整個查核中止，由主程式寄失敗通知
            except AgentError as e:
                errors[item_id] = str(e)
                logging.warning("查核失敗 %s：%s", item_id, e)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    if draft["items"] and not results:
        raise AgentError("全部則查核失敗：" + next(iter(errors.values()), ""))
    order = {item["id"]: n for n, item in enumerate(draft["items"])}
    results.sort(key=lambda r: order[r["id"]])
    return {"items": results, "errors": errors}


def _parse_top3(out):
    r = extract_json(out)
    if not isinstance(r, dict) or not isinstance(r.get("top3"), list):
        raise ValueError("焦點輸出缺少 top3 陣列")
    return r["top3"]


def _brief(item):
    return {"id": item["id"], "title": item["title"], "summary": item["summary"],
            "key_points": [k["text"] for k in item.get("key_points") or []]}


def write_top3(cfg, items):
    """依入選項目重寫 3 大焦點（不開工具，SPEC §6.6）。回傳 [{"text", "related_ids"}]；呼叫失敗回傳 []。"""
    if not items:
        return []
    c = cfg["agents"]["reviewer"]
    prompt = (Path(TOP3_WRITE_PROMPT).read_text(encoding="utf-8") + "\n"
              + json.dumps([_brief(i) for i in items], ensure_ascii=False, indent=2))
    try:
        points = run_agent(c["command"], ["-p", "--model", c["model"]], _parse_top3,
                           c["timeout_seconds"], c["retries"], input_text=prompt)
    except AgentError as e:
        logging.warning("焦點撰寫失敗，本週不顯示焦點：%s", e)
        return []
    ids = {i["id"] for i in items}
    out = []
    for p in points[:3]:
        if not isinstance(p, dict) or not isinstance(p.get("text"), str) or not p["text"].strip():
            continue
        rel = [r for r in p.get("related_ids") or [] if r in ids] if isinstance(p.get("related_ids"), list) else []
        if rel:  # 沒有引用入選項目的焦點無法比對，捨棄
            out.append({"text": p["text"].strip(), "related_ids": rel})
    return out


def check_top3(cfg, top3, items):
    """焦點與其引用項目做文字比對（不開工具）。回傳 [{"index", "verdict", "reason"}]；呼叫失敗回傳 None。"""
    if not top3:
        return []
    by_id = {i["id"]: i for i in items}
    payload = [{"index": n, "text": p["text"],
                "related": [_brief(by_id[rid]) for rid in p["related_ids"] if rid in by_id]}
               for n, p in enumerate(top3)]
    c = cfg["agents"]["reviewer"]
    prompt = Path(TOP3_PROMPT).read_text(encoding="utf-8") + "\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        return run_agent(c["command"], ["-p", "--model", c["model"]], _parse_top3,
                         c["timeout_seconds"], c["retries"], input_text=prompt)
    except AgentError as e:
        logging.warning("焦點比對失敗，本週不顯示焦點：%s", e)
        return None
