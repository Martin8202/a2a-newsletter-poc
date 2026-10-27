"""SPEC §13.2 Phase 3 pipeline：P、F、D、T、K 系列。"""
import copy

import pytest

from pipeline import apply_review, apply_top3, dedupe

D = "2026-10-25"


def _review(draft, pass_review, idx=0, core=None, **overrides):
    r = pass_review(draft)
    if core:
        r["items"][idx]["core"].update(core)
    r["items"][idx].update(overrides)
    return r


def ids(final):
    return [i["id"] for i in final["items"]]


def _score(item, score, hn_age=None, peak=0):
    ms = [{"kind": "media", "ok": None, "score": score, "peak": peak}]
    if hn_age is not None:
        ms.append({"kind": "hn", "ok": True, "score": 0, "peak": 100, "age_days": hn_age})
    item["heat_metrics"] = ms


# ---------- P：核心判定、精選 ----------

def test_p01_all_pass(make_draft, pass_review):
    d = make_draft()
    final, fails = apply_review(d, pass_review(d), D)
    assert len(final["items"]) == 4 and fails == [] and not final["insufficient"]


@pytest.mark.parametrize("check", ["source_reachable", "event_supported", "in_date_range"])
def test_p02_core_failure_dropped(make_draft, pass_review, check):
    d = make_draft()
    final, fails = apply_review(d, _review(d, pass_review, 1, core={check: False}, issues=["原因"]), D)
    assert "L2" not in ids(final)
    assert fails[0]["failed_checks"] == [check] and fails[0]["issues"] == ["原因"] and fails[0]["sources"]


def test_p03_missing_or_errored_item_is_not_reviewed(make_draft, pass_review):
    d = make_draft()
    r = pass_review(d)
    r["items"] = [i for i in r["items"] if i["id"] not in ("L2", "L3")]
    r["errors"] = {"L3": "claude 逾時"}
    final, fails = apply_review(d, r, D)
    assert ids(final) == ["L1", "I1"]
    by = {f["id"]: f for f in fails}
    assert by["L2"]["issues"] == ["未查核"] and by["L3"]["issues"] == ["claude 逾時"]
    assert by["L2"]["failed_checks"] == ["not_reviewed"]


def test_p04_top3_dropped_when_related_removed(make_draft, pass_review):
    d = make_draft()
    final, _ = apply_review(d, _review(d, pass_review, 0, core={"event_supported": False}), D)
    assert final["top3"] == []


def test_p05_insufficient(make_draft, pass_review):
    d = make_draft(2, 0)
    final, _ = apply_review(d, pass_review(d), D, min_passed=3)
    assert final["insufficient"]


def test_p07_keep_ranks_by_score_then_peak(make_draft, pass_review):
    d = make_draft(4, 0)
    for item, (score, peak) in zip(d["items"], [(1, 50), (3, 100), (0, 0), (3, 900)]):
        _score(item, score, peak=peak)
    final, fails = apply_review(d, pass_review(d), D, keep={"onprem": 2, "industry": 4})
    assert ids(final) == ["L4", "L2"]
    assert final["stats"] == {"collected": 4, "passed": 4, "failed": 0, "shown": 2, "corrected": 0}
    assert fails == []
    assert final["decisions"]["L1"]["status"] == "not_selected"


def test_p08_keep_applies_per_section(make_draft, pass_review):
    d = make_draft(3, 3)
    for item in d["items"]:
        _score(item, 1)
    final, _ = apply_review(d, pass_review(d), D, keep={"onprem": 1, "industry": 2})
    assert sorted(i["section"] for i in final["items"]) == ["industry", "industry", "onprem"]


def test_p09_low_heat_dropped_and_logged(make_draft, pass_review):
    d = make_draft(2, 0)
    _score(d["items"][0], 0.5)
    _score(d["items"][1], 1.5)
    final, fails = apply_review(d, pass_review(d), D, min_heat_score=1.0)
    assert ids(final) == ["L2"]
    assert fails[0]["failed_checks"] == ["low_heat"] and "0.5" in fails[0]["issues"][0]
    assert final["decisions"]["L1"] == {"status": "dropped", "stage": "heat", "reasons": ["low_heat"]}


