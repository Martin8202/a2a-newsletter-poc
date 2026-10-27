"""評估腳本 eval/eval_review.py：Q-01 ~ Q-04。"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("eval_review", ROOT / "eval" / "eval_review.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

LABELS = {"L1": {"core_ok": True}, "L2": {"core_ok": False, "note": "事件編造"}, "L3": {"core_ok": True}}


def dec(status, reasons=(), stage="review"):
    return {"status": status, "stage": stage, "reasons": list(reasons)}


def test_q01_all_agree():
    d = {"L1": dec("kept"), "L2": dec("dropped", ["event_supported"]), "L3": dec("not_selected")}
    r = ev.compare(LABELS, d)
    assert (r["agree"], r["total"], r["false_keep"], r["false_drop"]) == (3, 3, [], [])


def test_q02_false_keep_and_false_drop_listed():
    d = {"L1": dec("dropped", ["event_supported"]), "L2": dec("kept"), "L3": dec("kept")}
    r = ev.compare(LABELS, d)
    assert [x["id"] for x in r["false_keep"]] == ["L2"] and [x["id"] for x in r["false_drop"]] == ["L1"]


def test_q03_heat_duplicate_and_rank_count_as_passed_review():
    d = {"L1": dec("dropped", ["low_heat"], "heat"), "L2": dec("dropped", ["source_dead"], "resolve"),
         "L3": dec("dropped", ["duplicate"], "dedupe")}
    assert ev.compare(LABELS, d)["agree"] == 3
    assert not ev.passed_review(None)


def test_q04_consistency_between_runs():
    a = {"L1": dec("kept"), "L2": dec("dropped", ["event_supported"]), "L3": dec("kept")}
    b = {"L1": dec("kept"), "L2": dec("kept"), "L3": dec("kept")}
    rate, diff = ev.consistency(a, b, list(LABELS))
    assert diff == ["L2"] and round(rate, 2) == 0.67


def test_main_prints_report(tmp_path, capsys):
    (tmp_path / "labels.json").write_text(json.dumps({"items": LABELS}), encoding="utf-8")
    for name in ("r1", "r2"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "decisions.json").write_text(json.dumps({"L1": dec("kept")}), encoding="utf-8")
    assert ev.main(["x", str(tmp_path / "labels.json"), str(tmp_path / "r1"), str(tmp_path / "r2")]) == 0
    out = capsys.readouterr().out
    assert "誤刪" in out and "穩定度" in out
