"""runs/YYYY-MM-DD_HHMM/ 與 failures.jsonl 的讀寫（SPEC §5.4、§7.1）。主程式是唯一寫檔者。"""
import json
from datetime import datetime
from pathlib import Path


def init_run_dir(base, run_id):
    d = Path(base) / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_failures(base, records):
    if not records:
        return
    with open(Path(base) / "failures.jsonl", "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def failure(run_date, stage, item_id=None, title=None, failed_checks=(), issues=(), sources=(), extra=None):
    """run_at 為記錄時間，用來分辨同一天重跑的紀錄；extra 為額外欄位（如校正內容）。"""
    rec = {"run_date": run_date, "run_at": datetime.now().isoformat(timespec="seconds"), "stage": stage,
           "id": item_id, "title": title, "failed_checks": list(failed_checks), "issues": list(issues),
           "sources": list(sources)}
    return {**rec, **(extra or {})}


def write_summary(run_dir, summary):
    write_json(Path(run_dir) / "summary.json", summary)