def test_p10_threshold_per_section(make_draft, pass_review):
    d = make_draft(1, 1)
    _score(d["items"][0], 0.5)
    _score(d["items"][1], 0.5)
    final, fails = apply_review(d, pass_review(d), D, min_heat_score={"onprem": 1.0, "industry": 0.5})
    assert ids(final) == ["I1"]
    assert "門檻 1" in fails[0]["issues"][0]


def test_p09_no_threshold_keeps_all(make_draft, pass_review):
    d = make_draft(2, 0)
    _score(d["items"][0], 0)
    final, _ = apply_review(d, pass_review(d), D)
    assert len(final["items"]) == 2


def test_p10_recent_hn_thread_relaxes_date(make_draft, pass_review):
    d = make_draft(1, 0)
    _score(d["items"][0], 1.5, hn_age=3.0)
    final, fails = apply_review(d, _review(d, pass_review, core={"in_date_range": False}), D, lookback_days=7)
    assert len(final["items"]) == 1 and fails == []


def test_p11_not_relaxed_when_hn_mismatch_or_other_core_failure(make_draft, pass_review):
    d = make_draft(1, 0)
    _score(d["items"][0], 1.5, hn_age=3.0)
    mismatch = _review(d, pass_review, core={"in_date_range": False}, heat_links=[{"index": 1, "match": False}])
    other = _review(d, pass_review, core={"in_date_range": False, "event_supported": False})
    for r in (mismatch, other):
        final, fails = apply_review(d, r, D, lookback_days=7)
        assert final["items"] == [] and "in_date_range" in fails[0]["failed_checks"]


def test_p12_old_hn_thread_does_not_relax(make_draft, pass_review):
    d = make_draft(1, 0)
    _score(d["items"][0], 1.5, hn_age=30.0)
    final, fails = apply_review(d, _review(d, pass_review, core={"in_date_range": False}), D, lookback_days=7)
    assert final["items"] == [] and fails[0]["failed_checks"] == ["in_date_range"]


# ---------- F：欄位層級處理 ----------

def _fix(item, **kw):
    c = {"field": "onprem_value.license", "verdict": "contradicted", "wrong": "Apache 2.0", "correct": "MIT",
         "quote": "Released under the MIT License", "url": item["sources"][0]["url"]}
    return {**c, **kw}


def _fields(draft, pass_review, fields, **kw):
    return _review(draft, pass_review, fields=fields, **kw)


def _correct_records(fails):
    return [f for f in fails if f["stage"] == "correct"]


def test_f01_unsupported_key_point_removed(make_draft, pass_review):
    d = make_draft(1, 0)
    r = _fields(d, pass_review, [{"field": "key_points[0]", "verdict": "unsupported", "reason": "來源沒有"}])
    final, fails = apply_review(d, r, D)
    assert [k["text"] for k in final["items"][0]["key_points"]] == ["細節1b"]
    assert _correct_records(fails)[0]["failed_checks"] == ["removed_unsupported"]
    assert final["stats"]["corrected"] == 1


def test_f02_unsupported_onprem_value_becomes_not_stated(make_draft, pass_review):
    d = make_draft(1, 0)
    r = _fields(d, pass_review, [{"field": "onprem_value.license", "verdict": "unsupported", "reason": "沒寫"}])
    final, fails = apply_review(d, r, D)
    assert final["items"][0]["onprem_value"]["license"] == "來源未載明"
    assert _correct_records(fails)[0]["failed_checks"] == ["not_stated"]


def test_f03_unsupported_why_hot_removed(make_draft, pass_review):
    d = make_draft(1, 0)
    final, fails = apply_review(d, _fields(d, pass_review, [{"field": "why_hot", "verdict": "unsupported"}]), D)
    assert "why_hot" not in final["items"][0]
    assert _correct_records(fails)[0]["failed_checks"] == ["removed_unsupported"]


@pytest.mark.parametrize("field", ["title", "summary"])
def test_f04_unsupported_title_or_summary_is_fatal_even_if_core_says_ok(make_draft, pass_review, field):
    d = make_draft(1, 0)
    final, fails = apply_review(d, _fields(d, pass_review, [{"field": field, "verdict": "unsupported"}]), D)
    assert final["items"] == [] and fails[0]["failed_checks"] == ["event_supported"]


def test_unsupported_published_date_is_fatal(make_draft, pass_review):
    d = make_draft(1, 0)
    final, fails = apply_review(d, _fields(d, pass_review, [{"field": "published_date", "verdict": "unsupported"}]), D)
    assert final["items"] == [] and fails[0]["failed_checks"] == ["in_date_range"]


