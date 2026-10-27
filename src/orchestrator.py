"""主程式：串起蒐集 → 還原 → 預檢 → 熱度 → 查核 → 過濾 → 排版 → 寄信（SPEC §3、§7.3）。"""
import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import heat  # noqa: E402
import mailer  # noqa: E402
import pipeline  # noqa: E402
import render  # noqa: E402
import storage  # noqa: E402
import url_resolver  # noqa: E402
from agents import collector, reviewer  # noqa: E402
from agents.runner import AgentError  # noqa: E402
from config import load_config  # noqa: E402

BASE = Path(__file__).resolve().parents[1]


def _now(cfg):
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(cfg["timezone"]))
    except Exception:  # 缺 tzdata 時退回 UTC+8
        return datetime.now(timezone(timedelta(hours=8)))


def _load_replay_draft(base, from_run):
    """重播模式：讀既有 run 資料夾的 draft.json（相對路徑先找目前目錄，再找專案根目錄）。"""
    p = Path(from_run)
    if not p.is_absolute() and not p.exists():
        p = Path(base) / p
    return json.loads((p / "draft.json").read_text(encoding="utf-8"))


def main(base=BASE, now=None, from_run=None, send=True):
    """回傳結束碼：0 成功；1 任何階段失敗或品質不足。
    每次執行使用獨立資料夾 runs/YYYY-MM-DD_HHMM/，同日重跑不覆蓋。
    from_run：沿用該次 draft.json，不重新蒐集；send=False：不寄任何信。"""
    cfg = load_config(Path(base) / "config.yaml")
    now = now or _now(cfg)
    today = now.date()
    run_date, end = today.isoformat(), today.isoformat()
    start = (today - timedelta(days=cfg["lookback_days"])).isoformat()
    run_dir = storage.init_run_dir(base, now.strftime("%Y-%m-%d_%H%M"))
    log_path = run_dir / "run.log"
    logging.basicConfig(level=logging.INFO, force=True, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()])
    summary = {"run_date": run_date, "run_id": run_dir.name, "status": "running", "stage": "init"}

    def send_mail(subject, html):
        if not send:
            logging.info("（--no-mail）略過寄信：%s", subject)
            return
        mailer.send_mail(cfg["mail"], subject, html)

    def fail(stage, message):
        logging.error("%s 失敗: %s", stage, message)
        summary.update(status="failed", stage=stage, error=message)
        storage.append_failures(base, [storage.failure(run_date, stage, issues=[message])])
        try:
            send_mail(f"[失敗] AI 週報 {run_date}",
                      f"<p>失敗階段：{stage}</p><pre>{message}</pre><p>日誌：{log_path}</p>")
        except mailer.MailError as e:
            logging.error("失敗通知也寄不出去: %s", e)
        storage.write_summary(run_dir, summary)
        return 1

    try:
        if from_run:
            draft = _load_replay_draft(base, from_run)
            start, end = draft["period"]["start"], draft["period"]["end"]
            logging.info("[1/5] 重播模式：沿用 %s 的 draft.json（%d 則），不重新蒐集", from_run, len(draft["items"]))
        else:
            summary["stage"] = "collect"
            logging.info("[1/5] 蒐集中（agy，約 5–20 分鐘）%s ~ %s", start, end)
            draft = collector.collect(cfg, start, end)
            logging.info("蒐集完成：%d 則", len(draft["items"]))
        storage.write_json(run_dir / "draft.json", draft)

        summary["stage"] = "resolve"
        logging.info("[2/5] 還原轉址網址、預檢來源、取得熱度數字")
        resolved, resolve_fails = url_resolver.resolve_urls(draft, cfg, run_date)
        logging.info("還原完成：剩 %d 則，移除 %d 筆", len(resolved["items"]), len(resolve_fails))
        resolved, dead_fails = url_resolver.check_sources(resolved, cfg, run_date)
        logging.info("來源預檢：剩 %d 則，剔除 %d 則（來源全死）",
                     len(resolved["items"]), sum("整則剔除" in f["issues"][0] for f in dead_fails))
        storage.append_failures(base, resolve_fails + dead_fails)
        resolved = heat.fetch_heat(resolved, cfg)
        storage.write_json(run_dir / "draft_resolved.json", resolved)
        ms = [m for i in resolved["items"] for m in i.get("heat_metrics", [])]
        logging.info("熱度取得：API 成功 %d 筆、失敗 %d 筆（失敗計 0 分）",
                     sum(m["ok"] is True for m in ms), sum(m["ok"] is False for m in ms))

        summary["stage"] = "review"
        rc = cfg["agents"]["reviewer"]
        logging.info("[3/5] 查核中（claude %s，每則獨立、同時 %s 則，共 %d 則）",
                     rc["model"], rc.get("concurrency", 1), len(resolved["items"]))
        review = reviewer.review_items(cfg, resolved, start, end)
        if review["errors"]:
            logging.warning("查核失敗 %d 則：%s", len(review["errors"]), ", ".join(review["errors"]))
    except AgentError as e:
        return fail(summary["stage"], str(e))

    summary["stage"] = "render"
    logging.info("[4/5] 欄位處理、重複判斷、精選、焦點比對與排版")
    final, review_fails = pipeline.apply_review(
        resolved, review, run_date, cfg["min_passed_items"],
        collected=len(draft["items"]), keep=cfg.get("keep"), correction=cfg.get("correction"),
        min_heat_score=cfg.get("min_heat_score", 0), lookback_days=cfg["lookback_days"])
    final["top3"] = reviewer.write_top3(cfg, final["items"])  # 不沿用蒐集端的焦點，依入選項目重寫（§6.6）
    review["top3_written"] = final["top3"]
    review["top3"] = reviewer.check_top3(cfg, final["top3"], final["items"])
    review_fails += pipeline.apply_top3(final, review["top3"], run_date)
    storage.write_json(run_dir / "review.json", review)
    storage.append_failures(base, review_fails)

    dropped_early = {i["id"] for i in draft["items"]} - {i["id"] for i in resolved["items"]}
    for item_id in dropped_early:  # 在還原 / 預檢就被剔除、沒送查核的則
        reasons = sorted({c for f in resolve_fails + dead_fails if f["id"] == item_id for c in f["failed_checks"]})
        final["decisions"][item_id] = {"status": "dropped", "stage": "resolve", "reasons": reasons}
    storage.write_json(run_dir / "decisions.json", final["decisions"])
    logging.info("處置：保留 %d 則、未入選 %d 則、剔除 %d 則",
                 *(sum(d["status"] == s for d in final["decisions"].values()) for s in ("kept", "not_selected", "dropped")))
    try:
        html = render.render(final, cfg["url_resolver"]["redirect_domains"])
    except ValueError as e:
        return fail("render", str(e))
    (run_dir / "newsletter.html").write_text(html, encoding="utf-8")

    st = final["stats"]
    insufficient_notice = final["insufficient"] and cfg.get("on_insufficient", "notify") == "notify"
    if insufficient_notice:
        subject = f"[品質不足] AI 週報 {end}"
        body = (f"<p>精選後僅 {st['shown']} 則（下限 {cfg['min_passed_items']}），本週未寄出週報。</p>"
                f"<p>蒐集 {st['collected']} 則、查核通過 {st['passed']} 則、未通過 {st['failed']} 則。</p>"
                f"<p>日誌：{log_path}<br>週報草稿：{run_dir / 'newsletter.html'}</p>")
    else:
        subject, body = cfg["mail"]["subject"].format(end_date=end), html

    summary["stage"] = "mail"
    logging.info("[5/5] 寄信給 %s：%s", cfg["mail"]["to"], subject)
    try:
        send_mail(subject, body)
    except mailer.MailError as e:
        storage.append_failures(base, [storage.failure(run_date, "mail", issues=[str(e)])])
        summary.update(status="failed", error=str(e), stats=st)
        storage.write_summary(run_dir, summary)
        logging.error(str(e))
        return 1

    summary.update(status="insufficient" if insufficient_notice else "ok", stage="done", stats=st,
                   insufficient=final["insufficient"])
    storage.write_summary(run_dir, summary)
    logging.info("完成 %s", st)
    return 1 if insufficient_notice else 0


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
    ap = argparse.ArgumentParser(description="AI 地端與開源模型週報")
    ap.add_argument("--from-run", help="重播：沿用指定 runs 資料夾的 draft.json，不重新蒐集")
    ap.add_argument("--no-mail", action="store_true", help="不寄任何信（只產生檔案與紀錄）")
    a = ap.parse_args()
    sys.exit(main(from_run=a.from_run, send=not a.no_mail))