def test_f05_valid_correction_applied(make_draft, pass_review):
    d = make_draft(1, 0)
    final, fails = apply_review(d, _fields(d, pass_review, [_fix(d["items"][0])]), D)
    item = final["items"][0]
    assert item["onprem_value"]["license"] == "MIT"
    assert final["stats"]["corrected"] == 1
    rec = _correct_records(fails)[0]
    assert rec["failed_checks"] == ["corrected"] and "Apache 2.0 → MIT" in rec["issues"][0]
    assert rec["edit"]["quote"] == "Released under the MIT License"


def test_f05_key_point_correction(make_draft, pass_review):
    d = make_draft(1, 0)
    fix = _fix(d["items"][0], field="key_points[1]", wrong="1b", correct="1c", quote="see 1c here")
    final, _ = apply_review(d, _fields(d, pass_review, [fix]), D)
    assert final["items"][0]["key_points"][1]["text"] == "細節1c"


@pytest.mark.parametrize("override", [
    {"field": "signals[0]"},                          # 不可校正的欄位
    {"wrong": "不存在的字"},                           # 錯值找不到
    {"wrong": ""},                                    # 錯值為空
    {"url": "https://evil.example.com/x"},            # 連結不屬於本則
    {"correct": "GPL-3.0"},                           # 對值不在原句
    {"quote": ""},                                    # 沒有原句
])
def test_f06_invalid_correction_rejects_item(make_draft, pass_review, override):
    d = make_draft(1, 0)
    final, fails = apply_review(d, _fields(d, pass_review, [_fix(d["items"][0], **override)]), D)
    assert final["items"] == [] and fails[0]["failed_checks"] == ["correction_rejected"]


def test_f06_wrong_appearing_twice_rejected(make_draft, pass_review):
    d = make_draft(1, 0)
    d["items"][0]["summary"] = "快 3 倍，並且 3 倍省電"
    fix = _fix(d["items"][0], field="summary", wrong="3 倍", correct="2 倍", quote="about 2 倍 faster")
    final, fails = apply_review(d, _fields(d, pass_review, [fix]), D)
    assert final["items"] == [] and fails[0]["failed_checks"] == ["correction_rejected"]


def test_f06_too_many_corrections(make_draft, pass_review):
    d = make_draft(1, 0)
    d["items"][0]["summary"] = "a1 a2 a3 a4"
    fixes = [_fix(d["items"][0], field="summary", wrong=f"a{n}", correct=f"b{n}", quote=f"b{n}") for n in range(1, 5)]
    final, fails = apply_review(d, _fields(d, pass_review, fixes), D)
    assert final["items"] == [] and "3" in fails[0]["issues"][0]


def _date_fix(item, correct, quote):
    return {"field": "published_date", "verdict": "contradicted", "wrong": item["published_date"],
            "correct": correct, "quote": quote, "url": item["sources"][0]["url"]}


@pytest.mark.parametrize("quote", ["Released 2026-10-21", "Posted on October 21, 2026", "發布於 2026年10月21日",
                                   "released this 21 Oct 02:55", "Oct 21"])
def test_f07_date_correction_inside_period_keeps_item(make_draft, pass_review, quote):
    d = make_draft(1, 0)
    d["items"][0]["published_date"] = "2026-10-13"
    r = _fields(d, pass_review, [_date_fix(d["items"][0], "2026-10-21", quote)], core={"in_date_range": False})
    final, _ = apply_review(d, r, D)
    assert final["items"][0]["published_date"] == "2026-10-21"


@pytest.mark.parametrize("correct,quote", [("2026-10-01", "Released 2026-10-01"), ("Oct 21", "Released Oct 21"),
                                           ("2026-10-21", "Released last week"), ("2026-10-21", "released 22 Oct")])
def test_f08_bad_date_correction_rejected(make_draft, pass_review, correct, quote):
    d = make_draft(1, 0)
    r = _fields(d, pass_review, [_date_fix(d["items"][0], correct, quote)], core={"in_date_range": False})
    final, fails = apply_review(d, r, D)
    assert final["items"] == [] and fails[0]["failed_checks"] == ["correction_rejected"]


def test_f09_heat_link_mismatch_zeroes_only_that_metric(make_draft, pass_review):
    d = make_draft(1, 0)
    d["items"][0]["heat_metrics"] = [{"kind": "hn", "ok": True, "score": 2, "peak": 300},
                                     {"kind": "media", "ok": None, "score": 0.5, "peak": 0}]
    r = _review(d, pass_review, heat_links=[{"index": 0, "match": False, "reason": "別的專案"}])
    final, _ = apply_review(d, r, D)
    m = final["items"][0]["heat_metrics"]
    assert m[0]["score"] == 0 and m[0]["mismatch"] and m[1]["score"] == 0.5
    assert final["stats"]["corrected"] == 0  # 熱度標記不算內容修改


def test_f10_multiple_key_points_removed_by_index(make_draft, pass_review):
    d = make_draft(1, 0)
    d["items"][0]["key_points"].append({"text": "細節1c", "quote": "q", "url": d["items"][0]["sources"][0]["url"]})
    r = _fields(d, pass_review, [{"field": "key_points[0]", "verdict": "unsupported"},
                                 {"field": "key_points[2]", "verdict": "unsupported"}])
    final, _ = apply_review(d, r, D)
    assert [k["text"] for k in final["items"][0]["key_points"]] == ["細節1b"]


def test_f11_input_draft_not_mutated(make_draft, pass_review):
    d = make_draft(1, 0)
    before = copy.deepcopy(d)
    apply_review(d, _fields(d, pass_review, [_fix(d["items"][0]),
                                             {"field": "key_points[0]", "verdict": "unsupported"}]), D)
    assert d == before


def test_supported_or_unknown_fields_are_ignored(make_draft, pass_review):
    d = make_draft(1, 0)
    r = _fields(d, pass_review, [{"field": "summary", "verdict": "supported"},
                                 {"field": "signals[0]", "verdict": "unsupported"}])
    final, _ = apply_review(d, r, D)
    assert len(final["items"]) == 1 and final["items"][0]["edits"] == []


# ---------- D：重複報導 ----------

def test_d01_shared_source_is_duplicate(make_draft, pass_review):
    d = make_draft(2, 0)
    d["items"][0]["sources"][0]["url"] = "https://www.Example.com/post/?utm_source=x"
    d["items"][1]["sources"][0]["url"] = "https://example.com/post"
    _score(d["items"][0], 1)
    _score(d["items"][1], 2)
    final, fails = apply_review(d, pass_review(d), D)
    assert ids(final) == ["L2"]
    assert fails[0]["failed_checks"] == ["duplicate"] and "L2" in fails[0]["issues"][0]
    assert final["decisions"]["L1"]["stage"] == "dedupe"


def test_d02_different_sources_kept():
    a = {"id": "L1", "sources": [{"url": "https://a.com/1"}]}
    b = {"id": "L2", "sources": [{"url": "https://a.com/2"}]}
    kept, dups = dedupe([a, b])
    assert [i["id"] for i in kept] == ["L1", "L2"] and dups == []


# ---------- T：3 大焦點 ----------

def test_t01_top3_fail_removed_and_logged(make_draft, pass_review):
    d = make_draft()
    d["top3"].append({"text": "焦點二", "related_ids": ["L2"]})
    final, _ = apply_review(d, pass_review(d), D)
    fails = apply_top3(final, [{"index": 0, "verdict": "pass"}, {"index": 1, "verdict": "fail", "reason": "多了 70B"}], D)
    assert [p["text"] for p in final["top3"]] == ["焦點"]
    assert fails[0]["failed_checks"] == ["top3"] and fails[0]["issues"] == ["多了 70B"]


def test_t02_top3_check_failure_hides_section(make_draft, pass_review):
    d = make_draft()
    final, _ = apply_review(d, pass_review(d), D)
    assert apply_top3(final, None, D) == [] and final["top3"] == []


# ---------- K：處置紀錄 ----------

def test_k01_decisions_cover_every_item(make_draft, pass_review):
    d = make_draft(2, 1)
    r = _review(d, pass_review, 1, core={"event_supported": False})
    final, _ = apply_review(d, r, D, keep={"onprem": 1, "industry": 1})
    dec = final["decisions"]
    assert set(dec) == {"L1", "L2", "I1"}
    assert dec["L2"] == {"status": "dropped", "stage": "review", "reasons": ["event_supported"]}
    assert dec["L1"]["status"] == "kept" and dec["L1"]["edits"] == 0
